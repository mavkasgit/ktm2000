import { useEffect, useState } from "react";

import { ArrowDown, ArrowUp, Loader2 } from "lucide-react";

import { Button, Dialog, DialogContent, DialogHeader, DialogTitle, Input, Badge } from "@/shared/ui";
import { listProducts, type Product } from "@/shared/api/products";
import {
  performManualStockOperation,
  type ManualOperationType,
  type ManualOperationInput,
} from "@/shared/api/spg";

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
}: ManualOperationDialogProps) {
  const [products, setProducts] = useState<Product[]>([]);
  const [productSearch, setProductSearch] = useState("");
  const [selectedProductId, setSelectedProductId] = useState<number | null>(null);
  const [sectionId, setSectionId] = useState<number | null>(null);
  const [operationType, setOperationType] = useState<ManualOperationType>(defaultType);
  const [quantity, setQuantity] = useState("");
  const [reason, setReason] = useState("");
  const [comment, setComment] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
      if (products.length === 0) {
        listProducts({ limit: 200 }).then(setProducts).catch(() => {});
      }
    }
  }, [open, defaultProductId, defaultSectionId, defaultType, sections, products.length]);

  const filteredProducts = productSearch.trim()
    ? products.filter(
        (p) =>
          p.sku.toLowerCase().includes(productSearch.toLowerCase()) ||
          p.name.toLowerCase().includes(productSearch.toLowerCase()),
      )
    : products.slice(0, 50);

  const handleSave = async () => {
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
    setSaving(true);
    try {
      const payload: ManualOperationInput = {
        product_id: selectedProductId,
        section_id: sectionId,
        operation_type: operationType,
        quantity: qty,
        reason: reason || null,
        comment: comment || null,
      };
      await performManualStockOperation(spgId, payload);
      onSaved();
      onOpenChange(false);
    } catch (e: unknown) {
      const msg = e && typeof e === "object" && "response" in e
        ? (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
        : undefined;
      setError(msg || "Ошибка сохранения");
    } finally {
      setSaving(false);
    }
  };

  const isIn = operationType === "in";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>Ручная операция с остатком</DialogTitle>
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
                className={`flex items-center justify-center gap-2 rounded-md border px-3 py-2 text-sm font-medium transition-colors ${
                  !isIn
                    ? "border-amber-500 bg-amber-50 text-amber-700"
                    : "hover:bg-accent text-muted-foreground"
                }`}
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
            <select
              className="w-full rounded-md border px-3 py-2 text-sm bg-background"
              value={sectionId ?? ""}
              onChange={(e) => setSectionId(Number(e.target.value))}
            >
              {sections.map((s) => (
                <option key={s.section_id} value={s.section_id}>
                  {s.section_code} — {s.section_name}
                </option>
              ))}
            </select>
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
            />
            <p className="text-xs text-muted-foreground">
              {isIn
                ? "Будет добавлено к текущему остатку артикула на выбранном участке"
                : "Будет списано. Допускается уход в минус (фиксируется постфактум)."}
            </p>
          </div>

          {/* Reason */}
          <div className="space-y-1">
            <label className="text-sm font-medium">Основание</label>
            <Input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="например, возврат от заказчика / списание брака / инвентаризация"
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
            <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
              Отмена
            </Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? (
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
