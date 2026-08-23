import { useState } from "react";
import { GitBranch, Pencil, Undo2 } from "lucide-react";
import type { ActionTreeNode, JournalAction } from "@/shared/api/actions";
import { Button } from "@/shared/ui";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/shared/ui/dialog";
import { useActionTree } from "../hooks/useActions";
import {
  ActionTreeDialog,
} from "./ActionTreeDialog";
import { ReversePreviewDialog } from "./ReversePreviewDialog";
import { AmendDialog } from "./AmendDialog";

/** Операции строки журнала: дерево цепочки / Отменить / Изменить.
 *  «Изменить» — только transfer_send со статусом active (решение 5 спеки #117). */
export function JournalRowOperations({
  action,
  onChanged,
}: {
  action: JournalAction;
  onChanged: () => void;
}) {
  const [treeOpen, setTreeOpen] = useState(false);
  const [reverseOpen, setReverseOpen] = useState(false);
  const [amendOpen, setAmendOpen] = useState(false);
  const [selectedNode, setSelectedNode] = useState<ActionTreeNode | null>(null);
  // Контекстное действие дерева: клик по узлу переключает его, дерево
  // перезагружается для нового action_id.
  const [activeId, setActiveId] = useState(action.id);
  const tree = useActionTree(treeOpen ? activeId : null);

  const canReverse = action.status === "active";
  const canAmend = action.action_type === "transfer_send" && action.status === "active";

  return (
    <div className="flex items-center justify-end gap-1">
      <Button
        variant="outline"
        size="sm"
        title="Дерево цепочки"
        data-testid={`tree-button-${action.id}`}
        onClick={() => {
          setSelectedNode(null);
          setActiveId(action.id);
          setTreeOpen(true);
        }}
      >
        <GitBranch className="h-4 w-4" />
      </Button>
      <Button
        variant="outline"
        size="sm"
        title={canReverse ? "Отменить действие" : "Только активные действия"}
        disabled={!canReverse}
        data-testid={`reverse-button-${action.id}`}
        onClick={() => setReverseOpen(true)}
      >
        <Undo2 className="h-4 w-4" />
      </Button>
      <Button
        variant="outline"
        size="sm"
        title={
          canAmend
            ? "Изменить передачу"
            : "Изменение доступно только для активной transfer_send"
        }
        disabled={!canAmend}
        data-testid={`amend-button-${action.id}`}
        onClick={() => setAmendOpen(true)}
      >
        <Pencil className="h-4 w-4" />
      </Button>

      <Dialog open={treeOpen} onOpenChange={setTreeOpen}>
        <DialogContent className="max-w-lg" data-testid="tree-dialog">
          <DialogHeader>
            <DialogTitle>Цепочка действия #{activeId}</DialogTitle>
            <DialogDescription>
              Зависимости (depends_on) и статус узлов. Клик по узлу — выбор
              действия.
            </DialogDescription>
          </DialogHeader>
          <ActionTreeDialog
            tree={tree.data}
            isLoading={tree.isLoading}
            error={tree.error}
            selectedId={selectedNode?.id ?? null}
            onSelectNode={setSelectedNode}
            onPickAction={(id) => {
              setSelectedNode(null);
              setActiveId(id);
            }}
          />
        </DialogContent>
      </Dialog>

      <ReversePreviewDialog
        action={action}
        open={reverseOpen}
        onOpenChange={setReverseOpen}
        onReversed={onChanged}
      />
      <AmendDialog
        action={action}
        open={amendOpen}
        onOpenChange={setAmendOpen}
        onAmended={onChanged}
      />
    </div>
  );
}
