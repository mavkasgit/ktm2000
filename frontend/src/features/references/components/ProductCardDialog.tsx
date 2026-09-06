// Карточка продукта (#152, вариант A прототипа #143): состав ГП (просмотр +
// правка по editReferences), размеры/длины/цвета. Только норматив (ADR-0001):
// ни остатков, ни факт-трассировки; блок операций маршрута — следующий тикет.
import { useMemo, useState } from "react";
import { Pencil, Plus, Search, X } from "lucide-react";
import { Badge } from "@/shared/ui/badge";
import { Button } from "@/shared/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/shared/ui/dialog";
import { Input } from "@/shared/ui/input";
import { toast } from "@/shared/ui/use-toast";
import {
  getErrorMessage,
  listProducts,
  replaceProductComposition,
  type CompositionItem,
  type Product,
} from "@/shared/api/products";
import { ProductPhoto } from "./ProductPhoto";
import { formatQuantity } from "../lib/formatQuantity";
import { cn } from "@/shared/utils/cn";

const MAX_COMPONENTS = 2;

/** Черновик строки состава в режиме правки: количество вводится текстом. */
type DraftItem = {
  component_product_id: number;
  sku: string;
  name: string;
  unit: string;
  is_active: boolean;
  quantity: string;
};

function toDraftItems(items: CompositionItem[]): DraftItem[] {
  return items.map((item) => ({
    component_product_id: item.component_product_id,
    sku: item.sku,
    name: item.name,
    unit: item.unit,
    is_active: item.is_active,
    quantity: formatQuantity(item.quantity),
  }));
}

function CharacteristicRow({ label, value }: { label: string; value: string | null | undefined }) {
  if (value == null || value === "") return null;
  return (
    <div className="flex items-baseline justify-between gap-4 text-sm">
      <span className="text-muted-foreground shrink-0">{label}</span>
      <span className="text-right font-medium truncate">{value}</span>
    </div>
  );
}

function Characteristics({ product }: { product: Product }) {
  return (
    <div className="space-y-1.5">
      <CharacteristicRow label="Цвет" value={product.color} />
      <CharacteristicRow label="Анодирование" value={product.anod_type} />
      <CharacteristicRow label="Сплав" value={product.alloy} />
      <CharacteristicRow label="Тип профиля" value={product.profile_type} />
      <CharacteristicRow
        label="Вес на метр"
        value={product.weight_per_meter != null ? `${product.weight_per_meter} кг` : null}
      />
      <CharacteristicRow
        label="Периметр сечения"
        value={product.perimeter_mm != null ? `${product.perimeter_mm} мм` : null}
      />
      <CharacteristicRow
        label="Габарит профиля"
        value={product.mount_width_mm != null ? `${product.mount_width_mm} мм` : null}
      />
      <CharacteristicRow label="Единица" value={product.unit} />
    </div>
  );
}

/** Поиск компонента (сырьё type=component) для добавления в состав. */
function ComponentPicker({
  excludeIds,
  onPick,
}: {
  excludeIds: number[];
  onPick: (component: { id: number; sku: string; name: string; unit: string; is_active: boolean }) => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Product[]>([]);
  const [searching, setSearching] = useState(false);

  const canSearch = query.trim().length > 0;

  const runSearch = async (q: string) => {
    setSearching(true);
    try {
      const items = await listProducts({ type: "component", q, limit: 8, sort: "sku:asc" });
      setResults(items);
    } catch (e) {
      toast({ title: "Ошибка поиска", description: getErrorMessage(e), variant: "destructive" });
    } finally {
      setSearching(false);
    }
  };

  const visible = results.filter((r) => !excludeIds.includes(r.id));

  return (
    <div className="rounded border p-2 space-y-2" data-testid="component-picker">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Поиск сырья по артикулу или названию"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && canSearch) {
              e.preventDefault();
              void runSearch(query.trim());
            }
          }}
          className="pl-9 h-8"
        />
      </div>
      {canSearch && (
        <Button type="button" variant="outline" size="sm" className="w-full" disabled={searching} onClick={() => void runSearch(query.trim())}>
          {searching ? "Поиск…" : "Найти"}
        </Button>
      )}
      {visible.length > 0 && (
        <div className="max-h-48 overflow-y-auto divide-y rounded border">
          {visible.map((item) => (
            <button
              key={item.id}
              type="button"
              className="w-full text-left px-2 py-1.5 hover:bg-muted/50 flex items-center gap-2"
              onClick={() => {
                onPick({
                  id: item.id,
                  sku: item.sku,
                  name: item.name,
                  unit: item.unit,
                  is_active: item.is_active,
                });
                setQuery("");
                setResults([]);
              }}
            >
              <span className="text-sm font-medium">{item.sku}</span>
              <span className="text-xs text-muted-foreground truncate flex-1">{item.name}</span>
              {!item.is_active && (
                <Badge variant="outline" className="text-[10px]">неактивно</Badge>
              )}
            </button>
          ))}
        </div>
      )}
      {canSearch && !searching && visible.length === 0 && results.length > 0 && (
        <p className="text-xs text-muted-foreground">Все найденные компоненты уже в составе</p>
      )}
    </div>
  );
}

