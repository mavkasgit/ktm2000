import { useEffect, useState, useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { ArrowDown, ArrowUp, Loader2 } from "lucide-react";

import { Button, Dialog, DialogContent, DialogHeader, DialogTitle, Input, Badge, SectionSelect } from "@/shared/ui";
import { listProducts, getProduct, type Product } from "@/shared/api/products";
import {
  performManualStockOperation,
  getSpgAvailability,
  type ManualOperationType,
  type ManualOperationInput,
  type SpgAvailability,
  type SpgOut,
} from "@/shared/api/spg";
import { spgI18n } from "@/shared/i18n/spg";
import { queryKeys } from "@/shared/api/queryKeys";

type SectionOption = {
  section_id: number;
  section_code: string;
  section_name: string;
};

interface ManualOperationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  spgId: number;
  sections: SectionOption[];
  defaultProductId?: number | null;
  defaultSectionId?: number | null;
  defaultType?: ManualOperationType;
  onSaved: () => void;
  spgs?: SpgOut[];
}

const TYPE_LABELS: Record<ManualOperationType, string> = {
  in: "Приход (увеличить остаток)",
  out: "Расход (уменьшить остаток)",
};

export function ManualOperationDialog({
  open,
  onOpenChange,
  spgId,
  sections,
  defaultProductId = null,
  defaultSectionId = null,
  defaultType = "in",
  onSaved,
  spgs,
}: ManualOperationDialogProps) {
  const queryClient = useQueryClient();

  const sectionsForSelect = useMemo(() => {
    return sections.map((s) => ({
      id: s.section_id,
      code: s.section_code,
      name: s.section_name,
      description: "",
      is_active: true,
      kind: "production" as any,
      icon: null,
      icon_color: null,
    }));
  }, [sections]);

  const [products, setProducts] = useState<Product[]>([]);
  const [productSearch, setProductSearch] = useState("");
  const [selectedProductId, setSelectedProductId] = useState<number | null>(null);
  const [sectionId, setSectionId] = useState<number | null>(null);
  const [operationType, setOperationType] = useState<ManualOperationType>(defaultType);
  const [quantity, setQuantity] = useState("");
  const [reason, setReason] = useState("");
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [availability, setAvailability] = useState<SpgAvailability | null>(null);
  const [availabilityLoading, setAvailabilityLoading] = useState(false);

  useEffect(() => {
    if (open) {
      setSelectedProductId(defaultProductId);
      setSectionId(defaultSectionId ?? sections[0]?.section_id ?? null);
      setOperationType(defaultType);
      setQuantity("");
      setReason("");
      setComment("");
      setError(null);
      setProductSearch("");
      setAvailability(null);
      setProducts([]);

      // Загружаем продукт по умолчанию, если он передан
      if (defaultProductId !== null) {
        getProduct(defaultProductId)
          .then((prod) => {
            setProducts((prev) => {
              if (prev.some((p) => p.id === prod.id)) return prev;
              return [prod, ...prev];
            });
            setProductSearch(prod.sku);
          })
          .catch(() => {});
      }
    }
  }, [open, defaultProductId, defaultSectionId, defaultType, sections]);

  useEffect(() => {
    if (!open) return;

    // Предотвращаем повторный поиск при клике на элемент
    const selectedProduct = products.find((p) => p.id === selectedProductId);
    if (selectedProduct && selectedProduct.sku === productSearch) {
      return;
    }

    const delayDebounceFn = setTimeout(() => {
      const query = productSearch.trim();
      listProducts(query ? { q: query, limit: 100 } : { limit: 100 })
        .then((data) => {
          setProducts((prev) => {
            const merged = [...data];
            const defProd = prev.find((p) => p.id === selectedProductId);
            if (defProd && !merged.some((p) => p.id === defProd.id)) {
              merged.unshift(defProd);
            }
            return merged;
          });
        })
        .catch(() => {});
    }, 300);

    return () => clearTimeout(delayDebounceFn);
  }, [productSearch, open, selectedProductId]);

  useEffect(() => {
    if (!open || selectedProductId == null || sectionId == null) {
      setAvailability(null);
      return;
    }
    let cancelled = false;
    setAvailabilityLoading(true);
    const actualSpgId = spgs?.find(s => s.sections.some(sec => sec.section_id === sectionId))?.id || spgId;
    getSpgAvailability(actualSpgId, selectedProductId, sectionId)
      .then((data) => {
        if (!cancelled) setAvailability(data);
      })
      .catch(() => {
        if (!cancelled) setAvailability(null);
      })
      .finally(() => {
        if (!cancelled) setAvailabilityLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, spgId, selectedProductId, sectionId, spgs]);

  const filteredProducts = productSearch.trim()
    ? products.filter(
        (p) =>
          p.sku.toLowerCase().includes(productSearch.toLowerCase()) ||
          p.name.toLowerCase().includes(productSearch.toLowerCase()),
      )
    : products.slice(0, 50);

  const saveMutation = useMutation({
    mutationFn: async (payload: ManualOperationInput) => {
      const actualSpgId = spgs?.find(s => s.sections.some(sec => sec.section_id === payload.section_id))?.id || spgId;
      await performManualStockOperation(actualSpgId, payload);
    },
    onSuccess: (_, variables) => {
      const actualSpgId = spgs?.find(s => s.sections.some(sec => sec.section_id === variables.section_id))?.id || spgId;
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.snapshot(actualSpgId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.remainders(actualSpgId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.defects(actualSpgId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.remainderHistory(actualSpgId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.manualOperations(actualSpgId) });
      onSaved();
      onOpenChange(false);
    },
    onError: (e: unknown) => {
      const msg = e && typeof e === "object" && "response" in e
        ? (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
        : undefined;
      setError((msg as string | undefined) || "Ошибка сохранения");
    },
  });

  const handleSave = () => {
    setError(null);
    if (!selectedProductId || !sectionId || !quantity) {
      setError("Заполните все обязательные поля");
      return;
    }
    const qty = parseFloat(quantity);
    if (!Number.isFinite(qty) || qty <= 0) {
      setError("Количество должно быть положительным числом");
      return;
    }
    const payload: ManualOperationInput = {
      product_id: selectedProductId,
      section_id: sectionId,
      operation_type: operationType,
      quantity: qty,
      reason: reason || null,
      comment: comment || null,
    };
    saveMutation.mutate(payload);
  };

  const isIn = operationType === "in";

  const isOutOfStock =
    availability !== null && availability.available <= 0 && operationType === "out";
  const exceedsAvailable =
    availability !== null &&
    operationType === "out" &&
    parseFloat(quantity || "0") > availability.available;
  const submitDisabled =
    saveMutation.isPending || isOutOfStock || exceedsAvailable;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <div className="flex items-center">
            <DialogTitle>Ручная операция с остатком</DialogTitle>
            {availability?.requires_lot && (
              <Badge variant="destructive" className="ml-2">
                {spgI18n.ru.requiresLotBadge}
              </Badge>
            )}
          </div>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {/* Operation type */}
          <div className="space-y-1">
            <label className="text-sm font-medium">Тип операции</label>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                className={`flex items-center justify-center gap-2 rounded-md border px-3 py-2 text-sm font-medium transition-colors ${
                  isIn
                    ? "border-emerald-500 bg-emerald-50 text-emerald-700"
                    : "hover:bg-accent text-muted-foreground"
                }`}
                onClick={() => setOperationType("in")}
              >
                <ArrowDown className="h-4 w-4" />
                Приход
              </button>
              <button
                type="button"
                disabled={isOutOfStock}
                title={isOutOfStock ? spgI18n.ru.availableNone : undefined}
                className={`flex items-center justify-center gap-2 rounded-md border px-3 py-2 text-sm font-medium transition-colors ${
                  !isIn
                    ? "border-amber-500 bg-amber-50 text-amber-700"
                    : "hover:bg-accent text-muted-foreground"
                } ${isOutOfStock ? "opacity-50 cursor-not-allowed" : ""}`}
                onClick={() => setOperationType("out")}
              >
                <ArrowUp className="h-4 w-4" />
                Расход
              </button>
            </div>
            <p className="text-xs text-muted-foreground">{TYPE_LABELS[operationType]}</p>
          </div>

          {/* Product */}
          <div className="space-y-1">
            <label className="text-sm font-medium">Артикул / Продукт</label>
            <Input
              placeholder="Поиск по артикулу или названию..."
              value={productSearch}
              onChange={(e) => {
                setProductSearch(e.target.value);
                setSelectedProductId(null);
              }}
            />
            {selectedProductId && (
              <Badge variant="secondary" className="mt-1">
                Выбран: {products.find((p) => p.id === selectedProductId)?.sku}
              </Badge>
            )}
            {!selectedProductId && filteredProducts.length > 0 && (
              <div className="max-h-[150px] overflow-auto border rounded-md mt-1">
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
          </div>

          {/* Section */}
          <div className="space-y-1">
            <label className="text-sm font-medium">Участок</label>
            <SectionSelect
              sections={sectionsForSelect}
              value={sectionId}
              onValueChange={setSectionId}
              placeholder="Выберите участок"
              className="w-full h-10 text-sm font-normal bg-background border rounded-md px-3"
              hideCode={true}
            />
          </div>

          {/* Quantity */}
          <div className="space-y-1">
            <label className="text-sm font-medium">Количество</label>
            <Input
              type="number"
              min="0"
              step="1"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              placeholder="0"
              aria-invalid={exceedsAvailable}
              className={exceedsAvailable ? "border-red-500 focus-visible:ring-red-500" : undefined}
            />
            {availabilityLoading ? (
              <p className="text-xs text-muted-foreground">
                <Loader2 className="inline h-3 w-3 mr-1 animate-spin" />
                {spgI18n.ru.loading}
              </p>
            ) : availability ? (
              <p className="text-sm text-muted-foreground">
                {spgI18n.ru.availableLabel}: {availability.available}
              </p>
            ) : (
              <p className="text-xs text-muted-foreground">
                {isIn
                  ? "Будет добавлено к текущему остатку артикула на выбранном участке"
                  : "Будет списано. Допускается уход в минус (фиксируется постфактум)."}
              </p>
            )}
            {exceedsAvailable && (
              <p className="text-sm text-red-600 mt-1">
                {spgI18n.ru.quantityExceedsAvailable}
              </p>
            )}
          </div>

          {/* Reason */}
          <div className="space-y-1">
            <label className="text-sm font-medium">Основание</label>
            <Input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="например, возврат от заказчика / списание брака / корректировка остатков"
            />
          </div>

          {/* Comment */}
          <div className="space-y-1">
            <label className="text-sm font-medium">Комментарий</label>
            <Input
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Опционально"
            />
          </div>

          {error && <div className="text-sm text-destructive">{error}</div>}

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saveMutation.isPending}>
              Отмена
            </Button>
            <Button onClick={handleSave} disabled={submitDisabled}>
              {saveMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                  Сохранение...
                </>
              ) : (
                "Сохранить"
              )}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
