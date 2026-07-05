import { useEffect, useState, useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
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
import { postStockAdjustment } from "@/shared/api/stock";
import type { QualityState } from "@/shared/api/stock";
import { queryKeys } from "@/shared/api/queryKeys";

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

export function StockAdjustmentDialog({ open, onOpenChange }: StockAdjustmentDialogProps) {
  const queryClient = useQueryClient();

  const [sections, setSections] = useState<Section[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [productSearch, setProductSearch] = useState("");
  const [selectedProductId, setSelectedProductId] = useState<number | null>(null);
  const [selectedSectionId, setSelectedSectionId] = useState<number | null>(null);
  const [operationType, setOperationType] = useState<OperationType>("manual_in");
  const [qualityState, setQualityState] = useState<QualityState>("GOOD");
  const [quantity, setQuantity] = useState("");
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
      setComment("");
      setError(null);
    }
  }, [open]);

  const filteredProducts = useMemo(() => {
    if (!productSearch.trim()) return products.slice(0, 30);
    const q = productSearch.toLowerCase();
    return products.filter(
      (p) => p.sku.toLowerCase().includes(q) || p.name.toLowerCase().includes(q),
    );
  }, [products, productSearch]);

  const selectedProduct = products.find((p) => p.id === selectedProductId);

  const saveMutation = useMutation({
    mutationFn: () =>
      postStockAdjustment({
        product_id: selectedProductId as number,
        location_id: selectedSectionId as number,
        quantity: parseFloat(quantity),
        reason: operationType,
        quality_state: qualityState,
        comment: comment || undefined,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.stock.balancesAll() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.stock.productBalance(selectedProductId!) });
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
