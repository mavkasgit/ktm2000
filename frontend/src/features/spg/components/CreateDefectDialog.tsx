import { useEffect, useState, useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Search, Loader2 } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  Button,
  Input,
  Badge,
  SectionSelect,
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/shared/ui";
import type { SpgOut, SpgRemainder } from "@/shared/api/spg";
import type { Product, ProductRouteStageOut } from "@/shared/api/products";
import { listProducts, getProductRouteStages } from "@/shared/api/products";
import type { DefectTypeOut } from "@/shared/api/defects";
import { getDefectTypes, createDefect } from "@/shared/api/defects";
import { queryKeys } from "@/shared/api/queryKeys";

interface CreateDefectDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  spgId: number;
  sections: SpgOut["sections"];
  remainders: SpgRemainder[];
  onSaved: () => void;
  defaultSectionId?: number | null;
  spgs?: SpgOut[];
}

export function CreateDefectDialog({
  open,
  onOpenChange,
  spgId,
  sections,
  remainders,
  onSaved,
  defaultSectionId,
  spgs,
}: CreateDefectDialogProps) {
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
  const [selectedSectionId, setSelectedSectionId] = useState<number | null>(null);

  // Route stages states
  const [routeStages, setRouteStages] = useState<ProductRouteStageOut[]>([]);
  const [selectedStageId, setSelectedStageId] = useState<number | null>(null);
  const [loadingStages, setLoadingStages] = useState(false);

  // Defect types states
  const [defectTypes, setDefectTypes] = useState<DefectTypeOut[]>([]);
  const [selectedTypeError, setSelectedTypeError] = useState(false);
  const [defectTypeCode, setDefectTypeCode] = useState("");

  // Remainders states
  const [selectedRemainderId, setSelectedRemainderId] = useState<number | null>(null);

  const [quantity, setQuantity] = useState("");
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Load products and defect types when open
  useEffect(() => {
    if (open) {
      listProducts({ limit: 300 }).then((items) => setProducts(items)).catch(() => {});
      getDefectTypes().then((types) => setDefectTypes(types)).catch(() => {});
      
      setSelectedProductId(null);
      setSelectedSectionId(defaultSectionId ?? sections[0]?.section_id ?? null);
      setRouteStages([]);
      setSelectedStageId(null);
      setDefectTypeCode("");
      setSelectedRemainderId(null);
      setQuantity("");
      setComment("");
      setError(null);
    }
  }, [open, sections, defaultSectionId]);

  // Load product route stages when product changes
  useEffect(() => {
    if (selectedProductId) {
      setLoadingStages(true);
      getProductRouteStages(selectedProductId)
        .then((stages) => {
          setRouteStages(stages);
          if (stages.length > 0) {
            setSelectedStageId(stages[0].id);
          } else {
            setSelectedStageId(null);
          }
        })
        .catch(() => {
          setRouteStages([]);
          setSelectedStageId(null);
        })
        .finally(() => {
          setLoadingStages(false);
        });
    } else {
      setRouteStages([]);
      setSelectedStageId(null);
    }
    setSelectedRemainderId(null);
  }, [selectedProductId]);

  const filteredProducts = productSearch.trim()
    ? products.filter(
        (p) =>
          p.sku.toLowerCase().includes(productSearch.toLowerCase()) ||
          p.name.toLowerCase().includes(productSearch.toLowerCase()),
      )
    : products.slice(0, 30);

  // Filter remainders for the selected product and section
  const availableRemainders = remainders.filter(
    (r) => r.product_id === selectedProductId && r.section_id === selectedSectionId
  );

  const saveMutation = useMutation({
    mutationFn: () =>
      createDefect({
        product_id: selectedProductId as number,
        section_id: selectedSectionId as number,
        route_stage_id: selectedStageId,
        spg_remainder_id: selectedRemainderId,
        quantity: parseFloat(quantity),
        reason: defectTypeCode || null,
        comment: comment || null,
      }),
    onSuccess: () => {
      const actualSpgId = spgs?.find(s => s.sections.some(sec => sec.section_id === selectedSectionId))?.id || spgId;
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.defects(actualSpgId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.snapshot(actualSpgId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.remainders(actualSpgId) });
      onSaved();
      onOpenChange(false);
    },
    onError: (e: unknown) => {
      const msg = e && typeof e === "object" && "response" in e
        ? (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
        : undefined;
      setError((msg as string | undefined) || "Ошибка при сохранении дефекта");
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
      setError("Количество брака должно быть положительным числом");
      return;
    }

    // Check remainder bounds if selected
    if (selectedRemainderId) {
      const activeRem = remainders.find((r) => r.id === selectedRemainderId);
      if (activeRem && qty > activeRem.remainder_quantity) {
        setError(`Количество брака (${qty}) не может превышать количество в остатке (${activeRem.remainder_quantity})`);
        return;
      }
    }
    setError(null);
    saveMutation.mutate();
  };

  const selectedProduct = products.find((p) => p.id === selectedProductId);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Регистрация брака в ГХП</DialogTitle>
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
                {productSearch.trim().length > 0 && (
                  <div className="max-h-[150px] overflow-y-auto border rounded-md bg-background shadow-sm mt-1">
                    {filteredProducts.length === 0 ? (
                      <div className="p-2 text-sm text-muted-foreground text-center">Продукты не найдены</div>
                    ) : (
                      filteredProducts.map((p) => (
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
                      ))
                    )}
                  </div>
                )}
              </>
            )}
          </div>

          {/* Section Selector */}
          <div className="space-y-1">
            <label className="text-sm font-medium">Участок ГХП</label>
            <SectionSelect
              sections={sectionsForSelect}
              value={selectedSectionId}
              onValueChange={setSelectedSectionId}
              placeholder="Выберите участок"
              className="w-full h-10 text-sm font-normal bg-background border rounded-md px-3"
              hideCode={true}
            />
          </div>

          {/* Route Stage Selector */}
          {selectedProductId && (
            <div className="space-y-1">
              <label className="text-sm font-medium">Технологическая операция (этап)</label>
              {loadingStages ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground py-1">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Загрузка технологического маршрута...
                </div>
              ) : routeStages.length === 0 ? (
                <div className="text-sm text-amber-600 bg-amber-50 dark:bg-amber-950/20 p-2 rounded border border-amber-200">
                  Технологический маршрут для данного продукта не найден
                </div>
              ) : (
                <Select
                  value={selectedStageId ? String(selectedStageId) : ""}
                  onValueChange={(val) => setSelectedStageId(val ? Number(val) : null)}
                >
                  <SelectTrigger className="w-full h-10 text-sm bg-background">
                    <SelectValue placeholder="Выберите технологическую операцию" />
                  </SelectTrigger>
                  <SelectContent>
                    {routeStages.map((st) => {
                      const opName = st.operations?.[0]?.operation_name || st.section_name;
                      return (
                        <SelectItem key={st.id} value={String(st.id)}>
                          Шаг {st.sequence}: {st.section_code} — {opName}
                        </SelectItem>
                      );
                    })}
                  </SelectContent>
                </Select>
              )}
            </div>
          )}

          {/* Remainder selector */}
          {selectedProductId && (
            <div className="space-y-1">
              <label className="text-sm font-medium">Списать из партии остатка (опционально)</label>
              <Select
                value={selectedRemainderId ? String(selectedRemainderId) : "none"}
                onValueChange={(val) => setSelectedRemainderId(val === "none" ? null : Number(val))}
              >
                <SelectTrigger className="w-full h-10 text-sm bg-background">
                  <SelectValue placeholder="Без привязки к партии остатка" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Без привязки к партии остатка</SelectItem>
                  {availableRemainders.map((r) => (
                    <SelectItem key={r.id} value={String(r.id)}>
                      Партия #{r.id} ({r.remainder_quantity} шт.) от {new Date(r.created_at).toLocaleDateString()}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {availableRemainders.length === 0 && (
                <p className="text-[11px] text-muted-foreground">
                  На данном участке нет свободных остатков этого продукта для списания.
                </p>
              )}
            </div>
          )}

          {/* Quantity */}
          <div className="space-y-1">
            <label className="text-sm font-medium">Количество брака</label>
            <Input
              type="number"
              min="0"
              step="any"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              placeholder="Введите количество..."
            />
          </div>

          {/* Defect Type (Reason) */}
          <div className="space-y-1">
            <label className="text-sm font-medium">Причина брака (дефект)</label>
            <Select
              value={defectTypeCode || "none"}
              onValueChange={(val) => setDefectTypeCode(val === "none" ? "" : val)}
            >
              <SelectTrigger className="w-full h-10 text-sm bg-background">
                <SelectValue placeholder="Выберите причину брака..." />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">Выберите причину брака...</SelectItem>
                {defectTypes.map((dt) => (
                  <SelectItem key={dt.id} value={dt.code}>
                    {dt.category ? `[${dt.category}] ` : ""}{dt.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Comment */}
          <div className="space-y-1">
            <label className="text-sm font-medium">Комментарий / Примечание</label>
            <textarea
              className="w-full min-h-[80px] rounded-md border px-3 py-2 text-sm bg-background resize-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Опишите дефект более подробно..."
            />
          </div>

          {error && <div className="text-sm text-destructive font-medium bg-destructive/10 p-2 rounded">{error}</div>}

          <div className="flex justify-end gap-2 pt-2 border-t">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              Отмена
            </Button>
            <Button onClick={handleSave} disabled={saveMutation.isPending || !selectedProductId}>
              {saveMutation.isPending ? "Сохранение..." : "Зарегистрировать"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
