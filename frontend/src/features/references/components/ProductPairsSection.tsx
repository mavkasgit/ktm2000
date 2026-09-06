import React, { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";
import {
  createProductPair,
  deleteProductPair,
  getErrorMessage,
  listProductPairs,
  patchProductPair,
  searchProductsForAlias,
  type AliasSuggestion,
} from "@/shared/api/products";
import { queryKeys } from "@/shared/api/queryKeys";
import { lengthKey } from "@/shared/lib/hangerQuantity";
import { cn } from "@/shared/utils/cn";

/**
 * Секция «Пары» в CatalogForm (ADR-0023, #146): список пар сырьевого артикула
 * + «Добавить пару» (выбор партнёра + ручная N по длинам пересечения A и B).
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
  const [addOpen, setAddOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [suggestions, setSuggestions] = useState<AliasSuggestion[]>([]);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Черновики ручной N: {pairId: {lengthKey: text}} — серверные значения под ними.
  const [drafts, setDrafts] = useState<Record<number, Record<string, string>>>({});
  const dropdownRef = useRef<HTMLDivElement>(null);
  const debounce = useRef<ReturnType<typeof setTimeout>>();

  const { data: pairs = [], isLoading } = useQuery({
    queryKey: queryKeys.products.pairs(productId),
    queryFn: () => listProductPairs(productId),
  });

  const invalidate = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: queryKeys.products.pairs(productId) });
    // Флаг is_paired_profile выведенный — список артикулов тоже обновить.
    queryClient.invalidateQueries({ queryKey: queryKeys.products.all() });
  }, [queryClient, productId]);

  const doSearch = useCallback(
    async (q: string) => {
      setSearching(true);
      try {
        const exclude = pairs.map((p) => p.partner.sku);
        const results = await searchProductsForAlias(q, {
          excludeSku: sku,
          excludeAliases: exclude,
          limit: 20,
        });
        setSuggestions(results);
      } catch {
        setSuggestions([]);
      } finally {
        setSearching(false);
      }
    },
    [pairs, sku],
  );

  const handleSearchChange = (value: string) => {
    setSearch(value);
    if (debounce.current) clearTimeout(debounce.current);
    debounce.current = setTimeout(() => {
      doSearch(value.trim());
    }, 200);
  };

  const addPair = useMutation({
    mutationFn: (partnerId: number) =>
      createProductPair(productId, { partner_product_id: partnerId }),
    onSuccess: () => {
      setError(null);
      setSearch("");
      setSuggestions([]);
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

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setSuggestions([]);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

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
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">Пары</span>
        {!readOnly && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => {
              setAddOpen((o) => !o);
              setSuggestions([]);
            }}
          >
            <Plus className="h-3.5 w-3.5 mr-1" />
            Добавить пару
          </Button>
        )}
      </div>

      {addOpen && !readOnly && (
        <div ref={dropdownRef} className="relative">
          <Input
            className="h-9"
            placeholder="Партнёр: поиск по артикулу"
            value={search}
            onChange={(e) => handleSearchChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                setAddOpen(false);
                setSuggestions([]);
              }
            }}
          />
          {suggestions.length > 0 && (
            <div className="absolute z-50 w-full left-0 mt-1 bg-popover border rounded-md shadow-lg max-h-48 overflow-y-auto">
              {suggestions.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  className="w-full text-left px-3 py-1.5 text-sm hover:bg-muted cursor-pointer flex justify-between items-center"
                  disabled={addPair.isPending}
                  onClick={() => addPair.mutate(s.id)}
                >
                  <span className="font-medium">{s.sku}</span>
                  <span className="text-xs text-muted-foreground truncate max-w-[50%]">{s.name}</span>
                </button>
              ))}
            </div>
          )}
          {(searching || addPair.isPending) && (
            <Loader2 className="h-4 w-4 animate-spin absolute right-2 top-2.5 text-muted-foreground" />
          )}
          <p className="text-xs text-muted-foreground mt-1">
            Ручная N задаётся по длинам после добавления; длины пары — пересечение длин обоих артикулов.
          </p>
        </div>
      )}

      {error && <p className="text-xs text-destructive">{error}</p>}

      {isLoading ? (
        <p className="text-xs text-muted-foreground">Загрузка…</p>
      ) : pairs.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          Пар нет. Артикул обрабатывается одиночно; для совместного подвеса добавьте пару.
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
              {pair.lengths.length === 0 && (
                <p className="text-xs text-muted-foreground">Нет общих длин — пара не существует.</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
