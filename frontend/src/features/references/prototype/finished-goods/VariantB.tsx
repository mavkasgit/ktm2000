// ПРОТОТИП #143, вариант B — «Две панели» (master-detail).
// Полюс спора про операции: операции — вкладка карточки, по умолчанию открыт состав.
import { useEffect, useMemo, useState } from "react";
import { Search, Image, Route, Layers, Ruler, FlaskConical } from "lucide-react";
import { Input } from "@/shared/ui/input";
import { Badge } from "@/shared/ui/badge";
import { RouteStepsDisplay } from "@/shared/ui/RouteStepsDisplay";
import { getPhotoUrl } from "../../components/getPhotoUrl";
import type { Product } from "@/shared/api/products";
import {
  useFinishedGoods,
  useRawMaterialsForMock,
  useRouteStages,
  stagesToSteps,
  mockComposition,
} from "./data";

type CardTab = "composition" | "dimensions" | "operations";

const TABS: { key: CardTab; label: string; icon: typeof Layers }[] = [
  { key: "composition", label: "Состав", icon: Layers },
  { key: "dimensions", label: "Размеры и цвета", icon: Ruler },
  { key: "operations", label: "Операции", icon: Route },
];

export function VariantB() {
  const { items, loading, error } = useFinishedGoods();
  const rawMaterials = useRawMaterialsForMock();
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [tab, setTab] = useState<CardTab>("composition");

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return items;
    return items.filter((p) =>
      p.sku.toLowerCase().includes(q) || p.name.toLowerCase().includes(q),
    );
  }, [items, search]);

  // Ничего не выбрано → показываем первый, чтобы правая панель не была пустой
  useEffect(() => {
    if (selectedId == null && filtered.length > 0) {
      setSelectedId(filtered[0].id);
    }
  }, [filtered, selectedId]);

  const selected = filtered.find((p) => p.id === selectedId) ?? null;
  const { data: stages } = useRouteStages(selected?.id ?? null);
  const steps = stages ? stagesToSteps(stages) : [];
  const composition = selected ? mockComposition(selected.sku, rawMaterials) : [];

  return (
    <section className="space-y-4">
      <h2 className="text-xl font-semibold">
        Продукты <span className="text-sm text-muted-foreground font-normal">(наименования ГП)</span>
      </h2>

      {error && <div className="text-sm text-destructive bg-destructive/10 p-3 rounded-md">{error}</div>}

      {loading ? (
        <div className="text-muted-foreground py-8 text-center">Загрузка...</div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-4 items-start">
          {/* Левая панель: компактный список */}
          <div className="rounded-lg border bg-card overflow-hidden">
            <div className="p-2 border-b">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input placeholder="Поиск" value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9 h-8" />
              </div>
            </div>
            <div className="max-h-[70vh] overflow-y-auto divide-y">
              {filtered.map((product) => (
                <button
                  key={product.id}
                  type="button"
                  onClick={() => setSelectedId(product.id)}
                  className={`w-full text-left px-3 py-2 flex items-center gap-2 transition-colors ${
                    product.id === selectedId ? "bg-primary/10" : "hover:bg-muted/50"
                  }`}
                >
                  <div className="w-9 h-9 bg-muted rounded flex items-center justify-center overflow-hidden shrink-0">
                    {product.photo_thumb
                      ? <img src={getPhotoUrl(product.photo_thumb)!} alt="" className="w-full h-full object-contain" />
                      : <Image className="w-4 h-4 text-muted-foreground" />}
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-medium truncate">{product.sku}</div>
                    <div className="text-xs text-muted-foreground truncate">{product.name}</div>
                  </div>
                </button>
              ))}
              {filtered.length === 0 && (
                <div className="px-3 py-8 text-center text-sm text-muted-foreground">Ничего не найдено</div>
              )}
            </div>
          </div>

          {/* Правая панель: карточка всегда видна, вкладки */}
          {selected ? (
            <div className="rounded-lg border bg-card p-5">
              <div className="flex items-start gap-4 mb-4">
                <div className="w-20 h-20 bg-muted rounded flex items-center justify-center overflow-hidden shrink-0">
                  {selected.photo_thumb
                    ? <img src={getPhotoUrl(selected.photo_thumb)!} alt="" className="w-full h-full object-contain" />
                    : <Image className="w-8 h-8 text-muted-foreground" />}
                </div>
                <div>
                  <div className="text-lg font-semibold">{selected.sku}</div>
                  <div className="text-sm text-muted-foreground">{selected.name}</div>
                  <div className="flex gap-1 mt-2 flex-wrap">
                    {selected.color && <Badge variant="secondary">{selected.color}</Badge>}
                    {selected.lengths_mm.map((len) => <Badge key={len} variant="outline">{len} мм</Badge>)}
                  </div>
                </div>
              </div>

              <div className="flex gap-1 border-b mb-4">
                {TABS.map(({ key, label, icon: Icon }) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setTab(key)}
                    className={`inline-flex items-center gap-1.5 px-3 py-2 text-sm border-b-2 -mb-px transition-colors ${
                      tab === key
                        ? "border-primary text-primary font-medium"
                        : "border-transparent text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    <Icon className="h-4 w-4" />
                    {label}
                    {key === "operations" && steps.length > 0 && (
                      <span className="text-xs text-muted-foreground">· {steps.length}</span>
                    )}
                  </button>
                ))}
              </div>

              {tab === "composition" && (
                <div className="space-y-1.5">
                  <div className="flex items-center gap-2 mb-2">
                    <Badge variant="outline" className="text-[10px] text-amber-700 border-amber-300 bg-amber-50">
                      <FlaskConical className="h-3 w-3 mr-1" />данные прототипа
                    </Badge>
                  </div>
                  {composition.length === 0 ? (
                    <p className="text-sm text-muted-foreground">Состав не задан</p>
                  ) : (
                    composition.map((line) => (
                      <div key={line.sku} className="flex items-center gap-2 rounded border p-2 max-w-md">
                        <div className="w-8 h-8 bg-muted rounded flex items-center justify-center overflow-hidden shrink-0">
                          {line.photo_thumb
                            ? <img src={getPhotoUrl(line.photo_thumb)!} alt="" className="w-full h-full object-contain" />
                            : <Image className="w-4 h-4 text-muted-foreground" />}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-medium">{line.sku}</div>
                          <div className="text-xs text-muted-foreground truncate">{line.name}</div>
                        </div>
                        <Badge variant="secondary">×{line.qty} {line.unit}</Badge>
                      </div>
                    ))
                  )}
                </div>
              )}

              {tab === "dimensions" && (
                <div className="space-y-3 max-w-md">
                  <div>
                    <div className="text-xs text-muted-foreground mb-1">Длины</div>
                    <div className="flex flex-wrap gap-1">
                      {selected.lengths_mm.length
                        ? selected.lengths_mm.map((len) => <Badge key={len} variant="outline">{len} мм</Badge>)
                        : <span className="text-sm text-muted-foreground">—</span>}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground mb-1">Цвет</div>
                    {selected.color ? <Badge variant="secondary">{selected.color}</Badge> : <span className="text-sm text-muted-foreground">—</span>}
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground mb-1">Единица</div>
                    <span className="text-sm">{selected.unit}</span>
                  </div>
                </div>
              )}

              {tab === "operations" && (
                <div>
                  {steps.length === 0 ? (
                    <p className="text-sm text-muted-foreground">Маршрут не назначен</p>
                  ) : (
                    <RouteStepsDisplay steps={steps} size="sm" />
                  )}
                </div>
              )}
            </div>
          ) : (
            <div className="rounded-lg border bg-card p-10 text-center text-muted-foreground">
              Выберите продукт слева
            </div>
          )}
        </div>
      )}
    </section>
  );
}
