import React, { useCallback, useEffect, useState } from "react";
import { Search, Image, X, Grid, List, Plus, Pencil, Filter, FileUp } from "lucide-react";
import * as API from "@/shared/api/products";
import { Button } from "@/shared/ui/Button";
import { Input } from "@/shared/ui/Input";
import { Card } from "@/shared/ui/Card";
import { Badge } from "@/shared/ui/Badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/shared/ui/Dialog";
import { toast } from "@/shared/ui/use-toast";
import { ImportPreviewDialog } from "../ImportPreviewDialog";
import { CatalogForm } from "../components/CatalogForm";
import { CatalogCard } from "../components/CatalogCard";
import { getPhotoUrl } from "../components/getPhotoUrl";
import type { Product, CreateProductInput, PatchProductInput, CatalogPreview } from "@/shared/api/products";

type ViewMode = "grid" | "table";
type DialogMode = "create" | "edit";

export function RawMaterialsPage() {
  const [items, setItems] = useState<Product[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [viewMode, setViewMode] = useState<ViewMode>("table");
  const [search, setSearch] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [profileTypeFilter, setProfileTypeFilter] = useState("");
  const [alloyFilter, setAlloyFilter] = useState("");
  const [colorFilter, setColorFilter] = useState("");
  const [catalogOnly, setCatalogOnly] = useState(false);
  const [pairedProfileOnly, setPairedProfileOnly] = useState(false);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogMode, setDialogMode] = useState<DialogMode>("create");
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);

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
        profile_type: profileTypeFilter || undefined,
        alloy: alloyFilter || undefined,
        color: colorFilter || undefined,
        is_catalog_item: catalogOnly || undefined,
        is_paired_profile: pairedProfileOnly || undefined,
        limit: 500,
      });
      setItems(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  }, [search, profileTypeFilter, alloyFilter, colorFilter, catalogOnly, pairedProfileOnly]);

  useEffect(() => {
    void load();
  }, [load]);

  const openCreate = () => {
    setSelectedProduct(null);
    setDialogMode("create");
    setDialogOpen(true);
  };

  const openEdit = (product: Product) => {
    setSelectedProduct(product);
    setDialogMode("edit");
    setDialogOpen(true);
  };

  const handleSave = async (payload: CreateProductInput | PatchProductInput, mode: DialogMode) => {
    try {
      if (mode === "create") {
        await API.createProduct(payload as CreateProductInput);
        toast({ title: "Создано", description: "Сырье успешно создано", variant: "success" });
      } else if (mode === "edit" && selectedProduct) {
        await API.patchProduct(selectedProduct.id, payload as PatchProductInput);
        toast({ title: "Сохранено", description: "Изменения успешно сохранены", variant: "success" });
      }
      setDialogOpen(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка сохранения");
      toast({ title: "Ошибка", description: e instanceof Error ? e.message : "Ошибка сохранения", variant: "destructive" });
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

  const activeFiltersCount = [profileTypeFilter, alloyFilter, colorFilter, catalogOnly, pairedProfileOnly].filter(Boolean).length;

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
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input placeholder="Поиск по артикулу или названию..." value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9" />
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
      </div>

      {filtersOpen && (
        <Card className="p-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <div>
              <label className="text-sm font-medium mb-1 block">Вид профиля</label>
              <Input placeholder="Напр: короб" value={profileTypeFilter} onChange={(e) => setProfileTypeFilter(e.target.value)} />
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">Сплав</label>
              <Input placeholder="Напр: АД31" value={alloyFilter} onChange={(e) => setAlloyFilter(e.target.value)} />
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">Цвет</label>
              <Input placeholder="Напр: черный" value={colorFilter} onChange={(e) => setColorFilter(e.target.value)} />
            </div>
            <div className="flex items-end">
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="checkbox" checked={catalogOnly} onChange={(e) => setCatalogOnly(e.target.checked)} className="h-4 w-4" />
                Только сырье из каталога
              </label>
            </div>
            <div className="flex items-end">
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="checkbox" checked={pairedProfileOnly} onChange={(e) => setPairedProfileOnly(e.target.checked)} className="h-4 w-4" />
                Только парные профили
              </label>
            </div>
          </div>
          {activeFiltersCount > 0 && (
            <Button variant="ghost" size="sm" className="mt-3" onClick={() => {
              setProfileTypeFilter("");
              setAlloyFilter("");
              setColorFilter("");
              setCatalogOnly(false);
              setPairedProfileOnly(false);
            }}>
              Сбросить фильтры
            </Button>
          )}
        </Card>
      )}

      {error && <div className="text-sm text-destructive bg-destructive/10 p-3 rounded-md">{error}</div>}

      {loading ? (
        <div className="text-muted-foreground py-8 text-center">Загрузка...</div>
      ) : items.length === 0 ? (
        <div className="text-muted-foreground py-8 text-center">Ничего не найдено</div>
      ) : viewMode === "grid" ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {items.map((product) => (
            <CatalogCard key={product.id} product={product} onClick={() => openEdit(product)} />
          ))}
        </div>
      ) : (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted">
              <tr>
                <th className="px-4 py-3 text-left font-medium">Фото</th>
                <th className="px-4 py-3 text-left font-medium">Артикул</th>
                <th className="px-4 py-3 text-left font-medium">Длина</th>
                <th className="px-4 py-3 text-left font-medium">Парный</th>
                <th className="px-4 py-3 text-left font-medium">Источник</th>
                <th className="px-4 py-3 text-left font-medium w-20"></th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {items.map((product) => (
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
                  <td className="px-4 py-2 font-medium">{product.sku}</td>
                  <td className="px-4 py-2 text-muted-foreground">{product.length_mm ? `${product.length_mm} мм` : "—"}</td>
                  <td className="px-4 py-2">
                    {product.is_paired_profile && (
                      <Badge variant="secondary" className="text-xs bg-purple-100">Парный</Badge>
                    )}
                  </td>
                  <td className="px-4 py-2">
                    {product.is_catalog_item && (
                      <Badge variant="secondary" className="text-xs bg-blue-100">Сырье (каталог)</Badge>
                    )}
                  </td>
                  <td className="px-4 py-2">
                    <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); openEdit(product); }}>
                      <Pencil className="h-4 w-4" />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{dialogMode === "create" ? "Новое сырье" : "Редактирование"}</DialogTitle>
            <DialogDescription>Заполните все поля</DialogDescription>
          </DialogHeader>
          <CatalogForm product={selectedProduct} mode={dialogMode} onSave={handleSave} onCancel={() => setDialogOpen(false)} />
        </DialogContent>
      </Dialog>

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
