/**
 * Список батчей импорта плана с действиями над ними (ADR-0054).
 *
 * Живёт только на отдельной странице «История импортов плана»
 * (`/planning/import-history`). На странице плана таблицы файлов нет: прошлый
 * импорт был верхней панелью на пути к позициям, а история импорта — не
 * рабочее поле оператора, ведущего план.
 *
 * Список кросс-плановый: в нём батчи **всех** планов. План на странице плана
 * не выбирается — она всегда работает с первым из `listPlans`, — поэтому
 * история одного плана прятала бы импорты остальных, а `all-plan-files`
 * отдаёт файлы всех планов и так.
 *
 * Откат — LIFO **внутри плана** (ADR-0025, спека §4.5): «последний
 * применённый» считается по `applied_at` среди батчей того же плана, иначе
 * свежий импорт второго плана гасил бы откат у первого.
 *
 * «Убрать из списка» — не откат и не удаление: батч прячется, а позиции,
 * задачи, ledger и журнал остаются как были (ADR-0056). «Удалить» — отдельное
 * действие: батч исчезает из истории вместе с данными, живой downstream даёт
 * 409 и выбор: удалить одни черновики или (админом, с подтверждением имени
 * файла) снести поддерево батча.
 */
import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { toast } from "@/shared/ui";
import { getErrorMessage } from "@/shared/api/client";
import { queryKeys } from "@/shared/api/queryKeys";
import { invalidateAfter } from "@/shared/api/cacheInvalidation";
import {
  allPlanFiles,
  deleteImportBatch,
  hideImportBatch,
  listPlans,
  type BatchDeleteConflict,
} from "@/shared/api/productionPlans";
import { BatchDeleteBlockersDialog } from "./BatchDeleteBlockersDialog";
import { FileRow } from "./PlanFileRow";
import { parseBatchDeleteConflict } from "../lib/batchDeleteConflict";
import { lastAppliedBatchIdByPlan } from "../lib/appliedBatches";

type PendingDelete = {
  planId: number;
  batchId: number;
  filename: string;
  conflict: BatchDeleteConflict;
};

