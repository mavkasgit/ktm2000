import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Search, Image, X, Grid, List, Plus, Filter, FileUp, ArrowUp, ArrowDown, ArrowUpDown } from "lucide-react";
import * as API from "@/shared/api/products";
import { Button } from "@/shared/ui/Button";
import { Input } from "@/shared/ui/Input";
import { Card } from "@/shared/ui/Card";
import { Badge } from "@/shared/ui/Badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/shared/ui/Dialog";
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogAction, AlertDialogCancel } from "@/shared/ui/AlertDialog";
import { toast } from "@/shared/ui/use-toast";
import { ImportPreviewDialog } from "../ImportPreviewDialog";
import { CatalogForm, type CatalogFormRef } from "../components/CatalogForm";
import { CatalogCard } from "../components/CatalogCard";
import { getPhotoUrl } from "../components/getPhotoUrl";
import type { Product, CreateProductInput, PatchProductInput, CatalogPreview } from "@/shared/api/products";

type ViewMode = "grid" | "table";
type DialogMode = "create" | "edit";
type SortField = "sku" | "name" | "length_mm" | "quantity_per_hanger" | "id" | "is_paired_profile" | "skip_shot_blast" | "aliases";
type SortOrder = "asc" | "desc";

interface SortConfig {
  field: SortField;
  order: SortOrder;
}

