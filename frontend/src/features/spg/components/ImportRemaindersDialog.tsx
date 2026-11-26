import { useState, useRef, useEffect, useMemo, useCallback, Fragment, memo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle, Download, Loader2 } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  Button,
  Input,
  Badge,
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
  SectionSelect,
  SectionLocationBadge,
  DataTableColumnHeader,
  TableCornerResetCell,
  TableCornerResetHeader,
  DATA_TABLE_STYLES,
  TABLE_ROW_COMPACT,
  FiltersPanel,
  VirtualizedTableBody,
  toast,
  renderIcon,
} from "@/shared/ui";
import type { FiltersPanelField } from "@/shared/ui";
import { useFilterableTable } from "@/shared/hooks/useFilterableTable";
import { buildColumnApiParams, buildColumnFilterValues } from "@/shared/lib/columnSpecs";
import { getAriaSort } from "@/shared/lib/multiSort";
import { saveBlobAsFile } from "@/shared/lib/downloadFile";
import {
  remainderPreviewColumns,
  REMAINDER_PREVIEW_CHEVRON_COLUMN_WIDTH,
  REMAINDER_PREVIEW_RESET_COLUMN_WIDTH,
} from "../lib/remainderPreviewColumns";
import { isOptimalColumnWidthsEnabled } from "../lib/optimalColumnWidthsFlag";
import {
  previewErrorsCellText,
  previewErrorsText,
  previewNameCellClass,
} from "../lib/remainderPreviewErrors";
import { PREVIEW_MIN_ROW_HEIGHT_PX } from "../lib/previewColumnWidths";
import { useOptimalColumnWidths } from "../lib/useOptimalColumnWidths";

import {
  useImportRowExpansion,
  useImportClipboardPaste,
  ImportUpload,
  ImportPreview,
  ImportRawRows,
  getImportDialogContentClass,
} from "@/shared/ui/import-utils";
import {
  previewRemaindersExcel,
  importRemaindersExcel,
  downloadRemaindersImportTemplate,
  getRemainderImportOperations,
  getRemainderSheets,
  formatQualityStateLabel,
  formatDimensionsLabel,
  formatCompletedOperationsLabel,
  completedOperationsServerLabel,
  OPERATIONS_EMPTY_LABEL,
  OPERATIONS_NOT_RECORDED_LABEL,
  IMPORT_QUALITY_OPTIONS,
  normalizeImportQualityState,
  type QualityState,
  type RemainderPreviewResponse,
  type RemainderImportSource,
  type RemainderSheet,
  type RemainderSheetKind,
  type ImportOperationStep,
} from "@/shared/api/stock";
import { getErrorMessage } from "@/shared/api/client";
import { translateImportError } from "@/shared/api/errorMessages";
import { invalidateAfter } from "@/shared/api/cacheInvalidation";
import { queryKeys } from "@/shared/api/queryKeys";
import { RouteStepsDisplay } from "@/shared/ui/RouteStepsDisplay";
import { listSections } from "@/shared/api/sections";
import type { Section } from "@/shared/api/sections";
import type { RemainderImportItem, RemainderSectionMeta } from "@/shared/api/stock";
import { useDebouncedValue } from "@/shared/lib/useDebouncedValue";
import { fmtQty, fmtQtyPrecise } from "@/shared/lib/quantityFormat";
import {
  buildRemainderPreviewSortParam,
  DEFAULT_REMAINDER_PREVIEW_SORT,
  type RemainderPreviewSortField,
} from "@/shared/lib/stockSortParams";

function hasSectionInFile(item: Pick<RemainderImportItem, "target_section_name">): boolean {
  const name = item.target_section_name?.trim();
  return Boolean(name && name !== "—" && name !== "-");
}

/**
 * Истёк серверный токен источника (#472): сервер отвечает 410, и файл нужно
 * отправить заново. Это не ошибка листа — повтор прозрачен для оператора.
 */
function isPreviewSourceGone(error: unknown): boolean {
  return (error as { response?: { status?: number } } | null)?.response?.status === 410;
}

function getEffectiveSectionId(
  item: Pick<RemainderImportItem, "source_row_number" | "target_section_id">,
  defaultSectionId: number | null,
  overrides: Record<number, number>,
): number | null {
  if (overrides[item.source_row_number] != null) {
    return overrides[item.source_row_number];
  }
  if (item.target_section_id != null) {
    return item.target_section_id;
  }
  return defaultSectionId;
}

function getEffectiveSectionIdFromMeta(
  row: RemainderSectionMeta,
  overrides: Record<number, number>,
): number | null {
  return getEffectiveSectionId(row, null, overrides);
}

function buildRemainderPreviewColumnApiParams(
  columnFilters: Partial<Record<RemainderPreviewSortField, Set<string>>>,
  columnSearchQueries: Partial<Record<RemainderPreviewSortField, string>>,
) {
  return buildColumnApiParams(columnFilters, columnSearchQueries, remainderPreviewColumns);
}

function getEffectiveQualityState(
  item: RemainderImportItem,
  overrides: Record<number, QualityState>,
): QualityState {
  if (overrides[item.source_row_number] != null) {
    return overrides[item.source_row_number];
  }
  return normalizeImportQualityState(item.quality_state);
}

/**
 * Серверная подпись оси операций строки предпросмотра: то, что ждёт
 * `?operations=` и с чем сравнивает `_preview_operations_label`.
 *
 * Правило повторяет `_row_completed_operations` (`stock/import_service.py`):
 * колонки нет или текст не разрешился в справочник — «не зафиксировано»
 * (NULL-группа), ячейка есть, но пустая (в т.ч. «—», «-» и пробелы) — «без
 * операций» (`[]`), разрешённые этапы — их имена. Разбор нужен именно здесь:
 * в списке фильтра стоят серверные подписи, а ячейка печатает прочерк для
 * обоих пустых состояний — по прочерку их не различить (ADR-0055 п.5).
 */
const EMPTY_OPERATIONS_CELLS = new Set(["", "—", "-"]);

export function getImportItemOperationsServerLabel(item: RemainderImportItem): string {
  const raw = item.completed_operations_raw;
  if (raw != null && EMPTY_OPERATIONS_CELLS.has(raw.trim())) return OPERATIONS_EMPTY_LABEL;
  // `?.` — граница с сервером: поле объявлено списком, но ответ без
  // `completed_stages` (старый бэкенд, null) не должен ронять диалог при
  // сборке списка фильтра. Отсутствие — не «без операций»: состояние
  // пустоты несёт `completed_operations_raw`.
  if (!item.completed_stages?.length) return OPERATIONS_NOT_RECORDED_LABEL;
  return completedOperationsServerLabel(undefined, item.completed_stages);
}

/**
 * Подпись оси операций строки предпросмотра в ячейке — единое правило
 * подписи (#242, ADR-0055 п.5).
 *
 * Превью не отдаёт ось отдельным полем (в ответе `completed_operations_raw` и
 * разрешённые `completed_stages`), поэтому правило работает по названиям
 * этапов: `undefined` — это «ответ без `completed_operations`», ветка,
 * оставленная для таких ответов. Оба пустых состояния — и «колонки нет»
 * (NULL), и «ячейка пуста» (`[]`) — печатают прочерк, как любая ячейка с
 * пустым состоянием.
 *
 * Список фильтра берёт не эту, а серверную подпись
 * (`getImportItemOperationsServerLabel` в `getImportItemCellValue`): иначе
 * выбор значения уехал бы туда, чего в ячейке нет, и молча вернул бы ноль
 * строк (`_preview_operations_label`, `stock/import_service.py`).
 */
export function getImportItemOperationsLabel(item: RemainderImportItem): string {
  return formatCompletedOperationsLabel(undefined, item.completed_stages);
}

function getImportItemQualityLabel(
  item: RemainderImportItem,
  qualityOverrides: Record<number, QualityState>,
): string {
  const state = getEffectiveQualityState(item, qualityOverrides);
  return (
    IMPORT_QUALITY_OPTIONS.find((option) => option.value === state)?.label
    ?? formatQualityStateLabel(state)
  );
}

function getImportItemSectionLabel(
  item: RemainderImportItem,
  sectionOverrides: Record<number, number>,
  sections: { id: number; name: string }[],
): string {
  if (hasSectionInFile(item) && item.target_section_name) {
    return item.target_section_name;
  }
  const sectionId = getEffectiveSectionId(item, null, sectionOverrides);
  if (sectionId == null) return "—";
  return sections.find((section) => section.id === sectionId)?.name ?? `#${sectionId}`;
}

function getImportItemCellValue(
  item: RemainderImportItem,
  field: RemainderPreviewSortField,
  sectionOverrides: Record<number, number>,
  qualityOverrides: Record<number, QualityState>,
  sections: { id: number; name: string }[],
): string {
  switch (field) {
    case "row":
      return String(item.source_row_number);
    case "sku":
      return item.sku;
    case "quantity":
      return item.quantity != null ? String(item.quantity) : "—";
    case "length":
      return formatDimensionsLabel(item.dimensions, item.dimensions_label);
    case "operations":
      // Список фильтра — серверные подписи: ячейка печатает прочерк обоим
      // пустым состояниям, а сервер различает «не зафиксировано» и «без
      // операций» (ADR-0055 п.5).
      return getImportItemOperationsServerLabel(item);
    case "quality":
      return getImportItemQualityLabel(item, qualityOverrides);
    case "section":
      return getImportItemSectionLabel(item, sectionOverrides, sections);
    case "errors":
      return previewErrorsText(item);
  }
}

function qualityBadgeClass(state: QualityState): string {
  switch (state) {
    case "FINAL_SCRAP":
      return "bg-rose-50/50 text-rose-700 border-rose-200 dark:bg-rose-950/20 dark:text-rose-400 dark:border-rose-900/50";
    case "SCRAP":
      return "bg-amber-50/50 text-amber-700 border-amber-200 dark:bg-amber-950/20 dark:text-amber-400 dark:border-amber-900/50";
    default:
      return "bg-emerald-50/50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/20 dark:text-emerald-400 dark:border-emerald-900/50";
  }
}

