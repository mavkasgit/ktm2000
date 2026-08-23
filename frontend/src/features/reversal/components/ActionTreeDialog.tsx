import { Fragment } from "react";
import type { ActionStatus, ActionTreeNode } from "@/shared/api/actions";
import { Button } from "@/shared/ui";
import { Loader2, Undo2 } from "lucide-react";

const STATUS_MARK: Record<ActionStatus, string> = {
  active: "🟢",
  reversed: "🔴",
  amended: "✏️",
};

function TreeRow({
  node,
  depth,
  selectedId,
  onSelect,
}: {
  node: ActionTreeNode;
  depth: number;
  selectedId: number | null;
  onSelect?: (node: ActionTreeNode) => void;
}) {
  const selected = selectedId === node.id;
  return (
    <>
      <button
        type="button"
        data-testid={`tree-node-${node.id}`}
        onClick={() => onSelect?.(node)}
        className={`flex w-full items-center gap-2 rounded px-2 py-1 text-left text-sm hover:bg-slate-100 ${
          selected ? "bg-slate-200 font-medium" : ""
        }`}
        style={{ paddingLeft: `${depth * 20 + 8}px` }}
      >
        <span aria-hidden>{STATUS_MARK[node.status] ?? "❔"}</span>
        <span className="font-mono">#{node.id}</span>
        <span>{node.action_type}</span>
        {node.ref_id != null && (
          <span className="text-xs text-slate-500">объект #{node.ref_id}</span>
        )}
      </button>
      {node.children.map((child) => (
        <TreeRow
          key={child.id}
          node={child}
          depth={depth + 1}
          selectedId={selectedId}
          onSelect={onSelect}
        />
      ))}
    </>
  );
}

export function ActionTreeDialog({
  tree,
  isLoading,
  error,
  selectedId = null,
  onSelectNode,
  onPickAction,
}: {
  tree: { root: ActionTreeNode; total_nodes: number } | undefined;
  isLoading: boolean;
  error: unknown;
  selectedId?: number | null;
  onSelectNode?: (node: ActionTreeNode) => void;
  onPickAction?: (actionId: number) => void;
}) {
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 py-6 text-sm text-slate-500">
        <Loader2 className="h-4 w-4 animate-spin" /> Загрузка цепочки…
      </div>
    );
  }
  if (error || !tree) {
    return (
      <p className="py-6 text-sm text-red-600">
        Не удалось загрузить дерево цепочки
      </p>
    );
  }
  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-500">
        Узлов в цепочке: {tree.total_nodes}
      </p>
      <div className="max-h-[50vh] overflow-auto rounded border border-slate-200 bg-slate-50/60 p-1">
        <TreeRow
          node={tree.root}
          depth={0}
          selectedId={selectedId}
          onSelect={onSelectNode}
        />
      </div>
      {onPickAction && (
        <Fragment>
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-testid="tree-pick-action"
            disabled={selectedId == null}
            onClick={() => selectedId != null && onPickAction(selectedId)}
          >
            <Undo2 className="mr-1 h-4 w-4" />
            Открыть действие #{selectedId ?? "—"}
          </Button>
        </Fragment>
      )}
    </div>
  );
}
