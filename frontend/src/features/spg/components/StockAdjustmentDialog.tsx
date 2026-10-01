import { useEffect, useState, useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Search } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  Button,
  Input,
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/shared/ui";
import { listSections } from "@/shared/api/sections";
import type { Section } from "@/shared/api/sections";
import { listProducts } from "@/shared/api/products";
import type { Product } from "@/shared/api/products";
import {
  formatCompletedOperationsLabel,
  formatDimensionsLabel,
  getStockBalances,
  OPERATIONS_NOT_RECORDED_LABEL,
  postStockAdjustment,
} from "@/shared/api/stock";
import type { QualityState, StockBalanceEntry } from "@/shared/api/stock";
import { queryKeys } from "@/shared/api/queryKeys";
import { invalidateAfter } from "@/shared/api/cacheInvalidation";
import { fmtQty } from "@/shared/lib/quantityFormat";

interface StockAdjustmentDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type OperationType = "manual_in" | "manual_out" | "adjustment_in" | "adjustment_out";

const OPERATION_OPTIONS: { value: OperationType; label: string }[] = [
  { value: "manual_in", label: "Приход (manual_in)" },
  { value: "manual_out", label: "Расход (manual_out)" },
  { value: "adjustment_in", label: "Корректировка +" },
  { value: "adjustment_out", label: "Корректировка −" },
];

const QUALITY_OPTIONS: { value: QualityState; label: string }[] = [
  { value: "GOOD", label: "Годные" },
  { value: "SCRAP", label: "Брак" },
  { value: "REWORK", label: "Переделка" },
];

/** Пункт выбора группы остатка: подпись слева, количество справа. */
const groupRadioClass = (active: boolean): string =>
  `w-full flex items-center justify-between gap-2 px-3 py-1.5 text-sm text-left hover:bg-accent${
    active ? " bg-accent font-medium" : ""
  }`;