/** Пустые карты оверрайдов: стабильная ссылка, чтобы мемо не пересобиралось. */
const EMPTY_SECTION_OVERRIDES: Record<number, number> = {};
const EMPTY_QUALITY_OVERRIDES: Record<number, QualityState> = {};

/**
 * Видимая категория строк предпросмотра (#472).
 *
 * ``default`` — то, что импортируется и требует внимания: годные и ошибочные
 * строки. ``skipped`` (реестр исключений) по умолчанию скрыт: на листе
 * заказчика его сотни, и оператор листал их, чтобы дойти до рабочих строк.
 */
type PreviewStatusFilter = "default" | "invalid" | "skipped";

function qualityStateLabel(state: QualityState): string {
  return (
    IMPORT_QUALITY_OPTIONS.find((option) => option.value === state)?.label
    ?? formatQualityStateLabel(state)
  );
}

/** Участок строки, которую нельзя менять (skipped/invalid): только чтение. */
function getStaticSectionLabel(
  item: RemainderImportItem,
  sections: { id: number; name: string }[],
): string {
  const name = item.target_section_name?.trim();
  if (name && name !== "—" && name !== "-") return name;
  if (item.target_section_id == null) return "—";
  return sections.find((section) => section.id === item.target_section_id)?.name
    ?? `#${item.target_section_id}`;
}

type PreviewRowProps = {
  item: RemainderImportItem;
  sections: Section[];
  operations: ImportOperationStep[] | undefined;
  expanded: boolean;
  qualityOverride: QualityState | null;
  sectionOverride: number | null;
  /**
   * Под флагом #483 «Наименование» переносится: ширина колонки посчитана, а
   * высота строки предсказана моделью. Без флага — прежний `truncate`.
   */
  nameWraps: boolean;
  /**
   * Предсказанная моделью высота строки (#483), px. Живёт в `data-*` только
   * для наблюдаемости: E2E #484 сверяет её с фактической высотой `<tr>`.
   * На раскладку не влияет; без флага — `null`.
   */
  predictedHeight: number | null;
  onToggle: (rowNumber: number) => void;
  onQualityChange: (rowNumber: number, state: QualityState) => void;
  onSectionChange: (rowNumber: number, sectionId: number | null) => void;
};

/**
 * Строка предпросмотра. Мемоизирована и получает оверрайды примитивами:
 * переключение качества/участка в одной строке не перерисовывает соседние.
 *
 * Качество и участок интерактивны только у ``valid``: у пропущенной и
 * ошибочной строки импорт их не применит, поэтому там статичный бейдж, а не
 * ``Select`` (ADR-0030 — строка остаётся компактной).
 *
 * Без флага #483 текстовые ячейки печатаются одной строкой (`truncate`), а
 * полное значение — в `title`: виртуализатор не знал переменной высоты.
 * Под флагом ширина колонок посчитана, высота каждой строки предсказана
 * моделью, и «Наименование» печатается полностью (`whitespace-pre-line`).
 */
const PreviewRow = memo(function PreviewRow({
  item,
  sections,
  operations,
  expanded,
  qualityOverride,
  sectionOverride,
  nameWraps,
  predictedHeight,
  onToggle,
  onQualityChange,
  onSectionChange,
}: PreviewRowProps) {
  const rowKey = item.source_row_number;
  const isSkipped = item.status === "skipped";
  const isInvalid = item.status === "invalid";
  const isInteractive = item.status === "valid";
  const hasRaw = item.raw_values.length > 0;
  const qualityState = qualityOverride ?? normalizeImportQualityState(item.quality_state);
  const sectionLabel = getStaticSectionLabel(item, sections);

  return (
    <Fragment>
      <tr
        data-row-key={rowKey}
        data-predicted-height={predictedHeight ?? undefined}
        onClick={() => hasRaw && onToggle(rowKey)}
        className={`border-b transition-colors cursor-pointer hover:bg-muted/30 ${
          isInvalid
            ? "bg-red-50/50 dark:bg-red-950/5"
            : isSkipped
              ? "bg-amber-50/40 dark:bg-amber-950/5"
              : ""
        }`}
      >
        <td className="px-1 py-0.5 text-left">
          <ImportRawRows.Chevron expanded={expanded} hasContent={hasRaw} />
        </td>
        <td className="px-1.5 py-0.5 text-left font-bold text-muted-foreground tabular-nums">
          {item.source_row_number}
        </td>
        <td
          className="px-1.5 py-0.5 font-mono tabular-nums whitespace-nowrap overflow-hidden text-ellipsis"
          title={item.source_code ?? undefined}
        >
          {item.source_code ?? "—"}
        </td>
        <td
          className="px-1.5 py-0.5 font-mono font-semibold whitespace-nowrap overflow-hidden text-ellipsis"
          title={
            item.matched_sku && item.matched_sku !== item.sku
              ? `${item.sku} → найдено: ${item.matched_sku}`
              : item.sku
          }
        >
          {item.sku}
          {item.matched_sku && item.matched_sku !== item.sku ? (
            <span className="ml-1 font-sans font-normal text-amber-700">→ {item.matched_sku}</span>
          ) : null}
        </td>
        <td
          className={`px-1.5 py-0.5 ${previewNameCellClass(nameWraps)} ${item.product_name ? "text-foreground" : "text-muted-foreground"}`}
          title={item.source_name ?? item.product_name ?? undefined}
        >
          {item.product_name ?? item.source_name ?? "—"}
        </td>
        <td className="px-1.5 py-0.5 font-semibold text-foreground tabular-nums text-right">
          {fmtQty(item.quantity)}
        </td>
        <td className="px-1.5 py-0.5 tabular-nums whitespace-nowrap text-right">
          {fmtQtyPrecise(item.source_quantity_m)}
        </td>
        <td
          className={`px-1.5 py-0.5 tabular-nums whitespace-nowrap overflow-hidden text-ellipsis ${
            item.dimensions ? "font-medium text-foreground" : "text-muted-foreground"
          }`}
          title={formatDimensionsLabel(item.dimensions, item.dimensions_label)}
        >
          {formatDimensionsLabel(item.dimensions, item.dimensions_label)}
        </td>
        <td className="px-1.5 py-0.5 overflow-hidden">
          {item.completed_stages && item.completed_stages.length > 0 ? (
            <RouteStepsDisplay
              steps={item.completed_stages}
              referenceOps={operations}
              compact
              size="sm"
              // Одна строка: перенос пилюль поднимал высоту строки (ADR-0030).
              nowrap
            />
          ) : (
            <span className="block truncate text-xs text-muted-foreground">
              {getImportItemOperationsLabel(item)}
            </span>
          )}
        </td>
        <td
          className="px-1.5 py-0.5"
          onClick={(e) => e.stopPropagation()}
        >
          {isInteractive ? (
            <Select
              value={qualityState}
              onValueChange={(value) => onQualityChange(rowKey, value as QualityState)}
            >
              <SelectTrigger
                className={`h-6 w-full text-[10px] font-semibold border px-2 ${qualityBadgeClass(
                  qualityState,
                )}`}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {IMPORT_QUALITY_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <span
              className={`inline-flex h-6 w-full items-center justify-center rounded-md border px-2 text-[10px] font-semibold ${qualityBadgeClass(
                qualityState,
              )}`}
            >
              {qualityStateLabel(qualityState)}
            </span>
          )}
        </td>
        <td
          className="px-1.5 py-0.5"
          onClick={(e) => e.stopPropagation()}
        >
          {hasSectionInFile(item) ? (
            <SectionLocationBadge
              sections={sections}
              sectionId={item.target_section_id}
              sectionName={item.target_section_name}
              invalid={!item.target_section_id}
              size="sm"
            />
          ) : isInteractive ? (
            <SectionSelect
              sections={sections}
              value={sectionOverride ?? item.target_section_id ?? null}
              onValueChange={(sectionId) => onSectionChange(rowKey, sectionId)}
              placeholder="Выберите участок"
              className="h-6 w-full text-[10px]"
            />
          ) : (
            <span className="text-xs text-muted-foreground">{sectionLabel}</span>
          )}
        </td>
        <td
          className={`px-1.5 py-0.5 font-medium leading-snug ${
            isSkipped
              ? "whitespace-nowrap text-amber-700 dark:text-amber-400"
              : "whitespace-pre-line text-destructive"
          }`}
        >
          {previewErrorsCellText(item)}
        </td>
        <TableCornerResetCell />
      </tr>
      {expanded && hasRaw ? (
        // Шеврон + все колонки + ячейка сброса фильтров: детализация должна
        // растягиваться на всю ширину.
        <ImportRawRows.Detail
          colSpan={remainderPreviewColumns.length + 2}
          values={item.raw_values}
        />
      ) : null}
    </Fragment>
  );
});


/** Подпись типа листа на вкладке (спека §9). */
const SHEET_KIND_LABELS: Record<RemainderSheetKind, string> = {
  "1c_osv": "ОСВ 1С",
  manual_template: "шаблон",
  unknown: "неизвестно",
};

function sheetTabLabel(sheet: RemainderSheet): string {
  return `${sheet.name} · ${SHEET_KIND_LABELS[sheet.kind]}`;
}

/**
 * Ключ кэша предпросмотра: лист и параметры страницы.
 *
 * `location_id` в ключ не входит: сервер проверяет только его существование,
 * строки от него не зависят (спека §5.2), а участок как раз берётся из ответа
 * предпросмотра — ключ с ним замкнулся бы сам на себя.
 */
function buildPreviewCacheKey(
  sheetIndex: number,
  params: Record<string, unknown>,
): string {
  const parts = Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== "")
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([name, value]) => `${name}=${String(value)}`);
  return `${sheetIndex}|${parts.join("&")}`;
}

