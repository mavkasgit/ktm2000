// Страница «Продукты» (#152) — вариант A прототипа #143: таблица ГП +
// карточка-модалка. Образец — RawMaterialsPage, но список отдельный:
// только type=finished_good, только норматив (ADR-0001) — без остатков и факта.
import { useCallback, useEffect, useState } from "react";
import { Search, X } from "lucide-react";
import * as API from "@/shared/api/products";
import type { CompositionItem, Product } from "@/shared/api/products";
import { Badge } from "@/shared/ui/badge";
import { Input } from "@/shared/ui/input";
import { DATA_TABLE_STYLES } from "@/shared/ui";
import { usePermission } from "@/features/auth/hooks/usePermission";
import { ProductPhoto } from "../components/ProductPhoto";
import { ProductCardDialog } from "../components/ProductCardDialog";
import { formatQuantity } from "../lib/formatQuantity";

const headerCellClass = `${DATA_TABLE_STYLES.headerRow} ${DATA_TABLE_STYLES.headerCell}`;

export function ProductsPage() {
  const { canEditReferences } = usePermission();
  const [items, setItems] = useState<Product[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [selected, setSelected] = useState<Product | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search), 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await API.fetchAllProducts({
        type: "finished_good",
        q: debouncedSearch || undefined,
        include_composition: true,
        sort: "sku:asc",
      });
      setItems(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  }, [debouncedSearch]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleCompositionSaved = (productId: number, composition: CompositionItem[]) => {
    setItems((prev) => prev.map((p) => (p.id === productId ? { ...p, composition } : p)));
    setSelected((prev) => (prev && prev.id === productId ? { ...prev, composition } : prev));
  };

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">
          Продукты <span className="text-sm text-muted-foreground font-normal">(наименования ГП)</span>
        </h2>
      </div>

      <div className="relative w-52">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Поиск"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9"
          data-testid="products-search"
        />
        {search && (
          <button
            onClick={() => setSearch("")}
            className="absolute right-3 top-1/2 -translate-y-1/2"
            aria-label="Очистить поиск"
          >
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
              <tr className={DATA_TABLE_STYLES.headerRow}>
                <th className={`${headerCellClass} w-16`}>Фото</th>
                <th className={`${headerCellClass} w-56`}>Артикул</th>
                <th className={`${headerCellClass} w-32`}>Цвет</th>
                <th className={`${headerCellClass} w-40`}>Длины</th>
                <th className={headerCellClass}>Состав</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {items.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-10 text-center text-muted-foreground">
                    Ничего не найдено
                  </td>
                </tr>
              ) : (
                items.map((product) => (
                  <tr
                    key={product.id}
                    className="hover:bg-muted/50 cursor-pointer"
                    onClick={() => setSelected(product)}
                    data-testid={`product-row-${product.sku}`}
                  >
                    <td className="px-4 py-2">
                      <ProductPhoto product={product} />
                    </td>
                    <td className="px-4 py-2">
                      <div className="font-medium flex items-center gap-2">
                        {product.sku}
                        {!product.is_active && (
                          <Badge variant="outline" className="text-[10px]">неактивен</Badge>
                        )}
                      </div>
                      <div className="text-xs text-muted-foreground truncate max-w-[200px]">{product.name}</div>
                    </td>
                    <td className="px-4 py-2 text-muted-foreground">{product.color ?? "—"}</td>
                    <td className="px-4 py-2 text-muted-foreground">
                      {(product.lengths ?? []).length > 0 ? product.lengths.map((length) => `${length.length_mm} мм${length.raw_length_mm != null ? ` (сырьё ${length.raw_length_mm})` : ""}`).join(", ") : "—"}
                    </td>
                    <td className="px-4 py-2">
                      {product.composition && product.composition.length > 0 ? (
                        <div className="flex flex-wrap gap-1">
                          {product.composition.map((item) => (
                            <Badge key={item.component_product_id} variant="outline" className="text-xs font-normal">
                              {item.sku} ×{formatQuantity(item.quantity)}
                            </Badge>
                          ))}
                        </div>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      <ProductCardDialog
        product={selected}
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
        canEdit={canEditReferences}
        onCompositionSaved={handleCompositionSaved}
      />
    </section>
  );
}
