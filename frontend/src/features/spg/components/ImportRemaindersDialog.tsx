import { useState, useRef, useEffect, useMemo, useCallback, Fragment } from "react";
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
  SortableFilterHeader,
  toast,
} from "@/shared/ui";
import {
  useTableQueryEngine,
  type SortConfig,
  type ColumnSortDef,
} from "@/shared/hooks/useTableQueryEngine";
import { nextMultiSortConfigs } from "@/shared/lib/multiSort";
import {
  useImportRowExpansion,
  useImportClipboardPaste,
  ImportUpload,
  ImportPreview,
  ImportRawRows,
} from "@/shared/ui/import";
import {
  previewRemaindersExcel,
  importRemaindersExcel,
  downloadRemaindersImportTemplate,
  getRemainderImportOperations,
  formatQualityStateLabel,
  IMPORT_QUALITY_OPTIONS,
  normalizeImportQualityState,
  type QualityState,
  type RemainderPreviewResponse,
  type RemainderImportSource,
  type ImportOperationStep,
} from "@/shared/api/stock";
import { getErrorMessage } from "@/shared/api/client";
import { translateImportError } from "@/shared/api/errorMessages";
import { getExcelSheetNames } from "@/shared/api/imports";
import { queryKeys } from "@/shared/api/queryKeys";
import { RouteStepsDisplay } from "@/shared/ui/RouteStepsDisplay";
import { listSections } from "@/shared/api/sections";
import type { RemainderImportItem } from "@/shared/api/stock";

function hasSectionInFile(item: RemainderImportItem): boolean {
  const name = item.target_section_name?.trim();
  return Boolean(name && name !== "—" && name !== "-");
}

