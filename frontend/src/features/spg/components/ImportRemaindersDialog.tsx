import { useState, useRef, useEffect, useMemo, Fragment } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Upload, FileText, Loader2, AlertCircle, CheckCircle, ChevronDown, ChevronRight, Download, Search } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  Button,
  Input,
  Badge,
  SpgSelect,
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/shared/ui";
import {
  importRemaindersExcel,
  previewSpgRemaindersExcel,
  getSpgImportOperations,
  type SpgSheetPreviewResponse,
  type SheetPreviewItem,
  type SpgOut,
} from "@/shared/api/spg";
import { getExcelSheetNames } from "@/shared/api/imports";
import { queryKeys } from "@/shared/api/queryKeys";
import { RouteStepsDisplay } from "@/shared/ui/RouteStepsDisplay";
import { apiClient } from "@/shared/api/client";

interface ImportRemaindersDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  spgId: number;
  spgs?: SpgOut[];
  selectedSpgIds?: number[];
  onSaved: () => void;
}

export function ImportRemaindersDialog({
  open,
  onOpenChange,
  spgId,
  spgs,
  selectedSpgIds,
  onSaved,
}: ImportRemaindersDialogProps) {
  const queryClient = useQueryClient();
  const [currentSpgId, setCurrentSpgId] = useState(spgId);

  useEffect(() => {
    setCurrentSpgId(spgId);
  }, [spgId, open]);
  
  const { data: operations } = useQuery({
    queryKey: ["spg", currentSpgId, "import-operations"],
    queryFn: () => getSpgImportOperations(currentSpgId),
    enabled: open,
  });
  
  const [step, setStep] = useState<"upload" | "preview" | "result">("upload");
  const [file, setFile] = useState<File | null>(null);
  const [sheets, setSheets] = useState<string[]>([]);
  const [selectedSheet, setSelectedSheet] = useState(0);
  const [rowSelection, setRowSelection] = useState("");
  const [clearExisting, setClearExisting] = useState(false);
  const [showRawRows, setShowRawRows] = useState(false);
  
  const [searchQuery, setSearchQuery] = useState("");
  const [filterStatus, setFilterStatus] = useState<"all" | "invalid">("all");
  
  const [previewData, setPreviewData] = useState<SpgSheetPreviewResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ imported_count: number; errors: string[] } | null>(null);
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set());

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Load preview when sheet, row selection or target SPG changes
  useEffect(() => {
    if (step !== "preview" || !file) return;
    loadPreview();
  }, [step, selectedSheet, rowSelection, currentSpgId]);

  const loadPreview = async () => {
    if (!file) return;
    setPreviewLoading(true);
    setError(null);
    try {
      const data = await previewSpgRemaindersExcel(currentSpgId, file, {
        sheet_index: selectedSheet,
        row_selection: rowSelection || undefined,
      });
      setPreviewData(data);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Не удалось загрузить предварительный просмотр листа.");
      setPreviewData(null);
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const selectedFile = e.target.files[0];
      setFile(selectedFile);
      setError(null);
      setPreviewLoading(true);
      try {
        const sheetNames = await getExcelSheetNames(selectedFile);
        setSheets(sheetNames);
        setSelectedSheet(0);
        setStep("preview");
      } catch (err: any) {
        setError(err?.response?.data?.detail || "Ошибка при чтении структуры Excel-файла");
        setFile(null);
      } finally {
        setPreviewLoading(false);
      }
    }
  };

  const downloadTemplate = async () => {
    try {
      const response = await apiClient.get(`/spg/${currentSpgId}/remainders/import/template`, {
        responseType: "blob",
      });
      const url = window.URL.createObjectURL(new Blob([response.data]));
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

  const importMutation = useMutation({
    mutationFn: (skipInvalid: boolean) =>
      importRemaindersExcel(currentSpgId, file as File, {
        sheet_index: selectedSheet,
        row_selection: rowSelection || undefined,
        skip_invalid: skipInvalid,
        clear_existing: clearExisting,
      }),
    onSuccess: (response) => {
      if (response.success) {
        setResult({
          imported_count: response.imported_count,
          errors: response.errors,
        });
        void queryClient.invalidateQueries({ queryKey: queryKeys.spg.remainders(currentSpgId) });
        void queryClient.invalidateQueries({ queryKey: queryKeys.spg.snapshot(currentSpgId) });
        void queryClient.invalidateQueries({ queryKey: queryKeys.spg.remainderHistory(currentSpgId) });
        onSaved();
        setStep("result");
      } else {
        // If not success, response has errors (atomic validation failed)
        setError(`Импорт отклонен. Обнаружено ошибок: ${response.errors.length}. Загрузите исправленный файл или примените импорт с пропуском ошибок.`);
      }
    },
    onError: (e: any) => {
      setError(e?.response?.data?.detail || "Ошибка при импорте Excel-файла");
    },
  });

  const handleApply = (skipInvalid: boolean) => {
    if (!file) return;
    setError(null);
    importMutation.mutate(skipInvalid);
  };

  const handleClose = () => {
    setFile(null);
    setSheets([]);
    setSelectedSheet(0);
    setRowSelection("");
    setClearExisting(false);
    setSearchQuery("");
    setFilterStatus("all");
    setPreviewData(null);
    setError(null);
    setResult(null);
    setExpandedRows(new Set());
    setStep("upload");
    onOpenChange(false);
  };

  const toggleRow = (idx: number) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) {
        next.delete(idx);
      } else {
        next.add(idx);
      }
      return next;
    });
  };

  // Client-side filtering and searching of preview items
  const filteredItems = useMemo(() => {
    if (!previewData) return [];
    let items = previewData.items;

    if (filterStatus === "invalid") {
      items = items.filter((item) => item.status === "invalid");
    }

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim();
      items = items.filter(
        (item) =>
          item.sku.toLowerCase().includes(q) ||
          String(item.source_row_number).includes(q) ||
          (item.product_name && item.product_name.toLowerCase().includes(q))
      );
    }

    return items;
  }, [previewData, filterStatus, searchQuery]);

  const stats = useMemo(() => {
    if (!previewData) return { total: 0, valid: 0, invalid: 0, qty: 0 };
    return {
      total: previewData.summary.total,
      valid: previewData.summary.valid,
      invalid: previewData.summary.invalid,
      qty: previewData.summary.quantity_total,
    };
  }, [previewData]);

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) handleClose(); }}>
      <DialogContent className={`w-full max-h-[90vh] overflow-hidden flex flex-col transition-all duration-300 ${step === "preview" ? "max-w-[95vw] h-[85vh]" : "max-w-[500px]"}`}>
        <DialogHeader className="shrink-0">
          <DialogTitle>Импорт остатков из Excel</DialogTitle>
        </DialogHeader>

        {error && (
          <div className="shrink-0 flex items-start gap-2 rounded-lg border border-destructive/20 bg-destructive/10 p-3 text-xs text-destructive">
            <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <span className="font-semibold block">Ошибка импорта</span>
              <span className="leading-relaxed block whitespace-pre-wrap">{error}</span>
            </div>
          </div>
        )}

        <div className="flex-1 overflow-y-auto py-2">
          {step === "upload" && (
            <div className="space-y-6">
              <p className="text-xs text-muted-foreground leading-relaxed">
                Загрузите Excel-файл для пакетного импорта остатков. 
                Система автоматически распознает артикулы, количества и выполненные операции.
              </p>



              {/* Excel table preview example */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <label className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
                    Пример структуры таблицы:
                  </label>
                  <Button
                    variant="link"
                    size="sm"
                    onClick={downloadTemplate}
                    className="h-auto p-0 text-xs text-emerald-600 hover:text-emerald-700 font-medium inline-flex items-center gap-1"
                  >
                    <Download className="h-3.5 w-3.5" />
                    Скачать шаблон Excel
                  </Button>
                </div>
                <div className="border border-border rounded-lg overflow-hidden bg-background">
                  <table className="w-full text-left border-collapse text-xs">
                    <thead>
                      <tr className="bg-muted/50 border-b-2 border-b-emerald-500 dark:border-b-emerald-600">
                        <th className="p-2 font-semibold border-r border-border text-foreground">Артикул</th>
                        <th className="p-2 font-semibold border-r border-border text-foreground">Количество</th>
                        <th className="p-2 font-semibold text-foreground">Выполненные операции</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr className="border-b border-border">
                        <td className="p-2 font-mono border-r border-border text-foreground">ALS-1289</td>
                        <td className="p-2 border-r border-border text-foreground">150</td>
                        <td className="p-2 text-muted-foreground">Дробеструй</td>
                      </tr>
                      <tr className="border-b border-border bg-muted/20">
                        <td className="p-2 font-mono border-r border-border text-foreground">ЮП-2630</td>
                        <td className="p-2 border-r border-border text-foreground">80</td>
                        <td className="p-2 text-muted-foreground">Сверловка, Дробеструй</td>
                      </tr>
                      <tr>
                        <td className="p-2 font-mono border-r border-border text-foreground">361</td>
                        <td className="p-2 border-r border-border text-foreground">200</td>
                        <td className="p-2 text-muted-foreground">— <span className="text-[10px] text-muted-foreground/50">(начнет с первого этапа)</span></td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                {operations && operations.length > 0 && (
                  <div className="mt-2.5 p-2.5 bg-muted/40 rounded-lg border border-border/60">
                    <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider block mb-1">
                      Доступные операции для заполнения:
                    </span>
                    <div className="flex flex-wrap gap-1">
                      {operations.map((op) => (
                        <span
                          key={op.operation_name}
                          className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-muted text-foreground border border-border/80"
                          title={`Раздел: ${op.section_name}`}
                        >
                          {op.operation_name}
                        </span>
                      ))}
                    </div>
                    <span className="text-[9px] text-muted-foreground block mt-1.5 leading-tight">
                      * Вы можете указывать эти названия через запятую в колонке «Выполненные операции» в любом порядке.
                    </span>
                  </div>
                )}
              </div>

              {/* Upload Dropzone */}
              <div
                onClick={() => fileInputRef.current?.click()}
                className="border-2 border-dashed border-muted-foreground/30 rounded-xl p-8 flex flex-col items-center justify-center cursor-pointer hover:bg-accent/40 hover:border-primary/50 transition-colors"
              >
                <input
                  type="file"
                  ref={fileInputRef}
                  onChange={handleFileChange}
                  accept=".xlsx, .xls"
                  className="hidden"
                />
                <Upload className="h-10 w-10 text-muted-foreground mb-3" />
                <span className="text-sm font-medium">Выберите файл для загрузки</span>
                <span className="text-xs text-muted-foreground mt-1">
                  Поддерживаются .xlsx, .xls
                </span>
              </div>
            </div>
          )}

          {step === "preview" && (
            <div className="h-full flex flex-col space-y-3 overflow-hidden">
              {/* Sheet Selection & Main Options */}
              <div className="flex flex-wrap items-center justify-between gap-3 bg-muted/40 p-3 rounded-lg border">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground font-semibold uppercase">Лист Excel:</span>
                  <div className="flex gap-1 flex-wrap">
                    {sheets.map((name, idx) => (
                      <button
                        key={idx}
                        onClick={() => setSelectedSheet(idx)}
                        className={`px-3 py-1 text-xs rounded border transition-colors ${
                          selectedSheet === idx
                            ? "bg-primary text-primary-foreground border-primary font-medium"
                            : "bg-background hover:bg-accent border-input text-foreground"
                        }`}
                      >
                        {name}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs font-medium text-foreground">Строки:</span>
                    <Input
                      value={rowSelection}
                      onChange={(e) => setRowSelection(e.target.value)}
                      placeholder="Напр. 2-10,12"
                      className="h-7 w-28 text-xs"
                    />
                  </div>

                  <label className="flex items-center gap-2 text-xs font-medium cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={clearExisting}
                      onChange={(e) => setClearExisting(e.target.checked)}
                      className="h-3.5 w-3.5 rounded border-input text-primary focus:ring-primary"
                    />
                    <span className="text-destructive font-semibold">Очистить остатки ГХП перед импортом</span>
                  </label>
                </div>
              </div>

              {/* Statistics & Fast Filters */}
              {previewData && (
                <div className="flex flex-wrap items-center gap-4 text-xs font-semibold shrink-0">
                  <Badge variant="outline" className="bg-background px-2.5 py-1">
                    Всего строк: {stats.total}
                  </Badge>
                  <Badge variant="outline" className="text-green-700 border-green-200 bg-green-50/50 px-2.5 py-1">
                    Корректных: {stats.valid} (кол-во: {stats.qty})
                  </Badge>
                  {stats.invalid > 0 && (
                    <Badge variant="outline" className="text-red-700 border-red-200 bg-red-50/50 px-2.5 py-1">
                      Ошибок: {stats.invalid}
                    </Badge>
                  )}

                  {/* Client Filter Inputs */}
                  <div className="flex items-center gap-2 ml-auto shrink-0">
                    <div className="relative">
                      <Search className="absolute left-2 top-1.5 h-3.5 w-3.5 text-muted-foreground" />
                      <Input
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        placeholder="Поиск по SKU..."
                        className="h-7 pl-7 w-48 text-xs"
                      />
                    </div>

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

                    <Button
                      variant={showRawRows ? "default" : "outline"}
                      size="sm"
                      className="h-7 text-xs"
                      onClick={() => setShowRawRows(!showRawRows)}
                    >
                      Сырые строки
                    </Button>
                  </div>
                </div>
              )}

              {/* Table Data Preview */}
              <div className="flex-1 overflow-auto border rounded-xl bg-background">
                {previewLoading ? (
                  <div className="p-8 flex flex-col items-center justify-center gap-2 text-muted-foreground h-full min-h-[200px]">
                    <Loader2 className="h-6 w-6 animate-spin text-primary" />
                    <span className="text-xs">Загрузка данных листа...</span>
                  </div>
                ) : filteredItems.length === 0 ? (
                  <div className="p-8 text-center text-xs text-muted-foreground h-full flex items-center justify-center min-h-[200px]">
                    Нет данных для отображения. Загрузите файл или измените фильтры.
                  </div>
                ) : (
                  <table className="w-full text-xs text-left border-collapse">
                    <thead className="border-b bg-muted/50 sticky top-0 font-semibold text-muted-foreground z-10">
                      <tr>
                        <th className="p-2.5 w-10"></th>
                        <th className="p-2.5 w-16 text-center">Строка</th>
                        <th className="p-2.5 w-36">Артикул</th>
                        <th className="p-2.5 w-64">Наименование изделия</th>
                        <th className="p-2.5 w-24">Количество</th>
                        <th className="p-2.5">Пройденные операции</th>
                        <th className="p-2.5 w-72">Ошибки валидации</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredItems.map((item, idx) => {
                        const isExpanded = showRawRows || expandedRows.has(idx);
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
                              <td className="p-2.5 text-center">
                                {hasRaw && (
                                  isExpanded ? (
                                    <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                                  ) : (
                                    <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
                                  )
                                )}
                              </td>
                              <td className="p-2.5 text-center font-bold text-muted-foreground">
                                #{item.source_row_number}
                              </td>
                              <td className="p-2.5 font-mono font-semibold">{item.sku}</td>
                              <td className="p-2.5 font-medium truncate max-w-[240px]" title={item.product_name || ""}>
                                {item.product_name || "—"}
                              </td>
                              <td className="p-2.5 font-semibold text-foreground">
                                {item.quantity != null ? item.quantity : "—"}
                              </td>
                              <td className="p-2.5">
                                {item.completed_stages.length > 0 ? (
                                  <RouteStepsDisplay steps={item.completed_stages} compact />
                                ) : (
                                  <span className="text-muted-foreground">—</span>
                                )}
                              </td>
                              <td className="p-2.5 text-destructive font-medium leading-relaxed whitespace-pre-line">
                                {item.errors.join(", ") || "—"}
                              </td>
                            </tr>
                            {isExpanded && hasRaw && (
                              <tr className="bg-muted/20 border-b">
                                <td colSpan={7} className="p-2 pl-10 text-[10px] font-mono text-muted-foreground">
                                  <div className="flex flex-wrap gap-1 items-center">
                                    <span className="font-bold uppercase tracking-wider text-muted-foreground/60 mr-2">Сырые ячейки:</span>
                                    {item.raw_values.map((val, cellIdx) => (
                                      <Badge key={cellIdx} variant="secondary" className="px-1 py-0 h-4 text-[9px] rounded font-mono border">
                                        {val || "пусто"}
                                      </Badge>
                                    ))}
                                  </div>
                                </td>
                              </tr>
                            )}
                          </Fragment>
                        );
                      })}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          )}

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
                        {err}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        <DialogFooter className="shrink-0 pt-2 border-t flex items-center justify-end gap-2">
          {step === "upload" && (
            <Button variant="outline" onClick={handleClose}>
              Отмена
            </Button>
          )}

          {step === "preview" && (
            <>
              {spgs && spgs.length > 1 && (!selectedSpgIds || selectedSpgIds.length !== 1) && (
                <div className="flex items-center gap-2 mr-auto">
                  <span className="text-xs font-semibold text-muted-foreground whitespace-nowrap">Импортировать в:</span>
                  <SpgSelect
                    spgs={spgs}
                    value={currentSpgId}
                    onValueChange={(val) => {
                      if (val !== null) {
                        setCurrentSpgId(val);
                      }
                    }}
                    placeholder="Выберите ГХП"
                    className="w-48 h-8 text-xs font-normal bg-background border rounded-md px-2"
                  />
                </div>
              )}
              <Button
                variant="outline"
                onClick={() => {
                  setStep("upload");
                  setFile(null);
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
                    disabled={previewLoading || importMutation.isPending || stats.valid === 0}
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
                  disabled={previewLoading || importMutation.isPending || stats.total === 0}
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