export function PlanImportHistoryPanel() {
  const queryClient = useQueryClient();
  const [pendingDelete, setPendingDelete] = useState<PendingDelete | null>(null);
  const [deletingDrafts, setDeletingDrafts] = useState(false);
  // Тумблер чтения: по умолчанию скрытых батчей в списке нет — в этом и смысл
  // «убрать из списка». Включённый тумблер просит у сервера `include_hidden`.
  const [includeHidden, setIncludeHidden] = useState(false);

  const { data: files, isLoading, error } = useQuery({
    queryKey: queryKeys.plan.allFiles(includeHidden),
    queryFn: () => allPlanFiles({ includeHidden }),
  });
  // LIFO-гейт отката (ADR-0025) считается по ПОЛНОМУ списку, включая скрытые:
  // убранный из списка батч не перестаёт быть последним применённым, иначе
  // скрытие разрешило бы откатить более старый батч — «спрятать» не значит
  // «освободить место в очереди отката». Когда скрытые и так показаны, полный
  // список уже в руках и второй запрос не нужен.
  const { data: allFiles } = useQuery({
    queryKey: queryKeys.plan.allFiles(true),
    queryFn: () => allPlanFiles({ includeHidden: true }),
    enabled: !includeHidden,
  });
  // Подпись плана для колонки: батч несёт только `production_plan_id`, а
  // план — номер и имя. Обе выборки идут по одному и тому же фильтру
  // (`ProductionPlan.deleted_at IS NULL`), поэтому расхождение — гонка двух
  // запросов, а не норма: подпись тогда деградирует до «План #id», а адрес
  // действия остаётся верным.
  const { data: plans } = useQuery({ queryKey: queryKeys.execution.plans(), queryFn: listPlans });
  const plansById = useMemo(() => new Map((plans ?? []).map((plan) => [plan.id, plan])), [plans]);

  const lastAppliedBatchIdByPlanId = useMemo(
    () => lastAppliedBatchIdByPlan((includeHidden ? files : allFiles) ?? []),
    [files, allFiles, includeHidden],
  );

  const planLabel = (planId: number): string => {
    const plan = plansById.get(planId);
    return plan ? `${plan.plan_no} · ${plan.name}` : `План #${planId}`;
  };

  const handleHideFile = async (planId: number, batchId: number) => {
    try {
      await hideImportBatch(planId, batchId);
      // Скрытие меняет только состав списка импортов: позиции, задачи, остатки
      // и журнал не тронуты, поэтому домен один — `plan` (ADR-0056).
      void invalidateAfter(queryClient, "importHidden");
      toast({
        title: "Импорт убран из списка",
        description: "Позиции, задачи и остатки не тронуты. Показать — тумблером ниже",
        variant: "success",
      });
    } catch (e) {
      toast({
        title: "Ошибка",
        description: e instanceof Error ? e.message : "Не удалось убрать импорт из списка",
        variant: "destructive",
      });
    }
  };

  const handleDeleteFile = async (planId: number, batchId: number) => {
    try {
      await deleteImportBatch(planId, batchId);
      void invalidateAfter(queryClient, "importDiscarded");
      toast({ title: "Импорт удалён", variant: "success" });
    } catch (e) {
      const conflict = parseBatchDeleteConflict(e);
      // Действие берём из ответа (safe_action), не хардкодим: неизвестное или
      // отсутствующее поле парсер отсекает в null — экран блокировок тогда не
      // открываем, а показываем ошибку.
      if (conflict && conflict.safe_action === "delete_drafts_only") {
        const filename = files?.find((f) => f.batch_id === batchId)?.filename ?? `батч #${batchId}`;
        setPendingDelete({ planId, batchId, filename, conflict });
        return;
      }
      toast({
        title: "Ошибка",
        description: e instanceof Error ? e.message : "Не удалось удалить импорт",
        variant: "destructive",
      });
    }
  };

  const handleConfirmDeleteDrafts = async () => {
    if (!pendingDelete) return;
    setDeletingDrafts(true);
    try {
      const result = await deleteImportBatch(pendingDelete.planId, pendingDelete.batchId, {
        deleteDraftsOnly: true,
      });
      void invalidateAfter(queryClient, "importDiscarded");
      toast({
        title: result.deleted ? "Импорт удалён" : `Черновики удалены (${result.deleted_drafts ?? 0})`,
        description: result.deleted ? undefined : "Запущенные позиции, задачи и передачи не тронуты",
        variant: "success",
      });
      setPendingDelete(null);
    } catch (e) {
      toast({
        title: "Ошибка",
        description: e instanceof Error ? e.message : "Не удалось удалить черновики",
        variant: "destructive",
      });
    } finally {
      setDeletingDrafts(false);
    }
  };

  return (
    <>
      {/* Тумблер живёт у таблицы, а не в шапке страницы: он меняет состав
          списка, то есть это фильтр данных, а не кнопка обновления. */}
      <div className="flex items-center gap-2 pb-2">
        <input
          id="plan-history-include-hidden"
          type="checkbox"
          checked={includeHidden}
          onChange={(event) => setIncludeHidden(event.target.checked)}
        />
        <label htmlFor="plan-history-include-hidden" className="text-sm text-muted-foreground">
          Показывать убранные из списка
        </label>
      </div>
      {isLoading && <p className="p-4 text-sm text-muted-foreground">Загрузка...</p>}
      {error != null && (
        <p className="p-4 text-sm text-destructive">
          Не удалось загрузить список импортов: {getErrorMessage(error)}
        </p>
      )}
      {files && files.length === 0 && (
        <div className="rounded-lg border border-dashed p-12 text-center">
          <p className="text-sm text-muted-foreground">
            Импортов плана пока нет. Файл загружается на странице «План».
          </p>
        </div>
      )}
      {files && files.length > 0 && (
        <div className="overflow-auto rounded-lg border">
          <table className="w-full">
            <thead className="border-b bg-muted/50">
              <tr>
                <th className="text-left p-3 text-xs font-medium text-muted-foreground">План</th>
                <th className="text-left p-3 text-xs font-medium text-muted-foreground">Файл</th>
                <th className="text-left p-3 text-xs font-medium text-muted-foreground">Дата загрузки</th>
                <th className="text-left p-3 text-xs font-medium text-muted-foreground">Лист</th>
                <th className="text-left p-3 text-xs font-medium text-muted-foreground">Строк</th>
                <th className="text-left p-3 text-xs font-medium text-muted-foreground">Размер</th>
                <th className="text-left p-3 text-xs font-medium text-muted-foreground">Статус</th>
                <th className="text-left p-3 text-xs font-medium text-muted-foreground">Действия</th>
              </tr>
            </thead>
            <tbody>
              {/* Порядок — серверный (`ImportBatch.created_at DESC`): свежие
                  сверху. Своей сортировки здесь нет намеренно — иначе их две. */}
              {files.map((file) => (
                <FileRow
                  key={file.batch_id}
                  file={file}
                  planId={file.production_plan_id}
                  planLabel={planLabel(file.production_plan_id)}
                  isLastApplied={
                    lastAppliedBatchIdByPlanId.get(file.production_plan_id) === file.batch_id
                  }
                  onDelete={handleDeleteFile}
                  onHide={handleHideFile}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {pendingDelete && (
        <BatchDeleteBlockersDialog
          open
          onOpenChange={(open) => {
            if (!open) setPendingDelete(null);
          }}
          filename={pendingDelete.filename}
          conflict={pendingDelete.conflict}
          deleting={deletingDrafts}
          onConfirmDrafts={handleConfirmDeleteDrafts}
          planId={pendingDelete.planId}
          batchId={pendingDelete.batchId}
          onForceDeleted={() => {
            setPendingDelete(null);
            void invalidateAfter(queryClient, "importForceDeleted");
          }}
        />
      )}
    </>
  );
}