export function RawMaterialsPage() {
  const [items, setItems] = useState<Product[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [viewMode, setViewMode] = useState<ViewMode>("table");
  const [search, setSearch] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [lengthFrom, setLengthFrom] = useState("");
  const [lengthTo, setLengthTo] = useState("");
  const [qtyFrom, setQtyFrom] = useState("");
  const [qtyTo, setQtyTo] = useState("");
  const [sortConfigs, setSortConfigs] = useState<SortConfig[]>([]);
  const [groupByAliases, setGroupByAliases] = useState(false);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogMode, setDialogMode] = useState<DialogMode>("create");
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
  const [formDirty, setFormDirty] = useState(false);
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
        toast({ title: "Ошибка", description: `Не удалось загрузить ${sku}`, variant: "destructive" });
      }
    } else {
      toast({ title: "Не найден", description: `Артикул ${sku} не найден в списке`, variant: "destructive" });
    }
  };

  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewData, setPreviewData] = useState<CatalogPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [pendingZipFile, setPendingZipFile] = useState<File | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await API.listProducts({
        q: search || undefined,
        type: "component",
        limit: 500,
      });
      setItems(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  }, [search]);

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
        toast({ title: "Создано", description: "Сырье успешно создано", variant: "success" });
        if (result.activatedAliases?.length) {
          toast({
            title: "Алиасы активированы",
            description: `Алиас ${result.activatedAliases.join(", ")} активирован в обратном направлении`,
          });
        }
      } else if (mode === "edit" && selectedProduct) {
        const result = await API.patchProduct(selectedProduct.id, payload as PatchProductInput);
        toast({ title: "Сохранено", description: "Изменения успешно сохранены", variant: "success" });
        if (result.activatedAliases?.length) {
          toast({
            title: "Алиасы активированы",
            description: `Алиас ${result.activatedAliases.join(", ")} активирован в обратном направлении`,
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
      setError(e instanceof Error ? e.message : "Ошибка сохранения");
      toast({ title: "Ошибка", description: e instanceof Error ? e.message : "Ошибка сохранения", variant: "destructive" });
    }
  };

  const handleDelete = async () => {
    if (!selectedProduct) return;
    try {
      await API.deleteProduct(selectedProduct.id);
      toast({ title: "Удалено", description: `${selectedProduct.sku} удалён`, variant: "success" });
      setDialogOpen(false);
      setFormDirty(false);
      await load();
    } catch (e) {
      toast({ title: "Ошибка", description: e instanceof Error ? e.message : "Не удалось удалить", variant: "destructive" });
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
      setPendingZipFile(file);
      setPreviewOpen(true);
    } catch (err) {
      toast({ variant: "destructive", title: "Ошибка предпросмотра", description: err instanceof Error ? err.message : "Не удалось прочитать ZIP" });
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleConfirmImport = async () => {
    if (!pendingZipFile) return;
    setPreviewLoading(true);
    try {
      const result = await API.uploadCatalogZip(pendingZipFile);
      setPreviewOpen(false);
      setPreviewData(null);
      setPendingZipFile(null);
      toast({ variant: "success", title: "Импорт завершён", description: `${result.imported} создано, ${result.updated} обновлено, ${result.skipped} без изменений` });
      await load();
    } catch (err) {
      toast({ variant: "destructive", title: "Ошибка импорта", description: err instanceof Error ? err.message : "Не удалось импортировать" });
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleSort = (field: SortField) => {
    setSortConfigs((prev) => {
      const existing = prev.find((c) => c.field === field);
      if (!existing) return [...prev, { field, order: "asc" }];
      if (existing.order === "asc") return prev.map((c) => c.field === field ? { ...c, order: "desc" } : c);
      return prev.filter((c) => c.field !== field);
    });
  };

  const SortIcon = ({ field }: { field: SortField }) => {
    const config = sortConfigs.find((c) => c.field === field);
    const sortIndex = sortConfigs.findIndex((c) => c.field === field) + 1;
    if (!config) return <ArrowUpDown className="h-3 w-3 ml-1 opacity-40" />;
    return (
      <span className="flex items-center ml-1">
        <span className="text-xs text-muted-foreground mt-0.5">{sortIndex}</span>
        {config.order === "asc" ? <ArrowUp className="h-3 w-3 ml-0.5" /> : <ArrowDown className="h-3 w-3 ml-0.5" />}
      </span>
    );
  };

  const sortedItems = useMemo(() => {
    let filtered = items;
    if (lengthFrom) filtered = filtered.filter((p) => (p.length_mm ?? 0) >= parseFloat(lengthFrom));
    if (lengthTo) filtered = filtered.filter((p) => (p.length_mm ?? 0) <= parseFloat(lengthTo));
    if (qtyFrom) filtered = filtered.filter((p) => (p.quantity_per_hanger ?? 0) >= parseFloat(qtyFrom));
    if (qtyTo) filtered = filtered.filter((p) => (p.quantity_per_hanger ?? 0) <= parseFloat(qtyTo));
    if (sortConfigs.length === 0) return filtered;
    return [...filtered].sort((a, b) => {
      for (const { field, order } of sortConfigs) {
        let aVal: string | number | boolean;
        let bVal: string | number | boolean;
        if (field === "aliases") {
          aVal = (a.aliases?.length ?? 0);
          bVal = (b.aliases?.length ?? 0);
        } else {
          aVal = (a[field as keyof Product] ?? (typeof a[field as keyof Product] === "boolean" ? false : "")) as string | number | boolean;
          bVal = (b[field as keyof Product] ?? (typeof b[field as keyof Product] === "boolean" ? false : "")) as string | number | boolean;
        }
        if (aVal < bVal) return order === "asc" ? -1 : 1;
        if (aVal > bVal) return order === "asc" ? 1 : -1;
      }
      return 0;
    });
  }, [items, sortConfigs, lengthFrom, lengthTo, qtyFrom, qtyTo]);

  const SortHeader = ({ field, children }: { field: SortField; children: React.ReactNode }) => (
    <th
      className="px-4 py-3 text-left font-medium cursor-pointer select-none hover:bg-muted/50 transition-colors"
      onClick={() => handleSort(field)}
    >
      <div className="flex items-center">
        {children}
        <SortIcon field={field} />
      </div>
    </th>
  );

  const activeFiltersCount = [lengthFrom, lengthTo, qtyFrom, qtyTo].filter(Boolean).length;

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Справочник сырья</h2>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => setViewMode(viewMode === "grid" ? "table" : "grid")}>
            {viewMode === "grid" ? <List className="h-4 w-4" /> : <Grid className="h-4 w-4" />}
          </Button>
          <label>
            <input type="file" accept=".zip" className="hidden" onChange={handleImportZip} />
            <Button variant="outline" size="sm" asChild>
              <span><FileUp className="h-4 w-4 mr-1" />Импорт ZIP</span>
            </Button>
          </label>
          <Button size="sm" onClick={openCreate}>
            <Plus className="h-4 w-4 mr-1" />
            Добавить
          </Button>
        </div>
      </div>

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
        <Button variant="outline" size="sm" onClick={() => { setSearch(""); setLengthFrom(""); setLengthTo(""); setQtyFrom(""); setQtyTo(""); setSortConfigs([]); }}>
          Очистить
        </Button>
        <Button variant={filtersOpen ? "default" : "outline"} size="sm" onClick={() => setFiltersOpen(!filtersOpen)} className="relative">
          <Filter className="h-4 w-4 mr-1" />
          Фильтры
          {activeFiltersCount > 0 && (
            <Badge variant="secondary" className="ml-1 h-5 min-w-[1.25rem] px-1 text-xs">{activeFiltersCount}</Badge>
          )}
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

      {error && <div className="text-sm text-destructive bg-destructive/10 p-3 rounded-md">{error}</div>}

      {loading ? (
        <div className="text-muted-foreground py-8 text-center">Загрузка...</div>
      ) : sortedItems.length === 0 ? (
        <div className="text-muted-foreground py-8 text-center">Ничего не найдено</div>
      ) : viewMode === "grid" ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {sortedItems.map((product) => (
            <CatalogCard key={product.id} product={product} onClick={() => openEdit(product)} />
          ))}
        </div>
      ) : (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted">
              <tr>
                <th className="px-4 py-3 text-left font-medium w-16">Фото</th>
                <SortHeader field="sku">Артикул</SortHeader>
                <SortHeader field="quantity_per_hanger">Кол-во на подвесе</SortHeader>
                <SortHeader field="length_mm">Длина</SortHeader>
                <SortHeader field="is_paired_profile">Парный</SortHeader>
                <SortHeader field="skip_shot_blast">Дробеструй</SortHeader>
              </tr>
            </thead>
            <tbody className="divide-y">
              {sortedItems.map((product) => (
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
                      <span className="font-medium">{product.sku}</span>
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
                  <td className="px-4 py-2 text-muted-foreground">{product.quantity_per_hanger ?? "—"}</td>
                  <td className="px-4 py-2 text-muted-foreground">{product.length_mm ? `${product.length_mm} мм` : "—"}</td>
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
        <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{dialogMode === "create" ? "Новое сырье" : "Редактирование"}</DialogTitle>
          </DialogHeader>
          <CatalogForm
            ref={formRef}
            product={selectedProduct}
            mode={dialogMode}
            onSave={handleSave}
            onDelete={() => setDeleteDialogOpen(true)}
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
          />
        </DialogContent>
      </Dialog>

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent className="max-w-sm">
          <AlertDialogHeader>
            <AlertDialogTitle>Несохранённые изменения</AlertDialogTitle>
            <AlertDialogDescription>
              Вы внесли изменения. Сохранить перед выходом?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter className="flex-col-reverse sm:flex-row gap-2">
            <AlertDialogCancel onClick={() => { setConfirmOpen(false); setPendingAliasSku(null); }}>Отмена</AlertDialogCancel>
            <Button variant="destructive" onClick={() => {
              setConfirmOpen(false);
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
          if (!open) { setPreviewData(null); setPendingZipFile(null); }
        }}
        preview={previewData}
        loading={previewLoading}
        onImport={handleConfirmImport}
      />
    </section>
  );
}
