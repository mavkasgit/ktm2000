import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Search,
  Image,
  X,
  Upload,
  Grid,
  List,
  Plus,
  Pencil,
  Trash2,
  ChevronDown,
  Filter,
} from "lucide-react";
import * as API from "@/shared/api/products";
import { Button } from "@/shared/ui/Button";
import { Input } from "@/shared/ui/Input";
import { Card, CardContent } from "@/shared/ui/Card";
import { Badge } from "@/shared/ui/Badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/shared/ui/Dialog";
import type { Product, ProductType, CreateProductInput, PatchProductInput } from "@/shared/api/products";

type ViewMode = "grid" | "table";
type DialogMode = "view" | "create" | "edit";

const TYPE_LABELS: Record<ProductType, string> = {
  finished_good: "ГП",
  semi_finished: "П/ф",
  component: "Комплект",
  material: "Материал",
};

const TYPE_OPTIONS: { value: ProductType; label: string }[] = [
  { value: "finished_good", label: "Готовая продукция" },
  { value: "semi_finished", label: "Полуфабрикат" },
  { value: "component", label: "Комплект" },
  { value: "material", label: "Материал" },
];

function getPhotoUrl(path: string | null): string | null {
  if (!path) return null;
  return path.startsWith("/") ? path : `/static/${path}`;
}

