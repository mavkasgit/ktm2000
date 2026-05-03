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
  FileUp,
  Maximize2,
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
  component: "Сырье",
  material: "Материал",
};

const TYPE_OPTIONS: { value: ProductType; label: string }[] = [
  { value: "finished_good", label: "Готовая продукция" },
  { value: "semi_finished", label: "Полуфабрикат" },
  { value: "component", label: "Сырье" },
  { value: "material", label: "Материал" },
];

function getPhotoUrl(path: string | null): string | null {
  if (!path) return null;
  if (path.startsWith("http")) return path;
  const normalized = path.replace(/\\/g, "/");
  return normalized.startsWith("/") ? normalized : `/static/${normalized}`;
}

export function ProductsScreen({ forcedType, title = "Справочник изделий" }: { forcedType?: ProductType; title?: string } = {}) {
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
  const [catalogOnly, setCatalogOnly] = useState(false);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogMode, setDialogMode] = useState<DialogMode>("view");
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await API.listProducts({
        q: search || undefined,
        type: forcedType || typeFilter || undefined,
        profile_type: profileTypeFilter || undefined,
        alloy: alloyFilter || undefined,
        color: colorFilter || undefined,
        is_catalog_item: catalogOnly || undefined,
        limit: 500,
      });
      setItems(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  }, [search, typeFilter, profileTypeFilter, alloyFilter, colorFilter, catalogOnly, forcedType]);

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

  const handleImportZip = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setError("");
    try {
      const result = await API.uploadCatalogZip(file);
      await load();
      setError(`Импорт завершён: ${result.imported} создано, ${result.updated} обновлено, ${result.skipped} без изменений`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка импорта");
    }
    e.target.value = "";
  };

  const activeFiltersCount = [forcedType ? "" : typeFilter, profileTypeFilter, alloyFilter, colorFilter, catalogOnly].filter(Boolean).length;

  return (
    <section className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">{title}</h2>
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
            {!forcedType && <div>
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
            </div>}
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
            <div className="flex items-end">
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  checked={catalogOnly}
                  onChange={(e) => setCatalogOnly(e.target.checked)}
                  className="h-4 w-4"
                />
                Только сырье из каталога
              </label>
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
                setCatalogOnly(false);
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
                <th className="px-4 py-3 text-left font-medium">Длина</th>
                <th className="px-4 py-3 text-left font-medium">Источник</th>
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
                  <td className="px-4 py-2 text-muted-foreground">{product.length_mm ? `${product.length_mm} мм` : "—"}</td>
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
            <div className="flex gap-1 mt-2 flex-wrap">
              <Badge variant="outline" className="text-xs">{TYPE_LABELS[product.type]}</Badge>
              {product.profile_type && <Badge variant="secondary" className="text-xs">{product.profile_type}</Badge>}
              {product.color && <Badge variant="secondary" className="text-xs">{product.color}</Badge>}
              {product.is_catalog_item && <Badge variant="secondary" className="text-xs bg-blue-100">Сырье (каталог)</Badge>}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function FullscreenPhoto({
  src,
  alt,
  onClose,
}: {
  src: string;
  alt: string;
  onClose: () => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const [scale, setScale] = useState(1);
  const [translate, setTranslate] = useState({ x: 0, y: 0 });
  const isDragging = useRef(false);
  const dragStart = useRef({ x: 0, y: 0 });
  const translateStart = useRef({ x: 0, y: 0 });
  const clickStart = useRef({ x: 0, y: 0 });
  const hasDragged = useRef(false);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    el.requestFullscreen().catch(() => {});

    const handleFullscreenChange = () => {
      if (!document.fullscreenElement) onClose();
    };
    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => {
      document.removeEventListener("fullscreenchange", handleFullscreenChange);
      if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    };
  }, [onClose]);

  const zoomToPoint = (clientX: number, clientY: number, newScale: number) => {
    const container = containerRef.current;
    if (!container) return;
    const rect = container.getBoundingClientRect();
    const px = clientX - rect.left - rect.width / 2;
    const py = clientY - rect.top - rect.height / 2;

    setTranslate((prev) => ({
      x: px - (px - prev.x) * (newScale / scale),
      y: py - (py - prev.y) * (newScale / scale),
    }));
    setScale(newScale);
  };

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? -0.15 : 0.15;
    const newScale = Math.max(0.5, Math.min(10, scale + delta));
    if (newScale !== scale) {
      zoomToPoint(e.clientX, e.clientY, newScale);
    }
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    isDragging.current = true;
    hasDragged.current = false;
    dragStart.current = { x: e.clientX, y: e.clientY };
    translateStart.current = { ...translate };
    clickStart.current = { x: e.clientX, y: e.clientY };
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging.current) return;
    const dx = e.clientX - dragStart.current.x;
    const dy = e.clientY - dragStart.current.y;
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
      hasDragged.current = true;
    }
    setTranslate({
      x: translateStart.current.x + dx,
      y: translateStart.current.y + dy,
    });
  };

  const handleMouseUp = (e: React.MouseEvent) => {
    if (!isDragging.current) return;
    isDragging.current = false;

    // If not dragged, treat as click -> zoom in
    if (!hasDragged.current) {
      const dist = Math.hypot(e.clientX - clickStart.current.x, e.clientY - clickStart.current.y);
      if (dist < 5) {
        const newScale = scale >= 3 ? 1 : Math.min(10, scale * 1.6);
        zoomToPoint(e.clientX, e.clientY, newScale);
      }
    }
  };

  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    // Right click -> zoom out or reset
    const newScale = Math.max(0.5, scale / 1.6);
    if (newScale < 0.7) {
      setScale(1);
      setTranslate({ x: 0, y: 0 });
    } else {
      zoomToPoint(e.clientX, e.clientY, newScale);
    }
  };

  const handleDoubleClick = () => {
    setScale(1);
    setTranslate({ x: 0, y: 0 });
  };

  return (
    <div
      ref={containerRef}
      className="fixed inset-0 z-[100] bg-black flex items-center justify-center overflow-hidden select-none"
      onWheel={handleWheel}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      onContextMenu={handleContextMenu}
      onDoubleClick={handleDoubleClick}
    >
      {/* Controls */}
      <div className="absolute top-4 right-4 flex gap-2 z-10">
        <button
          onClick={() => {
            const newScale = Math.min(10, scale * 1.5);
            const rect = containerRef.current?.getBoundingClientRect();
            if (rect) zoomToPoint(rect.left + rect.width / 2, rect.top + rect.height / 2, newScale);
          }}
          className="p-2 bg-black/50 hover:bg-black/70 text-white rounded-full"
          type="button"
          title="Приблизить (+)"
        >
          <Plus className="w-5 h-5" />
        </button>
        <button
          onClick={() => {
            const newScale = Math.max(0.5, scale / 1.5);
            const rect = containerRef.current?.getBoundingClientRect();
            if (rect) zoomToPoint(rect.left + rect.width / 2, rect.top + rect.height / 2, newScale);
          }}
          className="p-2 bg-black/50 hover:bg-black/70 text-white rounded-full"
          type="button"
          title="Отдалить (-)"
        >
          <X className="w-5 h-5" />
        </button>
        <button
          onClick={handleDoubleClick}
          className="p-2 bg-black/50 hover:bg-black/70 text-white rounded-full"
          type="button"
          title="Сбросить (1:1)"
        >
          <Maximize2 className="w-5 h-5" />
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            document.exitFullscreen().catch(() => {});
          }}
          className="p-2 bg-black/50 hover:bg-black/70 text-white rounded-full"
          type="button"
          title="Закрыть"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      {/* Info */}
      <div className="absolute bottom-4 left-4 text-white/60 text-sm z-10 pointer-events-none">
        {Math.round(scale * 100)}% • ЛКМ: приблизить/перетащить • Колесико: зум • ПКМ: отдалить • Двойной клик: сброс
      </div>

      <img
        ref={imageRef}
        src={src}
        alt={alt}
        draggable={false}
        className="max-w-none transition-transform duration-75 ease-out"
        style={{
          transform: `translate(${translate.x}px, ${translate.y}px) scale(${scale})`,
          cursor: isDragging.current ? "grabbing" : scale > 1 ? "grab" : "zoom-in",
        }}
      />
    </div>
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
  const [fullscreenPhoto, setFullscreenPhoto] = useState<string | null>(null);
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
      {/* Photo - full size in dialog */}
      <div className="flex justify-center">
        <div
          className="relative w-full max-w-md h-64 bg-muted rounded-lg flex items-center justify-center overflow-hidden group/photo cursor-pointer hover:ring-2 ring-primary transition-all"
          onClick={() => {
            const full = product?.photo_full || product?.photo_thumb;
            if (full) setFullscreenPhoto(getPhotoUrl(full)!);
          }}
        >
          {product?.photo_full || product?.photo_thumb ? (
            <>
              <img
                src={getPhotoUrl(product?.photo_full || product?.photo_thumb)!}
                alt={product?.name || ""}
                className="w-full h-full object-contain pointer-events-none"
              />
              <div className="absolute bottom-2 right-2 p-2 bg-black/50 text-white rounded-full pointer-events-none">
                <Maximize2 className="w-5 h-5" />
              </div>
            </>
          ) : (
            <Image className="w-16 h-16 text-muted-foreground" />
          )}
        </div>
      </div>

      {fullscreenPhoto && (
        <FullscreenPhoto
          src={fullscreenPhoto}
          alt={product?.name || ""}
          onClose={() => setFullscreenPhoto(null)}
        />
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="space-y-1">
          <label className="text-sm font-medium">Артикул *</label>
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
