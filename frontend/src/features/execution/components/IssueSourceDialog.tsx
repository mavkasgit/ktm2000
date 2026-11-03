import { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { AlertCircle, Layers, Loader2, Package } from "lucide-react";
import {
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/shared/ui";
import { getErrorMessage } from "@/shared/api/client";
import { issuePreview, type IssueManualSelection } from "@/shared/api/productionPlans";
import { queryKeys } from "@/shared/api/queryKeys";
import { formatCompletedOperationsLabel, formatDimensionsLabel } from "@/shared/api/stock";
import type { ShortageStrategy } from "@/shared/api/shopfloor";
import { DIALOG_SIZES } from "@/shared/lib/dialogSizes";
import { TABLE_ROW_COMPACT } from "@/shared/lib/dataTableStyles";
import { fmtServerQty } from "@/shared/lib/quantityFormat";
import {
  ISSUE_DEFAULT_STRATEGY,
  ISSUE_SHORTAGE_OPTIONS,
  buildIssueSelection,
  isCandidateChecked,
  issueCollectLine,
  issueConfirmBlockReason,
  remainingAfterCell,
  toggleBalanceExcluded,
  visibleIssueHints,
} from "../lib/issueSource";

/**
 * Строки печатаются в присланном сервером порядке: `order` — единственный
 * порядок отображения, своего сравнения (по остатку, складу, операциям) здесь
 * нет. Локальная сортировка ломала бы смысл подбора — очередь выдачи идёт
 * именно так, как её посчитал `source_selection`.
 */
const ROW = { ...TABLE_ROW_COMPACT };

interface IssueSourceDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  positionId: number | null;
  positionSku: string;
  positionName: string;
  /** Запуск уже идёт: второе подтверждение не отправляет выдачу дважды. */
  pending: boolean;
  onConfirm: (selection: IssueManualSelection) => void;
  /**
   * Явный выбор одного остатка (#314) — alternate путь для тех, кому нужен
   * конкретный склад, а не подбор. Без него кнопка не показывается.
   */
  onPickExplicitSource?: () => void;
}

export function IssueSourceDialog({
  open,
  onOpenChange,
  positionId,
  positionSku,
  positionName,
  pending,
  onConfirm,
  onPickExplicitSource,
}: IssueSourceDialogProps) {
  // Снятые галочки живут ровно этот вызов: они не сохраняются и не едут на
  // следующую выдачу, поэтому при закрытии окна сбрасываются.
  const [excludedBalanceIds, setExcludedBalanceIds] = useState<number[]>([]);
  const [strategy, setStrategy] = useState<ShortageStrategy>(ISSUE_DEFAULT_STRATEGY);

  useEffect(() => {
    if (!open) {
      setExcludedBalanceIds([]);
      setStrategy(ISSUE_DEFAULT_STRATEGY);
    }
  }, [open]);

  // Порядок id в ключе кэша не должен плодить копии одного и того же набора.
  const excludedForKey = useMemo(
    () => [...excludedBalanceIds].sort((a, b) => a - b),
    [excludedBalanceIds],
  );

  const { data: preview, isLoading, isFetching, error } = useQuery({
    queryKey: queryKeys.execution.issuePreview(positionId as number, {
      excluded_balance_ids: excludedForKey,
    }),
    queryFn: () =>
      issuePreview(positionId as number, {
        // Схема сервера `extra="forbid`: лишних полей нет, а количество к
        // выпуску не вводится — `null` значит «количество позиции».
        excluded_balance_ids: excludedBalanceIds,
        release_quantity: null,
        product_id: null,
      }),
    enabled: open && positionId !== null,
    placeholderData: keepPreviousData,
  });

  const candidates = preview?.candidates ?? [];
  const hints = visibleIssueHints(preview?.hints ?? [], candidates);
  const blockReason = issueConfirmBlockReason({
    preview: preview ?? null,
    isLoading: isLoading || (isFetching && !pending),
    errorText: error ? getErrorMessage(error) : null,
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={`${DIALOG_SIZES.md.width} ${DIALOG_SIZES.md.height} gap-0 p-0`}>
        <DialogHeader className="px-5 pt-5 pb-3 border-b bg-muted/30">
          <DialogTitle className="flex items-center gap-2 text-base font-semibold">
            <Layers className="h-4 w-4 text-primary shrink-0" />
            <span>Взять в работу</span>
            <span
              className="ml-auto font-mono text-xs border border-primary/30 text-primary rounded-full px-2 py-0.5"
              data-testid="issue-source-sku"
            >
              {positionSku}
            </span>
          </DialogTitle>
          <DialogDescription>
            {positionName
              ? `${positionName}: откуда брать материал считает сервер — снять можно только галочку склада.`
              : "Откуда брать материал считает сервер — снять можно только галочку склада."}
          </DialogDescription>
        </DialogHeader>

        <div className="px-5 py-4 space-y-3">
          {isLoading && !preview ? (
            <div className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Подбор склада…
            </div>
          ) : error && !preview ? (
            <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
              <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
              <span data-testid="issue-preview-error">{getErrorMessage(error)}</span>
            </div>
          ) : (
            <>
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-sm leading-tight">
                <dt className="text-muted-foreground">Нужно</dt>
                <dd className="font-mono font-semibold tabular-nums">
                  {fmtServerQty(preview?.required)} шт.
                  {preview?.required_dimensions_label || preview?.required_dimensions ? (
                    <span className="ml-1 font-normal text-muted-foreground">
                      · {formatDimensionsLabel(preview?.required_dimensions, preview?.required_dimensions_label)}
                    </span>
                  ) : null}
                </dd>
              </dl>

              <section className="rounded-lg border px-3 py-2.5 space-y-2">
                <div className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  <Package className="h-3.5 w-3.5" />
                  Откуда брать
                </div>

                {candidates.length === 0 ? (
                  <div className="text-xs text-muted-foreground py-1">
                    Складов-кандидатов нет — подбирать нечего.
                  </div>
                ) : (
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b text-left text-muted-foreground">
                        <th className={`${ROW.headerCell} w-6`} />
                        <th className={ROW.headerCell}>Склад</th>
                        <th className={`${ROW.headerCell} text-right`}>Остаток</th>
                        <th className={`${ROW.headerCell} text-right`}>Возьмём</th>
                        <th className={`${ROW.headerCell} text-right`}>Останется после</th>
                      </tr>
                    </thead>
                    <tbody>
                      {candidates.map((candidate) => {
                        const checked = isCandidateChecked(candidate, excludedBalanceIds);
                        const remaining = remainingAfterCell(candidate.remaining_after);
                        return (
                          <tr
                            key={candidate.balance_id}
                            data-testid={`issue-candidate-row-${candidate.balance_id}`}
                            className="border-b border-border/50 last:border-0"
                          >
                            <td className={ROW.cell}>
                              <Checkbox
                                checked={checked}
                                aria-label={`Брать со склада «${candidate.location_name}»`}
                                onCheckedChange={(next) =>
                                  setExcludedBalanceIds((prev) =>
                                    toggleBalanceExcluded(prev, candidate.balance_id, next === true),
                                  )
                                }
                              />
                            </td>
                            <td className={ROW.cell}>
                              <div className="max-w-[180px] truncate font-medium" title={candidate.location_name}>
                                {candidate.location_name}
                              </div>
                              <div
                                className="text-muted-foreground max-w-[180px] truncate"
                                title={formatCompletedOperationsLabel(candidate.completed_operations)}
                              >
                                {formatCompletedOperationsLabel(candidate.completed_operations)}
                                <span className="ml-1">({candidate.ops_count})</span>
                                <span className="ml-1 text-muted-foreground/70">
                                  · {formatDimensionsLabel(candidate.dimensions)}
                                </span>
                              </div>
                            </td>
                            <td className={`${ROW.cell} text-right font-mono tabular-nums`}>
                              {fmtServerQty(candidate.available)}
                            </td>
                            <td className={`${ROW.cell} text-right font-mono tabular-nums`}>
                              {fmtServerQty(candidate.take)}
                            </td>
                            <td className={`${ROW.cell} text-right font-mono tabular-nums`}>
              <span
                data-testid={`issue-remaining-${candidate.balance_id}`}
                className={remaining.drawnOut ? "text-amber-700 dark:text-amber-400" : "text-muted-foreground"}
                title={
                  remaining.drawnOut
                    ? "Склад вычерпан целиком"
                    : remaining.notReached
                      ? "Не доходила очередь"
                      : undefined
                }
              >
                              {remaining.text}
                              {remaining.drawnOut ? " — вычерпан" : ""}
              </span>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}

                <p className="text-sm font-medium tabular-nums" data-testid="issue-collect-line">
                  {preview ? issueCollectLine(preview) : "Подбор ещё не посчитан"}
                </p>

                {hints.length > 0 ? (
                  <ul className="space-y-0.5 text-[11px] text-amber-700 dark:text-amber-400">
                    {hints.map((hint) => (
                      <li
                        key={`${hint.kind}-${hint.location_id}`}
                        data-testid={`issue-hint-${hint.location_id}-${hint.kind}`}
                      >
                        {hint.text}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </section>

              <div className="space-y-1.5">
                <div className="text-sm font-medium">Если не хватает</div>
                <Select value={strategy} onValueChange={(value) => setStrategy(value as ShortageStrategy)}>
                  <SelectTrigger data-testid="issue-shortage-strategy">
                    <SelectValue placeholder="Стратегия недостачи" />
                  </SelectTrigger>
                  <SelectContent>
                    {ISSUE_SHORTAGE_OPTIONS.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-[11px] text-muted-foreground leading-snug">
                  {ISSUE_SHORTAGE_OPTIONS.find((option) => option.value === strategy)?.hint}
                </p>
              </div>
            </>
          )}
        </div>

        <DialogFooter className="px-5 py-3 border-t bg-muted/20 gap-2">
          {/* Причина недоступности — текстом под кнопкой, а не `title`: по
              ADR-0032 её видно без наведения. */}
          {blockReason ? (
            <p
              className="mr-auto max-w-[60%] text-[11px] leading-tight text-destructive"
              data-testid="issue-confirm-reason"
            >
              {blockReason}
            </p>
          ) : null}
          {onPickExplicitSource ? (
            <Button variant="ghost" size="sm" onClick={onPickExplicitSource}>
              Выбрать один остаток
            </Button>
          ) : null}
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
            Отмена
          </Button>
          <Button
            size="sm"
            data-testid="issue-confirm-launch"
            disabled={Boolean(blockReason) || pending}
            onClick={() =>
              onConfirm(
                buildIssueSelection({
                  excludedBalanceIds,
                  strategy,
                  idempotencyKey: `take-to-work:${positionId}:${Date.now()}`,
                }),
              )
            }
          >
            {pending ? "Запуск…" : "Взять в работу"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