function getEffectiveSectionId(
  item: RemainderImportItem,
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

function getEffectiveQualityState(
  item: RemainderImportItem,
  overrides: Record<number, QualityState>,
): QualityState {
  if (overrides[item.source_row_number] != null) {
    return overrides[item.source_row_number];
  }
  return normalizeImportQualityState(item.quality_state);
}

type RemainderPreviewSortField =
  | "row"
  | "sku"
  | "quantity"
  | "operations"
  | "quality"
  | "section"
  | "errors";

function getImportItemOperationsLabel(item: RemainderImportItem): string {
  if (item.completed_stages?.length > 0) {
    return item.completed_stages.map((stage) => stage.operation_name).join(", ");
  }
  const raw = item.completed_operations_raw?.trim();
  return raw || "—";
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

function getImportItemErrorsLabel(item: RemainderImportItem): string {
  if (item.errors.length === 0) {
    return item.status === "valid" ? "—" : "Ошибка";
  }
  return item.errors.map(translateImportError).join(", ");
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
    case "operations":
      return getImportItemOperationsLabel(item);
    case "quality":
      return getImportItemQualityLabel(item, qualityOverrides);
    case "section":
      return getImportItemSectionLabel(item, sectionOverrides, sections);
    case "errors":
      return getImportItemErrorsLabel(item);
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

interface ImportRemaindersDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}

const SEED_TARGET_SECTION_CODES = ["WH", "PREP_STOCK", "WIP_WH", "FG_WH", "SHIPMENT", "SENT"] as const;

const SEED_TARGET_SECTION_FALLBACKS: Record<(typeof SEED_TARGET_SECTION_CODES)[number], string> = {
  WH: "Склад сырья",
  PREP_STOCK: "Склад подготовки",
  WIP_WH: "Склад полуфабриката",
  FG_WH: "Склад готовой продукции",
  SHIPMENT: "К отгрузке",
  SENT: "Отправлено",
};

export function ImportRemaindersDialog({
  open,
  onOpenChange,
  onSaved,
}: ImportRemaindersDialogProps) {
  const queryClient = useQueryClient();

  // ── Operations reference ──────────────────────────────────────────────
  const { data: operations } = useQuery({
    queryKey: ["stock-remainder-import-operations"],
    queryFn: () => getRemainderImportOperations(),
    enabled: open,
  });

  // ── Sections list for target selector ─────────────────────────────────
  const { data: allSections } = useQuery({
    queryKey: ["sections", "all"],
    queryFn: () => listSections(),
    enabled: open,
  });

  const importableSections = useMemo(() => {
    if (!allSections) return [];
    return allSections
      .filter((s) => s.is_active && s.type !== "production")
      .sort((a, b) => a.name.localeCompare(b.name, "ru"));
  }, [allSections]);

  const seedTargetSections = useMemo(() => {
    const byCode = new Map(importableSections.map((s) => [s.code, s]));
    return SEED_TARGET_SECTION_CODES.map((code) => {
      const section = byCode.get(code);
      return {
        code,
        name: section?.name ?? SEED_TARGET_SECTION_FALLBACKS[code],
      };
    });
  }, [importableSections]);

  const exampleTargetSections = useMemo(
    () => ({
      raw: seedTargetSections.find((s) => s.code === "WH")?.name ?? "Склад сырья",
      prep: seedTargetSections.find((s) => s.code === "PREP_STOCK")?.name ?? "Склад подготовки",
      wip: seedTargetSections.find((s) => s.code === "WIP_WH")?.name ?? "Склад полуфабриката",
    }),
    [seedTargetSections],
  );

  // Сид: Дробеструй (SHOT) → цвет анода (ANOD) → одна упаковка на аноде (Стрейч ИЛИ Спанбонд)
  const exampleRow3Operations = useMemo(() => {
    const seedOrder = ["Дробеструй", "Чёрный", "Стрейч"];
    if (!operations?.length) return seedOrder.join(", ");
    const resolved = seedOrder
      .map((name) => operations.find((op) => op.operation_name === name)?.operation_name)
      .filter((name): name is string => Boolean(name));
    return resolved.length > 0 ? resolved.join(", ") : seedOrder.join(", ");
  }, [operations]);

  // ── State machine ─────────────────────────────────────────────────────
  const [step, setStep] = useState<"upload" | "preview" | "result">("upload");
  const [importMode, setImportMode] = useState<"file" | "clipboard">("file");
  const [file, setFile] = useState<File | null>(null);
  const [clipboardText, setClipboardText] = useState("");
  const [sheets, setSheets] = useState<string[]>([]);
  const [selectedSheet, setSelectedSheet] = useState(0);
  const [rowSelection, setRowSelection] = useState("");
  const [clearExisting, setClearExisting] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [filterStatus, setFilterStatus] = useState<"all" | "invalid">("all");
  const [targetSectionOverrides, setTargetSectionOverrides] = useState<Record<number, number>>({});
  const [qualityStateOverrides, setQualityStateOverrides] = useState<Record<number, QualityState>>({});
  const [sortConfigs, setSortConfigs] = useState<SortConfig<RemainderPreviewSortField>[]>([]);
  const [columnFilters, setColumnFilters] = useState<
    Partial<Record<RemainderPreviewSortField, Set<string>>>
  >({});

  const [previewData, setPreviewData] = useState<RemainderPreviewResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ imported_count: number; errors: string[] } | null>(null);

  const expansion = useImportRowExpansion();
  const { toggleRow, isRowExpanded, resetExpansion } = expansion;

  const fileInputRef = useRef<HTMLInputElement>(null);

  // ── Resolve location id for API (из файла, per-row override или первая валидная строка) ──
  const resolveImportLocationId = useMemo((): number | null => {
    if (!previewData) return null;
    const firstResolved = previewData.items.find(
      (item) =>
        item.status === "valid" &&
        getEffectiveSectionId(item, null, targetSectionOverrides) != null,
    );
    if (!firstResolved) return null;
    return getEffectiveSectionId(firstResolved, null, targetSectionOverrides);
  }, [previewData, targetSectionOverrides]);

  // ── Reset state when dialog opens ─────────────────────────────────────
  useEffect(() => {
    if (open) {
      setStep("upload");
      setImportMode("file");
      setFile(null);
      setClipboardText("");
      setSheets([]);
      setSelectedSheet(0);
      setRowSelection("");
      setClearExisting(false);
      resetExpansion();
      setSearchQuery("");
      setFilterStatus("all");
      setTargetSectionOverrides({});
      setQualityStateOverrides({});
      setSortConfigs([]);
      setColumnFilters({});
      setPreviewData(null);
      setError(null);
      setResult(null);
    }
  }, [open, resetExpansion]);

  const getImportSource = (): RemainderImportSource | null => {
    if (importMode === "file" && file) {
      return { kind: "file", file };
    }
    if (importMode === "clipboard" && clipboardText.trim()) {
      return { kind: "clipboard", clipboardText: clipboardText.trim() };
    }
    return null;
  };

  // ── Load preview when relevant params change ──────────────────────────
  useEffect(() => {
    if (step !== "preview" || !getImportSource()) return;
    loadPreview();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, selectedSheet, rowSelection, importMode, file, clipboardText]);

  const loadPreview = async () => {
    const source = getImportSource();
    if (!source) return;
    setPreviewLoading(true);
    setError(null);
    try {
      const data = await previewRemaindersExcel(source, {
        location_id: resolveImportLocationId ?? undefined,
        sheet_index: selectedSheet,
        row_selection: rowSelection || undefined,
        target_section_overrides:
          Object.keys(targetSectionOverrides).length > 0 ? targetSectionOverrides : undefined,
        quality_state_overrides:
          Object.keys(qualityStateOverrides).length > 0 ? qualityStateOverrides : undefined,
      });
      setPreviewData(data);
    } catch (err: unknown) {
      setError(getErrorMessage(err) || "Не удалось загрузить предварительный просмотр листа.");
      setPreviewData(null);
    } finally {
      setPreviewLoading(false);
    }
  };

  // ── File selection handler ────────────────────────────────────────────
  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const selectedFile = e.target.files[0];
      setImportMode("file");
      setClipboardText("");
      setFile(selectedFile);
      setError(null);
      setPreviewLoading(true);
      try {
        const sheetNames = await getExcelSheetNames(selectedFile);
        setSheets(sheetNames);
        setSelectedSheet(0);
        setStep("preview");
      } catch (err: unknown) {
        setError(getErrorMessage(err) || "Ошибка при чтении структуры Excel-файла");
        setFile(null);
      } finally {
        setPreviewLoading(false);
      }
    }
  };

  const applyClipboardText = useCallback((text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    setImportMode("clipboard");
    setClipboardText(trimmed);
    setFile(null);
    setSheets(["Буфер обмена"]);
    setSelectedSheet(0);
    setError(null);
    setFilterStatus("all");
    setSearchQuery("");
    setStep("preview");
  }, []);

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
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.setAttribute("download", "Шаблон импорта остатков.xlsx");
      document.body.appendChild(link);
      link.click();
      link.parentNode?.removeChild(link);
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
        void queryClient.invalidateQueries({ queryKey: queryKeys.stock.balances() });
        void queryClient.invalidateQueries({ queryKey: queryKeys.stock.transactions() });
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
    onOpenChange(false);
  };

  const handleRowSectionChange = (rowNumber: number, sectionId: number | null) => {
    setTargetSectionOverrides((prev) => {
      const next = { ...prev };
      if (sectionId == null) {
        delete next[rowNumber];
      } else {
        next[rowNumber] = sectionId;
      }
      return next;
    });
  };

  const handleRowQualityChange = (rowNumber: number, state: QualityState) => {
    setQualityStateOverrides((prev) => {
      const next = { ...prev };
      next[rowNumber] = state;
      return next;
    });
  };

  const handleSortChange = useCallback((field: RemainderPreviewSortField) => {
    setSortConfigs((prev) => nextMultiSortConfigs(prev, field));
  }, []);

  const handleColumnFilterChange = useCallback(
    (field: RemainderPreviewSortField, selected: Set<string>) => {
      setColumnFilters((prev) => ({ ...prev, [field]: selected }));
    },
    [],
  );

  const resetPreviewFilters = useCallback(() => {
    setFilterStatus("all");
    setSearchQuery("");
    setSortConfigs([]);
    setColumnFilters({});
  }, []);

  const rowsMissingSection = useMemo(() => {
    if (!previewData) return [];
    return previewData.items.filter(
      (item) =>
        item.status === "valid" &&
        getEffectiveSectionId(item, null, targetSectionOverrides) == null,
    );
  }, [previewData, targetSectionOverrides]);

  const basePreviewItems = useMemo(() => {
    if (!previewData) return [];
    if (filterStatus === "invalid") {
      return previewData.items.filter((item) => item.status === "invalid");
    }
    return previewData.items;
  }, [previewData, filterStatus]);

  const sortDefs = useMemo((): ColumnSortDef<RemainderImportItem, RemainderPreviewSortField>[] => [
    { field: "row", getSortValue: (item) => item.source_row_number },
    { field: "sku", getSortValue: (item) => item.sku },
    { field: "quantity", getSortValue: (item) => item.quantity ?? -1 },
    { field: "operations", getSortValue: (item) => getImportItemOperationsLabel(item) },
    {
      field: "quality",
      getSortValue: (item) => getImportItemQualityLabel(item, qualityStateOverrides),
    },
    {
      field: "section",
      getSortValue: (item) =>
        getImportItemSectionLabel(item, targetSectionOverrides, importableSections),
    },
    { field: "errors", getSortValue: (item) => getImportItemErrorsLabel(item) },
  ], [qualityStateOverrides, targetSectionOverrides, importableSections]);

  const filterPredicate = useMemo(() => {
    const hasFilters = Object.values(columnFilters).some((selected) => selected && selected.size > 0);
    if (!hasFilters) return null;
    return (item: RemainderImportItem) => {
      for (const [field, selected] of Object.entries(columnFilters)) {
        if (selected && selected.size > 0) {
          const cellValue = getImportItemCellValue(
            item,
            field as RemainderPreviewSortField,
            targetSectionOverrides,
            qualityStateOverrides,
            importableSections,
          );
          if (!selected.has(cellValue)) return false;
        }
      }
      return true;
    };
  }, [columnFilters, targetSectionOverrides, qualityStateOverrides, importableSections]);

  const uniqueValues = useMemo(() => {
    const fields: RemainderPreviewSortField[] = [
      "row",
      "sku",
      "quantity",
      "operations",
      "quality",
      "section",
      "errors",
    ];
    const result = {} as Record<RemainderPreviewSortField, string[]>;
    for (const field of fields) {
      result[field] = [
        ...new Set(
          basePreviewItems.map((item) =>
            getImportItemCellValue(
              item,
              field,
              targetSectionOverrides,
              qualityStateOverrides,
              importableSections,
            ),
          ),
        ),
      ].sort((a, b) => {
        if (field === "row" || field === "quantity") {
          return (Number.parseFloat(a) || 0) - (Number.parseFloat(b) || 0);
        }
        return a.localeCompare(b, "ru");
      });
    }
    return result;
  }, [basePreviewItems, targetSectionOverrides, qualityStateOverrides, importableSections]);

  const { rows: filteredItems } = useTableQueryEngine<RemainderImportItem, RemainderPreviewSortField>({
    rows: basePreviewItems,
    getId: (item) => item.source_row_number,
    searchQuery,
    searchKeys: ["sku", "product_name", "source_row_number"],
    filterPredicate,
    sortConfigs,
    sortDefs,
  });

  const stats = useMemo(() => {
    if (!previewData) return { total: 0, valid: 0, invalid: 0, qty: 0 };
    return {
      total: previewData.summary.total,
      valid: previewData.summary.valid,
      invalid: previewData.summary.invalid,
      qty: previewData.summary.quantity_total,
    };
  }, [previewData]);

  const canApplyImport = useMemo(() => {
    if (previewLoading || importMutation.isPending) return false;
    if (!previewData || stats.total === 0) return false;
    if (rowsMissingSection.length > 0) return false;
    return resolveImportLocationId != null;
  }, [
    previewLoading,
    importMutation.isPending,
    previewData,
    stats.total,
    rowsMissingSection.length,
    resolveImportLocationId,
  ]);

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) handleClose(); }}>
      <DialogContent className={`w-full max-h-[90vh] overflow-hidden flex flex-col transition-all duration-300 ${step === "preview" ? "w-[80vw] max-w-[80vw] h-[85vh]" : "w-[50vw] max-w-[50vw]"}`}>
        <DialogHeader className="shrink-0">
          <DialogTitle>Импорт остатков</DialogTitle>
        </DialogHeader>

        {error ? <ImportPreview.Error message={error} /> : null}

        <div className="flex-1 overflow-y-auto py-2">
          {/* ═══════════════════════ UPLOAD STEP ═══════════════════════ */}
          {step === "upload" && (
            <div className="space-y-3">
              <p className="text-xs text-muted-foreground leading-relaxed">
                Одна таблица для всех остатков: годный, брак или окончательный брак — статус указывается в колонке{" "}
                <strong className="text-foreground">«Статус качества»</strong>. Заголовки необязательны: без них
                столбцы читаются в порядке шаблона. Загрузите Excel или нажмите{" "}
                <kbd className="px-1 py-0.5 rounded border border-border bg-muted text-[10px] font-mono">Ctrl+V</kbd>{" "}
                — данные из буфера подхватятся сразу.
              </p>

              <div className="grid grid-cols-[minmax(0,3fr)_minmax(180px,2fr)] gap-4 items-start">
                {/* Левая колонка: таблица + загрузка */}
                <div className="space-y-3 min-w-0">
                  <div className="space-y-1.5">
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
                            <th className="px-1.5 py-1.5 font-semibold text-foreground whitespace-nowrap">Коммент.</th>
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
                            <td className="px-1.5 py-1.5 text-muted-foreground">—</td>
                          </tr>
                          <tr className="border-b border-border bg-muted/20">
                            <td className="px-1.5 py-1.5 font-mono border-r border-border text-foreground">ALS-1289</td>
                            <td className="px-1.5 py-1.5 border-r border-border text-foreground">150</td>
                            <td className="px-1.5 py-1.5 border-r border-border font-medium text-emerald-700 whitespace-nowrap">Годный</td>
                            <td className="px-1.5 py-1.5 border-r border-border text-muted-foreground">Дробеструй</td>
                            <td className="px-1.5 py-1.5 border-r border-border font-medium text-emerald-700 whitespace-nowrap">{exampleTargetSections.prep}</td>
                            <td className="px-1.5 py-1.5 text-muted-foreground">Партия A</td>
                          </tr>
                          <tr>
                            <td className="px-1.5 py-1.5 font-mono border-r border-border text-foreground">ЮП-2630</td>
                            <td className="px-1.5 py-1.5 border-r border-border text-foreground">80</td>
                            <td className="px-1.5 py-1.5 border-r border-border font-medium text-rose-700 whitespace-nowrap">Окончательный брак</td>
                            <td className="px-1.5 py-1.5 border-r border-border text-muted-foreground">{exampleRow3Operations}</td>
                            <td className="px-1.5 py-1.5 border-r border-border font-medium text-emerald-700/80 whitespace-nowrap">{exampleTargetSections.wip}</td>
                            <td className="px-1.5 py-1.5 text-muted-foreground">Срочный заказ</td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  </div>

                  <ImportUpload.Dropzone
                    inputRef={fileInputRef}
                    onFileChange={handleFileChange}
                    accept=".xlsx,.xls"
                    disabled={previewLoading}
                  />
                </div>

                {/* Правая колонка: справочники */}
                <aside className="space-y-2.5 text-xs text-muted-foreground leading-relaxed min-w-0">
                  <div className="p-2 bg-muted/40 rounded-lg border border-border/60 space-y-1.5">
                    <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider block">
                      Доступные участки
                    </span>
                    <div className="flex flex-wrap gap-1">
                      {seedTargetSections.map((section) => (
                        <span
                          key={section.code}
                          className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-emerald-50/80 text-emerald-800 border border-emerald-200/80 dark:bg-emerald-950/20 dark:text-emerald-300 dark:border-emerald-900/50"
                          title={section.code}
                        >
                          {section.name}
                        </span>
                      ))}
                    </div>
                    <span className="text-[9px] leading-snug block">
                      * пусто (—) — участок выбирается в таблице предпросмотра
                    </span>
                  </div>

                  <div className="p-2 bg-muted/40 rounded-lg border border-border/60 space-y-1.5">
                    <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider block">
                      Статусы качества
                    </span>
                    <div className="flex flex-wrap gap-1">
                      {IMPORT_QUALITY_OPTIONS.map((option) => (
                        <span
                          key={option.value}
                          className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium border ${qualityBadgeClass(option.value)}`}
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
                    <div className="p-2 bg-muted/40 rounded-lg border border-border/60 space-y-1.5">
                      <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider block">
                        Доступные операции
                      </span>
                      <div className="flex flex-wrap gap-1">
                        {operations.map((op: ImportOperationStep) => (
                          <span
                            key={op.operation_name}
                            className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-muted text-foreground border border-border/80"
                            title={`Участок: ${op.section_name}`}
                          >
                            {op.operation_name}
                          </span>
                        ))}
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
            <ImportPreview.Layout>
              <ImportPreview.Toolbar
                left={
                  <>
                    <ImportPreview.SheetTabs
                      sheets={sheets}
                      selectedIndex={selectedSheet}
                      onSelect={setSelectedSheet}
                      disabled={importMode === "clipboard"}
                      label={importMode === "clipboard" ? "Источник" : "Лист"}
                    />
                    <div className="flex items-center gap-1.5">
                      <span className="font-medium text-foreground">Строки</span>
                      <Input
                        value={rowSelection}
                        onChange={(e) => setRowSelection(e.target.value)}
                        placeholder="2-10,12"
                        className="h-7 w-24 text-xs"
                      />
                    </div>
                    <label
                      className={`flex items-center gap-1.5 font-medium select-none ${
                        Object.keys(targetSectionOverrides).length > 0
                          ? "cursor-not-allowed opacity-50"
                          : "cursor-pointer"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={clearExisting}
                        disabled={Object.keys(targetSectionOverrides).length > 0}
                        onChange={(e) => setClearExisting(e.target.checked)}
                        className="h-3.5 w-3.5 rounded border-input text-primary focus:ring-primary"
                      />
                      <span className="text-destructive font-semibold">Очистить перед импортом</span>
                    </label>
                  </>
                }
              />

              {importMode === "clipboard" && clipboardText ? (
                <ImportUpload.ClipboardBanner
                  text={clipboardText}
                  invalidCount={previewData ? stats.invalid : 0}
                  totalCount={previewData ? stats.total : 0}
                />
              ) : null}

              {previewData ? (
                <>
                  <ImportPreview.Stats
                    badges={[
                      { label: `Всего строк: ${stats.total}` },
                      {
                        label: `Корректных: ${stats.valid} (кол-во: ${stats.qty})`,
                        className: "text-green-700 border-green-200 bg-green-50/50",
                      },
                      ...(stats.invalid > 0
                        ? [
                            {
                              label: `Ошибок: ${stats.invalid}`,
                              className: "text-red-700 border-red-200 bg-red-50/50",
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
                    ]}
                  />
                  <ImportPreview.FilterRow
                    search={searchQuery}
                    onSearchChange={setSearchQuery}
                    searchPlaceholder="Поиск по SKU..."
                    filterSlot={
                      <Select
                        value={filterStatus}
                        onValueChange={(value) => setFilterStatus(value as "all" | "invalid")}
                      >
                        <SelectTrigger className="h-7 text-xs w-[120px] font-medium bg-background">
                          <SelectValue placeholder="Все строки" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="all">Все строки</SelectItem>
                          <SelectItem value="invalid">Только ошибки</SelectItem>
                        </SelectContent>
                      </Select>
                    }
                    expansion={expansion}
                  />
                </>
              ) : null}

              <ImportPreview.TableFrame
                loading={previewLoading}
                isEmpty={!previewLoading && filteredItems.length === 0}
                onResetFilters={
                  previewData && previewData.items.length > 0 ? resetPreviewFilters : undefined
                }
                emptyContent={
                  previewData && previewData.items.length > 0 ? (
                    <>
                      <span>Нет строк по текущему фильтру или поиску.</span>
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 text-xs"
                        onClick={resetPreviewFilters}
                      >
                        Сбросить фильтры
                      </Button>
                    </>
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
                <table className="w-full text-xs text-left border-collapse">
                    <thead className="border-b bg-muted/50 sticky top-0 font-semibold text-muted-foreground z-10">
                      <tr>
                        <th className="p-2.5 w-10" />
                        <th className="p-2.5 w-14 text-left">
                          <SortableFilterHeader
                            field="row"
                            label="#"
                            currentSorts={sortConfigs}
                            onSortChange={handleSortChange}
                            values={uniqueValues.row}
                            selectedValues={columnFilters.row ?? new Set()}
                            onFilterChange={handleColumnFilterChange}
                          />
                        </th>
                        <th className="p-2.5 w-32">
                          <SortableFilterHeader
                            field="sku"
                            label="Артикул"
                            currentSorts={sortConfigs}
                            onSortChange={handleSortChange}
                            values={uniqueValues.sku}
                            selectedValues={columnFilters.sku ?? new Set()}
                            onFilterChange={handleColumnFilterChange}
                          />
                        </th>
                        <th className="p-2.5 w-20">
                          <SortableFilterHeader
                            field="quantity"
                            label="Кол-во"
                            currentSorts={sortConfigs}
                            onSortChange={handleSortChange}
                            values={uniqueValues.quantity}
                            selectedValues={columnFilters.quantity ?? new Set()}
                            onFilterChange={handleColumnFilterChange}
                          />
                        </th>
                        <th className="p-2.5 min-w-[140px]">
                          <SortableFilterHeader
                            field="operations"
                            label="Операции"
                            currentSorts={sortConfigs}
                            onSortChange={handleSortChange}
                            values={uniqueValues.operations}
                            selectedValues={columnFilters.operations ?? new Set()}
                            onFilterChange={handleColumnFilterChange}
                          />
                        </th>
                        <th className="p-2.5 w-28">
                          <SortableFilterHeader
                            field="quality"
                            label="Статус качества"
                            currentSorts={sortConfigs}
                            onSortChange={handleSortChange}
                            values={uniqueValues.quality}
                            selectedValues={columnFilters.quality ?? new Set()}
                            onFilterChange={handleColumnFilterChange}
                          />
                        </th>
                        <th className="p-2.5 min-w-[200px]">
                          <SortableFilterHeader
                            field="section"
                            label="Участок"
                            currentSorts={sortConfigs}
                            onSortChange={handleSortChange}
                            values={uniqueValues.section}
                            selectedValues={columnFilters.section ?? new Set()}
                            onFilterChange={handleColumnFilterChange}
                          />
                        </th>
                        <th className="p-2.5 w-72">
                          <SortableFilterHeader
                            field="errors"
                            label="Ошибки валидации"
                            currentSorts={sortConfigs}
                            onSortChange={handleSortChange}
                            values={uniqueValues.errors}
                            selectedValues={columnFilters.errors ?? new Set()}
                            onFilterChange={handleColumnFilterChange}
                          />
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredItems.map((item, idx) => {
                        const isExpanded = isRowExpanded(idx);
                        const hasErrors = item.status === "invalid";
                        const hasRaw = item.raw_values.length > 0;

                        return (
                          <Fragment key={idx}>
                            <tr
                              onClick={() => hasRaw && toggleRow(idx)}
                              className={`border-b transition-colors cursor-pointer hover:bg-muted/30 ${
                                hasErrors ? "bg-red-50/50 dark:bg-red-950/5" : ""
                              }`}
                            >
                              <td className="p-2.5 text-left">
                                <ImportRawRows.Chevron expanded={isExpanded} hasContent={hasRaw} />
                              </td>
                              <td className="p-2.5 text-left font-bold text-muted-foreground">
                                #{item.source_row_number}
                              </td>
                              <td className="p-2.5 font-mono font-semibold">{item.sku}</td>
                              <td className="p-2.5 font-semibold text-foreground">
                                {item.quantity != null ? item.quantity : "—"}
                              </td>
                              <td className="p-2.5 max-w-[280px]">
                                {item.completed_stages && item.completed_stages.length > 0 ? (
                                  <RouteStepsDisplay steps={item.completed_stages} compact />
                                ) : (
                                  <span className="text-muted-foreground">—</span>
                                )}
                              </td>
                              <td
                                className="p-2.5"
                                onClick={(e) => e.stopPropagation()}
                              >
                                <Select
                                  value={getEffectiveQualityState(item, qualityStateOverrides)}
                                  onValueChange={(value) =>
                                    handleRowQualityChange(
                                      item.source_row_number,
                                      value as QualityState,
                                    )
                                  }
                                >
                                  <SelectTrigger
                                    className={`h-7 w-full min-w-[120px] text-[11px] font-semibold border ${qualityBadgeClass(
                                      getEffectiveQualityState(item, qualityStateOverrides),
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
                              </td>
                              <td
                                className="p-2.5"
                                onClick={(e) => e.stopPropagation()}
                              >
                                {hasSectionInFile(item) ? (
                                  <Badge
                                    variant="outline"
                                    className={`font-semibold px-2 py-0.5 rounded text-[10px] whitespace-nowrap ${
                                      item.target_section_id
                                        ? "bg-emerald-50/50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/20 dark:text-emerald-400 dark:border-emerald-900/50"
                                        : "bg-amber-50/50 text-amber-700 border-amber-200"
                                    }`}
                                  >
                                    {item.target_section_name}
                                  </Badge>
                                ) : (
                                  <SectionSelect
                                    sections={importableSections}
                                    value={
                                      targetSectionOverrides[item.source_row_number] ??
                                      item.target_section_id ??
                                      null
                                    }
                                    onValueChange={(sectionId) =>
                                      handleRowSectionChange(item.source_row_number, sectionId)
                                    }
                                    placeholder="Выберите участок"
                                    className="h-7 w-full min-w-[180px] text-[11px]"
                                  />
                                )}
                              </td>
                              <td className="p-2.5 text-destructive font-medium leading-relaxed whitespace-pre-line">
                                {item.errors.map(translateImportError).join(", ") || "—"}
                              </td>
                            </tr>
                            {isExpanded && hasRaw ? (
                              <ImportRawRows.Detail colSpan={9} values={item.raw_values} />
                            ) : null}
                          </Fragment>
                        );
                      })}
                    </tbody>
                  </table>
              </ImportPreview.TableFrame>
            </ImportPreview.Layout>
          )}

          {/* ═══════════════════════ RESULT STEP ════════════════════════ */}
          {step === "result" && result && (
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
        <DialogFooter className="shrink-0 pt-2 border-t flex items-center justify-end gap-2">
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
                  setSheets([]);
                  setPreviewData(null);
                  setError(null);
                }}
                disabled={previewLoading || importMutation.isPending}
              >
                Назад
              </Button>

              {stats.invalid > 0 ? (
                <>
                  <Button
                    variant="outline"
                    onClick={() => handleApply(false)}
                    disabled={previewLoading || importMutation.isPending}
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
