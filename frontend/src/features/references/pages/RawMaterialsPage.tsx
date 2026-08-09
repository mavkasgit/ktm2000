import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, Image, X, Grid, List, Plus, Filter, FileUp, FileSpreadsheet, Check, CheckCheck } from "lucide-react";
import * as API from "@/shared/api/products";
import type { ProductFilters } from "@/shared/api/products";
import { listRouteSelectionRules } from "@/shared/api/routes";
import { queryKeys } from "@/shared/api/queryKeys";
import { pickColumnApiValue } from "@/shared/lib/columnFilterSearch";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";
import { Card } from "@/shared/ui/card";
import { Badge } from "@/shared/ui/badge";
import { Dialog, DialogContent } from "@/shared/ui/dialog";
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogAction, AlertDialogCancel } from "@/shared/ui/alert-dialog";
import { toast } from "@/shared/ui/use-toast";
import { ImportPreviewDialog } from "../ImportPreviewDialog";
import { ImportWizardDialog } from "../components/ImportWizardDialog";
import { CatalogForm, type CatalogFormRef, type FieldChange } from "../components/CatalogForm";
import { CatalogCard } from "../components/CatalogCard";
import { getPhotoUrl } from "../components/getPhotoUrl";
import type { Product, CreateProductInput, PatchProductInput, CatalogPreview } from "@/shared/api/products";
import { usePermission } from "@/features/auth/hooks/usePermission";
import { SortableFilterHeader } from "@/shared/ui/SortableFilterHeader";
import { TableCornerResetCell, TableCornerResetHeader, DATA_TABLE_STYLES } from "@/shared/ui";
import { useSortableColumnFilters } from "@/shared/hooks/useSortableColumnFilters";
import { skipShotBlastSectionLabel } from "../lib/skipShotBlastLabel";
import { HangerCalcTable } from "../components/HangerCalcTable";
import { primaryHangerValue, effectiveForLength, productLengths } from "@/shared/lib/hangerQuantity";
import { isLengthState } from "@/shared/lib/dimensionState";
import { cn } from "@/shared/utils/cn";

type ViewMode = "grid" | "table" | "calc";
type DialogMode = "create" | "edit";
type SortField = "sku" | "name" | "length_mm" | "quantity_per_hanger" | "id" | "is_paired_profile" | "skip_shot_blast" | "is_laminated";
type ColumnFilterField = "sku" | "quantity_per_hanger" | "length_mm" | "is_paired_profile" | "skip_shot_blast" | "is_laminated";
type SortOrder = "asc" | "desc";

interface SortConfig {
  field: SortField;
  order: SortOrder;
}

function boolFromYesNo(value: string | undefined): boolean | undefined {
  if (value === "Да") return true;
  if (value === "Нет") return false;
  return undefined;
}

function buildRawMaterialsApiParams(
  columnFilters: Partial<Record<ColumnFilterField, Set<string>>>,
  columnSearchQueries: Partial<Record<ColumnFilterField, string>>,
  lengthFrom: string,
  lengthTo: string,
  qtyFrom: string,
  qtyTo: string,
  sortConfigs: SortConfig[],
): Pick<
  ProductFilters,
  | "sku"
  | "length_from"
  | "length_to"
  | "qty_from"
  | "qty_to"
  | "is_paired_profile"
  | "skip_shot_blast"
  | "is_laminated"
  | "sort"
