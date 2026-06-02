import { useEffect, useState } from "react";
import { ArrowDownUp, History as HistoryIcon, Pencil, Plus, Trash2 } from "lucide-react";
import { IconAlertTriangle } from "@tabler/icons-react";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  Button,
  Input,
  Badge,
} from "@/shared/ui";
import type {
  SpgOut,
  SpgRemainder,
  ManualRemainderCreateInput,
  ManualRemainderUpdateInput,
} from "@/shared/api/spg";
import {
  createManualRemainder,
  updateManualRemainder,
  deleteManualRemainder,
} from "@/shared/api/spg";
import type { Product } from "@/shared/api/products";
import { listProducts } from "@/shared/api/products";
import { ManualOperationDialog } from "./ManualOperationDialog";
import { RemainderHistoryDrawer } from "./RemainderHistoryDrawer";

interface RemainderEditDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  spgId: number;
  sections: SpgOut["sections"];
  editingRemainder: SpgRemainder | null;
  onSaved: () => void;
}

export function RemainderEditDialog({
  open,
  onOpenChange,
  spgId,
  sections,
  editingRemainder,
  onSaved,
}: RemainderEditDialogProps) {
  const [products, setProducts] = useState<Product[]>([]);
  const [productSearch, setProductSearch] = useState("");
  const [selectedProductId, setSelectedProductId] = useState<number | null>(null);
  const [selectedSectionId, setSelectedSectionId] = useState<number | null>(null);
  const [quantity, setQuantity] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      listProducts({ limit: 200 }).then((items) => setProducts(items)).catch(() => {});
      if (editingRemainder) {
        setSelectedProductId(editingRemainder.product_id);
        setSelectedSectionId(editingRemainder.section_id);
        setQuantity(String(editingRemainder.remainder_quantity));
        setProductSearch(editingRemainder.product_sku);
      } else {
        setSelectedProductId(null);
        setSelectedSectionId(sections[0]?.section_id ?? null);
        setQuantity("");
        setProductSearch("");
      }
      setError(null);
    }
  }, [open, editingRemainder, sections]);

  const filteredProducts = productSearch.trim()
    ? products.filter(
        (p) =>
          p.sku.toLowerCase().includes(productSearch.toLowerCase()) ||
          p.name.toLowerCase().includes(productSearch.toLowerCase()),
      )
    : products.slice(0, 50);

  const handleSave = async () => {
    if (!selectedProductId || !selectedSectionId || !quantity) {
      setError("Заполните все поля");
      return;
    }
    const qty = parseFloat(quantity);
    if (isNaN(qty) || qty <= 0) {
      setError("Количество должно быть положительным");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      if (editingRemainder) {
        const payload: ManualRemainderUpdateInput = {
          quantity: qty,
          section_id: selectedSectionId,
        };
        await updateManualRemainder(spgId, editingRemainder.id, payload);
      } else {
        const payload: ManualRemainderCreateInput = {
          product_id: selectedProductId,
          section_id: selectedSectionId,
          quantity: qty,
        };
        await createManualRemainder(spgId, payload);
      }
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

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>
            {editingRemainder ? "Редактировать остаток" : "Добавить остаток (инвентаризация)"}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {/* Product search */}
          <div className="space-y-1">
            <label className="text-sm font-medium">Артикул / Продукт</label>
            {editingRemainder ? (
              <div className="text-sm font-semibold">
                {editingRemainder.product_sku} — {editingRemainder.product_name}
              </div>
            ) : (
              <>
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
              </>
            )}
          </div>

          {/* Section select */}
          <div className="space-y-1">
            <label className="text-sm font-medium">Участок</label>
            <select
              className="w-full rounded-md border px-3 py-2 text-sm bg-background"
              value={selectedSectionId ?? ""}
              onChange={(e) => setSelectedSectionId(Number(e.target.value))}
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
          </div>

          {error && <div className="text-sm text-destructive">{error}</div>}

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              Отмена
            </Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? "Сохранение..." : editingRemainder ? "Обновить" : "Добавить"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ─── Remainders List Panel ──────────────────────────────────────────────────

interface RemaindersListPanelProps {
  spgId: number;
  sections: SpgOut["sections"];
  remainders: SpgRemainder[];
  isLoading: boolean;
  onRefresh: () => void;
}

export function RemaindersListPanel({
  spgId,
  sections,
  remainders,
  isLoading,
  onRefresh,
}: RemaindersListPanelProps) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<SpgRemainder | null>(null);
  const [manualOpOpen, setManualOpOpen] = useState(false);
  const [historyRemainderId, setHistoryRemainderId] = useState<number | null>(null);

  const handleAdd = () => {
    setEditing(null);
    setDialogOpen(true);
  };

  const handleEdit = (r: SpgRemainder) => {
    setEditing(r);
    setDialogOpen(true);
  };

  const handleDelete = async (r: SpgRemainder) => {
    if (!confirm(`Удалить остаток ${r.product_sku} (${r.remainder_quantity} шт.)?`)) return;
    await deleteManualRemainder(spgId, r.id);
    onRefresh();
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">
          Остатки ({remainders.length})
        </h3>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={() => setManualOpOpen(true)}>
            <ArrowDownUp className="h-3.5 w-3.5 mr-1" />
            Ручная операция
          </Button>
          <Button size="sm" onClick={handleAdd}>
            <Plus className="h-3.5 w-3.5 mr-1" />
            Добавить остаток
          </Button>
        </div>
      </div>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Загрузка...</p>
      ) : remainders.length === 0 ? (
        <p className="text-sm text-muted-foreground">Остатков нет</p>
      ) : (
        <div className="overflow-x-auto border rounded-lg">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 border-b">
              <tr>
                <th className="p-2 text-left font-medium">Артикул</th>
                <th className="p-2 text-left font-medium">Участок</th>
                <th className="p-2 text-right font-medium">Кол-во</th>
                <th className="p-2 text-center font-medium">Источник</th>
                <th className="p-2 text-center font-medium">Действия</th>
              </tr>
            </thead>
            <tbody>
              {remainders.map((r) => {
                const isNegative = r.remainder_quantity < 0;
                return (
                  <tr key={r.id} className="border-b hover:bg-muted/30">
                    <td className="p-2">
                      <div className="font-medium">{r.product_sku}</div>
                      <div className="text-xs text-muted-foreground truncate max-w-[180px]">
                        {r.product_name}
                      </div>
                    </td>
                    <td className="p-2">
                      <div className="text-xs font-medium">{r.section_code}</div>
                      <div className="text-xs text-muted-foreground">{r.section_name}</div>
                    </td>
                    <td className="p-2 text-right">
                      <span className={`font-semibold ${isNegative ? "text-amber-700" : ""}`}>
                        {r.remainder_quantity}
                      </span>
                      {isNegative && (
                        <span
                          title="Остаток ушёл в минус — зафиксируйте ручной операцией"
                          className="inline-block"
                        >
                          <Badge
                            variant="destructive"
                            className="ml-2 text-[10px] inline-flex items-center gap-1"
                          >
                            <IconAlertTriangle size={12} />
                            Отрицательный
                          </Badge>
                        </span>
                      )}
                    </td>
                    <td className="p-2 text-center">
                      <Badge variant={r.source === "manual" ? "default" : "secondary"} className="text-xs">
                        {r.source === "manual" ? "Ручной" : "Задача"}
                      </Badge>
                    </td>
                    <td className="p-2 text-center">
                      <div className="flex items-center justify-center gap-1">
                        <button
                          type="button"
                          onClick={() => setHistoryRemainderId(r.id)}
                          className="p-1 rounded hover:bg-accent text-blue-600"
                          title="История"
                        >
                          <HistoryIcon className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() => handleEdit(r)}
                          className="p-1 rounded hover:bg-accent"
                          title="Редактировать"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDelete(r)}
                          className="p-1 rounded hover:bg-destructive/10 text-destructive"
                          title="Удалить"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <RemainderEditDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        spgId={spgId}
        sections={sections}
        editingRemainder={editing}
        onSaved={onRefresh}
      />

      <ManualOperationDialog
        open={manualOpOpen}
        onOpenChange={setManualOpOpen}
        spgId={spgId}
        sections={sections}
        onSaved={onRefresh}
      />

      <RemainderHistoryDrawer
        open={historyRemainderId !== null}
        onOpenChange={(open) => {
          if (!open) setHistoryRemainderId(null);
        }}
        spgId={spgId}
        remainderId={historyRemainderId}
      />
    </div>
  );
}
