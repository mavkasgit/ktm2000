import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import type { Node, NodeProps } from "@xyflow/react";
import { Badge } from "@/shared/ui/Badge";
import { renderIcon } from "@/shared/ui/EntityDialog";
import { CheckCircle, GitBranch } from "lucide-react";

export interface RouteFlowNodeData extends Record<string, unknown> {
  section_id: number;
  section_code: string;
  section_name: string;
  icon: string | null;
  icon_color: string | null;
  operation_code: string | null;
  operation_name: string;
  norm_time_minutes: number | null;
  is_final: boolean;
  allow_parallel: boolean;
  requires_acceptance: boolean;
  usedInRoutes?: number;
  // Track whether port is occupied by any connection (incoming or outgoing)
  occupiedPorts?: {
    right?: boolean;
    left?: boolean;
  };
  isStartNode?: boolean;
  isEndNode?: boolean;
  onInsertAtStart?: () => void;
  onInsertAtEnd?: () => void;
}

function RouteFlowNodeComponent({ data, selected }: NodeProps<Node<RouteFlowNodeData>>) {
  const nodeData = data as RouteFlowNodeData;
  const occupied = nodeData.occupiedPorts || {};

  const getPortStyle = (port: 'right' | 'left') => {
    const isOccupied = Boolean(occupied[port]);

    return {
      width: 16,
      height: 16,
      background: isOccupied ? '#6b7280' : '#3b82f6',
      border: '3px solid white',
      boxShadow: isOccupied ? '0 0 0 2px rgba(107, 114, 128, 0.5)' : '0 0 0 1px rgba(59, 130, 246, 0.3)',
      transition: 'all 0.15s ease',
      cursor: isOccupied ? 'not-allowed' : 'crosshair',
      opacity: isOccupied ? 0.6 : 1,
    };
  };

  const getPortTitle = (port: 'right' | 'left') => {
    const isOccupied = Boolean(occupied[port]);
    return isOccupied ? `Порт ${port} занят` : `Порт ${port} свободен`;
  };

  return (
    <div
      className={`
        relative min-w-[180px] rounded-lg border-2 bg-card p-3 shadow-sm transition-all
        ${selected ? "border-primary ring-2 ring-primary/20" : "border-border"}
        ${nodeData.is_final ? "border-green-500 bg-green-50/50" : ""}
      `}
    >
      <Handle
        type="source"
        position={Position.Right}
        style={getPortStyle('right')}
        className="hover:!w-5 hover:!h-5 hover:!bg-blue-600 hover:shadow-lg active:scale-90"
        id="right"
        title={getPortTitle('right')}
      />

      {/* Header: Icon + Name */}
      <div className="flex items-start gap-2 mb-2">
        {nodeData.icon && nodeData.icon_color && (
          <div
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md"
            style={{ backgroundColor: nodeData.icon_color + "20" }}
          >
            <span style={{ color: nodeData.icon_color }}>
              {renderIcon(nodeData.icon, "h-5 w-5")}
            </span>
          </div>
        )}
        <div className="flex-1 min-w-0">
          <div className="text-xs font-medium text-muted-foreground">{nodeData.section_code}</div>
          <div className="text-sm font-semibold truncate">{nodeData.section_name}</div>
        </div>
      </div>

      {/* Operation */}
      {nodeData.operation_code && (
        <div className="mb-2 rounded bg-muted px-2 py-1 text-xs font-mono">
          {nodeData.operation_code}
        </div>
      )}

      {/* Time */}
      {nodeData.norm_time_minutes && (
        <div className="text-xs text-muted-foreground mb-2">
          ⏱ {nodeData.norm_time_minutes} мин
        </div>
      )}

      {/* Badges */}
      <div className="flex flex-wrap gap-1">
        {nodeData.is_final && (
          <Badge variant="outline" className="bg-green-50 text-green-700 border-green-200 text-[10px]">
            <CheckCircle className="h-3 w-3 mr-1" />
            Финал
          </Badge>
        )}
        {nodeData.allow_parallel && (
          <Badge variant="outline" className="bg-blue-50 text-blue-700 border-blue-200 text-[10px]">
            <GitBranch className="h-3 w-3 mr-1" />
            Параллельно
          </Badge>
        )}
      </div>

      <Handle
        type="source"
        position={Position.Left}
        style={getPortStyle('left')}
        className="hover:!w-5 hover:!h-5 hover:!bg-blue-600 hover:shadow-lg active:scale-90"
        id="left"
        title={getPortTitle('left')}
      />

      {nodeData.isStartNode && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            nodeData.onInsertAtStart?.();
          }}
          className="absolute left-[-14px] top-1/2 -translate-y-1/2 h-6 w-6 rounded-full border bg-background text-muted-foreground hover:text-foreground hover:border-primary shadow-sm text-sm leading-none"
          title="Добавить в начало"
        >
          +
        </button>
      )}
      {nodeData.isEndNode && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            nodeData.onInsertAtEnd?.();
          }}
          className="absolute right-[-14px] top-1/2 -translate-y-1/2 h-6 w-6 rounded-full border bg-background text-muted-foreground hover:text-foreground hover:border-primary shadow-sm text-sm leading-none"
          title="Добавить в конец"
        >
          +
        </button>
      )}
    </div>
  );
}

export const RouteFlowNode = memo(RouteFlowNodeComponent);
RouteFlowNode.displayName = "RouteFlowNode";