> {
  const params: Pick<
    ProductFilters,
    | "sku"
    | "length_from"
    | "length_to"
    | "qty_from"
    | "qty_to"
    | "is_paired_profile"
    | "skip_shot_blast"
    | "is_laminated"
    | "sort"
  > = {};

  const sku = pickColumnApiValue(columnFilters, columnSearchQueries, "sku");
  if (sku) params.sku = sku;

  const lengthValue = pickColumnApiValue(columnFilters, columnSearchQueries, "length_mm");
  if (lengthValue) {
    const parsed = Number.parseFloat(lengthValue);
    if (Number.isFinite(parsed)) {
      params.length_from = parsed;
      params.length_to = parsed;
    }
  }

  const qtyValue = pickColumnApiValue(columnFilters, columnSearchQueries, "quantity_per_hanger", (v) =>
    v === "—" ? undefined : v,
  );
  if (qtyValue) {
    const parsed = Number.parseInt(qtyValue, 10);
    if (Number.isFinite(parsed)) {
      params.qty_from = parsed;
      params.qty_to = parsed;
    }
  }

  const paired = boolFromYesNo(
    pickColumnApiValue(columnFilters, columnSearchQueries, "is_paired_profile"),
  );
  if (paired !== undefined) params.is_paired_profile = paired;

  const skipShot = boolFromYesNo(
    pickColumnApiValue(columnFilters, columnSearchQueries, "skip_shot_blast"),
  );
  if (skipShot !== undefined) params.skip_shot_blast = skipShot;

  const laminated = boolFromYesNo(
    pickColumnApiValue(columnFilters, columnSearchQueries, "is_laminated"),
  );
  if (laminated !== undefined) params.is_laminated = laminated;

  if (lengthFrom) {
    const parsed = Number.parseFloat(lengthFrom);
    if (Number.isFinite(parsed)) params.length_from = parsed;
  }
  if (lengthTo) {
    const parsed = Number.parseFloat(lengthTo);
    if (Number.isFinite(parsed)) params.length_to = parsed;
  }
  if (qtyFrom) {
    const parsed = Number.parseInt(qtyFrom, 10);
    if (Number.isFinite(parsed)) params.qty_from = parsed;
  }
  if (qtyTo) {
    const parsed = Number.parseInt(qtyTo, 10);
    if (Number.isFinite(parsed)) params.qty_to = parsed;
  }

  const activeSort = sortConfigs[0];
  if (activeSort) {
    params.sort = `${activeSort.field}:${activeSort.order}`;
  }

  return params;
}

const headerCellClass = `${DATA_TABLE_STYLES.headerRow} ${DATA_TABLE_STYLES.headerCell}`;

/** Колонка «Кол-во на подвесе» в списке сырья (#65, #85): значение основной длины, подпись «при N мм», бейдж «авто/ручное». */
function QuantityPerHangerCell({ product }: { product: Product }) {
  const primary = primaryHangerValue(product);
  const lengths = productLengths(product);
  const entries = lengths
    .map((len) => ({ len, eff: effectiveForLength(product.quantity_per_hanger, len) }))
    .filter(({ eff }) => eff.value != null);
  if (entries.length === 0) return <span className="text-muted-foreground">—</span>;
  const groups = new Map<number, typeof entries>();
  for (const entry of entries) {
    const group = groups.get(entry.eff.value!) ?? [];
    group.push(entry);
    groups.set(entry.eff.value!, group);
  }
  return (
    <div className="flex flex-wrap gap-1">
      {[...groups.entries()].map(([value, groupEntries]) => {
        const primaryEntry = groupEntries.find(({ len }) => primary?.lengthMm === len);
        const isPrimary = primaryEntry != null;
        const source = primaryEntry?.eff.source ?? groupEntries[0]?.eff.source ?? null;
        const multipleLengths = groupEntries.length > 1;
        return (
          <span
            key={value}
            className={cn(
              "inline-flex items-center gap-1 rounded bg-secondary px-1.5 py-0.5 text-xs text-secondary-foreground",
              isPrimary && "font-medium ring-1 ring-primary/40 bg-primary/10",
            )}
            title={groupEntries.map(({ len, eff }) => `${len} мм: ${eff.value} шт (${eff.source === "auto" ? "авто" : "ручное"})`).join("\n")}
          >
            {value} шт{multipleLengths ? "" : ` при ${groupEntries[0].len} мм`}
            {source === "auto" && (
              <span className="rounded bg-emerald-100 px-1 text-[10px] font-semibold text-emerald-800">авто</span>
            )}
            {source === "manual" && (
              <span className="rounded bg-amber-100 px-1 text-[10px] font-semibold text-amber-800">ручное</span>
            )}
          </span>
        );
      })}
    </div>
  );
}

