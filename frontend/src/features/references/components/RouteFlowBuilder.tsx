import { useState, useEffect, useCallback, useRef } from "react";
import {
  ReactFlow,
  Controls,
  Background,
  addEdge,
  reconnectEdge,
  useNodesState,
  useEdgesState,
  Panel,
  useReactFlow,
  useNodesInitialized,
  ReactFlowProvider,
  BaseEdge,
  EdgeLabelRenderer,
  getSmoothStepPath,
  ConnectionMode,
  MarkerType,
  type Node,
  type Edge,
  type EdgeProps,
  type OnConnect,
  type NodeTypes,
  type Connection,
  type NodeMouseHandler,
  type EdgeMouseHandler,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { X, Plus, Trash2, AlertTriangle, Info } from "lucide-react";
import * as API from "@/shared/api/routes";
import type { Section } from "@/shared/api/sections";
import { Button } from "@/shared/ui/Button";
import { Input } from "@/shared/ui/Input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/shared/ui/Dialog";
import { toast } from "@/shared/ui/use-toast";
import { apiClient } from "@/shared/api/client";
import { renderIcon } from "@/shared/ui/EntityDialog";
import { RouteFlowNode, type RouteFlowNodeData } from "./RouteFlowNode";

type PortId = "right" | "left";
type RouteNode = Node<RouteFlowNodeData>;
type RouteEdge = Edge;
type InsertTarget =
  | { kind: "edge"; edgeId: string }
  | { kind: "start" }
  | { kind: "end" }
  | null;
const GRID_SPACING_X = 260;
const GRID_SPACING_Y = 170;

function getGridColumns(total: number): number {
  return total > 9 ? 4 : 3;
}

function getGridPosition(index: number, total: number): { x: number; y: number } {
  const columns = getGridColumns(total);
  return {
    x: (index % columns) * GRID_SPACING_X,
    y: Math.floor(index / columns) * GRID_SPACING_Y,
  };
}

function relayoutNodesByOrder(
  nodes: RouteNode[],
  edges: RouteEdge[]
): RouteNode[] {
  const inDegree: Record<string, number> = {};
  const adj: Record<string, string[]> = {};
  const ids = new Set(nodes.map((n) => n.id));

  for (const n of nodes) {
    inDegree[n.id] = 0;
    adj[n.id] = [];
  }
  for (const e of edges) {
    if (!ids.has(e.source) || !ids.has(e.target)) continue;
    adj[e.source].push(e.target);
    inDegree[e.target] = (inDegree[e.target] || 0) + 1;
  }

  const q = Object.keys(inDegree).filter((id) => inDegree[id] === 0);
  const order: string[] = [];
  while (q.length > 0) {
    const cur = q.shift()!;
    order.push(cur);
    for (const nx of adj[cur] || []) {
      inDegree[nx]--;
      if (inDegree[nx] === 0) q.push(nx);
    }
  }
  for (const n of nodes) if (!order.includes(n.id)) order.push(n.id);
  const idx = new Map(order.map((id, i) => [id, i]));

  return nodes.map((n) => {
    const i = idx.get(n.id) ?? 0;
    const pos = getGridPosition(i, nodes.length);
    return { ...n, position: { x: pos.x, y: pos.y } };
  });
}

const OPERATIONS = [
  { value: "ISSUE_RAW", label: "Выдача сырья" },
  { value: "DRILL", label: "Сверловка" },
  { value: "PRESS_WINDOW", label: "Пресс окно" },
  { value: "PRESS_COMB", label: "Пресс гребенка" },
  { value: "SHOT", label: "Дробеструй" },
  { value: "ANOD", label: "Анодирование" },
  { value: "MOVE_TO_WIP", label: "Передача на п/ф" },
  { value: "SAW", label: "Пила" },
  { value: "PACK", label: "Упаковка" },
  { value: "ACCEPT_FINISHED", label: "Приемка ГП" },
];

const nodeTypes: NodeTypes = {
  routeFlow: RouteFlowNode as any,
};

// Calculate port occupancy from edges
function calculatePortOccupancy(nodes: RouteNode[], edges: RouteEdge[]): RouteNode[] {
  return nodes.map(node => {
    const occupied: RouteFlowNodeData['occupiedPorts'] = {};

    // Mark port as occupied if it participates in any incoming/outgoing connection
    edges.forEach(edge => {
      if (edge.source === node.id && edge.sourceHandle) {
        occupied[edge.sourceHandle as PortId] = true;
      }
      if (edge.target === node.id && edge.targetHandle) {
        occupied[edge.targetHandle as PortId] = true;
      }
    });

    return {
      ...node,
      data: {
        ...node.data,
        occupiedPorts: occupied,
      },
    };
  });
}

// Internal component to access useReactFlow hook
function FlowCanvas({
  open,
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onConnect,
  onReconnect,
  isValidConnection,
  onInsertEdgeClick,
  onInsertAtStartClick,
  onInsertAtEndClick,
  onNodeClick,
  onPaneClick,
  onEdgeClick,
}: {
  open: boolean;
  nodes: RouteNode[];
  edges: RouteEdge[];
  onNodesChange: any;
  onEdgesChange: any;
  onConnect: OnConnect;
  onReconnect: (oldEdge: RouteEdge, newConnection: Connection) => void;
  isValidConnection: (connection: Connection | RouteEdge) => boolean;
  onInsertEdgeClick: (edgeId: string) => void;
  onInsertAtStartClick: () => void;
  onInsertAtEndClick: () => void;
  onNodeClick: any;
  onPaneClick: any;
  onEdgeClick?: any;
}) {
  const { fitView } = useReactFlow();
  const nodesInitialized = useNodesInitialized();
  const [showHintCard, setShowHintCard] = useState(true);
  const [hintClosing, setHintClosing] = useState(false);

  // Calculate port occupancy
  const nodesWithPorts = calculatePortOccupancy(nodes, edges);
  const sourceSet = new Set(edges.map((e) => e.source));
  const targetSet = new Set(edges.map((e) => e.target));
  const startNodeId = nodes.find((n) => !targetSet.has(n.id))?.id ?? null;
  const endNodeId = nodes.find((n) => !sourceSet.has(n.id))?.id ?? null;
  const nodesWithDecorators = nodesWithPorts.map((n) => ({
    ...n,
    data: {
      ...(n.data as RouteFlowNodeData),
      isStartNode: n.id === startNodeId,
      isEndNode: n.id === endNodeId,
      onInsertAtStart: () => onInsertAtStartClick(),
      onInsertAtEnd: () => onInsertAtEndClick(),
    },
  }));

  // Fit when modal is open and nodes are fully initialized/measured
  useEffect(() => {
    if (!open || nodes.length === 0 || !nodesInitialized) return;
    let raf1 = 0;
    let raf2 = 0;
    const t1 = setTimeout(() => fitView({ padding: 0.12, duration: 0 }), 80);
    const t2 = setTimeout(() => fitView({ padding: 0.12, duration: 200 }), 260);

    raf1 = requestAnimationFrame(() => {
      fitView({ padding: 0.12, duration: 0 });
      raf2 = requestAnimationFrame(() => {
        fitView({ padding: 0.12, duration: 180 });
      });
    });

    return () => {
      cancelAnimationFrame(raf1);
      cancelAnimationFrame(raf2);
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, [open, nodesInitialized, nodes.length, edges.length, fitView]);

  useEffect(() => {
    setShowHintCard(true);
    setHintClosing(false);
    const startClose = setTimeout(() => setHintClosing(true), 4600);
    const hide = setTimeout(() => setShowHintCard(false), 5000);
    return () => {
      clearTimeout(startClose);
      clearTimeout(hide);
    };
  }, []);

  // Smart edge component
  const SmartEdge = ({
    id,
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    markerEnd,
    style,
  }: EdgeProps<RouteEdge>) => {
    const [edgePath, labelX, labelY] = getSmoothStepPath({
      sourceX,
      sourceY,
      sourcePosition,
      targetX,
      targetY,
      targetPosition,
      borderRadius: 20,
      offset: 24,
    });

    return (
      <>
        <BaseEdge
          id={id}
          path={edgePath}
          markerEnd={markerEnd}
          style={style}
          interactionWidth={20}
        />
        <EdgeLabelRenderer>
          <button
            type="button"
            className="absolute h-5 w-5 rounded-full border bg-background text-muted-foreground hover:text-foreground hover:border-primary shadow-sm text-xs leading-none"
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              pointerEvents: "all",
            }}
            onClick={(e) => {
              e.stopPropagation();
              onInsertEdgeClick(id);
            }}
            title="Вставить участок между этапами"
          >
            +
          </button>
        </EdgeLabelRenderer>
      </>
    );
  };

  const edgeTypes = {
    smart: SmartEdge,
  };

  return (
    <ReactFlow
      nodes={nodesWithDecorators}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onConnect={onConnect}
      onReconnect={onReconnect}
      isValidConnection={isValidConnection}
      onNodeClick={onNodeClick}
      onEdgeClick={onEdgeClick}
      onPaneClick={onPaneClick}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      fitView
      fitViewOptions={{ padding: 0.12 }}
      minZoom={0.1}
      maxZoom={1.5}
      defaultEdgeOptions={{
        type: 'smart',
        reconnectable: true,
        interactionWidth: 20,
        markerEnd: { type: MarkerType.ArrowClosed },
      }}
      connectionMode={ConnectionMode.Loose}
      edgesReconnectable
      nodesDraggable={false}
      connectionLineStyle={{
        stroke: '#3b82f6',
        strokeWidth: 2,
      }}
    >
      <Controls />
      <Background />
      <Panel position="top-right">
        {showHintCard ? (
          <div
            className={`bg-card border rounded-md p-2 text-xs text-muted-foreground transition-all duration-400 ease-out ${
              hintClosing ? "opacity-0 translate-y-1 scale-[0.98]" : "opacity-100 translate-y-0 scale-100"
            }`}
          >
            <div className="font-semibold mb-1">Подсказка:</div>
            <div>• Кликните по участку или + в палитре</div>
            <div>• Нажмите + на линии, чтобы вставить этап</div>
            <div>• Соедините ноды: точка → точка</div>
            <div>• Кликните на ноду для настроек</div>
            <div>• Delete — удалить ноду/соединение</div>
          </div>
        ) : (
          <div className="relative group">
            <div className="h-8 w-8 rounded-md border bg-card text-muted-foreground flex items-center justify-center">
              <Info className="h-4 w-4" />
            </div>
            <div className="absolute right-0 top-9 hidden group-hover:block z-20">
              <div className="bg-card border rounded-md p-2 text-xs text-muted-foreground w-64 shadow-md">
                <div className="font-semibold mb-1">Подсказка:</div>
                <div>• Кликните по участку или + в палитре</div>
                <div>• Нажмите + на линии, чтобы вставить этап</div>
                <div>• Соедините ноды: точка → точка</div>
                <div>• Кликните на ноду для настроек</div>
                <div>• Delete — удалить ноду/соединение</div>
              </div>
            </div>
          </div>
        )}
      </Panel>
    </ReactFlow>
  );
}

interface RouteFlowBuilderProps {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  route: API.RouteDetail | null;
  onSave: () => void;
}

export function RouteFlowBuilder({ open, onOpenChange, route, onSave }: RouteFlowBuilderProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState<RouteNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<RouteEdge>([]);
  const [sections, setSections] = useState<Section[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [saving, setSaving] = useState(false);
  const [sectionUsage, setSectionUsage] = useState<Record<number, number>>({});
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [autoConnect, setAutoConnect] = useState(true);
  const [insertTarget, setInsertTarget] = useState<InsertTarget>(null);
  const lastNodeId = useRef<string | null>(null);

  const getEndNodeId = useCallback((currentNodes: RouteNode[], currentEdges: RouteEdge[]): string | null => {
    if (currentNodes.length === 0) return null;
    const sourceSet = new Set(currentEdges.map((e) => e.source));
    const endCandidates = currentNodes.filter((n) => !sourceSet.has(n.id));
    if (endCandidates.length === 0) return currentNodes[currentNodes.length - 1]?.id ?? null;
    return endCandidates[endCandidates.length - 1].id;
  }, []);

  const isPortBusy = useCallback(
    (
      nodeId: string,
      port: string,
      direction: "source" | "target",
      excludingEdgeId?: string
    ) =>
      edges.some((edge: RouteEdge) => {
        if (excludingEdgeId && edge.id === excludingEdgeId) return false;
        if (direction === "source") {
          return edge.source === nodeId && edge.sourceHandle === port;
        }
        return edge.target === nodeId && edge.targetHandle === port;
      }),
    [edges]
  );

  const isValidConnection = useCallback(
    (connection: Connection | RouteEdge) => {
      const source = connection.source;
      const target = connection.target;
      const sourceHandle = connection.sourceHandle;
      const targetHandle = connection.targetHandle;

      if (!source || !target || !sourceHandle || !targetHandle) return false;

      const currentEdgeId = (connection as RouteEdge).id;
      const sourceBusy = isPortBusy(source, sourceHandle, "source", currentEdgeId);
      const targetBusy = isPortBusy(target, targetHandle, "target", currentEdgeId);
      return !sourceBusy && !targetBusy;
    },
    [isPortBusy]
  );

  // Load sections
  useEffect(() => {
    if (open) {
      apiClient.get<Section[]>("/sections").then((r) => setSections(r.data)).catch(() => {});
    }
  }, [open]);

  // Delete node function (defined early for keyboard handler)
  const deleteNode = useCallback(
    (nodeId: string) => {
      setNodes((nds) => {
        const filtered = nds.filter((n) => n.id !== nodeId);
        // Update lastNodeId if we deleted the last node
        if (lastNodeId.current === nodeId) {
          lastNodeId.current = filtered.length > 0 ? filtered[filtered.length - 1].id : null;
        }
        return filtered;
      });
      setEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId));
      if (selectedNodeId === nodeId) setSelectedNodeId(null);
    },
    [setNodes, setEdges, selectedNodeId]
  );

  // Keyboard handler for delete
  useEffect(() => {
    if (!open) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Delete' || e.key === 'Backspace') {
        // Don't delete if typing in input
        const target = e.target as HTMLElement;
        if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT') {
          return;
        }

        if (selectedEdgeId) {
          setEdges((eds) => eds.filter((edge) => edge.id !== selectedEdgeId));
          setSelectedEdgeId(null);
        } else if (selectedNodeId) {
          deleteNode(selectedNodeId);
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, selectedEdgeId, selectedNodeId, deleteNode]);

  // Load section usage across all routes
  useEffect(() => {
    if (open) {
      apiClient.get<API.ProductionRoute[]>("/routes").then(async (r) => {
        const usage: Record<number, number> = {};
        for (const route of r.data) {
          const detail = await API.getRoute(route.id);
          for (const step of detail.steps) {
            usage[step.section_id] = (usage[step.section_id] || 0) + 1;
          }
        }
        setSectionUsage(usage);
      }).catch(() => {});
    }
  }, [open]);

  // Load existing route data
  useEffect(() => {
    if (route && open) {
      setName(route.name);
      setDescription(route.description || "");
      setIsActive(route.is_active);

      const newNodes: Node<RouteFlowNodeData>[] = route.steps.map((step, index) => ({
        id: `node-${step.id}`,
        type: "routeFlow",
        position: getGridPosition(index, route.steps.length),
        data: {
          section_id: step.section_id,
          section_code: step.section_code || "",
          section_name: step.section_name || "",
          icon: sections.find((s) => s.id === step.section_id)?.icon || null,
          icon_color: sections.find((s) => s.id === step.section_id)?.icon_color || null,
          operation_code: step.operation_code,
          operation_name: step.operation_name,
          norm_time_minutes: step.norm_time_minutes,
          is_final: step.is_final,
          allow_parallel: step.allow_parallel || false,
          requires_acceptance: step.requires_acceptance || false,
          usedInRoutes: sectionUsage[step.section_id] || 1,
        },
      }));

      const newEdges: Edge[] = [];
      for (let i = 0; i < route.steps.length - 1; i++) {
        newEdges.push({
          id: `edge-${i}`,
          source: `node-${route.steps[i].id}`,
          target: `node-${route.steps[i + 1].id}`,
          sourceHandle: "right",
          targetHandle: "left",
          type: "smart",
          animated: route.steps[i].allow_parallel,
        });
      }

      setNodes(newNodes);
      setEdges(newEdges);
      lastNodeId.current = getEndNodeId(newNodes as RouteNode[], newEdges as RouteEdge[]);
      setSelectedEdgeId(null);
    } else if (!route && open) {
      setName("");
      setDescription("");
      setIsActive(true);
      setNodes([]);
      setEdges([]);
      setSelectedNodeId(null);
      setSelectedEdgeId(null);
      lastNodeId.current = null;
    }
  }, [route, open, sections, sectionUsage, getEndNodeId]);

  const onConnect: OnConnect = useCallback(
    (params) => {
      if (!params.source || !params.target || !params.sourceHandle || !params.targetHandle) return;
      if (!isValidConnection(params)) return;

      const newEdge: Edge = {
        id: `${params.source}-${params.sourceHandle}-${params.target}-${params.targetHandle}`,
        source: params.source,
        target: params.target,
        sourceHandle: params.sourceHandle,
        targetHandle: params.targetHandle,
        type: 'smart',
        animated: false,
      };

      setEdges((eds) => addEdge(newEdge, eds));
    },
    [isValidConnection, setEdges]
  );

  const onReconnect = useCallback(
    (oldEdge: RouteEdge, newConnection: Connection) => {
      if (!newConnection.source || !newConnection.target || !newConnection.sourceHandle || !newConnection.targetHandle) {
        return;
      }
      if (!isValidConnection({ ...newConnection, id: oldEdge.id } as RouteEdge)) return;

      setEdges((currentEdges) =>
        reconnectEdge(
          oldEdge,
          {
            ...newConnection,
            sourceHandle: newConnection.sourceHandle,
            targetHandle: newConnection.targetHandle,
          },
          currentEdges
        )
      );
    },
    [isValidConnection, setEdges]
  );

  const insertNode = useCallback((sectionId: string) => {
    if (!insertTarget || !sectionId) return;
    const section = sections.find((s) => String(s.id) === sectionId);
    if (!section) return;

    const newNodeId = `node-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
    const newNode: Node<RouteFlowNodeData> = {
      id: newNodeId,
      type: "routeFlow",
      position: getGridPosition(nodes.length, nodes.length + 1),
      data: {
        section_id: section.id,
        section_code: section.code,
        section_name: section.name,
        icon: section.icon,
        icon_color: section.icon_color,
        operation_code: null,
        operation_name: "",
        norm_time_minutes: null,
        is_final: false,
        allow_parallel: false,
        requires_acceptance: false,
        usedInRoutes: sectionUsage[section.id] || 0,
      },
    };

    let nextEdges = [...edges];
    if (insertTarget.kind === "edge") {
      const edge = edges.find((e) => e.id === insertTarget.edgeId);
      if (!edge) return;
      const firstEdge: Edge = {
        id: `edge-${edge.source}-${newNodeId}`,
        source: edge.source,
        target: newNodeId,
        sourceHandle: edge.sourceHandle || "right",
        targetHandle: "left",
        type: "smart",
        animated: false,
      };
      const secondEdge: Edge = {
        id: `edge-${newNodeId}-${edge.target}`,
        source: newNodeId,
        target: edge.target,
        sourceHandle: "right",
        targetHandle: edge.targetHandle || "left",
        type: "smart",
        animated: false,
      };
      nextEdges = [...edges.filter((e) => e.id !== edge.id), firstEdge, secondEdge];
    } else if (insertTarget.kind === "start") {
      const startNode = nodes.find((n) => !edges.some((e) => e.target === n.id));
      if (startNode) {
        nextEdges.push({
          id: `edge-${newNodeId}-${startNode.id}`,
          source: newNodeId,
          target: startNode.id,
          sourceHandle: "right",
          targetHandle: "left",
          type: "smart",
          animated: false,
        });
      }
    } else if (insertTarget.kind === "end") {
      const endNode = nodes.find((n) => !edges.some((e) => e.source === n.id));
      if (endNode) {
        nextEdges.push({
          id: `edge-${endNode.id}-${newNodeId}`,
          source: endNode.id,
          target: newNodeId,
          sourceHandle: "right",
          targetHandle: "left",
          type: "smart",
          animated: false,
        });
      }
    }

    const nextNodes = [...nodes, newNode];
    setEdges(nextEdges);
    setNodes(relayoutNodesByOrder(nextNodes, nextEdges));
    setInsertTarget(null);
    lastNodeId.current = getEndNodeId(nextNodes, nextEdges);
  }, [insertTarget, edges, sections, sectionUsage, nodes, setNodes, setEdges, getEndNodeId]);

  const addSectionToRoute = useCallback(
    (section: Section) => {
      const index = nodes.length;
      const nextTotal = nodes.length + 1;
      const position = getGridPosition(index, nextTotal);

      const newNodeId = `node-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
      const newNode: Node<RouteFlowNodeData> = {
        id: newNodeId,
        type: "routeFlow",
        position,
        data: {
          section_id: section.id,
          section_code: section.code,
          section_name: section.name,
          icon: section.icon,
          icon_color: section.icon_color,
          operation_code: null,
          operation_name: "",
          norm_time_minutes: null,
          is_final: false,
          allow_parallel: false,
          requires_acceptance: false,
          usedInRoutes: sectionUsage[section.id] || 0,
        },
      };
      const nextNodes = [...nodes, newNode];
      let nextEdges = [...edges];
      const currentEndNodeId = getEndNodeId(nodes, edges);
      if (autoConnect && currentEndNodeId) {
        nextEdges = [
          ...nextEdges,
          {
            id: `edge-${currentEndNodeId}-${newNodeId}`,
            source: currentEndNodeId,
            target: newNodeId,
            sourceHandle: "right",
            targetHandle: "left",
            type: "smart",
            animated: false,
          } as Edge,
        ];
      }

      setEdges(nextEdges);
      setNodes(relayoutNodesByOrder(nextNodes, nextEdges));

      lastNodeId.current = getEndNodeId(nextNodes, nextEdges);
    },
    [autoConnect, nodes, sectionUsage, setEdges, setNodes, edges, getEndNodeId]
  );

  const updateNodeData = useCallback(
    (nodeId: string, patch: Partial<RouteFlowNodeData>) => {
      setNodes((nds) =>
        nds.map((node) =>
          node.id === nodeId ? { ...node, data: { ...node.data, ...patch } } : node
        )
      );
    },
    [setNodes]
  );

  const handleDelete = async () => {
    if (!route) return;
    try {
      await API.deleteRoute(route.id);
      toast({ variant: "success", title: "Удалено", description: `Маршрут "${route.name}" удалён` });
      onOpenChange(false);
      onSave();
    } catch (e) {
      toast({ variant: "destructive", title: "Ошибка", description: e instanceof Error ? e.message : "Не удалось удалить маршрут" });
    }
  };

  const handleSave = async () => {
    if (!name.trim()) {
      toast({ variant: "destructive", title: "Ошибка", description: "Название обязательно" });
      return;
    }
    if (nodes.length === 0) {
      toast({ variant: "destructive", title: "Ошибка", description: "Добавьте хотя бы один участок" });
      return;
    }

    setSaving(true);
    try {
      // Topological sort to determine sequence
      const inDegree: Record<string, number> = {};
      const adjList: Record<string, string[]> = {};

      for (const node of nodes) {
        inDegree[node.id] = 0;
        adjList[node.id] = [];
      }
      for (const edge of edges) {
        adjList[edge.source]?.push(edge.target);
        inDegree[edge.target] = (inDegree[edge.target] || 0) + 1;
      }

      const queue = Object.keys(inDegree).filter((id) => inDegree[id] === 0);
      const sorted: string[] = [];
      while (queue.length > 0) {
        const current = queue.shift()!;
        sorted.push(current);
        for (const neighbor of adjList[current] || []) {
          inDegree[neighbor]--;
          if (inDegree[neighbor] === 0) queue.push(neighbor);
        }
      }

      const steps: API.StepInput[] = sorted.map((nodeId, index) => {
        const node = nodes.find((n) => n.id === nodeId)!;
        const incomingEdges = edges.filter((e) => e.target === nodeId);
        return {
          sequence: (index + 1) * 10,
          section_id: node.data.section_id,
          operation_code: node.data.operation_code,
          operation_name: node.data.operation_name || node.data.section_name,
          norm_time_minutes: node.data.norm_time_minutes,
          is_final: node.data.is_final,
          allow_parallel: incomingEdges.length > 1 || node.data.allow_parallel,
          requires_acceptance: node.data.requires_acceptance,
        };
      });

      if (route) {
        await API.updateRoute(route.id, { name: name.trim(), description: description.trim() || null, is_active: isActive });
        await API.replaceSteps(route.id, steps);
        toast({ variant: "success", title: "Сохранено", description: "Маршрут обновлён" });
      } else {
        const created = await API.createRoute({ name: name.trim(), description: description.trim() || null, is_active: isActive });
        if (steps.length > 0) await API.replaceSteps(created.id, steps);
        toast({ variant: "success", title: "Создано", description: "Маршрут создан" });
      }
      onOpenChange(false);
      onSave();
    } catch (e) {
      toast({ variant: "destructive", title: "Ошибка", description: e instanceof Error ? e.message : "Ошибка сохранения" });
    } finally {
      setSaving(false);
    }
  };

  const selectedNode = nodes.find((n) => n.id === selectedNodeId);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[1400px] max-h-[90vh] w-[90vw] h-[85vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle>{route ? "Редактирование маршрута" : "Новый маршрут"}</DialogTitle>
          <DialogDescription>
            Перетащите участки из палитры на холст и соедините их стрелками
          </DialogDescription>
        </DialogHeader>

        {/* Basic Info */}
        <div className="flex items-end gap-4 py-2">
          <div className="w-52">
            <label className="text-sm font-medium">Название *</label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Основной маршрут" />
          </div>
          <div className="w-52">
            <label className="text-sm font-medium">Описание</label>
            <Input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Необязательно" />
          </div>
          <div>
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} className="h-4 w-4" />
              Активен
            </label>
          </div>
        </div>

        {/* Flow Builder */}
        <div className="flex-1 flex gap-4 min-h-[500px]">
          {/* Palette */}
          <div className="w-64 border rounded-lg p-3 overflow-y-auto bg-muted/30">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold">Участки</h3>
              <label className="flex items-center gap-1.5 text-xs cursor-pointer" title="Автоматически соединять новые участки с предыдущим">
                <input
                  type="checkbox"
                  checked={autoConnect}
                  onChange={(e) => setAutoConnect(e.target.checked)}
                  className="h-3.5 w-3.5"
                />
                <span className="text-muted-foreground">Авто</span>
              </label>
            </div>
            <div className="space-y-2">
              {sections.map((section) => (
                <div
                  key={section.id}
                  onClick={() => addSectionToRoute(section)}
                  className="group flex items-center gap-2 p-2 rounded-md border bg-card cursor-pointer hover:shadow-md transition-all"
                  style={{
                    borderLeft: section.icon_color ? `3px solid ${section.icon_color}` : undefined,
                  }}
                >
                  {section.icon && section.icon_color && (
                    <div
                      className="flex h-8 w-8 shrink-0 items-center justify-center rounded"
                      style={{ backgroundColor: section.icon_color + "20" }}
                    >
                      <span style={{ color: section.icon_color }}>
                        {renderIcon(section.icon, "h-4 w-4")}
                      </span>
                    </div>
                  )}
                  <div className="min-w-0">
                    <div className="text-xs font-medium text-muted-foreground">{section.code}</div>
                    <div className="text-sm truncate">{section.name}</div>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="ml-1 h-7 w-7 p-0 shrink-0 opacity-0 pointer-events-none group-hover:opacity-100 group-hover:pointer-events-auto transition-opacity"
                    onClick={(e) => {
                      e.stopPropagation();
                      addSectionToRoute(section);
                    }}
                    title="Добавить в маршрут"
                  >
                    <Plus className="h-3.5 w-3.5" />
                  </Button>
                </div>
              ))}
            </div>
          </div>

          {/* Canvas */}
          <div className="flex-1 border rounded-lg overflow-hidden min-h-[400px]">
            <ReactFlowProvider>
              <FlowCanvas
                open={open}
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                onReconnect={onReconnect}
                isValidConnection={isValidConnection}
                onInsertEdgeClick={(edgeId) => {
                  setInsertTarget({ kind: "edge", edgeId });
                }}
                onInsertAtStartClick={() => setInsertTarget({ kind: "start" })}
                onInsertAtEndClick={() => setInsertTarget({ kind: "end" })}
                onNodeClick={((_, node) => {
                  setSelectedNodeId(node.id);
                  setSelectedEdgeId(null);
                }) as NodeMouseHandler<RouteNode>}
                onEdgeClick={((_, edge) => {
                  setSelectedEdgeId(edge.id);
                  setSelectedNodeId(null);
                }) as EdgeMouseHandler<RouteEdge>}
                onPaneClick={() => {
                  setSelectedNodeId(null);
                  setSelectedEdgeId(null);
                }}
              />
            </ReactFlowProvider>
          </div>

          {/* Node Properties Panel */}
          {selectedNode && (
            <div className="w-72 border rounded-lg p-4 bg-card overflow-y-auto">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-semibold">Свойства этапа</h3>
                <Button variant="ghost" size="sm" onClick={() => setSelectedNodeId(null)}>
                  <X className="h-4 w-4" />
                </Button>
              </div>

              <div className="space-y-4">
                <div>
                  <label className="text-sm font-medium">Операция</label>
                  <select
                    className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm mt-1"
                    value={(selectedNode.data as RouteFlowNodeData).operation_code || ""}
                    onChange={(e) => {
                      const op = OPERATIONS.find((o) => o.value === e.target.value);
                      updateNodeData(selectedNode.id, {
                        operation_code: e.target.value || null,
                        operation_name: op?.label || "",
                      });
                    }}
                  >
                    <option value="">Выберите операцию</option>
                    {OPERATIONS.map((op) => (
                      <option key={op.value} value={op.value}>{op.label}</option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="text-sm font-medium">Время, мин</label>
                  <Input
                    type="number"
                    className="mt-1"
                    value={(selectedNode.data as RouteFlowNodeData).norm_time_minutes || ""}
                    onChange={(e) =>
                      updateNodeData(selectedNode.id, {
                        norm_time_minutes: e.target.value ? Number(e.target.value) : null,
                      })
                    }
                  />
                </div>

                <div className="space-y-2">
                  <label className="flex items-center gap-2 text-sm cursor-pointer">
                    <input
                      type="checkbox"
                      checked={(selectedNode.data as RouteFlowNodeData).is_final}
                      onChange={(e) => updateNodeData(selectedNode.id, { is_final: e.target.checked })}
                      className="h-4 w-4"
                    />
                    Финальный этап
                  </label>
                  <label className="flex items-center gap-2 text-sm cursor-pointer">
                    <input
                      type="checkbox"
                      checked={(selectedNode.data as RouteFlowNodeData).allow_parallel}
                      onChange={(e) => updateNodeData(selectedNode.id, { allow_parallel: e.target.checked })}
                      className="h-4 w-4"
                    />
                    Параллельное выполнение
                  </label>
                  <label className="flex items-center gap-2 text-sm cursor-pointer">
                    <input
                      type="checkbox"
                      checked={(selectedNode.data as RouteFlowNodeData).requires_acceptance}
                      onChange={(e) => updateNodeData(selectedNode.id, { requires_acceptance: e.target.checked })}
                      className="h-4 w-4"
                    />
                    Требует приемки
                  </label>
                </div>

                <Button variant="destructive" size="sm" className="w-full" onClick={() => deleteNode(selectedNode.id)}>
                  <Trash2 className="h-4 w-4 mr-1" />
                  Удалить этап
                </Button>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between pt-2 border-t">
          <div className="flex gap-2">
            {route && (
              <Button variant="destructive" onClick={() => setShowDeleteConfirm(true)}>
                <Trash2 className="h-4 w-4 mr-1" />
                Удалить маршрут
              </Button>
            )}
            <Button
              variant="outline"
              onClick={() => {
                setNodes([]);
                setEdges([]);
                setSelectedNodeId(null);
                setSelectedEdgeId(null);
                lastNodeId.current = null;
              }}
            >
              Очистить
            </Button>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>Отмена</Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? "Сохранение..." : "Сохранить"}
            </Button>
          </div>
        </div>
      </DialogContent>

      {/* Insert section between nodes */}
      <Dialog open={Boolean(insertTarget)} onOpenChange={(v) => !v && setInsertTarget(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>
              {insertTarget?.kind === "start"
                ? "Добавить участок в начало"
                : insertTarget?.kind === "end"
                ? "Добавить участок в конец"
                : "Добавить участок между этапами"}
            </DialogTitle>
            <DialogDescription>
              Выберите участок из списка
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <div className="max-h-64 overflow-y-auto space-y-1.5 pr-1">
              {sections.map((section) => {
                return (
                  <button
                    key={section.id}
                    type="button"
                    onClick={() => insertNode(String(section.id))}
                    className="w-full text-left flex items-center gap-2 p-1.5 rounded-md border transition-colors border-border bg-card hover:bg-muted/40"
                  >
                    {section.icon && section.icon_color && (
                      <div
                        className="flex h-8 w-8 shrink-0 items-center justify-center rounded"
                        style={{ backgroundColor: section.icon_color + "20" }}
                      >
                        <span style={{ color: section.icon_color }}>
                          {renderIcon(section.icon, "h-4 w-4")}
                        </span>
                      </div>
                    )}
                    <div className="min-w-0">
                      <div className="text-xs font-medium text-muted-foreground">{section.code}</div>
                      <div className="text-sm truncate">{section.name}</div>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog open={showDeleteConfirm} onOpenChange={setShowDeleteConfirm}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-destructive" />
              Удалить маршрут?
            </DialogTitle>
            <DialogDescription>
              {route && `Маршрут "${route.name}" будет удалён со всеми этапами. Это действие нельзя отменить.`}
            </DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setShowDeleteConfirm(false)}>Отмена</Button>
            <Button variant="destructive" onClick={handleDelete}>Удалить</Button>
          </div>
        </DialogContent>
      </Dialog>
    </Dialog>
  );
}