/** Итог применения одного листа в режиме «все листы ОСВ» (спека §9). */
type MultiSheetOutcome = {
  sheetIndex: number;
  sheetName: string;
  sectionId: number | null;
  sectionName: string | null;
  status: "applied" | "failed";
  imported: number;
  skipped: number;
  errors: string[];
  /** Причина остановки: ошибка листа, а не ошибки отдельных строк. */
  error: string | null;
};

interface ImportRemaindersDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}

const headerCellClass = `${DATA_TABLE_STYLES.headerRow} ${DATA_TABLE_STYLES.headerCell}`;
// Итоговая таблица мультилиста — та же компактная строка, что у соседей
// (ADR-0030): размеры берутся из общего набора, своих `px-*` у неё нет.
const summaryHeaderCellClass = `${DATA_TABLE_STYLES.headerRow} ${TABLE_ROW_COMPACT.headerCell}`;
const summaryCellClass = TABLE_ROW_COMPACT.cell;

/**
 * Сколько строк предпросмотра просит диалог: лист целиком, без пагинации.
 * Потолок совпадает с `PREVIEW_ITEMS_MAX_LIMIT` на сервере; больше листа
 * одного ОСВ не бывает на практике, а строки сверх потолка достаются
 * поиском/фильтрами (они применяются до нарезки страницы).
 */
const PREVIEW_ALL_ROWS_LIMIT = 5000;

/** Флаг #483: без него экран ведёт себя как раньше — текущие доли колонок. */
const OPTIMAL_COLUMN_WIDTHS_ENABLED = isOptimalColumnWidthsEnabled();

