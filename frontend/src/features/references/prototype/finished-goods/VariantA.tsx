// ПРОТОТИП #143, вариант A — «Таблица + модалка» (образец: RawMaterialsPage).
// Полюс спора про операции: маршрут — ГЛАВНЫЙ блок карточки, все секции и переходы.
import { useMemo, useState } from "react";
import { Search, Image, X, Route } from "lucide-react";
import { Input } from "@/shared/ui/input";
import { Badge } from "@/shared/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/shared/ui/dialog";
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

function Photo({ src, className }: { src: string | null; className: string }) {
  return (
    <div className={`${className} bg-muted rounded flex items-center justify-center overflow-hidden shrink-0`}>
      {src ? <img src={src} alt="" className="w-full h-full object-contain" /> : <Image className="w-5 h-5 text-muted-foreground" />}
    </div>
  );
}

/** Блок состава — мок, помечен явно. */
function CompositionBlock({ sku, rawMaterials }: { sku: string; rawMaterials: Product[] }) {
  const lines = mockComposition(sku, rawMaterials);
  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <h4 className="text-sm font-semibold">Состав</h4>
        <Badge variant="outline" className="text-[10px] text-amber-700 border-amber-300 bg-amber-50">данные прототипа</Badge>
      </div>
      {lines.length === 0 ? (
        <p className="text-sm text-muted-foreground">Состав не задан</p>
      ) : (
        <div className="space-y-1.5">
          {lines.map((line) => (
            <div key={line.sku} className="flex items-center gap-2 rounded border p-2">
              <Photo src={getPhotoUrl(line.photo_thumb)} className="w-8 h-8" />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium">{line.sku}</div>
                <div className="text-xs text-muted-foreground truncate">{line.name}</div>
              </div>
              <Badge variant="secondary">×{line.qty} {line.unit}</Badge>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function VariantA() {
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

  const { data: stages } = useRouteStages(selected?.id ?? null);
  const steps = stages ? stagesToSteps(stages) : [];

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">
          Продукты <span className="text-sm text-muted-foreground font-normal">(наименования ГП)</span>
        </h2>
      </div>

      <div className="relative w-52">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input placeholder="Поиск" value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9" />
        {search && (
          <button onClick={() => setSearch("")} className="absolute right-3 top-1/2 -translate-y-1/2">
            <X className="h-4 w-4 text-muted-foreground" />
          </button>
        )}
      </div>

      {error && <div className="text-sm text-destructive bg-destructive/10 p-3 rounded-md">{error}</div>}

      {loading ? (
        <div className="text-muted-foreground py-8 text-center">Загрузка...</div>
      ) : (
        <div className="rounded-lg border bg-card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th className="px-4 py-2 font-medium w-16">Фото</th>
                <th className="px-4 py-2 font-medium w-56">Артикул</th>
                <th className="px-4 py-2 font-medium w-32">Цвет</th>
                <th className="px-4 py-2 font-medium w-40">Длины</th>
                <th className="px-4 py-2 font-medium">Состав</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {filtered.length === 0 ? (
                <tr><td colSpan={5} className="px-4 py-10 text-center text-muted-foreground">Ничего не найдено</td></tr>
              ) : (
                filtered.map((product) => {
                  const composition = mockComposition(product.sku, rawMaterials);
                  return (
                    <tr
                      key={product.id}
                      className="hover:bg-muted/50 cursor-pointer"
                      onClick={() => setSelected(product)}
                    >
                      <td className="px-4 py-2"><Photo src={getPhotoUrl(product.photo_thumb)} className="w-10 h-10" /></td>
                      <td className="px-4 py-2">
                        <div className="font-medium">{product.sku}</div>
                        <div className="text-xs text-muted-foreground truncate max-w-[200px]">{product.name}</div>
                      </td>
                      <td className="px-4 py-2 text-muted-foreground">{product.color ?? "—"}</td>
                      <td className="px-4 py-2 text-muted-foreground">
                        {product.lengths_mm.length ? product.lengths_mm.join(", ") + " мм" : "—"}
                      </td>
                      <td className="px-4 py-2">
                        {composition.length === 0 ? (
                          <span className="text-muted-foreground">—</span>
                        ) : (
                          <div className="flex flex-wrap gap-1">
                            {composition.map((line) => (
                              <Badge key={line.sku} variant="outline" className="text-xs font-normal">
                                {line.sku} ×{line.qty}
                              </Badge>
                            ))}
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      )}

      <Dialog open={selected !== null} onOpenChange={(open) => { if (!open) setSelected(null); }}>
        <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
          {selected && (
            <>
              <DialogHeader>
                <DialogTitle className="flex items-center gap-3">
                  <Photo src={getPhotoUrl(selected.photo_thumb)} className="w-12 h-12" />
                  <div>
                    <div>{selected.sku}</div>
                    <div className="text-sm font-normal text-muted-foreground">{selected.name}</div>
                  </div>
                  {selected.color && <Badge variant="secondary">{selected.color}</Badge>}
                </DialogTitle>
              </DialogHeader>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="space-y-6">
                  <CompositionBlock sku={selected.sku} rawMaterials={rawMaterials} />

                  <div>
                    <h4 className="text-sm font-semibold mb-2">Размеры</h4>
                    <div className="flex flex-wrap gap-1">
                      {selected.lengths_mm.length
                        ? selected.lengths_mm.map((len) => <Badge key={len} variant="outline">{len} мм</Badge>)
                        : <span className="text-sm text-muted-foreground">—</span>}
                    </div>
                  </div>
                </div>

                {/* Спорный блок в варианте A — первый среди равных: полный маршрут */}
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <Route className="h-4 w-4" />
                    <h4 className="text-sm font-semibold">Маршрут (операции)</h4>
                    <Badge variant="secondary" className="text-xs">{steps.length} операций</Badge>
                  </div>
                  {steps.length === 0 ? (
                    <p className="text-sm text-muted-foreground">Маршрут не назначен</p>
                  ) : (
                    <RouteStepsDisplay steps={steps} size="sm" />
                  )}
                </div>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </section>
  );
}