export function ProductCardDialog({
  product,
  open,
  onOpenChange,
  canEdit,
  onCompositionSaved,
}: {
  product: Product | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  canEdit: boolean;
  onCompositionSaved?: (productId: number, items: CompositionItem[]) => void;
}) {
  const [composition, setComposition] = useState<CompositionItem[]>([]);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<DraftItem[]>([]);
  const [saving, setSaving] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);

  // Продукт приходит из списка с составом (include_composition); при смене
  // выбранного продукта состояние карточки сбрасывается.
  const key = product?.id ?? null;
  const compositionFromList = useMemo(() => product?.composition ?? [], [product]);
  const [loadedKey, setLoadedKey] = useState<number | null>(null);
  if (key !== loadedKey) {
    setLoadedKey(key);
    setComposition(compositionFromList);
    setEditing(false);
    setDraft([]);
    setPickerOpen(false);
  }

  const startEdit = () => {
    setDraft(toDraftItems(composition));
    setPickerOpen(false);
    setEditing(true);
  };

  const addComponent = (component: { id: number; sku: string; name: string; unit: string; is_active: boolean }) => {
    setDraft((prev) => [
      ...prev,
      {
        component_product_id: component.id,
        sku: component.sku,
        name: component.name,
        unit: component.unit,
        is_active: component.is_active,
        quantity: "1",
      },
    ]);
    setPickerOpen(false);
  };

  const save = async () => {
    if (!product) return;
    const parsed = draft.map((item) => ({ item, quantity: Number(item.quantity.replace(",", ".")) }));
    const invalid = parsed.find(({ quantity }) => !Number.isFinite(quantity) || quantity <= 0);
    if (invalid) {
      toast({
        title: "Проверьте количество",
        description: `Количество для ${invalid.item.sku} должно быть числом больше нуля`,
        variant: "destructive",
      });
      return;
    }
    setSaving(true);
    try {
      const items = await replaceProductComposition(
        product.id,
        // unit передаём как есть: сервер при null подставляет единицу компонента,
        // что молча сбрасывало бы настроенную единицу (ревью #152).
        parsed.map(({ item, quantity }) => ({
          component_product_id: item.component_product_id,
          quantity,
          unit: item.unit,
        })),
      );
      setComposition(items);
      setEditing(false);
      onCompositionSaved?.(product.id, items);
      toast({ title: "Состав сохранён", description: `${product.sku}: компонентов — ${items.length}`, variant: "success" });
    } catch (e) {
      toast({ title: "Не удалось сохранить состав", description: getErrorMessage(e), variant: "destructive" });
    } finally {
      setSaving(false);
    }
  };

  if (!product) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-3">
            <ProductPhoto product={product} className="w-12 h-12" />
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                {product.sku}
                {!product.is_active && (
                  <Badge variant="outline" className="text-[10px]">неактивен</Badge>
                )}
              </div>
              <div className="text-sm font-normal text-muted-foreground">{product.name}</div>
            </div>
            {product.color && <Badge variant="secondary">{product.color}</Badge>}
          </DialogTitle>
        </DialogHeader>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="space-y-6">
            <section>
              <div className="flex items-center gap-2 mb-2">
                <h4 className="text-sm font-semibold">Состав</h4>
                {!editing && canEdit && (
                  <Button type="button" variant="ghost" size="sm" className="h-6 px-2" onClick={startEdit}>
                    <Pencil className="h-3.5 w-3.5" /> Изменить
                  </Button>
                )}
                {editing && (
                  <div className="flex items-center gap-1">
                    <Button type="button" size="sm" className="h-6 px-2" disabled={saving} onClick={() => void save()}>
                      Сохранить
                    </Button>
                    <Button type="button" variant="ghost" size="sm" className="h-6 px-2" disabled={saving} onClick={() => setEditing(false)}>
                      Отмена
                    </Button>
                  </div>
                )}
              </div>

              {!editing ? (
                composition.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Состав не задан</p>
                ) : (
                  <div className="space-y-1.5">
                    {composition.map((item) => (
                      <div key={item.component_product_id} className="flex items-center gap-2 rounded border p-2">
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-medium flex items-center gap-2">
                            {item.sku}
                            {!item.is_active && (
                              <Badge variant="outline" className="text-[10px]">неактивно</Badge>
                            )}
                          </div>
                          <div className="text-xs text-muted-foreground truncate">{item.name}</div>
                        </div>
                        <Badge variant="secondary">
                          ×{formatQuantity(item.quantity)} {item.unit}
                        </Badge>
                      </div>
                    ))}
                  </div>
                )
              ) : (
                <div className="space-y-2">
                  {draft.map((item, index) => (
                    <div key={item.component_product_id} className="flex items-center gap-2 rounded border p-2">
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium">{item.sku}</div>
                        <div className="text-xs text-muted-foreground truncate">{item.name}</div>
                      </div>
                      <Input
                        className="h-8 w-24"
                        inputMode="decimal"
                        value={item.quantity}
                        aria-label={`Количество ${item.sku}`}
                        onChange={(e) =>
                          setDraft((prev) =>
                            prev.map((d, i) => (i === index ? { ...d, quantity: e.target.value } : d)),
                          )
                        }
                      />
                      <span className="text-xs text-muted-foreground">{item.unit}</span>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-8 w-8 p-0"
                        aria-label={`Убрать ${item.sku}`}
                        onClick={() => setDraft((prev) => prev.filter((_, i) => i !== index))}
                      >
                        <X className="h-4 w-4" />
                      </Button>
                    </div>
                  ))}

                  {draft.length < MAX_COMPONENTS ? (
                    pickerOpen ? (
                      <ComponentPicker
                        excludeIds={draft.map((d) => d.component_product_id)}
                        onPick={addComponent}
                      />
                    ) : (
                      <Button type="button" variant="outline" size="sm" onClick={() => setPickerOpen(true)}>
                        <Plus className="h-4 w-4" /> Добавить компонент
                      </Button>
                    )
                  ) : (
                    <p className="text-xs text-muted-foreground">Максимум {MAX_COMPONENTS} компонента</p>
                  )}
                </div>
              )}
            </section>

            <section>
              <h4 className="text-sm font-semibold mb-2">Длины</h4>
              <div className="flex flex-wrap gap-1">
                {product.lengths_mm.length > 0 ? (
                  product.lengths_mm.map((len) => (
                    <Badge
                      key={len}
                      variant="outline"
                      className={cn(len === product.primary_length_mm && "ring-1 ring-primary/40 bg-primary/10")}
                    >
                      {len} мм
                    </Badge>
                  ))
                ) : (
                  <span className="text-sm text-muted-foreground">—</span>
                )}
              </div>
            </section>
          </div>

          <section>
            <h4 className="text-sm font-semibold mb-2">Характеристики</h4>
            <Characteristics product={product} />
          </section>
        </div>
      </DialogContent>
    </Dialog>
  );
}