export function StockAdjustmentDialog({ open, onOpenChange }: StockAdjustmentDialogProps) {
  const queryClient = useQueryClient();

  const [sections, setSections] = useState<Section[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [productSearch, setProductSearch] = useState("");
  const [selectedProductId, setSelectedProductId] = useState<number | null>(null);
  const [selectedSectionId, setSelectedSectionId] = useState<number | null>(null);
  const [operationType, setOperationType] = useState<OperationType>("manual_in");
  const [qualityState, setQualityState] = useState<QualityState>("GOOD");
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null);
  const [quantity, setQuantity] = useState("");
  const [lengthMeters, setLengthMeters] = useState("");
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      listSections().then((items) => setSections(items)).catch(() => {});
      listProducts({ limit: 300 }).then((items) => setProducts(items)).catch(() => {});
      setSelectedProductId(null);
      setSelectedSectionId(null);
      setOperationType("manual_in");
      setQualityState("GOOD");
      setQuantity("");
      setLengthMeters("");
      setComment("");
      setError(null);
    }
  }, [open]);

  // Выбор группы привязан к осям ключа остатка: смена артикула, участка или
  // качества делает прежнюю строку чужой (ADR-0055).
  useEffect(() => {
    setSelectedGroupId(null);
  }, [selectedProductId, selectedSectionId, qualityState]);

  const isOut = operationType === "manual_out" || operationType === "adjustment_out";

  // Группы артикула на выбранной локации — существующий эндпоинт балансов
  // (/stock/balance): он отдаёт строки по полному ключу остатка, включая
  // completed_operations + completed_stages + quantity. Фильтр по качеству —
  // не косметика: списание ищет строку с quality_state команды, и группы
  // другого качества в списке гарантированно недоступны.
  const groupQueryParams = useMemo(() => {
    if (selectedProductId === null || selectedSectionId === null) return null;
    return {
      product_id: selectedProductId,
      location_id: selectedSectionId,
      quality_state: qualityState,
      limit: 500,
    };
  }, [selectedProductId, selectedSectionId, qualityState]);

  // Фабрика ключей типизирует только поля, которые клиент шлёт в query string,
  // — productId/qualityState в ней не объявлены. Объект собирается в
  // переменную (excess property check действует только на литерал), чтобы
  // выбор артикула/качества не схлопывался в один кэш-ключ и диалог не
  // показывал группы чужого артикула, пока летит рефетч.
  const groupQueryKeyParams = useMemo(() => {
    if (groupQueryParams === null) return undefined;
    return {
      locationId: groupQueryParams.location_id,
      productId: groupQueryParams.product_id,
      qualityState: groupQueryParams.quality_state,
      limit: groupQueryParams.limit,
    };
  }, [groupQueryParams]);

  const {
    data: groupsData,
    isPending: groupsPending,
    isError: groupsFailed,
  } = useQuery({
    queryKey: queryKeys.stock.balances(groupQueryKeyParams),
    queryFn: () => {
      if (groupQueryParams === null) {
        throw new Error("группы остатка запрашиваются после выбора артикула и участка");
      }
      return getStockBalances(groupQueryParams);
    },
    enabled: groupQueryParams !== null,
  });

  const groups = useMemo(
    () => groupsData?.balances ?? [],
    [groupsData],
  );
  const selectedGroup = useMemo(
    () => groups.find((row) => row.id === selectedGroupId) ?? null,
    [groups, selectedGroupId],
  );

  const filteredProducts = useMemo(() => {
    if (!productSearch.trim()) return products.slice(0, 30);
    const q = productSearch.toLowerCase();
    return products.filter(
      (p) => p.sku.toLowerCase().includes(q) || p.name.toLowerCase().includes(q),
    );
  }, [products, productSearch]);

  const selectedProduct = products.find((p) => p.id === selectedProductId);

  // Габарит (ADR-0001): длина в метрах (запятая/точка) → {"length_mm": N};
  // пусто — безразмерные штуки (dimensions не передаётся).
  const parseLengthToDimensions = (): Record<string, unknown> | undefined | "invalid" => {
    const raw = lengthMeters.trim();
    if (!raw) return undefined;
    const meters = Number.parseFloat(raw.replace(",", "."));
    if (!Number.isFinite(meters) || meters <= 0) return "invalid";
    return { length_mm: Math.round(meters * 1000) };
  };

  // «Нет габарита» — это и null из ответа, и пустой объект: ledger хранит
  // каноническую форму, где {} схлопывается в null.
  const normalizeDims = (
    dims: Record<string, unknown> | null | undefined,
  ): Record<string, unknown> | null =>
    dims && Object.keys(dims).length > 0 ? dims : null;

  const sameDims = (
    a: Record<string, unknown>,
    b: Record<string, unknown>,
  ): boolean =>
    JSON.stringify(Object.fromEntries(Object.entries(a).sort())) ===
    JSON.stringify(Object.fromEntries(Object.entries(b).sort()));

  /**
   * Габарит проводки при выбранной группе: группа — часть ключа остатка,
   * поэтому молча создать «та же операция, другой размер» нельзя.
   * Без введённой длины берётся размер самой группы (иначе списание из
   * размерной группы не нашло бы строку), с чужой длиной — явный отказ.
   */
  const resolveDimensions = (
    typedDims: Record<string, unknown> | undefined,
  ): { dims: Record<string, unknown> | undefined } | { error: string } => {
    if (!selectedGroup) return { dims: typedDims };
    const rowDims = normalizeDims(selectedGroup.dimensions);
    const typed = normalizeDims(typedDims);
    if (typed === null) return { dims: rowDims ?? undefined };
    if (rowDims === null) {
      return {
        error: "Выбранная группа без размера — уберите длину или выберите другую группу",
      };
    }
    if (!sameDims(typed, rowDims)) {
      return {
        error: `Длина ${formatDimensionsLabel(typed)} не совпадает с размером выбранной группы (${formatDimensionsLabel(rowDims)})`,
      };
    }
    return { dims: typedDims };
  };

  const saveMutation = useMutation({
    mutationFn: () => {
      const parsed = parseLengthToDimensions();
      const resolved = resolveDimensions(parsed === "invalid" ? undefined : parsed);
      return postStockAdjustment({
        product_id: selectedProductId as number,
        location_id: selectedSectionId as number,
        quantity: parseFloat(quantity),
        reason: operationType,
        quality_state: qualityState,
        dimensions: "dims" in resolved ? resolved.dims : undefined,
        // Группа, из которой списываем/в которую кладём (ADR-0055). Без
        // выбора — null, то есть NULL-группа «не зафиксировано».
        completed_operations: selectedGroup
          ? selectedGroup.completed_operations ?? null
          : null,
        comment: comment || undefined,
      });
    },
    onSuccess: () => {
      void invalidateAfter(queryClient, "stockChanged");
      onOpenChange(false);
    },
    onError: (e: unknown) => {
      const msg =
        e && typeof e === "object" && "response" in e
          ? (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : undefined;
      setError(msg || "Ошибка при выполнении операции");
    },
  });

  const handleSave = () => {
    if (!selectedProductId) {
      setError("Выберите продукт");
      return;
    }
    if (!selectedSectionId) {
      setError("Выберите участок");
      return;
    }
    const qty = parseFloat(quantity);
    if (isNaN(qty) || qty <= 0) {
      setError("Количество должно быть положительным числом");
      return;
    }
    const parsedDims = parseLengthToDimensions();
    if (parsedDims === "invalid") {
      setError("Длина должна быть положительным числом в метрах (например 2,7)");
      return;
    }
    // Списание строго из выбранной группы (ADR-0055 п.3): без выбора
    // расход пошёл бы в NULL-группу, а она может быть пустой при полном
    // участке. Для прихода выбор опционален.
    if (isOut && !selectedGroup) {
      setError(
        groups.length > 0
          ? "Для списания выберите группу операций"
          : "На участке нет строк остатка этого артикула — списывать нечего",
      );
      return;
    }
    const resolved = resolveDimensions(parsedDims);
    if ("error" in resolved) {
      setError(resolved.error);
      return;
    }
    setError(null);
    saveMutation.mutate();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Ручная операция со складом</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {/* Product selection */}
          <div className="space-y-1">
            <label className="text-sm font-medium text-foreground">Продукт (SKU)</label>
            {selectedProductId && selectedProduct ? (
              <div className="flex items-center justify-between border rounded-md p-2 bg-muted/20">
                <div className="text-sm">
                  <span className="font-semibold">{selectedProduct.sku}</span> — {selectedProduct.name}
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setSelectedProductId(null);
                    setProductSearch("");
                  }}
                  className="h-7 px-2 text-xs"
                >
                  Изменить
                </Button>
              </div>
            ) : (
              <>
                <div className="relative">
                  <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                  <Input
                    placeholder="Поиск по артикулу или названию..."
                    value={productSearch}
                    onChange={(e) => setProductSearch(e.target.value)}
                    className="pl-9"
                  />
                </div>
                {filteredProducts.length > 0 && (
                  <div className="max-h-[150px] overflow-y-auto border rounded-md bg-background shadow-sm mt-1">
                    {filteredProducts.map((p) => (
                      <button
                        key={p.id}
                        type="button"
                        className="w-full text-left px-3 py-1.5 text-sm hover:bg-accent truncate"
                        onClick={() => {
                          setSelectedProductId(p.id);
                          setProductSearch(p.sku);
                        }}
                      >
                        <span className="font-medium">{p.sku}</span> — {p.name}
                      </button>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>

          {/* Section selection */}
          <div className="space-y-1">
            <label className="text-sm font-medium">Участок / Секция</label>
            <Select
              value={selectedSectionId ? String(selectedSectionId) : ""}
              onValueChange={(val) => setSelectedSectionId(val ? Number(val) : null)}
            >
              <SelectTrigger className="w-full h-10 text-sm bg-background">
                <SelectValue placeholder="Выберите участок" />
              </SelectTrigger>
              <SelectContent>
                {sections.map((s) => (
                  <SelectItem key={s.id} value={String(s.id)}>
                    {s.name} ({s.code})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Operation type */}
          <div className="space-y-1">
            <label className="text-sm font-medium">Тип операции</label>
            <Select
              value={operationType}
              onValueChange={(val) => setOperationType(val as OperationType)}
            >
              <SelectTrigger className="w-full h-10 text-sm bg-background">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {OPERATION_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Quality state */}
          <div className="space-y-1">
            <label className="text-sm font-medium">Состояние качества</label>
            <Select
              value={qualityState}
              onValueChange={(val) => setQualityState(val as QualityState)}
            >
              <SelectTrigger className="w-full h-10 text-sm bg-background">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {QUALITY_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Группа операций (ADR-0055 п.3, п.12): из какой группы списывать /
              в какую класть. Список — строки баланса выбранного артикула на
              выбранной локации: у каждой видно подпись признака и количество. */}
          {groupQueryParams !== null && (
            <div className="space-y-1">
              <label className="text-sm font-medium">
                Группа операций{isOut ? "" : " (необязательно)"}
              </label>
              <p className="text-xs text-muted-foreground">
                {isOut
                  ? "Списание идёт строго из выбранной группы."
                  : `Без выбора материал ляжет в группу «${OPERATIONS_NOT_RECORDED_LABEL}».`}
              </p>
              {groupsPending ? (
                <div className="flex items-center gap-2 text-xs text-muted-foreground border rounded-md p-2">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  Загрузка групп остатка…
                </div>
              ) : groupsFailed ? (
                <div className="text-xs text-destructive border rounded-md p-2">
                  Не удалось загрузить группы остатка
                </div>
              ) : groups.length === 0 ? (
                <div className="text-xs text-muted-foreground border rounded-md p-2">
                  На участке нет строк остатка этого артикула
                </div>
              ) : (
                <div
                  role="radiogroup"
                  aria-label="Группа операций"
                  className="max-h-[170px] overflow-y-auto border rounded-md divide-y"
                >
                  {!isOut && (
                    <button
                      type="button"
                      role="radio"
                      aria-checked={selectedGroup === null}
                      onClick={() => setSelectedGroupId(null)}
                      className={groupRadioClass(selectedGroup === null)}
                    >
                      <span className="truncate">{OPERATIONS_NOT_RECORDED_LABEL}</span>
                    </button>
                  )}
                  {groups.map((row) => {
                    const dims = normalizeDims(row.dimensions);
                    return (
                      <button
                        key={row.id}
                        type="button"
                        role="radio"
                        aria-checked={selectedGroupId === row.id}
                        onClick={() => setSelectedGroupId(row.id)}
                        className={groupRadioClass(selectedGroupId === row.id)}
                      >
                        <span className="truncate">
                          {formatCompletedOperationsLabel(
                            row.completed_operations,
                            row.completed_stages,
                          )}
                          {dims ? ` · ${formatDimensionsLabel(row.dimensions)}` : ""}
                        </span>
                        <span className="whitespace-nowrap font-medium">
                          {` ${fmtQty(row.balance_qty)} шт`}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* Quantity */}
          <div className="space-y-1">
            <label className="text-sm font-medium">Количество</label>
            <Input
              type="number"
              min="0"
              step="any"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              placeholder="Введите количество..."
            />
          </div>

          {/* Length (dimensions, ADR-0001) */}
          <div className="space-y-1">
            <label className="text-sm font-medium">Длина, м (необязательно)</label>
            <Input
              value={lengthMeters}
              onChange={(e) => setLengthMeters(e.target.value)}
              placeholder="Например 2,7 — остаток будет учтён по этой длине"
            />
          </div>

          {/* Comment */}
          <div className="space-y-1">
            <label className="text-sm font-medium">Комментарий</label>
            <textarea
              className="w-full min-h-[60px] rounded-md border px-3 py-2 text-sm bg-background resize-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Опциональный комментарий..."
            />
          </div>

          {error && <div className="text-sm text-destructive font-medium bg-destructive/10 p-2 rounded">{error}</div>}

          <div className="flex justify-end gap-2 pt-2 border-t">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              Отмена
            </Button>
            <Button onClick={handleSave} disabled={saveMutation.isPending || !selectedProductId || !selectedSectionId}>
              {saveMutation.isPending ? "Выполнение..." : "Выполнить"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
