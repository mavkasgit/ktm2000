import { useState } from "react";
import { GitBranch, Pencil, Undo2 } from "lucide-react";
import type { ActionTreeNode, JournalAction } from "@/shared/api/actions";
import { ADMIN_ONLY_REVERSE_ACTION_TYPES } from "@/shared/api/actions";
import { Button } from "@/shared/ui";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { POLICIES } from "@/features/auth/policies";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/shared/ui/dialog";
import { actionTypeLabel } from "../lib/actionColumns";
import { TABLE_ROW_DENSE } from "@/shared/lib/dataTableStyles";
import { useActionTree } from "../hooks/useActions";
import {
  ActionTreeDialog,
} from "./ActionTreeDialog";
import { ReversePreviewDialog } from "./ReversePreviewDialog";
import { AmendDialog } from "./AmendDialog";

/**
 * Кнопки строки — плотные, как во всех остальных таблицах журнала: штатный
 * `size="sm"` даёт h-9 (36px), и строка в 32px (`TABLE_ROW_DENSE.rowHeightPx`)
 * от кнопки растёт — колонка «Операции» выходит выше соседних строк (ADR-0030).
 */
const ACTION_BUTTON_CLASS = TABLE_ROW_DENSE.actionButton;
const ACTION_ICON_CLASS = "h-3.5 w-3.5";

/** Операции строки журнала: дерево цепочки / Отменить / Изменить.
 *  «Изменить» — только передача со статусом active (решение 5 спеки #117). */
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

  const { user } = useAuth();
  // Откат импорта остатков — отдельное право админа (ADR-0052 п.6):
  // сервер ответит 403, поэтому кнопка не показывается вовсе, а не ведёт
  // зрителя в ошибку. Неактивное действие (status ≠ active) — напротив,
  // обычная disabled-кнопка с причиной в title.
  const reverseByRoleForbidden =
    ADMIN_ONLY_REVERSE_ACTION_TYPES.includes(
      action.action_type as (typeof ADMIN_ONLY_REVERSE_ACTION_TYPES)[number],
    ) && !POLICIES.rollbackImport(user?.role);
  const canReverse = action.status === "active";
  const canAmend = action.action_type === "transfer_send" && action.status === "active";

  return (
    <div className="flex items-center justify-end gap-1">
      <Button
        variant="outline"
        className={ACTION_BUTTON_CLASS}
        title="Дерево цепочки"
        data-testid={`tree-button-${action.id}`}
        onClick={() => {
          setSelectedNode(null);
          setActiveId(action.id);
          setTreeOpen(true);
        }}
      >
        <GitBranch className={ACTION_ICON_CLASS} />
      </Button>
      {!reverseByRoleForbidden && (
        <Button
          variant="outline"
          className={ACTION_BUTTON_CLASS}
          title={canReverse ? "Отменить действие" : "Только активные действия"}
          disabled={!canReverse}
          data-testid={`reverse-button-${action.id}`}
          onClick={() => setReverseOpen(true)}
        >
          <Undo2 className={ACTION_ICON_CLASS} />
        </Button>
      )}
      <Button
        variant="outline"
        className={ACTION_BUTTON_CLASS}
        title={
          canAmend
            ? "Изменить передачу"
            : `Изменение доступно только для активной ${actionTypeLabel(action.action_type)}`
        }
        disabled={!canAmend}
        data-testid={`amend-button-${action.id}`}
        onClick={() => setAmendOpen(true)}
      >
        <Pencil className={ACTION_ICON_CLASS} />
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
