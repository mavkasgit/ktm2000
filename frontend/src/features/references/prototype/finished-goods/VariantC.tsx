// ПРОТОТИП #143, вариант C — «Плитки» (образец: CatalogCard / «Сетка» у сырья).
// Полюс спора про операции: на карточке операций НЕТ (позиция research Odoo/SAP) —
// только строка «N переходов → страница Маршруты». Состав виден прямо на плитке.
import { useMemo, useState } from "react";
import { Search, Image, ArrowRight, FlaskConical } from "lucide-react";
import { Input } from "@/shared/ui/input";
import { Badge } from "@/shared/ui/badge";
import { Card, CardContent } from "@/shared/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/shared/ui/dialog";
import { getPhotoUrl } from "../../components/getPhotoUrl";
import type { Product } from "@/shared/api/products";
import {
  useFinishedGoods,
  useRawMaterialsForMock,
  useRouteStages,
  stagesToSteps,
  mockComposition,
} from "./data";

export function VariantC() {
  const { items, loading, error } = useFinishedGoods();
  const rawMaterials = useRawMaterialsForMock();
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Product | null>(null);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return items;
    return items.filter((p) =>
      p.sku.toLowerCase().includes(q) || p.name.toLowerCase().includes(q),
    );
  }, [items, search]);

  // Тот же счётчик, что в A/B — операции (плоские шаги маршрута)
  const { data: stages } = useRouteStages(selected?.id ?? null);
  const stageCount = stages ? stagesToSteps(stages).length : 0;

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">
          Продукты <span className="text-sm text-muted-foreground font-normal">(наименования ГП)</span>
        </h2>
        <div className="relative w-52">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input placeholder="Поиск" value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9" />
        </div>
      </div>

      {error && <div className="text-sm text-destructive bg-destructive/10 p-3 rounded-md">{error}</div>}

      {loading ? (
        <div className="text-muted-foreground py-8 text-center">Загрузка...</div>
      ) : filtered.length === 0 ? (
        <div className="text-muted-foreground py-8 text-center">Ничего не найдено</div>
      ) : (
        <div className="grid gap-4 grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {filtered.map((product) => {
            const composition = mockComposition(product.sku, rawMaterials);
            return (
              <Card
                key={product.id}
                className="cursor-pointer hover:shadow-md transition-shadow group overflow-hidden"
                onClick={() => setSelected(product)}
              >
                <div className="relative aspect-square w-full bg-muted flex items-center justify-center overflow-hidden">
                  {product.photo_thumb
                    ? <img src={getPhotoUrl(product.photo_thumb)!} alt={product.name} className="w-full h-full object-contain" />
                    : <Image className="w-8 h-8 text-muted-foreground" />}
                </div>
                <CardContent className="p-3 space-y-1.5">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <h3 className="font-medium truncate text-sm">{product.sku}</h3>
                    {product.color && <Badge variant="secondary" className="text-xs shrink-0">{product.color}</Badge>}
                  </div>
                  <div className="text-xs text-muted-foreground truncate">{product.name}</div>
                  {/* Состав прямо на плитке — главный эксперимент варианта C */}
                  <div className="text-xs text-muted-foreground border-t pt-1.5">
                    {composition.length === 0 ? (
                      <span>Состав не задан</span>
                    ) : (
                      <span className="line-clamp-2">
                        Из {composition.length} {"компонент" + (composition.length === 1 ? "а" : "ов")}:{" "}
                        {composition.map((l) => `${l.sku} ×${l.qty}`).join(" + ")}
                      </span>
                    )}
                  </div>
                  {product.lengths_mm.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      <Badge variant="outline" className="text-xs">{product.lengths_mm.join(", ")} мм</Badge>
                    </div>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      <Dialog open={selected !== null} onOpenChange={(open) => { if (!open) setSelected(null); }}>
        <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
          {selected && (
            <>
              <DialogHeader>
                <DialogTitle className="flex items-center gap-3">
                  <span>{selected.sku}</span>
                  <span className="text-sm font-normal text-muted-foreground">{selected.name}</span>
                </DialogTitle>
              </DialogHeader>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="aspect-square bg-muted rounded flex items-center justify-center overflow-hidden">
                  {selected.photo_thumb
                    ? <img src={getPhotoUrl(selected.photo_thumb)!} alt="" className="w-full h-full object-contain" />
                    : <Image className="w-10 h-10 text-muted-foreground" />}
                </div>

                <div className="space-y-5">
                  <div>
                    <div className="flex items-center gap-2 mb-2">
                      <h4 className="text-sm font-semibold">Состав</h4>
                      <Badge variant="outline" className="text-[10px] text-amber-700 border-amber-300 bg-amber-50">
                        <FlaskConical className="h-3 w-3 mr-1" />данные прототипа
                      </Badge>
                    </div>
                    {(() => {
                      const composition = mockComposition(selected.sku, rawMaterials);
                      if (composition.length === 0) return <p className="text-sm text-muted-foreground">Состав не задан</p>;
                      return (
                        <div className="space-y-1.5">
                          {composition.map((line) => (
                            <div key={line.sku} className="flex items-center gap-2 rounded border p-2">
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
                          ))}
                        </div>
                      );
                    })()}
                  </div>

                  <div>
                    <h4 className="text-sm font-semibold mb-2">Размеры и цвета</h4>
                    <div className="flex flex-wrap gap-1">
                      {selected.lengths_mm.map((len) => <Badge key={len} variant="outline">{len} мм</Badge>)}
                      {selected.color && <Badge variant="secondary">{selected.color}</Badge>}
                      {selected.lengths_mm.length === 0 && !selected.color && (
                        <span className="text-sm text-muted-foreground">—</span>
                      )}
                    </div>
                  </div>

                  {/* Операций на карточке НЕТ — только указатель на страницу «Маршруты» */}
                  <div className="rounded-md bg-muted/60 p-3 text-sm text-muted-foreground flex items-center gap-2">
                    <span>{stageCount > 0 ? `Операций: ${stageCount}.` : "Маршрут не назначен."}</span>
                    <a href="/references/routes" className="inline-flex items-center gap-1 text-primary hover:underline shrink-0">
                      Страница «Маршруты» <ArrowRight className="h-3.5 w-3.5" />
                    </a>
                  </div>
                </div>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </section>
  );
}
