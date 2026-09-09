import { useCallback, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { Input } from "@/shared/ui/input";
import {
  createProductPair,
  deleteProductPair,
  getErrorMessage,
  listProductPairs,
  patchProductPair,
  searchProductsForAlias,
} from "@/shared/api/products";
import { queryKeys } from "@/shared/api/queryKeys";
import { lengthKey } from "@/shared/lib/hangerQuantity";
import { cn } from "@/shared/utils/cn";
import { ProductSkuSearchInput } from "./ProductSkuSearchInput";

/**
 * Секция «Пары» в CatalogForm (ADR-0023, #146): список пар сырьевого артикула
 * + поиск артикула (общий ProductSkuSearchInput — единый стиль с эквивалентами)
 * + ручная N по длинам пересечения A и B.
 * Пары — отдельный ресурс (pairs-API), сохраняются сразу, мимо общей кнопки
 * «Сохранить»: редактирование симметричное, без «владельца» записи.
 */
export function ProductPairsSection({
  productId,
  sku,
  readOnly = false,
}: {
  productId: number;
  sku?: string;
  readOnly?: boolean;
}) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  // Черновики ручной N: {pairId: {lengthKey: text}} — серверные значения под ними.
  const [drafts, setDrafts] = useState<Record<number, Record<string, string>>>({});

  const { data: pairs = [], isLoading } = useQuery({
    queryKey: queryKeys.products.pairs(productId),
    queryFn: () => listProductPairs(productId),
  });

  const invalidate = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: queryKeys.products.pairs(productId) });
    // Флаг is_paired_profile выведенный — список артикулов тоже обновить.
    queryClient.invalidateQueries({ queryKey: queryKeys.products.all() });
  }, [queryClient, productId]);

  const fetchSuggestions = useCallback(
    (q: string) =>
      searchProductsForAlias(q, {
        excludeSku: sku,
        excludeAliases: pairs.map((p) => p.partner.sku),
        limit: 20,
      }),
    [pairs, sku],
  );

  const addPair = useMutation({
    mutationFn: (partnerId: number) =>
      createProductPair(productId, { partner_product_id: partnerId }),
    onSuccess: () => {
      setError(null);
      invalidate();
    },
    onError: (e) => setError(getErrorMessage(e)),
  });


  const removePair = useMutation({
    mutationFn: (pairId: number) => deleteProductPair(productId, pairId),
    onSuccess: () => {
      setError(null);
      invalidate();
    },
    onError: (e) => setError(getErrorMessage(e)),
  });

  const saveManuals = useMutation({
    mutationFn: ({ pairId, dict }: { pairId: number; dict: Record<string, { manual: number | null }> }) =>
      patchProductPair(productId, pairId, { quantity_per_hanger: dict }),
    onSuccess: () => {
      setError(null);
      invalidate();
    },
    onError: (e) => setError(getErrorMessage(e)),
  });


  const manualFor = (pairId: number, key: string, serverValue: number | null): string => {
    const draft = drafts[pairId]?.[key];
    return draft ?? (serverValue != null ? String(serverValue) : "");
  };

  const updateDraft = (pairId: number, key: string, text: string) => {
    setDrafts((d) => ({ ...d, [pairId]: { ...(d[pairId] ?? {}), [key]: text } }));
  };

  const commitManuals = (pair: (typeof pairs)[number]) => {
    const dict: Record<string, { manual: number | null }> = {};
    let changed = false;
    for (const length of pair.lengths) {
      const key = lengthKey(length);
      const serverManual = pair.quantity_per_hanger[key]?.manual ?? null;
      const raw = drafts[pair.id]?.[key];
      if (raw == null) {
        dict[key] = { manual: serverManual };
        continue;
      }
      const parsed = raw.trim() === "" ? null : Number(raw.replace(",", "."));
      if (parsed != null && (isNaN(parsed) || parsed <= 0 || !Number.isInteger(parsed))) {
        // Некорректное значение — не отправляем, поле подсвечено.
        return;
      }
      dict[key] = { manual: parsed };
      if (parsed !== serverManual) changed = true;
    }
    if (!changed) return;
    saveManuals.mutate({ pairId: pair.id, dict });
  };

  const invalidFor = (pairId: number, key: string): boolean => {
    const raw = drafts[pairId]?.[key];
    if (raw == null || raw.trim() === "") return false;
    const parsed = Number(raw.replace(",", "."));
    return isNaN(parsed) || parsed <= 0 || !Number.isInteger(parsed);
  };

  return (
    <div className="rounded-lg border bg-muted/20 p-3 space-y-3" data-testid="product-pairs-section">
      <span className="text-sm font-medium">Пары</span>

      <div
        className={cn(
          "items-start gap-3",
          readOnly ? "space-y-3" : "grid grid-cols-2",
        )}
      >
        {!readOnly && (
          <div className="space-y-1">
            <ProductSkuSearchInput
              fetchSuggestions={fetchSuggestions}
              onSelect={(s) => addPair.mutate(s.id)}
              busy={addPair.isPending}
            />
            {error && <p className="text-xs text-destructive">{error}</p>}
          </div>
        )}
        <div className={cn(readOnly && "space-y-3")}>
          {isLoading ? (
            <p className="text-xs text-muted-foreground">Загрузка…</p>
          ) : pairs.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              Пар пока нет. Выберите артикул в поиске создания для парного.
            </p>
          ) : (
            <div className="space-y-2">
              {pairs.map((pair) => (
                <div key={pair.id} className="rounded-md border bg-background p-2 space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{pair.partner.sku}</span>
                    <span className="text-xs text-muted-foreground truncate min-w-0 flex-1">
                      {pair.partner.name}
                    </span>
                    {pair.lengths.length === 0 && (
                      <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800 shrink-0">
                        нет общих длин
                      </span>
                    )}
                    {!readOnly && (
                      <button
                        type="button"
                        className="text-muted-foreground hover:text-destructive shrink-0"
                        title="Удалить пару"
                        onClick={() => removePair.mutate(pair.id)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    )}
                  </div>
                  {pair.lengths.length > 0 && (
                    <table className="text-sm w-full">
                      <thead>
                        <tr className="bg-muted/50 text-xs text-muted-foreground border-b">
                          <th className="text-left font-medium px-2 py-1.5">Длина, мм</th>
                          <th className="text-left font-medium px-2 py-1.5">Кол-во на подвесе пары, шт</th>
                          <th className="text-left font-medium px-2 py-1.5">Авто</th>
                        </tr>
                      </thead>
                      <tbody>
                        {pair.lengths.map((length) => {
                          const key = lengthKey(length);
                          const auto = pair.quantity_per_hanger[key]?.auto ?? null;
                          const invalid = invalidFor(pair.id, key);
                          return (
                            <tr key={key} className="border-t">
                              <td className="px-2 py-1">{length}</td>
                              <td className="px-2 py-1">
                                <Input
                                  type="number"
                                  className={cn(
                                    "h-8 w-28",
                                    invalid && "border-destructive focus-visible:ring-destructive",
                                    !invalid && "bg-amber-50 border-amber-300",
                                  )}
                                  value={manualFor(pair.id, key, pair.quantity_per_hanger[key]?.manual ?? null)}
                                  onChange={(e) => updateDraft(pair.id, key, e.target.value)}
                                  onBlur={() => commitManuals(pair)}
                                  disabled={readOnly || saveManuals.isPending}
                                />
                              </td>
                              <td className="px-2 py-1 text-xs text-muted-foreground">
                                {auto != null ? (
                                  <span className="flex items-center gap-1">
                                    {auto}
                                    <span className="rounded bg-emerald-100 px-1 text-[10px] font-semibold text-emerald-800">
                                      авто
                                    </span>
                                  </span>
                                ) : (
                                  "—"
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  )}
                  {pair.lengths.length === 0 && (
                    <p className="rounded bg-amber-50 border border-amber-200 px-2 py-1.5 text-xs text-amber-800">
                      Нет общих длин — пара создана, но не действует: добавьте общие длины обоим артикулам,
                      и пара заработает сама.
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