export function ProductsScreen() {
  const [items, setItems] = useState<Product[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [viewMode, setViewMode] = useState<ViewMode>("table");
  const [search, setSearch] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [typeFilter, setTypeFilter] = useState<ProductType | "">("");
  const [profileTypeFilter, setProfileTypeFilter] = useState("");
  const [alloyFilter, setAlloyFilter] = useState("");
  const [colorFilter, setColorFilter] = useState("");

  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogMode, setDialogMode] = useState<DialogMode>("view");
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await API.listProducts({
        q: search || undefined,
        type: typeFilter || undefined,
        profile_type: profileTypeFilter || undefined,
        alloy: alloyFilter || undefined,
        color: colorFilter || undefined,
        limit: 500,
      });
      setItems(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  }, [search, typeFilter, profileTypeFilter, alloyFilter, colorFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const openCreate = () => {
    setSelectedProduct(null);
    setDialogMode("create");
    setDialogOpen(true);
  };

  const openView = (product: Product) => {
    setSelectedProduct(product);
    setDialogMode("view");
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
      } else if (mode === "edit" && selectedProduct) {
        await API.patchProduct(selectedProduct.id, payload as PatchProductInput);
      }
      setDialogOpen(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка сохранения");
    }
  };

  const activeFiltersCount = [typeFilter, profileTypeFilter, alloyFilter, colorFilter].filter(Boolean).length;

  return (
    <section className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Справочник изделий</h2>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => setViewMode(viewMode === "grid" ? "table" : "grid")}>
            {viewMode === "grid" ? <List className="h-4 w-4" /> : <Grid className="h-4 w-4" />}
          </Button>
          <Button size="sm" onClick={openCreate}>
            <Plus className="h-4 w-4 mr-1" />
            Добавить
          </Button>
        </div>
      </div>

      {/* Search & Filters */}
      <div className="flex flex-col sm:flex-row gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Поиск по артикулу или названию..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
          {search && (
            <button
              onClick={() => setSearch("")}
              className="absolute right-3 top-1/2 -translate-y-1/2"
            >
              <X className="h-4 w-4 text-muted-foreground" />
            </button>
          )}
        </div>
        <Button
          variant={filtersOpen ? "default" : "outline"}
          size="sm"
          onClick={() => setFiltersOpen(!filtersOpen)}
          className="relative"
        >
          <Filter className="h-4 w-4 mr-1" />
          Фильтры
          {activeFiltersCount > 0 && (
            <Badge variant="secondary" className="ml-1 h-5 min-w-[1.25rem] px-1 text-xs">
              {activeFiltersCount}
            </Badge>
          )}
        </Button>
      </div>

      {/* Filters Panel */}
      {filtersOpen && (
        <Card className="p-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <div>
              <label className="text-sm font-medium mb-1 block">Тип</label>
              <select
                className="w-full h-10 rounded-md border border-input bg-background px-3 text-sm"
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value as ProductType)}
              >
                <option value="">Все</option>
                {TYPE_OPTIONS.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">Вид профиля</label>
              <Input
                placeholder="Напр: короб"
                value={profileTypeFilter}
                onChange={(e) => setProfileTypeFilter(e.target.value)}
              />
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">Сплав</label>
              <Input
                placeholder="Напр: АД31"
                value={alloyFilter}
                onChange={(e) => setAlloyFilter(e.target.value)}
              />
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">Цвет</label>
              <Input
                placeholder="Напр: черный"
                value={colorFilter}
                onChange={(e) => setColorFilter(e.target.value)}
              />
            </div>
          </div>
          {activeFiltersCount > 0 && (
            <Button
              variant="ghost"
              size="sm"
              className="mt-3"
              onClick={() => {
                setTypeFilter("");
                setProfileTypeFilter("");
                setAlloyFilter("");
                setColorFilter("");
              }}
            >
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
            <ProductCard
              key={product.id}
              product={product}
              onClick={() => openView(product)}
              onEdit={(e) => {
                e.stopPropagation();
                openEdit(product);
              }}
            />
          ))}
        </div>
      ) : (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted">
              <tr>
                <th className="px-4 py-3 text-left font-medium">Фото</th>
                <th className="px-4 py-3 text-left font-medium">Артикул</th>
                <th className="px-4 py-3 text-left font-medium">Наименование</th>
                <th className="px-4 py-3 text-left font-medium">Тип</th>
                <th className="px-4 py-3 text-left font-medium">Вид</th>
                <th className="px-4 py-3 text-left font-medium">Сплав</th>
                <th className="px-4 py-3 text-left font-medium">Цвет</th>
                <th className="px-4 py-3 text-left font-medium">Длина</th>
                <th className="px-4 py-3 text-left font-medium w-20"></th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {items.map((product) => (
                <tr
                  key={product.id}
                  className="hover:bg-muted/50 cursor-pointer"
                  onClick={() => openView(product)}
                >
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
                  <td className="px-4 py-2">{product.name}</td>
                  <td className="px-4 py-2">
                    <Badge variant="outline">{TYPE_LABELS[product.type]}</Badge>
                  </td>
                  <td className="px-4 py-2 text-muted-foreground">{product.profile_type || "—"}</td>
                  <td className="px-4 py-2 text-muted-foreground">{product.alloy || "—"}</td>
                  <td className="px-4 py-2 text-muted-foreground">{product.color || "—"}</td>
                  <td className="px-4 py-2 text-muted-foreground">{product.length_mm ? `${product.length_mm} мм` : "—"}</td>
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

      {/* Product Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {dialogMode === "create" ? "Новое изделие" : dialogMode === "edit" ? "Редактирование" : selectedProduct?.name}
            </DialogTitle>
            <DialogDescription>
              {dialogMode === "view" ? "Просмотр карточки изделия" : "Заполните все поля"}
            </DialogDescription>
          </DialogHeader>
          <ProductForm
            product={selectedProduct}
            mode={dialogMode}
            onSave={handleSave}
            onCancel={() => setDialogOpen(false)}
          />
        </DialogContent>
      </Dialog>
    </section>
  );
}

function ProductCard({
  product,
  onClick,
  onEdit,
}: {
  product: Product;
  onClick: () => void;
  onEdit: (e: React.MouseEvent) => void;
}) {
  const photoUrl = getPhotoUrl(product.photo_thumb);

  return (
    <Card className="cursor-pointer hover:shadow-md transition-shadow group" onClick={onClick}>
      <CardContent className="p-4">
        <div className="flex gap-3">
          <div className="w-16 h-16 bg-muted rounded flex items-center justify-center overflow-hidden flex-shrink-0">
            {photoUrl ? (
              <img src={photoUrl} alt={product.name} className="w-full h-full object-contain" />
            ) : (
              <Image className="w-6 h-6 text-muted-foreground" />
            )}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-start justify-between">
              <h3 className="font-medium truncate text-sm">{product.sku}</h3>
              <Button variant="ghost" size="sm" className="h-8 w-8 p-0 opacity-0 group-hover:opacity-100" onClick={onEdit}>
                <Pencil className="h-4 w-4" />
              </Button>
            </div>
            <p className="text-sm text-muted-foreground truncate">{product.name}</p>
            <div className="flex gap-1 mt-2 flex-wrap">
              <Badge variant="outline" className="text-xs">{TYPE_LABELS[product.type]}</Badge>
              {product.profile_type && <Badge variant="secondary" className="text-xs">{product.profile_type}</Badge>}
              {product.color && <Badge variant="secondary" className="text-xs">{product.color}</Badge>}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function ProductForm({
  product,
  mode,
  onSave,
  onCancel,
}: {
  product: Product | null;
  mode: DialogMode;
  onSave: (payload: any, mode: DialogMode) => void;
  onCancel: () => void;
}) {
  const isView = mode === "view";
  const [form, setForm] = useState<CreateProductInput>({
    sku: product?.sku ?? "",
    name: product?.name ?? "",
    type: product?.type ?? "finished_good",
    unit: product?.unit ?? "шт",
    is_active: product?.is_active ?? true,
    notes: product?.notes ?? null,
    profile_type: product?.profile_type ?? null,
    alloy: product?.alloy ?? null,
    color: product?.color ?? null,
    anod_type: product?.anod_type ?? null,
    length_mm: product?.length_mm ?? null,
    weight_per_meter: product?.weight_per_meter ?? null,
    quantity_per_hanger: product?.quantity_per_hanger ?? null,
    cross_section: product?.cross_section ?? null,
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (mode === "create") {
      onSave(form, mode);
    } else if (mode === "edit" && product) {
      const patch: PatchProductInput = {};
      (Object.keys(form) as Array<keyof CreateProductInput>).forEach((key) => {
        if (key === "sku") return;
        const val = form[key];
        const orig = product[key as keyof Product];
        if (val !== orig) {
          (patch as any)[key] = val;
        }
      });
      onSave(patch, mode);
    }
  };

  const update = <K extends keyof CreateProductInput>(key: K, value: CreateProductInput[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4 mt-4">
      {/* Photo placeholder */}
      <div className="flex justify-center">
        <div className="w-32 h-32 bg-muted rounded-lg flex items-center justify-center overflow-hidden">
          {product?.photo_thumb ? (
            <img src={getPhotoUrl(product.photo_thumb)!} alt="" className="w-full h-full object-contain" />
          ) : (
            <Image className="w-10 h-10 text-muted-foreground" />
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="space-y-1">
          <label className="text-sm font-medium">Артикул (SKU) *</label>
          <Input
            value={form.sku}
            onChange={(e) => update("sku", e.target.value)}
            disabled={isView || mode === "edit"}
            placeholder="ЮП-1234"
          />
        </div>
        <div className="space-y-1">
          <label className="text-sm font-medium">Наименование *</label>
          <Input
            value={form.name}
            onChange={(e) => update("name", e.target.value)}
            disabled={isView}
            placeholder="Полное название"
          />
        </div>
        <div className="space-y-1">
          <label className="text-sm font-medium">Тип</label>
          <select
            className="w-full h-10 rounded-md border border-input bg-background px-3 text-sm disabled:opacity-50"
            value={form.type}
            onChange={(e) => update("type", e.target.value as ProductType)}
            disabled={isView}
          >
            {TYPE_OPTIONS.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <label className="text-sm font-medium">Ед. изм.</label>
          <Input
            value={form.unit}
            onChange={(e) => update("unit", e.target.value)}
            disabled={isView}
            placeholder="шт, м, кг"
          />
        </div>
        <div className="space-y-1">
          <label className="text-sm font-medium">Вид профиля</label>
          <Input
            value={form.profile_type ?? ""}
            onChange={(e) => update("profile_type", e.target.value || null)}
            disabled={isView}
            placeholder="короб, кант, рассеиватель"
          />
        </div>
        <div className="space-y-1">
          <label className="text-sm font-medium">Сплав</label>
          <Input
            value={form.alloy ?? ""}
            onChange={(e) => update("alloy", e.target.value || null)}
            disabled={isView}
            placeholder="АД31, АД0"
          />
        </div>
        <div className="space-y-1">
          <label className="text-sm font-medium">Цвет</label>
          <Input
            value={form.color ?? ""}
            onChange={(e) => update("color", e.target.value || null)}
            disabled={isView}
            placeholder="черный, серебро"
          />
        </div>
        <div className="space-y-1">
          <label className="text-sm font-medium">Тип анодирования</label>
          <Input
            value={form.anod_type ?? ""}
            onChange={(e) => update("anod_type", e.target.value || null)}
            disabled={isView}
            placeholder="матовое, глянцевое"
          />
        </div>
        <div className="space-y-1">
          <label className="text-sm font-medium">Длина, мм</label>
          <Input
            type="number"
            step="0.1"
            value={form.length_mm ?? ""}
            onChange={(e) => update("length_mm", e.target.value ? parseFloat(e.target.value) : null)}
            disabled={isView}
          />
        </div>
        <div className="space-y-1">
          <label className="text-sm font-medium">Вес погонного метра, кг/м</label>
          <Input
            type="number"
            step="0.001"
            value={form.weight_per_meter ?? ""}
            onChange={(e) => update("weight_per_meter", e.target.value ? parseFloat(e.target.value) : null)}
            disabled={isView}
          />
        </div>
        <div className="space-y-1">
          <label className="text-sm font-medium">Кол-во на подвесе, шт</label>
          <Input
            type="number"
            value={form.quantity_per_hanger ?? ""}
            onChange={(e) => update("quantity_per_hanger", e.target.value ? parseInt(e.target.value) : null)}
            disabled={isView}
          />
        </div>
        <div className="space-y-1">
          <label className="text-sm font-medium">Сечение / габариты</label>
          <Input
            value={form.cross_section ?? ""}
            onChange={(e) => update("cross_section", e.target.value || null)}
            disabled={isView}
            placeholder="20x30, 47мм"
          />
        </div>
      </div>

      <div className="space-y-1">
        <label className="text-sm font-medium">Примечания</label>
        <textarea
          className="w-full min-h-[80px] rounded-md border border-input bg-background px-3 py-2 text-sm disabled:opacity-50"
          value={form.notes ?? ""}
          onChange={(e) => update("notes", e.target.value || null)}
          disabled={isView}
          placeholder="Дополнительная информация..."
        />
      </div>

      {!isView && (
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="outline" onClick={onCancel}>
            Отмена
          </Button>
          <Button type="submit">
            {mode === "create" ? "Создать" : "Сохранить"}
          </Button>
        </div>
      )}
      {isView && (
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="outline" onClick={onCancel}>
            Закрыть
          </Button>
          <Button type="button" onClick={() => onSave(form, "edit")}>
            <Pencil className="h-4 w-4 mr-1" />
            Редактировать
          </Button>
        </div>
      )}
    </form>
  );
}