export function ImportRemaindersDialog({
  open,
  onOpenChange,
  onSaved,
}: ImportRemaindersDialogProps) {
  const queryClient = useQueryClient();

  // ── Operations reference ──────────────────────────────────────────────
  const {
    data: operations,
    isLoading: operationsLoading,
    isError: operationsError,
  } = useQuery({
    queryKey: queryKeys.stock.remainderImportOperations(),
    queryFn: () => getRemainderImportOperations(),
    enabled: open,
  });

  // ── Sections list for target selector ─────────────────────────────────
  const {
    data: allSections,
    isLoading: sectionsLoading,
    isError: sectionsError,
  } = useQuery({
    queryKey: queryKeys.sections.all(),
    queryFn: () => listSections(),
    enabled: open,
  });

  // Справочники обязательны для шага upload: без них нечего показывать
  const referencesLoading = operationsLoading || sectionsLoading;
  const referencesError = operationsError || sectionsError;

  const importableSections = useMemo(() => {
    if (!allSections) return [];
    return allSections
      .filter((s) => s.is_active && s.type !== "production")
      .sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name, "ru"));
  }, [allSections]);

  // Примеры участков для таблицы-подсказки: первые складские участки в порядке справочника
  const exampleTargetSections = useMemo(() => {
    const [first, second, third] = importableSections;
    return {
      raw: first?.name ?? "—",
      prep: (second ?? first)?.name ?? "—",
      wip: (third ?? second ?? first)?.name ?? "—",
    };
  }, [importableSections]);

  // Примеры операций для таблицы-подсказки: первые операции справочника.
  // Порядок задан сервером (section.sort_order → operation.sort_order), без литералов в коде
  const exampleOperations = useMemo(
    () => (operations ?? []).slice(0, 3).map((op) => op.operation_name),
    [operations],
  );
  const exampleRow2Operations = exampleOperations[0] ?? "—";
  const exampleRow3Operations = exampleOperations.length > 0 ? exampleOperations.join(", ") : "—";

  // ── State machine ─────────────────────────────────────────────────────
  const [step, setStep] = useState<"upload" | "preview" | "result">("upload");
  const [importMode, setImportMode] = useState<"file" | "clipboard">("file");
  const [file, setFile] = useState<File | null>(null);
  const [clipboardText, setClipboardText] = useState("");
  // Вкладки — листы файла с типом; `index` — настоящий индекс листа Excel,
  // он же `sheet_index` запроса, поэтому позиция вкладки и индекс не путаются.
  const [sheetTabs, setSheetTabs] = useState<RemainderSheet[]>([]);
  const [selectedSheet, setSelectedSheet] = useState(0);
  // Кэш предпросмотра по листу и параметрам страницы — как в `ImportWizard`
  // импорта плана: возврат на вкладку не повторяет запрос.
  const [previewCache, setPreviewCache] = useState<Record<string, RemainderPreviewResponse>>({});
  const [previewLoadingKeys, setPreviewLoadingKeys] = useState<Record<string, boolean>>({});
  // Последнее показанное превью листа: пока грузится новый фильтр, таблица
  // остаётся на экране вместе с полем поиска и его фокусом (ADR-0060 п.1).
  const [lastPreviewBySheet, setLastPreviewBySheet] = useState<Record<number, RemainderPreviewResponse>>({});
  // Первый полный нефильтрованный ответ листа — вход модели ширин (#483).
  // Поиск, сортировка и чипы приходят позже и раскладку не пересчитывают.
  const [widthItemsBySheet, setWidthItemsBySheet] = useState<Record<number, RemainderImportItem[]>>({});
  const [sheetsLoading, setSheetsLoading] = useState(false);
  const [rowSelection, setRowSelection] = useState("");
  const [clearExisting, setClearExisting] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const debouncedSearch = useDebouncedValue(searchQuery);
  // Категория строк — только представление: лист уже загружен целиком, и
  // переключение чипа не ходит на сервер (#472).
  const [filterStatus, setFilterStatus] = useState<PreviewStatusFilter>("default");
  // Оверрайды живут по листам: номер строки в разных листах — разные строки,
  // и общая карта при переключении вкладки переписала бы чужой лист.
  const [targetSectionOverridesBySheet, setTargetSectionOverridesBySheet] = useState<
    Record<number, Record<number, number>>
  >({});
  const [qualityStateOverridesBySheet, setQualityStateOverridesBySheet] = useState<
    Record<number, Record<number, QualityState>>
  >({});
  const targetSectionOverrides = targetSectionOverridesBySheet[selectedSheet] ?? EMPTY_SECTION_OVERRIDES;
  const qualityStateOverrides =
    qualityStateOverridesBySheet[selectedSheet] ?? EMPTY_QUALITY_OVERRIDES;
  const resetAllPreviewFilters = useCallback(() => {
    setFilterStatus("default");
    setSearchQuery("");
  }, []);
  const {
    bindColumn,
    columnFilters,
    columnSearchQueries,
    debouncedColumnSearchQueries,
    sortConfigs,
    handleSort: applySort,
    setSortConfigs,
    hasActiveFilters: hasPreviewFilters,
    resetAll: resetPreviewFilters,
    resetColumnFilters,
  } = useFilterableTable<RemainderPreviewSortField>({
    extraHasActive: Boolean(searchQuery.trim() || filterStatus !== "default"),
    onExtraReset: resetAllPreviewFilters,
  });

  const columnApiParams = useMemo(
    () => buildRemainderPreviewColumnApiParams(columnFilters, debouncedColumnSearchQueries),
    [columnFilters, debouncedColumnSearchQueries],
  );

  const sort = buildRemainderPreviewSortParam(sortConfigs);

  const handleSortChange = useCallback(
    (field: RemainderPreviewSortField) => {
      applySort(field);
    },
    [applySort],
  );

  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ imported_count: number; errors: string[] } | null>(null);
  const [multiOutcomes, setMultiOutcomes] = useState<MultiSheetOutcome[] | null>(null);
  const [multiRunning, setMultiRunning] = useState(false);

  const expansion = useImportRowExpansion();
  const { toggleRow, isRowExpanded, resetExpansion } = expansion;

  const fileInputRef = useRef<HTMLInputElement>(null);
  // Версия источника предпросмотра: новый файл/буфер/открытие диалога её
  // поднимают, и ответ прошлого источника не попадает в кэш нового (ключ
  // кэша — лист и параметры, файла в нём нет).
  const previewSourceVersion = useRef(0);
  // Токен источника с сервера: после первого ответа файл больше не
  // отправляется — только параметры фильтра/сортировки (#472).
  const previewSourceToken = useRef<string | null>(null);

  // ── Preview request identity and per-sheet cache ──────────────────────
  // Параметры без `location_id`: ключ кэша не должен зависеть от участка,
  // который сам берётся из ответа предпросмотра.
  //
  // Клиентской пагинации нет: лист запрашивается целиком, чтобы оператор видел
  // все строки без переключения страниц. Сервер режет ответ потолком
  // `PREVIEW_ITEMS_MAX_LIMIT` (5000); строки сверх него достаются поиском и
  // фильтрами — они применяются до нарезки страницы.
  //
  // Статуса в параметрах нет: лист приходит целиком (`all`), а категорию
  // `valid/invalid/skipped` считает клиент — смена чипа не шлёт запрос (#472).
  const previewParams = useMemo(
    () => ({
      sheet_index: selectedSheet,
      row_selection: rowSelection || undefined,
      search: debouncedSearch.trim() || undefined,
      sort,
      limit: PREVIEW_ALL_ROWS_LIMIT,
      offset: 0,
      ...columnApiParams,
    }),
    [
      selectedSheet,
      rowSelection,
      debouncedSearch,
      sort,
      columnApiParams,
    ],
  );

  const previewKey = useMemo(
    () => buildPreviewCacheKey(selectedSheet, previewParams),
    [selectedSheet, previewParams],
  );
  const previewData = previewCache[previewKey] ?? null;
  const previewLoading = Boolean(previewLoadingKeys[previewKey]);

  // Пока грузится новый фильтр того же листа, на экране остаётся его прежнее
  // превью: иначе поле поиска размонтировалось бы и потеряло фокус (ADR-0060).
  const shownPreview = previewData ?? lastPreviewBySheet[selectedSheet] ?? null;

  useEffect(() => {
    if (!previewData) return;
    setLastPreviewBySheet((prev) =>
      prev[selectedSheet] === previewData ? prev : { ...prev, [selectedSheet]: previewData },
    );
  }, [previewData, selectedSheet]);

  // Снапшот для модели ширин — первая же (нефильтрованная) выдача листа.
  // Если лист впервые открыли уже с фильтром, снапшота нет: экран честно
  // остаётся на текущих долях, а не считает ширины по подвыборке.
  useEffect(() => {
    if (!previewData) return;
    // `sort` не бывает пустым: без выбора оператора он равен
    // `DEFAULT_REMAINDER_PREVIEW_SORT` (`row:asc`). Считать дефолтный порядок
    // фильтром нельзя — иначе первый ответ листа никогда не считался бы
    // «полным нефильтрованным», снапшот ширин не появлялся и таблица под
    // флагом навсегда оставалась на спиннере (#484 поймал это в браузере).
    const unfiltered =
      !debouncedSearch.trim() &&
      !rowSelection &&
      sort === DEFAULT_REMAINDER_PREVIEW_SORT &&
      Object.keys(columnApiParams).length === 0;
    if (!unfiltered) return;
    setWidthItemsBySheet((prev) =>
      prev[selectedSheet]?.length ? prev : { ...prev, [selectedSheet]: previewData.items },
    );
  }, [previewData, selectedSheet, debouncedSearch, rowSelection, sort, columnApiParams]);

  // ── Resolve location id for API (из файла, per-row override или первая валидная строка) ──
  const resolveImportLocationId = useMemo((): number | null => {
    if (!shownPreview?.section_meta) return null;
    const firstResolved = shownPreview.section_meta.find(
      (row) =>
        row.status === "valid" &&
        getEffectiveSectionIdFromMeta(row, targetSectionOverrides) != null,
    );
    if (!firstResolved) return null;
    return getEffectiveSectionIdFromMeta(firstResolved, targetSectionOverrides);
  }, [shownPreview, targetSectionOverrides]);

  const resetPreviewState = useCallback(() => {
    setSheetTabs([]);
    setSelectedSheet(0);
    setPreviewCache({});
    setPreviewLoadingKeys({});
    setLastPreviewBySheet({});
    setWidthItemsBySheet({});
    previewSourceToken.current = null;
  }, []);

  // ── Reset state when dialog opens ─────────────────────────────────────
  useEffect(() => {
    if (open) {
      previewSourceVersion.current += 1;
      setStep("upload");
      setImportMode("file");
      setFile(null);
      setClipboardText("");
      resetPreviewState();
      setRowSelection("");
      setClearExisting(false);
      resetExpansion();
      setSearchQuery("");
      setFilterStatus("default");
      setTargetSectionOverridesBySheet({});
      setQualityStateOverridesBySheet({});
      setSortConfigs([]);
      resetColumnFilters();
      setError(null);
      setResult(null);
      setMultiOutcomes(null);
      setMultiRunning(false);
    }
  }, [open, resetExpansion, resetColumnFilters, resetPreviewState]);

  const getImportSource = (): RemainderImportSource | null => {
    if (importMode === "file" && file) {
      return { kind: "file", file };
    }
    if (importMode === "clipboard" && clipboardText.trim()) {
      return { kind: "clipboard", clipboardText: clipboardText.trim() };
    }
    return null;
  };

  const previewQueryOptions = useMemo(
    () => ({
      ...previewParams,
      location_id: resolveImportLocationId ?? undefined,
    }),
    [previewParams, resolveImportLocationId],
  );

  // ── Load preview when relevant params change ──────────────────────────
  useEffect(() => {
    if (step !== "preview" || !getImportSource()) return;
    loadPreview();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, importMode, file, clipboardText, previewKey, previewQueryOptions]);

  const loadPreview = async () => {
    const source = getImportSource();
    if (!source) return;
    const key = buildPreviewCacheKey(selectedSheet, previewParams);
    if (previewCache[key] || previewLoadingKeys[key]) return;
    const sourceVersion = previewSourceVersion.current;
    setPreviewLoadingKeys((prev) => ({ ...prev, [key]: true }));
    setError(null);
    try {
      // Токен есть — файл уже на сервере: шлём только параметры (#472).
      const token = previewSourceToken.current;
      const request = (useToken: string | null) =>
        previewRemaindersExcel(useToken ? null : source, {
          ...previewQueryOptions,
          source_token: useToken ?? undefined,
        });
      let data;
      try {
        data = await request(token);
      } catch (err: unknown) {
        // Серверный кэш живёт TTL: протухший токен — это не ошибка файла,
        // а повод один раз переотправить его.
        if (!token || !isPreviewSourceGone(err)) throw err;
        previewSourceToken.current = null;
        data = await request(null);
      }
      if (previewSourceVersion.current !== sourceVersion) return;
      if (data.source_token) previewSourceToken.current = data.source_token;
      setPreviewCache((prev) => ({ ...prev, [key]: data }));
    } catch (err: unknown) {
      if (previewSourceVersion.current !== sourceVersion) return;
      setError(getErrorMessage(err) || "Не удалось загрузить предварительный просмотр листа.");
    } finally {
      if (previewSourceVersion.current === sourceVersion) {
        setPreviewLoadingKeys((prev) => ({ ...prev, [key]: false }));
      }
    }
  };

  // ── File selection handler ────────────────────────────────────────────
  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const selectedFile = e.target.files[0];
      previewSourceVersion.current += 1;
      setImportMode("file");
      setClipboardText("");
      setFile(selectedFile);
      setError(null);
      // Новый файл — новое решение об очистке: прежняя галочка относилась к
      // другому складу и к другому набору листов.
      setClearExisting(false);
      resetPreviewState();
      setSheetsLoading(true);
      try {
        const fileSheets = await getRemainderSheets(selectedFile);
        setSheetTabs(fileSheets);
        // По умолчанию — первый лист ОСВ: он и есть режим «Остатки из 1С»
        // (спека §9). Если ОСВ в файле нет, показываем первый лист как есть.
        const defaultSheet =
          fileSheets.find((sheet) => sheet.kind === "1c_osv") ?? fileSheets[0] ?? null;
        setSelectedSheet(defaultSheet?.index ?? 0);
        setStep("preview");
      } catch (err: unknown) {
        setError(getErrorMessage(err) || "Ошибка при чтении структуры Excel-файла");
        setFile(null);
      } finally {
        setSheetsLoading(false);
      }
    }
  };

  const applyClipboardText = useCallback((text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    previewSourceVersion.current += 1;
    setImportMode("clipboard");
    setClipboardText(trimmed);
    setFile(null);
    setClearExisting(false);
    resetPreviewState();
    setSheetTabs([
      {
        index: 0,
        name: "Буфер обмена",
        kind: "manual_template",
        detected_section_id: null,
        detected_section_name: null,
      },
    ]);
    setSelectedSheet(0);
    setError(null);
    setFilterStatus("default");
    setSearchQuery("");
    setStep("preview");
  }, [resetPreviewState]);

  useImportClipboardPaste({
    enabled: open && step === "upload",
    onPaste: applyClipboardText,
  });

  // ── Download template ─────────────────────────────────────────────────
  const downloadTemplate = async () => {
    const locId = importableSections[0]?.id ?? null;
    if (!locId) {
      toast({ title: "Нет доступных складских участков для шаблона", variant: "destructive" });
      return;
    }
    try {
      const blob = await downloadRemaindersImportTemplate(locId);
      saveBlobAsFile(blob, "Шаблон импорта остатков.xlsx");
    } catch (err) {
      console.error("Не удалось скачать шаблон", err);
      setError("Не удалось загрузить шаблон Excel.");
    }
  };

  // ── Import mutation ───────────────────────────────────────────────────
  const importMutation = useMutation({
    mutationFn: (skipInvalid: boolean) => {
      const locId = resolveImportLocationId;
      const source = getImportSource();
      if (!locId) throw new Error("Не выбран участок");
      if (!source) throw new Error("Не выбран источник данных");
      return importRemaindersExcel(locId, source, {
        sheet_index: selectedSheet,
        row_selection: rowSelection || undefined,
        skip_invalid: skipInvalid,
        clear_existing: clearExisting,
        target_section_overrides:
          Object.keys(targetSectionOverrides).length > 0 && !clearExisting
            ? targetSectionOverrides
            : undefined,
        quality_state_overrides:
          Object.keys(qualityStateOverrides).length > 0 ? qualityStateOverrides : undefined,
      });
    },
    onSuccess: (response) => {
      if (response.success) {
        setResult({
          imported_count: response.imported_count,
          errors: response.errors,
        });
        void invalidateAfter(queryClient, "stockChanged");
        onSaved();
        setStep("result");
      } else {
        setError(
          `Импорт отклонен. Обнаружено ошибок: ${response.errors.length}. Загрузите исправленный файл или примените импорт с пропуском ошибок.`,
        );
      }
    },
    onError: (e: unknown) => {
      setError(getErrorMessage(e) || "Ошибка при импорте Excel-файла");
    },
  });

  const handleApply = (skipInvalid: boolean) => {
    if (!getImportSource()) return;
    if (!resolveImportLocationId) {
      toast({
        title: clearExisting ? "Укажите участок для очистки" : "Укажите участок для импорта",
        description: clearExisting
          ? "При очистке укажите участок в колонке «Участок» файла или выберите для строк в таблице."
          : "Заполните колонку «Участок» в файле или выберите участок для каждой строки в таблице.",
        variant: "destructive",
      });
      return;
    }
    if (rowsMissingSection.length > 0) {
      toast({
        title: "Не для всех строк указан участок",
        description: `Строк без участка: ${rowsMissingSection.length}. Заполните колонку «Участок» или выберите в таблице.`,
        variant: "destructive",
      });
      return;
    }
    setError(null);
    importMutation.mutate(skipInvalid);
  };

  const handleClose = () => {
    setStep("upload");
    // Кэш и незавершённые ответы предпросмотра не переживают закрытие:
    // следующий сеанс начинает с чистого листа.
    previewSourceVersion.current += 1;
    resetPreviewState();
    onOpenChange(false);
  };

  const handleRowSectionChange = useCallback((rowNumber: number, sectionId: number | null) => {
    setTargetSectionOverridesBySheet((prev) => {
      const current = prev[selectedSheet] ?? EMPTY_SECTION_OVERRIDES;
      const next = { ...current };
      if (sectionId == null) {
        delete next[rowNumber];
      } else {
        next[rowNumber] = sectionId;
      }
      return { ...prev, [selectedSheet]: next };
    });
  }, [selectedSheet]);

  const handleRowQualityChange = useCallback((rowNumber: number, state: QualityState) => {
    setQualityStateOverridesBySheet((prev) => {
      const current = prev[selectedSheet] ?? EMPTY_QUALITY_OVERRIDES;
      return { ...prev, [selectedSheet]: { ...current, [rowNumber]: state } };
    });
  }, [selectedSheet]);

  const rowsMissingSection = useMemo(() => {
    if (!shownPreview?.section_meta) return [];
    return shownPreview.section_meta.filter(
      (row) =>
        row.status === "valid" &&
        getEffectiveSectionIdFromMeta(row, targetSectionOverrides) == null,
    );
  }, [shownPreview, targetSectionOverrides]);

  const previewItems = useMemo(() => shownPreview?.items ?? [], [shownPreview]);
  const previewItemsTotal = shownPreview?.items_total ?? 0;

  const stats = useMemo(() => {
    if (!shownPreview) return { total: 0, valid: 0, skipped: 0, invalid: 0, qty: 0 };
    return {
      total: shownPreview.summary.total,
      valid: shownPreview.summary.valid,
      skipped: shownPreview.summary.skipped ?? 0,
      invalid: shownPreview.summary.invalid,
      qty: shownPreview.summary.quantity_total,
    };
  }, [shownPreview]);

  // Категория — клиентская: лист уже на экране целиком, поэтому чип не шлёт
  // запрос. По умолчанию видны годные и ошибочные, пропущенные скрыты (#472).
  const visibleItems = useMemo(() => {
    if (filterStatus === "skipped") return previewItems.filter((item) => item.status === "skipped");
    if (filterStatus === "invalid") return previewItems.filter((item) => item.status === "invalid");
    return previewItems.filter((item) => item.status !== "skipped");
  }, [previewItems, filterStatus]);

  // Читатели значения колонок не зависят от оверрайдов качества/участка:
  // список значений фильтра от них не меняется, а пересборка описания колонок
  // перебирала бы все строки на каждый выбор в строке таблицы (#472).
  // Колонки без `filterField` читателя не получают (#322).
  const previewValueColumns = useMemo(
    () =>
      remainderPreviewColumns.map((column) => {
        const field = column.filterField;
        if (!field) return column;
        return {
          ...column,
          cellValue: (item: RemainderImportItem) =>
            getImportItemCellValue(
              item,
              field,
              EMPTY_SECTION_OVERRIDES,
              EMPTY_QUALITY_OVERRIDES,
              importableSections,
            ),
        };
      }),
    [importableSections],
  );

  const uniqueValues = useMemo(
    () => buildColumnFilterValues(previewItems, previewValueColumns),
    [previewItems, previewValueColumns],
  );

  // Чипы-переключатели как в импорте плана: включён один — другой выключен,
  // повторный клик возвращает дефолт. Чип виден, если счётчик > 0 или
  // категория активна.
  const previewFilterFields = useMemo<FiltersPanelField[]>(() => {
    const fields: FiltersPanelField[] = [
      {
        kind: "search",
        key: "preview-search",
        value: searchQuery,
        onChange: setSearchQuery,
        placeholder: "Код 1С, артикул или наименование…",
        layoutSpan: "min-w-[240px]",
      },
    ];
    if (stats.invalid > 0 || filterStatus === "invalid") {
      fields.push({
        kind: "toggle",
        key: "preview-status-invalid",
        label: "Ошибки",
        tone: "red",
        hideIcon: true,
        checked: filterStatus === "invalid",
        badgeCount: stats.invalid,
        onChange: () => {
          setFilterStatus((prev) => (prev === "invalid" ? "default" : "invalid"));
        },
        layoutSpan: "min-w-[0px]",
      });
    }
    if (stats.skipped > 0 || filterStatus === "skipped") {
      fields.push({
        kind: "toggle",
        key: "preview-status-skipped",
        label: "Пропущенные",
        tone: "amber",
        hideIcon: true,
        checked: filterStatus === "skipped",
        badgeCount: stats.skipped,
        onChange: () => {
          setFilterStatus((prev) => (prev === "skipped" ? "default" : "skipped"));
        },
        layoutSpan: "min-w-[0px]",
      });
    }
    return fields;
  }, [filterStatus, searchQuery, stats.invalid, stats.skipped]);

  const scrollContainerRef = useRef<HTMLDivElement | null>(null);

  // ── Оптимальные ширины колонок (#483, за флагом) ───────────────────────
  // Ширина контейнера — единственный вход, который пересчитывает раскладку.
  // Слушаем после монтирования рамки таблицы (шаг `preview`); сам пересчёт
  // дебаунсит хук.
  const [previewWidth, setPreviewWidth] = useState(0);
  useEffect(() => {
    const node = scrollContainerRef.current;
    if (!node) return;
    const update = () => setPreviewWidth(node.clientWidth);
    update();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(update);
    observer.observe(node);
    return () => observer.disconnect();
  }, [step]);

  const optimalWidths = useOptimalColumnWidths({
    enabled: OPTIMAL_COLUMN_WIDTHS_ENABLED,
    sheetIndex: selectedSheet,
    items: widthItemsBySheet[selectedSheet] ?? null,
    operations,
    containerWidth: previewWidth,
  });
  const optimalShares = optimalWidths.result?.shares ?? null;
  // Пока ширин нет (новый лист), таблицу держит спиннер: показать её на
  // текущих долях и потом переложить — это и есть «прыжок», который тикет
  // запрещает. На ресайз ширины остаются прошлые, пока не готовы новые.
  const widthsPending =
    OPTIMAL_COLUMN_WIDTHS_ENABLED &&
    !optimalShares &&
    optimalWidths.status !== "off";
  const overflowMinWidth =
    optimalShares && optimalWidths.result && optimalWidths.result.minTableWidthPx > 1180
      ? optimalWidths.result.minTableWidthPx
      : null;
  const rowHeights = optimalShares
    ? visibleItems.map(
        (item) =>
          optimalWidths.result?.rowHeights.get(item.source_row_number) ??
          PREVIEW_MIN_ROW_HEIGHT_PX,
      )
    : undefined;

  // Развёрнутая сырая строка — переменной высоты; виртуализатор считает строки
  // одинаковыми, поэтому на время разворота таблица рисуется обычным tbody.
  const hasExpandedPreviewRow = useMemo(
    () =>
      visibleItems.some(
        (item) => item.raw_values.length > 0 && isRowExpanded(item.source_row_number),
      ),
    [visibleItems, isRowExpanded],
  );

  const renderPreviewRow = useCallback(
    (item: RemainderImportItem) => (
      <PreviewRow
        key={item.source_row_number}
        item={item}
        sections={importableSections}
        operations={operations}
        expanded={isRowExpanded(item.source_row_number)}
        qualityOverride={qualityStateOverrides[item.source_row_number] ?? null}
        sectionOverride={targetSectionOverrides[item.source_row_number] ?? null}
        // Наименование переносится только когда применена посчитанная
        // раскладка: на текущих долях его высота не предсказана.
        nameWraps={Boolean(optimalShares)}
        predictedHeight={
          optimalShares
            ? optimalWidths.result?.rowHeights.get(item.source_row_number) ??
              PREVIEW_MIN_ROW_HEIGHT_PX
            : null
        }
        onToggle={toggleRow}
        onQualityChange={handleRowQualityChange}
        onSectionChange={handleRowSectionChange}
      />
    ),
    [
      importableSections,
      operations,
      isRowExpanded,
      qualityStateOverrides,
      targetSectionOverrides,
      optimalShares,
      optimalWidths.result?.rowHeights,
      toggleRow,
      handleRowQualityChange,
      handleRowSectionChange,
    ],
  );

  // Листы ОСВ файла: только они участвуют в «импортировать все листы».
  const osvSheets = useMemo(
    () => sheetTabs.filter((sheet) => sheet.kind === "1c_osv"),
    [sheetTabs],
  );
  const selectedSheetKind = sheetTabs.find((sheet) => sheet.index === selectedSheet)?.kind;
  // Буфер обмена — один лист: мультилистовое действие к нему не относится.
  // Действие живёт только на ОСВ-листе: на ручном/неизвестном листе кнопки
  // «все листы» нет — иначе она обещала бы не то, что делает.
  const multiSheetImportAvailable =
    importMode === "file" && osvSheets.length > 0 && selectedSheetKind === "1c_osv";
  // Очистка склада несовместима ни с построчными участками, ни с мультилистом:
  // она гасит остатки только одного склада, а «все листы ОСВ» заливают каждый
  // лист на свой (спека §9). На ручном листе одного файла очистка разрешена.
  const clearExistingBlockedByMultiSheet =
    multiSheetImportAvailable && osvSheets.length > 1;
  const clearExistingBlocked =
    Object.keys(targetSectionOverrides).length > 0 || clearExistingBlockedByMultiSheet;

  const canApplyImport = useMemo(() => {
    if (previewLoading || importMutation.isPending) return false;
    if (!shownPreview || stats.total === 0) return false;
    if (rowsMissingSection.length > 0) return false;
    return resolveImportLocationId != null;
  }, [
    previewLoading,
    importMutation.isPending,
    shownPreview,
    stats.total,
    rowsMissingSection.length,
    resolveImportLocationId,
  ]);

  /**
   * Импорт всех листов ОСВ: предпросмотр листа → применение листа, по одному
   * батчу истории на лист (спека §9).
   *
   * Останавливается на первом же ошибочном листе: применённые листы уже
   * изменили остатки, и продолжать «через ошибку» значило бы оставить склад
   * наполовину залитым без объяснения. `clear_existing` не отправляется
   * никогда: очистка одного склада погасила бы остатки другого.
   */
  const handleApplyAllOsv = async () => {
    const source = getImportSource();
    if (!source || source.kind !== "file" || osvSheets.length === 0 || multiRunning) return;
    setError(null);
    setMultiOutcomes(null);
    setMultiRunning(true);
    const outcomes: MultiSheetOutcome[] = [];
    for (const sheet of osvSheets) {
      try {
        const token = previewSourceToken.current;
        const preview = await previewRemaindersExcel(token ? null : source, {
          sheet_index: sheet.index,
          limit: 1,
          offset: 0,
          source_token: token ?? undefined,
        });
        const sectionId = preview.detected_section_id ?? sheet.detected_section_id;
        const sectionName = preview.detected_section_name ?? sheet.detected_section_name;
        if (sectionId == null) {
          outcomes.push({
            sheetIndex: sheet.index,
            sheetName: sheet.name,
            sectionId: null,
            sectionName,
            status: "failed",
            imported: 0,
            skipped: preview.summary.total,
            errors: [],
            error: "Не удалось определить участок листа — импорт остановлен",
          });
          break;
        }
        const qualityOverrides = qualityStateOverridesBySheet[sheet.index];
        const targetOverrides = targetSectionOverridesBySheet[sheet.index];
        const response = await importRemaindersExcel(sectionId, source, {
          sheet_index: sheet.index,
          skip_invalid: true,
          clear_existing: false,
          target_section_overrides:
            targetOverrides && Object.keys(targetOverrides).length > 0
              ? targetOverrides
              : undefined,
          quality_state_overrides:
            qualityOverrides && Object.keys(qualityOverrides).length > 0
              ? qualityOverrides
              : undefined,
        });
        if (!response.success) {
          outcomes.push({
            sheetIndex: sheet.index,
            sheetName: sheet.name,
            sectionId,
            sectionName,
            status: "failed",
            imported: 0,
            skipped: preview.summary.total,
            errors: response.errors,
            error: "Импорт листа отклонён сервером",
          });
          break;
        }
        outcomes.push({
          sheetIndex: sheet.index,
          sheetName: sheet.name,
          sectionId,
          sectionName,
          status: "applied",
          imported: response.imported_count,
          // Пропущено = всё, что лист не залил: невалидные строки и всё, что
          // сервер отклонил при `skip_invalid`.
          skipped: Math.max(0, preview.summary.total - response.imported_count),
          errors: response.errors,
          error: null,
        });
      } catch (err: unknown) {
        outcomes.push({
          sheetIndex: sheet.index,
          sheetName: sheet.name,
          sectionId: sheet.detected_section_id,
          sectionName: sheet.detected_section_name,
          status: "failed",
          imported: 0,
          skipped: 0,
          errors: [],
          error: getErrorMessage(err) || "Не удалось применить лист",
        });
        break;
      }
    }
    setMultiOutcomes(outcomes);
    setMultiRunning(false);
    if (outcomes.some((outcome) => outcome.status === "applied")) {
      void invalidateAfter(queryClient, "stockChanged");
      onSaved();
    }
    setStep("result");
  };

  const previewStatsBadges = shownPreview
    ? [
        { label: `Всего: ${stats.total}` },
        {
          label: `OK: ${stats.valid} (${stats.qty})`,
          className: "text-green-700 border-green-200 bg-green-50/50",
        },
        ...(stats.skipped > 0
          ? [
              {
                label: `Пропущено: ${stats.skipped}`,
                className: "text-amber-700 border-amber-200 bg-amber-50/50",
              },
            ]
          : []),
        ...(stats.invalid > 0
          ? [
              {
                label: `Ошибок: ${stats.invalid}`,
                className: "text-red-700 border-red-200 bg-red-50/50",
              },
            ]
          : []),
        ...(previewItemsTotal > previewItems.length
          ? [
              {
                label: `Показаны первые ${previewItems.length} из ${previewItemsTotal} — сузьте поиск`,
                className: "text-amber-700 border-amber-200 bg-amber-50/50",
              },
            ]
          : []),
        ...(rowsMissingSection.length > 0
          ? [
              {
                label: `Без участка: ${rowsMissingSection.length}`,
                className: "text-amber-700 border-amber-200 bg-amber-50/50",
              },
            ]
          : []),
      ]
    : [];

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) handleClose(); }}>
      <DialogContent className={getImportDialogContentClass(step, { uploadSize: "formWide" })}>
        <DialogHeader className="shrink-0 space-y-0">
          <DialogTitle className="text-base">Импорт остатков</DialogTitle>
        </DialogHeader>

        {error ? <ImportPreview.Error message={error} className="p-2" /> : null}

        <div
          className={`flex-1 min-h-0 ${
            step === "preview" ? "overflow-hidden" : "overflow-y-auto py-1"
          }`}
        >
          {/* ═══════════════════════ UPLOAD STEP ═══════════════════════ */}
          {step === "upload" && referencesLoading && (
            <div className="flex items-center justify-center gap-2 py-10 text-xs text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Загрузка справочников участков и операций…
            </div>
          )}

          {step === "upload" && !referencesLoading && referencesError && (
            <ImportPreview.Error
              message="Не удалось загрузить справочники участков и операций. Закройте диалог и повторите попытку."
              className="p-2"
            />
          )}

          {step === "upload" && !referencesLoading && !referencesError && (
            <div className="space-y-2">
              <p className="text-[11px] text-muted-foreground leading-snug">
                Одна таблица для всех остатков: годный, брак или окончательный брак — статус указывается в колонке{" "}
                <strong className="text-foreground">«Статус качества»</strong>. Заголовки необязательны: без них
                столбцы читаются в порядке шаблона. Загрузите Excel или нажмите{" "}
                <kbd className="px-1 py-0.5 rounded-sm border border-border bg-muted text-[10px] font-mono">Ctrl+V</kbd>{" "}
                — данные из буфера подхватятся сразу.
              </p>
              <p className="text-[11px] text-muted-foreground leading-snug">
                Поддерживаются выгрузка 1С (ОСВ) и ручной шаблон{" "}
                <strong className="text-foreground">«Артикул | Кол-во»</strong>. После загрузки
                тип каждого листа виден на вкладках — лист можно переключить.
              </p>

              <div className="grid grid-cols-[minmax(0,3fr)_minmax(160px,2fr)] gap-3 items-start">
                {/* Левая колонка: таблица + загрузка */}
                <div className="space-y-2 min-w-0">
                  <div className="space-y-1">
                    <div className="flex items-center justify-between gap-2">
                      <label className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
                        Пример структуры таблицы
                      </label>
                      <Button
                        variant="link"
                        size="sm"
                        onClick={downloadTemplate}
                        className="h-auto p-0 text-xs text-emerald-600 hover:text-emerald-700 font-medium inline-flex items-center gap-1 shrink-0"
                      >
                        <Download className="h-3.5 w-3.5" />
                        Шаблон Excel
                      </Button>
                    </div>
                    <div className="border border-border rounded-lg overflow-x-auto bg-background">
                      <table className="w-full min-w-[480px] text-left border-collapse text-[11px]">
                        <thead>
                          <tr className="bg-muted/50 border-b-2 border-b-emerald-500 dark:border-b-emerald-600">
                            <th className="px-1.5 py-1.5 font-semibold border-r border-border text-foreground whitespace-nowrap">Артикул</th>
                            <th className="px-1.5 py-1.5 font-semibold border-r border-border text-foreground whitespace-nowrap">Кол-во</th>
                            <th className="px-1.5 py-1.5 font-semibold border-r border-border text-foreground whitespace-nowrap">Статус качества</th>
                            <th className="px-1.5 py-1.5 font-semibold border-r border-border text-foreground whitespace-nowrap">Операции</th>
                            <th className="px-1.5 py-1.5 font-semibold border-r border-border text-foreground whitespace-nowrap">Участок</th>
                            <th className="px-1.5 py-1.5 font-semibold border-r border-border text-foreground whitespace-nowrap">Коммент.</th>
                            <th className="px-1.5 py-1.5 font-semibold text-foreground whitespace-nowrap">Длина</th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr className="border-b border-border">
                            <td className="px-1.5 py-1.5 font-mono border-r border-border text-foreground">361</td>
                            <td className="px-1.5 py-1.5 border-r border-border text-foreground">200</td>
                            <td className="px-1.5 py-1.5 border-r border-border font-medium text-emerald-700 whitespace-nowrap">Годный</td>
                            <td className="px-1.5 py-1.5 border-r border-border text-muted-foreground">
                              — <span className="text-[9px] text-muted-foreground/50">(с 1-го этапа)</span>
                            </td>
                            <td className="px-1.5 py-1.5 border-r border-border font-medium text-emerald-700 whitespace-nowrap">{exampleTargetSections.raw}</td>
                            <td className="px-1.5 py-1.5 border-r border-border text-muted-foreground">—</td>
                            <td className="px-1.5 py-1.5 text-muted-foreground">
                              — <span className="text-[9px] text-muted-foreground/50">(типовой размер)</span>
                            </td>
                          </tr>
                          <tr className="border-b border-border bg-muted/20">
                            <td className="px-1.5 py-1.5 font-mono border-r border-border text-foreground">ALS-1289</td>
                            <td className="px-1.5 py-1.5 border-r border-border text-foreground">150</td>
                            <td className="px-1.5 py-1.5 border-r border-border font-medium text-emerald-700 whitespace-nowrap">Годный</td>
                            <td className="px-1.5 py-1.5 border-r border-border text-muted-foreground">{exampleRow2Operations}</td>
                            <td className="px-1.5 py-1.5 border-r border-border font-medium text-emerald-700 whitespace-nowrap">{exampleTargetSections.prep}</td>
                            <td className="px-1.5 py-1.5 border-r border-border text-muted-foreground">Партия A</td>
                            <td className="px-1.5 py-1.5 text-foreground tabular-nums">2,7</td>
                          </tr>
                          <tr>
                            <td className="px-1.5 py-1.5 font-mono border-r border-border text-foreground">ЮП-2630</td>
                            <td className="px-1.5 py-1.5 border-r border-border text-foreground">80</td>
                            <td className="px-1.5 py-1.5 border-r border-border font-medium text-rose-700 whitespace-nowrap">Окончательный брак</td>
                            <td className="px-1.5 py-1.5 border-r border-border text-muted-foreground">{exampleRow3Operations}</td>
                            <td className="px-1.5 py-1.5 border-r border-border font-medium text-emerald-700/80 whitespace-nowrap">{exampleTargetSections.wip}</td>
                            <td className="px-1.5 py-1.5 border-r border-border text-muted-foreground">Срочный заказ</td>
                            <td className="px-1.5 py-1.5 text-foreground tabular-nums">1,8</td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  </div>

                  <ImportUpload.Dropzone
                    inputRef={fileInputRef}
                    onFileChange={handleFileChange}
                    accept=".xlsx,.xls"
                    disabled={sheetsLoading}
                  />
                </div>

                {/* Правая колонка: справочники */}
                <aside className="space-y-1.5 text-[11px] text-muted-foreground leading-snug min-w-0">
                  <div className="p-1.5 bg-muted/40 rounded-lg border border-border/60 space-y-1">
                    <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider block">
                      Доступные участки
                    </span>
                    <div className="flex flex-wrap gap-1">
                      {importableSections.length === 0 ? (
                        <span className="text-[10px] text-muted-foreground">Справочник участков пуст</span>
                      ) : (
                        importableSections.map((section) => (
                          <SectionLocationBadge
                            key={section.code}
                            sections={importableSections}
                            sectionId={section.id}
                            sectionName={section.name}
                            size="sm"
                          />
                        ))
                      )}
                    </div>
                    <span className="text-[9px] leading-snug block">
                      * пусто (—) — участок выбирается в таблице предпросмотра
                    </span>
                  </div>

                  <div className="p-1.5 bg-muted/40 rounded-lg border border-border/60 space-y-1">
                    <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider block">
                      Статусы качества
                    </span>
                    <div className="flex flex-wrap gap-1">
                      {IMPORT_QUALITY_OPTIONS.map((option) => (
                        <span
                          key={option.value}
                          className={`inline-flex items-center px-1.5 py-0.5 rounded-sm text-[10px] font-medium border ${qualityBadgeClass(option.value)}`}
                        >
                          {option.label}
                        </span>
                      ))}
                    </div>
                    <span className="text-[9px] leading-snug block">
                      * пусто — «Годный»
                    </span>
                  </div>

                  {operations && operations.length > 0 && (
                    <div className="p-1.5 bg-muted/40 rounded-lg border border-border/60 space-y-1 max-h-[220px] overflow-y-auto">
                      <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider block">
                        Доступные операции
                      </span>
                      <div className="flex flex-wrap gap-1">
                        {operations.map((op: ImportOperationStep) => {
                          const accentColor = op.op_icon_color ?? op.section_icon_color ?? null;
                          return (
                            <span
                              key={`${op.section_code}-${op.operation_code ?? op.operation_name}`}
                              className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm text-[10px] font-medium leading-5 ${
                                accentColor ? "" : "bg-muted text-foreground border border-border/80"
                              }`}
                              style={
                                accentColor
                                  ? {
                                      backgroundColor: `${accentColor}18`,
                                      color: accentColor,
                                    }
                                  : undefined
                              }
                              title={`Участок: ${op.section_name}`}
                            >
                              {op.op_icon && op.op_icon_color ? (
                                <span className="shrink-0" style={{ color: op.op_icon_color }}>
                                  {renderIcon(op.op_icon, "h-3 w-3")}
                                </span>
                              ) : op.section_icon && op.section_icon_color ? (
                                <span className="shrink-0" style={{ color: op.section_icon_color }}>
                                  {renderIcon(op.section_icon, "h-3 w-3")}
                                </span>
                              ) : null}
                              {op.operation_name}
                            </span>
                          );
                        })}
                      </div>
                      <span className="text-[9px] leading-snug block">
                        * через запятую в колонке «Операции»
                      </span>
                    </div>
                  )}
                </aside>
              </div>
            </div>
          )}

          {/* ═══════════════════════ PREVIEW STEP ═══════════════════════ */}
          {step === "preview" && (
            <ImportPreview.Layout className="space-y-1.5 min-h-0">
              <ImportPreview.Toolbar
                className="p-1.5 gap-2"
                left={
                  <>
                    <ImportPreview.SheetTabs
                      sheets={sheetTabs.map(sheetTabLabel)}
                      selectedIndex={Math.max(
                        0,
                        sheetTabs.findIndex((sheet) => sheet.index === selectedSheet),
                      )}
                      onSelect={(position) => {
                        const sheet = sheetTabs[position];
                        if (sheet) setSelectedSheet(sheet.index);
                      }}
                      disabled={importMode === "clipboard"}
                      label={importMode === "clipboard" ? "Источник" : "Лист"}
                    />
                    <div className="flex items-center gap-1">
                      <span className="font-medium text-foreground">Строки</span>
                      <Input
                        value={rowSelection}
                        onChange={(e) => setRowSelection(e.target.value)}
                        placeholder="2-10,12"
                        className="h-6 w-20 text-[11px] px-2"
                      />
                    </div>
                    <label
                      className={`flex items-center gap-1 font-medium select-none ${
                        clearExistingBlocked
                          ? "cursor-not-allowed opacity-50"
                          : "cursor-pointer"
                      }`}
                      title={
                        clearExistingBlockedByMultiSheet
                          ? "Очистка одного склада не должна гасить остатки другого — при импорте нескольких листов ОСВ она недоступна"
                          : undefined
                      }
                    >
                      <input
                        type="checkbox"
                        checked={clearExisting}
                        disabled={clearExistingBlocked}
                        onChange={(e) => setClearExisting(e.target.checked)}
                        className="h-3 w-3 rounded-sm border-input text-primary focus:ring-primary"
                      />
                      <span className="text-destructive font-semibold">Очистить перед импортом</span>
                    </label>
                    {clearExistingBlockedByMultiSheet ? (
                      <span className="text-[10px] text-muted-foreground leading-snug max-w-[220px]">
                        Очистка перед импортом недоступна в мультилисте: каждый
                        лист ОСВ заливается на свой склад.
                      </span>
                    ) : null}
                  </>
                }
                right={
                  shownPreview ? (
                    <div className="flex flex-wrap items-center justify-end gap-1 text-[11px] font-semibold">
                      {previewStatsBadges.map((badge, idx) => (
                        <Badge
                          key={idx}
                          variant="outline"
                          className={`px-1.5 py-0 text-[10px] leading-5 ${badge.className ?? "bg-background"}`}
                        >
                          {badge.label}
                        </Badge>
                      ))}
                    </div>
                  ) : undefined
                }
              />

              {importMode === "clipboard" && clipboardText ? (
                <ImportUpload.ClipboardBanner
                  text={clipboardText}
                  invalidCount={shownPreview ? stats.invalid : 0}
                  totalCount={shownPreview ? stats.total : 0}
                />
              ) : null}

              {shownPreview ? (
                // Ряд фильтров — общий `FiltersPanel` (compact), как в импорте
                // плана: поиск, цветные чипы категорий, «Сбросить» и разворот
                // сырых строк. Своего ряда вёрстки у диалога нет (#472).
                <FiltersPanel
                  compact
                  className="shrink-0 p-1.5"
                  fields={previewFilterFields}
                  onReset={resetPreviewFilters}
                  hasActiveFilters={hasPreviewFilters}
                  actions={
                    <ImportRawRows.Toggle
                      active={expansion.expandAllRaw}
                      onToggle={() => expansion.setExpandAllRaw(!expansion.expandAllRaw)}
                      className="h-6 text-[11px] px-2"
                    />
                  }
                />
              ) : null}

              <ImportPreview.TableFrame
                // Горизонтальный скролл объявлен здесь, а не взят из
                // `DATA_TABLE_STYLES.container` (`overflow-x-hidden`):
                // раскладка таблицы фиксированная (`table-fixed` + `<colgroup>`
                // ниже), колонки не сжимаются под узкое окно, и без прокрутки
                // правый край просто обрезался бы — тот же дефект, что
                // вылечен в `PlanPage`.
                className="min-h-0 min-w-0 overflow-auto rounded-lg border"
                containerRef={scrollContainerRef}
                // Спиннер — только пока предпросмотра на экране не было ни
                // разу: перечитывание по фильтру не должно уносить таблицу
                // вместе с открытым поповером и набранным текстом (ADR-0044).
                // Пока считаются ширины (#483), таблица тоже не показывается:
                // иначе колонки прыгнут после первого кадра.
                loading={(previewLoading && !shownPreview) || widthsPending}
                isEmpty={shownPreview !== null && visibleItems.length === 0}
                emptyContent={
                  shownPreview && previewItemsTotal > 0 ? (
                    <span>Нет строк по текущему фильтру или поиску.</span>
                  ) : importMode === "clipboard" && clipboardText ? (
                    <span className="max-w-md leading-relaxed">
                      Строки не распознаны — см. блок «Вставлено из буфера» выше.
                      Убедитесь, что данные скопированы из Excel с заголовками.
                    </span>
                  ) : (
                    <span>Нет данных для отображения. Загрузите файл или измените фильтры.</span>
                  )
                }
              >
                {/* `table-fixed` + `<colgroup>`: строки виртуализированы, и при
                    auto-раскладке ширины колонок считались по содержимому
                    смонтированных строк — при скролле они «перерисовывались».
                    Ширины объявлены один раз в `remainderPreviewColumns`
                    (вместе со служебными колонками дают 100%). */}
                {/* Наблюдаемость режима (#484): E2E проверяет, какая раскладка
                    применена, совпала ли предсказанная высота с фактической и
                    уложилась ли доля обрезанных пилюль в лимит текущего фикса.
                    Только чтение; на вёрстку не влияет. */}
                <table
                  className="w-full min-w-[1180px] table-fixed text-[11px] text-left border-collapse"
                  style={overflowMinWidth ? { minWidth: `${overflowMinWidth}px` } : undefined}
                  data-column-layout={optimalShares ? "optimal" : "baseline"}
                  data-pills-limit-share={optimalWidths.result?.pillsLimitShare}
                  data-predicted-total-height={optimalWidths.result?.totalHeightPx}
                  data-predicted-row-count={optimalWidths.result?.rowHeights.size}
                >
                    <colgroup>
                      <col style={{ width: REMAINDER_PREVIEW_CHEVRON_COLUMN_WIDTH }} />
                      {remainderPreviewColumns.map((column) => (
                        <col
                          key={column.id}
                          style={{ width: optimalShares?.[column.id] ?? column.width }}
                        />
                      ))}
                      <col style={{ width: REMAINDER_PREVIEW_RESET_COLUMN_WIDTH }} />
                    </colgroup>
                    <thead>
                      <tr>
                        <th className={headerCellClass} />
                        {remainderPreviewColumns.map((column) => (
                          <th
                            key={column.id}
                            className={`${headerCellClass} p-0 ${column.headerClassName ?? ""}`}
                            aria-sort={column.sortField ? getAriaSort(sortConfigs, column.sortField) : undefined}
                          >
                            <DataTableColumnHeader
                              column={column}
                              bindColumn={bindColumn}
                              values={column.filterField ? uniqueValues[column.filterField] : undefined}
                              currentSorts={sortConfigs}
                              onSortChange={handleSortChange}
                            />
                          </th>
                        ))}
                        <TableCornerResetHeader
                          hasActiveFilters={hasPreviewFilters}
                          onReset={resetPreviewFilters}
                          dataTableHeader
                        />
                      </tr>
                    </thead>
                    {hasExpandedPreviewRow ? (
                      // Развёрнутая сырая строка выше компактной и переменной
                      // высоты; виртуализатор считает строки одинаковыми,
                      // поэтому на время разворота рисуем обычный tbody.
                      <tbody>{visibleItems.map(renderPreviewRow)}</tbody>
                    ) : (
                      <VirtualizedTableBody
                        rows={visibleItems}
                        // Оценка из общего набора компактной строки (ADR-0030):
                        // фактическую высоту виртуализатор измеряет сам.
                        rowHeight={TABLE_ROW_COMPACT.rowHeightPx}
                        // С флагом #483 — предсказанная высота каждой строки
                        // (`lines × lineHeight` «Ошибок»); без флага — как раньше.
                        rowHeights={rowHeights}
                        colSpan={remainderPreviewColumns.length + 2}
                        scrollContainerRef={scrollContainerRef}
                        renderRow={renderPreviewRow}
                      />
                    )}
                  </table>
              </ImportPreview.TableFrame>
            </ImportPreview.Layout>
          )}

          {/* ═══════════════════════ RESULT STEP ════════════════════════ */}
          {step === "result" && multiOutcomes && (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                {multiOutcomes.some((outcome) => outcome.status === "failed") ? (
                  <AlertCircle className="h-5 w-5 text-destructive" />
                ) : (
                  <CheckCircle className="h-5 w-5 text-emerald-600" />
                )}
                <h3 className="text-base font-semibold text-foreground">
                  Импорт всех листов ОСВ
                </h3>
              </div>

              <p className="text-xs text-muted-foreground">
                Применено листов:{" "}
                {multiOutcomes.filter((outcome) => outcome.status === "applied").length} из{" "}
                {osvSheets.length}. Каждый лист — отдельный батч истории.
              </p>

              {multiOutcomes.some((outcome) => outcome.status === "failed") ? (
                <p className="text-xs text-destructive">
                  Импорт остановлен на листе «
                  {multiOutcomes.find((outcome) => outcome.status === "failed")?.sheetName}».
                  Следующие листы не применены.
                </p>
              ) : null}

              <div className="border border-border rounded-lg overflow-x-auto">
                <table className="w-full text-[11px] text-left border-collapse">
                  <thead>
                    <tr>
                      <th className={summaryHeaderCellClass}>Лист</th>
                      <th className={summaryHeaderCellClass}>Участок</th>
                      <th className={summaryHeaderCellClass}>Импортировано</th>
                      <th className={summaryHeaderCellClass}>Пропущено</th>
                      <th className={summaryHeaderCellClass}>Ошибки</th>
                    </tr>
                  </thead>
                  <tbody>
                    {multiOutcomes.map((outcome) => (
                      <tr
                        key={outcome.sheetIndex}
                        className={`border-b last:border-0 ${
                          outcome.status === "failed" ? "bg-red-50/50 dark:bg-red-950/5" : ""
                        }`}
                      >
                        <td className={`${summaryCellClass} font-medium`}>{outcome.sheetName}</td>
                        <td className={summaryCellClass}>{outcome.sectionName ?? "—"}</td>
                        <td className={`${summaryCellClass} tabular-nums`}>{outcome.imported}</td>
                        <td className={`${summaryCellClass} tabular-nums`}>{outcome.skipped}</td>
                        <td
                          className={`${summaryCellClass} leading-snug ${
                            outcome.status === "failed"
                              ? "text-destructive font-medium"
                              : "text-muted-foreground"
                          }`}
                        >
                          {outcome.error ??
                            (outcome.errors.length > 0
                              ? outcome.errors.map(translateImportError).join(", ")
                              : "—")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {step === "result" && !multiOutcomes && result && (
            <div className="text-center py-6 space-y-4">
              <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-emerald-100 dark:bg-emerald-950/30 text-emerald-600 mb-2">
                <CheckCircle className="h-7 w-7" />
              </div>
              <h3 className="text-base font-semibold text-foreground">Импорт успешно завершен</h3>

              <div className="inline-block border rounded-lg p-3 bg-muted/30 text-xs space-y-1 text-left min-w-[200px]">
                <div className="flex justify-between gap-4">
                  <span className="text-muted-foreground">Импортировано остатков:</span>
                  <span className="font-bold text-foreground">{result.imported_count} шт.</span>
                </div>
              </div>

              {result.errors.length > 0 && (
                <div className="space-y-2 text-left pt-2">
                  <div className="text-xs font-semibold text-destructive flex items-center gap-1.5">
                    <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                    Ошибки / Пропущенные строки ({result.errors.length}):
                  </div>
                  <div className="max-h-[160px] overflow-y-auto border border-destructive/20 rounded-lg bg-destructive/5 p-3 space-y-1 font-mono text-[10px]">
                    {result.errors.map((err, idx) => (
                      <div key={idx} className="text-destructive leading-tight border-b pb-1 last:border-0 last:pb-0">
                        {translateImportError(err)}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

        </div>

        {/* ═══════════════════════ FOOTER ═══════════════════════════════ */}
        <DialogFooter className="shrink-0 pt-1.5 border-t flex items-center justify-end gap-1.5">
          {step === "upload" && (
            <Button variant="outline" onClick={handleClose}>
              Отмена
            </Button>
          )}

          {step === "preview" && (
            <>
              <Button
                variant="outline"
                onClick={() => {
                  setStep("upload");
                  setImportMode("file");
                  setFile(null);
                  setClipboardText("");
                  previewSourceVersion.current += 1;
                  resetPreviewState();
                  setError(null);
                }}
                disabled={previewLoading || importMutation.isPending || multiRunning}
              >
                Назад
              </Button>

              {multiSheetImportAvailable && !clearExisting ? (
                <Button
                  variant="outline"
                  onClick={() => void handleApplyAllOsv()}
                  disabled={previewLoading || importMutation.isPending || multiRunning}
                  title="Применить каждый лист ОСВ на его склад, по одному батчу на лист"
                >
                  {multiRunning ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin mr-1.5" />
                      Импорт листов…
                    </>
                  ) : (
                    `Импортировать все листы ОСВ (${osvSheets.length})`
                  )}
                </Button>
              ) : null}

              {stats.invalid > 0 ? (
                <>
                  <Button
                    variant="outline"
                    onClick={() => handleApply(false)}
                    disabled={previewLoading || importMutation.isPending || multiRunning}
                    className="border-destructive hover:bg-destructive/10 text-destructive"
                  >
                    {importMutation.isPending ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin mr-1.5" />
                        Загрузка...
                      </>
                    ) : (
                      `Загрузить все (${stats.total} строк)`
                    )}
                  </Button>
                  <Button
                    onClick={() => handleApply(true)}
                    disabled={!canApplyImport || stats.valid === 0}
                  >
                    {importMutation.isPending ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin mr-1.5" />
                        Загрузка...
                      </>
                    ) : (
                      `Пропустить ошибки (${stats.valid} строк)`
                    )}
                  </Button>
                </>
              ) : (
                <Button
                  onClick={() => handleApply(false)}
                  disabled={!canApplyImport}
                >
                  {importMutation.isPending ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin mr-1.5" />
                      Импорт...
                    </>
                  ) : (
                    "Применить изменения"
                  )}
                </Button>
              )}
            </>
          )}

          {step === "result" && (
            <Button onClick={handleClose}>
              Закрыть
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