export function RawMaterialsPage() {
  const { canEditReferences } = usePermission();
  const isReadOnly = !canEditReferences;
  const [items, setItems] = useState<Product[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [viewMode, setViewMode] = useState<ViewMode>("table");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [lengthFrom, setLengthFrom] = useState("");
  const [lengthTo, setLengthTo] = useState("");
  const [qtyFrom, setQtyFrom] = useState("");
  const [qtyTo, setQtyTo] = useState("");
  const [sortConfigs, setSortConfigs] = useState<SortConfig[]>([]);
  const {
    columnFilters,
    columnSearchQueries,
    bindColumn,
    hasActiveColumnFilters: hasColumnFiltersActive,
    resetColumnFilters,
  } = useSortableColumnFilters<ColumnFilterField>();
  const [groupByAliases, setGroupByAliases] = useState(false);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogMode, setDialogMode] = useState<DialogMode>("create");
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
  const [formDirty, setFormDirty] = useState(false);
  const [pendingChanges, setPendingChanges] = useState<FieldChange[]>([]);
  const formRef = useRef<CatalogFormRef>(null);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmAction, setConfirmAction] = useState<(() => void) | null>(null);
  const [pendingAliasSku, setPendingAliasSku] = useState<string | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  const navigateToAlias = async (sku: string) => {
    const found = items.find((p) => p.sku === sku);
    if (found) {
      // Refresh this specific product to get updated aliases
      try {
        const freshProduct = await API.getProduct(found.id);
        setDialogOpen(false);
        setFormDirty(false);
        setTimeout(() => {
          setSelectedProduct(freshProduct);
          setDialogMode("edit");
          setDialogOpen(true);
        }, 150);
      } catch {
        toast({ title: `Ошибка загрузки: ${sku}`, description: `Не удалось загрузить сырьё с артикулом ${sku}`, variant: "destructive" });
      }
    } else {
      toast({ title: `Артикул не найден: ${sku}`, description: `Артикул ${sku} отсутствует в списке сырья`, variant: "destructive" });
    }
  };

  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewData, setPreviewData] = useState<CatalogPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [pendingImportFile, setPendingImportFile] = useState<File | null>(null);
  const [wizardOpen, setWizardOpen] = useState(false);

  // Подпись колонки флага skip_shot_blast — название пропускаемого участка
  // из правил выбора маршрута (БД), а не литерал в коде.
  const { data: selectionRules } = useQuery({
    queryKey: queryKeys.routes.selectionRules(),
    queryFn: () => listRouteSelectionRules(),
  });
  const skipSectionLabel = useMemo(
    () => skipShotBlastSectionLabel(selectionRules) ?? "Пропуск участка",
    [selectionRules],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search), 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  const filterApiParams = useMemo(
    () =>
      buildRawMaterialsApiParams(
        columnFilters,
        columnSearchQueries,
        lengthFrom,
        lengthTo,
        qtyFrom,
        qtyTo,
        sortConfigs,
      ),
    [columnFilters, columnSearchQueries, lengthFrom, lengthTo, qtyFrom, qtyTo, sortConfigs],
  );

  const productsQueryParams = useMemo(
    () => ({
      q: debouncedSearch || undefined,
      type: "component" as const,
      ...filterApiParams,
    }),
    [debouncedSearch, filterApiParams],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await API.fetchAllProducts(productsQueryParams);
      setItems(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  }, [productsQueryParams]);

  useEffect(() => {
    setError("");
    void load();
  }, [load]);

  const openCreate = () => {
    setSelectedProduct(null);
    setDialogMode("create");
    setFormDirty(false);
    setDialogOpen(true);
  };

  const openEdit = (product: Product) => {
    setSelectedProduct(product);
    setDialogMode("edit");
    setFormDirty(false);
    setDialogOpen(true);
  };

  const openConfirm = (action: () => void) => {
    setConfirmAction(() => action);
    setConfirmOpen(true);
  };

  const handleSave = async (payload: CreateProductInput | PatchProductInput, mode: DialogMode) => {
    try {
      if (mode === "create") {
        const result = await API.createProduct(payload as CreateProductInput);
        const product = result.data;
        toast({ title: "Создано", description: `Сырьё "${product.sku}" (ID: ${product.id}${product.name ? `, название: ${product.name}` : ""}) успешно создано`, variant: "success" });
        if (result.activatedAliases?.length) {
          toast({
            title: "Алиасы активированы",
            description: `${result.activatedAliases.length} алиас(ов): ${result.activatedAliases.join(", ")} активирован(ы) в обратном направлении для "${product.sku}"`,
            variant: "success",
          });
        }
      } else if (mode === "edit" && selectedProduct) {
        const result = await API.patchProduct(selectedProduct.id, payload as PatchProductInput);
        const product = result.data;
        toast({ title: "Сохранено", description: `Сырьё "${product.sku}" (ID: ${product.id}) успешно обновлено`, variant: "success" });
        if (result.activatedAliases?.length) {
          toast({
            title: "Алиасы активированы",
            description: `${result.activatedAliases.length} алиас(ов): ${result.activatedAliases.join(", ")} активирован(ы) в обратном направлении для "${product.sku}"`,
            variant: "success",
          });
        }
      }
      setDialogOpen(false);
      setFormDirty(false);
      await load();
      if (pendingAliasSku) {
        navigateToAlias(pendingAliasSku);
        setPendingAliasSku(null);
      }
    } catch (e) {
      const action = dialogMode === "create" ? `создания: ${(payload as CreateProductInput).sku}` : `сохранения: ${selectedProduct?.sku} (ID: ${selectedProduct?.id})`;
      setError(API.getErrorMessage(e));
      toast({ title: `Ошибка ${action}`, description: API.getErrorMessage(e), variant: "destructive" });
    }
  };

  const handleDelete = async () => {
    if (!selectedProduct) return;
    try {
      await API.deleteProduct(selectedProduct.id);
      const lengths = productLengths(selectedProduct);
      const lengthsText = lengths.length ? `${lengths.join(", ")} мм` : "—";
      const qtyText = primaryHangerValue(selectedProduct)?.value ?? "—";
      toast({ title: "Удалено", description: `Сырьё "${selectedProduct.sku}" (артикул: ${selectedProduct.sku}, ID: ${selectedProduct.id}, длины: ${lengthsText}, кол-во на подвесе: ${qtyText}) успешно удалено`, variant: "success" });
      setDialogOpen(false);
      setFormDirty(false);
      await load();
    } catch (e) {
      toast({ title: `Ошибка удаления: ${selectedProduct.sku} (ID: ${selectedProduct.id})`, description: API.getErrorMessage(e), variant: "destructive" });
    } finally {
      setDeleteDialogOpen(false);
    }
  };

  const handleImportZip = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";
    setError("");
    setPreviewLoading(true);
    try {
      const preview = await API.previewCatalogZip(file);
      setPreviewData(preview);
      setPendingImportFile(file);
      setPreviewOpen(true);
    } catch (err) {
      toast({ variant: "destructive", title: `Ошибка предпросмотра: ${file.name}`, description: API.getErrorMessage(err) });
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleConfirmImport = async () => {
    if (!pendingImportFile) return;
    const file = pendingImportFile;
    setPreviewLoading(true);
    try {
      const result = await API.uploadCatalogZip(file);
      setPreviewOpen(false);
      setPreviewData(null);
      setPendingImportFile(null);
      const errorsNote = result.errors.length > 0 ? `, с ошибками: ${result.errors.length}` : "";
      toast({ variant: "success", title: "Импорт завершён", description: `Файл: "${file.name}". Создано: ${result.imported}, обновлено: ${result.updated}, пропущено: ${result.skipped}${errorsNote}` });
      await load();
    } catch (err) {
      toast({ variant: "destructive", title: `Ошибка импорта: ${file.name}`, description: API.getErrorMessage(err) });
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleSort = (field: SortField) => {
    setSortConfigs((prev) => {
      const existing = prev.find((c) => c.field === field);
      if (!existing) return [...prev, { field, order: "desc" }];
      if (existing.order === "desc") return prev.map((c) => c.field === field ? { ...c, order: "asc" } : c);
      return prev.filter((c) => c.field !== field);
    });
  };

  const uniqueValues = useMemo(() => {
    return {
      sku: [...new Set(items.map((p) => p.sku))].sort(),
      quantity_per_hanger: [...new Set(items.map((p) => {
        const value = primaryHangerValue(p)?.value;
        return value != null ? String(value) : "—";
      }))]
        .sort((a, b) => {
          if (a === "—") return 1;
          if (b === "—") return -1;
          return Number(a) - Number(b);
        }),
      length_mm: [...new Set(items.flatMap((p) => productLengths(p).map(String)))]
        .sort((a, b) => Number(a) - Number(b)),
      is_paired_profile: ["Да", "Нет"],
      skip_shot_blast: ["Да", "Нет"],
      is_laminated: ["Да", "Нет"],
    };
  }, [items]);

  const displayedItems = useMemo(() => {
    if (!groupByAliases) return items;

    const withAliases = items.filter((p) => (p.aliases?.length ?? 0) > 0);
    const withoutAliases = items.filter((p) => (p.aliases?.length ?? 0) === 0);
    return [...withAliases, ...withoutAliases];
  }, [items, groupByAliases]);

  const activeFiltersCount = [lengthFrom, lengthTo, qtyFrom, qtyTo].filter(Boolean).length +
    Object.values(columnFilters).reduce((acc, set) => acc + (set?.size ?? 0), 0) +
    Object.values(columnSearchQueries).filter((q) => q?.trim()).length;

  const hasTableActiveFilters =
    search.trim().length > 0 ||
    [lengthFrom, lengthTo, qtyFrom, qtyTo].some(Boolean) ||
    hasColumnFiltersActive ||
    sortConfigs.length > 0;

  const resetTableFilters = () => {
    setSearch("");
    setDebouncedSearch("");
    setLengthFrom("");
    setLengthTo("");
    setQtyFrom("");
    setQtyTo("");
    setSortConfigs([]);
    resetColumnFilters();
  };

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Справочник сырья</h2>
        <div className="flex items-center gap-2">
          <div className="inline-flex items-center rounded-lg border overflow-hidden">
            {([
              ["grid", "Сетка", Grid],
              ["table", "Список", List],
              ["calc", "Расчёт подвесов", null],
            ] as [ViewMode, string, typeof Grid | null][]).map(([mode, label, Icon]) => (
              <button
                key={mode}
                type="button"
                onClick={() => setViewMode(mode)}
                className={cn(
                  "inline-flex items-center gap-1 px-3 h-9 text-sm transition-colors",
                  viewMode === mode
                    ? "bg-primary text-primary-foreground"
                    : "hover:bg-muted text-foreground",
                )}
              >
                {Icon && <Icon className="h-4 w-4" />}
                {label}
              </button>
            ))}
          </div>
          {!isReadOnly && (
            <>
              <label>
                <input type="file" accept=".zip" className="hidden" onChange={handleImportZip} disabled={isReadOnly} />
                <Button variant="outline" size="sm" asChild>
                  <span><FileUp className="h-4 w-4 mr-1" />Импорт ZIP</span>
                </Button>
              </label>
              <Button variant="outline" size="sm" onClick={() => setWizardOpen(true)}>
                <FileSpreadsheet className="h-4 w-4 mr-1" />
                Импорт
              </Button>
              <Button size="sm" onClick={openCreate}>
                <Plus className="h-4 w-4 mr-1" />
                Добавить
              </Button>
            </>
          )}
        </div>
      </div>

      {viewMode !== "calc" && (
        <>
          <div className="flex flex-col sm:flex-row gap-2">
            <div className="relative w-52">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input placeholder="Поиск" value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9" />
              {search && (
                <button onClick={() => setSearch("")} className="absolute right-3 top-1/2 -translate-y-1/2">
                  <X className="h-4 w-4 text-muted-foreground" />
                </button>
              )}
            </div>
            <Button variant={filtersOpen ? "default" : "outline"} size="sm" onClick={() => setFiltersOpen(!filtersOpen)} className="relative">
              <Filter className="h-4 w-4 mr-1" />
              Фильтры
              {activeFiltersCount > 0 && (
                <Badge variant="secondary" className="ml-1 h-5 min-w-[1.25rem] px-1 text-xs">{activeFiltersCount}</Badge>
              )}
            </Button>
            <Button variant={groupByAliases ? "default" : "outline"} size="sm" onClick={() => setGroupByAliases(!groupByAliases)}>
              Сгруппировать одинаковые
            </Button>
          </div>

          {filtersOpen && (
            <Card className="p-4">
              <div className="flex flex-wrap gap-3">
                <div>
                  <label className="text-sm font-medium mb-1 block">Длина от, мм</label>
                  <Input type="number" placeholder="0" value={lengthFrom} onChange={(e) => setLengthFrom(e.target.value)} className="w-40" />
                </div>
                <div>
                  <label className="text-sm font-medium mb-1 block">Длина до, мм</label>
                  <Input type="number" placeholder="6000" value={lengthTo} onChange={(e) => setLengthTo(e.target.value)} className="w-40" />
                </div>
                <div>
                  <label className="text-sm font-medium mb-1 block">Кол-во от</label>
                  <Input type="number" placeholder="0" value={qtyFrom} onChange={(e) => setQtyFrom(e.target.value)} className="w-40" />
                </div>
                <div>
                  <label className="text-sm font-medium mb-1 block">Кол-во до</label>
                  <Input type="number" placeholder="100" value={qtyTo} onChange={(e) => setQtyTo(e.target.value)} className="w-40" />
                </div>
              </div>
            </Card>
          )}
        </>
      )}

      {error && <div className="text-sm text-destructive bg-destructive/10 p-3 rounded-md">{error}</div>}

      {viewMode === "calc" ? (
        <HangerCalcTable readOnly={isReadOnly} onEdit={openEdit} />
      ) : loading ? (
        <div className="text-muted-foreground py-8 text-center">Загрузка...</div>
      ) : items.length === 0 ? (
        <div className="text-muted-foreground py-8 text-center">Ничего не найдено</div>
      ) : viewMode === "grid" ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {displayedItems.map((product) => (
            <CatalogCard key={product.id} product={product} onClick={() => openEdit(product)} />
          ))}
        </div>
      ) : (
        <div className={DATA_TABLE_STYLES.container}>
          <table className="w-full text-sm">
            <thead>
              <tr>
                <th className={`${headerCellClass} w-16`}>Фото</th>
                <th className={`${headerCellClass} p-0 w-48`}>
                  <SortableFilterHeader<ColumnFilterField>
                    field="sku"
                    label="Артикул"
                    currentSorts={sortConfigs as { field: ColumnFilterField; order: SortOrder }[]}
                    onSortChange={(field) => handleSort(field as SortField)}
                    values={uniqueValues.sku}
                    {...bindColumn("sku")}
                  />
                </th>
                <th className={`${headerCellClass} p-0 w-48`}>
                  <SortableFilterHeader<ColumnFilterField>
                    field="quantity_per_hanger"
                    label="Кол-во на подвесе"
                    currentSorts={sortConfigs as { field: ColumnFilterField; order: SortOrder }[]}
                    onSortChange={(field) => handleSort(field as SortField)}
                    values={uniqueValues.quantity_per_hanger}
                    {...bindColumn("quantity_per_hanger")}
                  />
                </th>
                <th className={`${headerCellClass} p-0 w-40`}>
                  <SortableFilterHeader<ColumnFilterField>
                    field="length_mm"
                    label="Размеры"
                    currentSorts={sortConfigs as { field: ColumnFilterField; order: SortOrder }[]}
                    onSortChange={(field) => handleSort(field as SortField)}
                    values={uniqueValues.length_mm}
                    {...bindColumn("length_mm")}
                    valueLabel={(v) => v + " мм"}
                  />
                </th>
                <th className={`${headerCellClass} p-0 w-36`}>
                  <SortableFilterHeader<ColumnFilterField>
                    field="is_paired_profile"
                    label="Парный"
                    currentSorts={sortConfigs as { field: ColumnFilterField; order: SortOrder }[]}
                    onSortChange={(field) => handleSort(field as SortField)}
                    values={uniqueValues.is_paired_profile}
                    {...bindColumn("is_paired_profile")}
                  />
                </th>
                <th className={`${headerCellClass} p-0 w-36`}>
                  <SortableFilterHeader<ColumnFilterField>
                    field="skip_shot_blast"
                    label={skipSectionLabel}
                    currentSorts={sortConfigs as { field: ColumnFilterField; order: SortOrder }[]}
                    onSortChange={(field) => handleSort(field as SortField)}
                    values={uniqueValues.skip_shot_blast}
                    {...bindColumn("skip_shot_blast")}
                  />
                </th>
                <th className={`${headerCellClass} p-0 w-40`}>
                  <SortableFilterHeader<ColumnFilterField>
                    field="is_laminated"
                    label="Ламинируется"
                    currentSorts={sortConfigs as { field: ColumnFilterField; order: SortOrder }[]}
                    onSortChange={(field) => handleSort(field as SortField)}
                    values={uniqueValues.is_laminated}
                    {...bindColumn("is_laminated")}
                  />
                </th>
                <TableCornerResetHeader
                  hasActiveFilters={hasTableActiveFilters}
                  onReset={resetTableFilters}
                  dataTableHeader
                />
              </tr>
            </thead>
            <tbody className="divide-y">
              {displayedItems.map((product) => (
                <tr key={product.id} className="hover:bg-muted/50 cursor-pointer" onClick={() => openEdit(product)}>
                  <td className="px-4 py-2">
                    <div className="w-10 h-10 bg-muted rounded flex items-center justify-center overflow-hidden">
                      {product.photo_thumb ? (
                        <img src={getPhotoUrl(product.photo_thumb)!} alt="" className="w-full h-full object-contain" />
                      ) : (
                        <Image className="w-5 h-5 text-muted-foreground" />
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-2">
                    <div className="flex flex-col gap-1">
                      <div className="flex items-center gap-1.5">
                        <span className="font-medium">{product.sku}</span>
                        {product.has_standard_techcard && (
                          <span title="Есть стандартная техкарта">
                            <Check
                              className="h-3.5 w-3.5 text-emerald-600 flex-shrink-0"
                            />
                          </span>
                        )}
                        {product.has_paired_techcard && (
                          <span title="Есть парная техкарта">
                            <CheckCheck
                              className="h-3.5 w-3.5 text-violet-600 flex-shrink-0"
                            />
                          </span>
                        )}
                      </div>
                      {product.aliases?.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {product.aliases.map((alias, i) => (
                            <span
                              key={i}
                              className="inline-flex px-1.5 py-0.5 rounded border border-transparent text-xs cursor-pointer transition-colors hover:border-primary hover:bg-secondary"
                              onClick={(e) => { e.stopPropagation(); openEdit(items.find(p => p.sku === alias)!); }}
                              title="Перейти к профилю"
                            >
                              {alias}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-2"><QuantityPerHangerCell product={product} /></td>
                  <td className="px-4 py-2 text-muted-foreground">
                    {(() => {
                      const state = product.dimension_state ?? "length";
                      if (isLengthState(state)) {
                        const lengths = productLengths(product);
                        return lengths.length ? lengths.join(", ") + " мм" : "—";
                      }
                      if (state === "area") {
                        const dims = product.dimensions;
                        if (!dims) return "—";
                        const parts = [dims.length_mm, dims.width_mm, dims.thickness_mm]
                          .filter((v): v is number => v != null)
                          .map(String);
                        return parts.length ? parts.join("×") + " мм" : "—";
                      }
                      // 3D
                      const dims3 = product.dimensions;
                      const parts3 = dims3
                        ? [dims3.length_mm, dims3.width_mm, dims3.height_mm]
                            .filter((v): v is number => v != null)
                            .map(String)
                        : [];
                      return (
                        <span className="flex items-center gap-1.5">
                          <Badge variant="secondary" className="text-xs">3D</Badge>
                          {parts3.length > 0 && <span>{parts3.join("×")} мм</span>}
                        </span>
                      );
                    })()}
                  </td>
                  <td className="px-4 py-2">
                    {product.is_paired_profile && (
                      <Badge variant="secondary" className="text-xs bg-purple-100">Парный</Badge>
                    )}
                  </td>
                  <td className="px-4 py-2">
                    {product.skip_shot_blast && (
                      <Badge variant="secondary" className="text-xs bg-amber-100">Пропуск</Badge>
                    )}
                  </td>
                  <td className="px-4 py-2">
                    {product.is_laminated
                      ? <Badge variant="secondary" className="text-xs bg-green-100">Да</Badge>
                      : <span className="text-muted-foreground text-xs">—</span>}
                  </td>
                  <TableCornerResetCell />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Dialog open={dialogOpen} onOpenChange={(open) => {
        if (!open && formDirty) {
          openConfirm(() => {
            setFormDirty(false);
            setDialogOpen(false);
          });
          return;
        }
        setDialogOpen(open);
      }}>
        <DialogContent className="max-w-6xl max-h-[90vh] overflow-y-auto">
          <CatalogForm
            key={`${dialogMode}-${selectedProduct?.id ?? "new"}`}
            ref={formRef}
            product={selectedProduct}
            mode={dialogMode}
            onSave={handleSave}
            onDelete={() => setDeleteDialogOpen(true)}
            readOnly={isReadOnly}
            onCancel={() => {
              if (formDirty) {
                openConfirm(() => {
                  setFormDirty(false);
                  setDialogOpen(false);
                });
                return;
              }
              setDialogOpen(false);
            }}
            onAliasClick={(sku) => {
              if (formDirty) {
                setPendingAliasSku(sku);
                openConfirm(() => {
                  setPendingAliasSku(null);
                  navigateToAlias(sku);
                });
                return;
              }
              navigateToAlias(sku);
            }}
            onDirtyChange={setFormDirty}
            onChangesChange={setPendingChanges}
          />
        </DialogContent>
      </Dialog>

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent className="max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle>Несохранённые изменения</AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div>
                {pendingChanges.length > 0 ? (
                  <>
                    <p className="mb-2">Вы изменили {pendingChanges.length} {pendingChanges.length === 1 ? "параметр" : pendingChanges.length < 5 ? "параметра" : "параметров"}:</p>
                    <ul className="text-sm space-y-1 max-h-48 overflow-auto">
                      {pendingChanges.map((c) => (
                        <li key={c.field} className="flex items-start gap-1">
                          <span className="text-muted-foreground min-w-[100px]">{c.label}:</span>
                          <span className="line-through text-red-600/80">{String(c.from)}</span>
                          <span className="text-muted-foreground mx-0.5">→</span>
                          <span className="text-green-700 font-medium">{String(c.to)}</span>
                        </li>
                      ))}
                    </ul>
                    <p className="mt-3">Сохранить перед выходом?</p>
                  </>
                ) : (
                  <p>Вы внесли изменения. Сохранить перед выходом?</p>
                )}
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter className="flex-col-reverse sm:flex-row gap-2">
            <AlertDialogCancel onClick={() => { setConfirmOpen(false); setPendingAliasSku(null); }}>Отмена</AlertDialogCancel>
            <Button variant="destructive" onClick={() => {
              setConfirmOpen(false);
              setPendingChanges([]);
              confirmAction?.();
            }}>Не сохранять</Button>
            <AlertDialogAction onClick={() => {
              setConfirmOpen(false);
              formRef.current?.save();
            }}>Сохранить</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent className="max-w-sm">
          <AlertDialogHeader>
            <AlertDialogTitle>Удалить {selectedProduct?.sku}?</AlertDialogTitle>
            <AlertDialogDescription>
              Это действие нельзя отменить. Артикул будет удалён из всех эквивалентов.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter className="flex-col-reverse sm:flex-row gap-2">
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <Button variant="destructive" onClick={handleDelete}>
              Удалить
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <ImportPreviewDialog
        open={previewOpen}
        onOpenChange={(open) => {
          setPreviewOpen(open);
          if (!open) { setPreviewData(null); setPendingImportFile(null); }
        }}
        preview={previewData}
        loading={previewLoading}
        onImport={handleConfirmImport}
      />

      <ImportWizardDialog
        open={wizardOpen}
        onOpenChange={setWizardOpen}
        onImported={load}
      />
    </section>
  );
}
