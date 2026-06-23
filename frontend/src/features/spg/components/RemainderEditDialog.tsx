import { useEffect, useState, useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowDownUp, History as HistoryIcon, Pencil, Plus, Trash2, Check, X, Search, Upload, Loader2, ChevronDown, ChevronRight } from "lucide-react";
import { IconAlertTriangle } from "@tabler/icons-react";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  Button,
  Input,
  Badge,
  renderIcon,
  SectionSelect,
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
import { listSectionsWithOperations } from "@/shared/api/sections";
import type { SectionWithOperations } from "@/shared/api/sections";
import { ManualOperationDialog } from "./ManualOperationDialog";
import { RemainderHistoryDrawer } from "./RemainderHistoryDrawer";
import { ImportRemaindersDialog } from "./ImportRemaindersDialog";
import { queryKeys } from "@/shared/api/queryKeys";

interface RemainderEditDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  spgId: number;
  sections: SpgOut["sections"];
  editingRemainder: SpgRemainder | null;
  onSaved: () => void;
  defaultSectionId?: number | null;
  spgs: SpgOut[];
}

export function RemainderEditDialog({
  open,
  onOpenChange,
  spgId,
  sections,
  editingRemainder,
  onSaved,
  defaultSectionId,
  spgs,
}: RemainderEditDialogProps) {
  const queryClient = useQueryClient();
  const [products, setProducts] = useState<Product[]>([]);
  const [productSearch, setProductSearch] = useState("");
  const [selectedProductId, setSelectedProductId] = useState<number | null>(null);
  const [selectedSectionId, setSelectedSectionId] = useState<number | null>(null);
  const [quantity, setQuantity] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Completed stages states
  const [sectionsWithOps, setSectionsWithOps] = useState<SectionWithOperations[]>([]);
  const [completedOperationKeys, setCompletedOperationKeys] = useState<string[]>([]);
  const [loadingStages, setLoadingStages] = useState(false);

  const sectionsForSelect = useMemo(() => {
    return sectionsWithOps.map((s) => ({
      id: s.id,
      code: s.code,
      name: s.name,
      description: "",
      is_active: true,
      kind: s.kind as any,
      icon: s.icon,
      icon_color: s.icon_color,
    }));
  }, [sectionsWithOps]);

  const flatOperations = useMemo(() => {
    const flatOps: any[] = [];
    sectionsWithOps.forEach((sec, secIdx) => {
      const sequence = (secIdx + 1) * 10;
      sec.operations.forEach((op) => {
        flatOps.push({
          sectionId: sec.id,
          sectionCode: sec.code,
          sectionName: sec.name,
          sequence: sequence,
          operationCode: op.operation_code,
          operationName: op.operation_name,
          uniqueKey: `stage_${sec.id}_op_${op.operation_code || "default"}`,
        });
      });
    });
    return flatOps;
  }, [sectionsWithOps]);

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
        setSelectedSectionId(defaultSectionId ?? sections[0]?.section_id ?? null);
        setQuantity("");
        setProductSearch("");
      }
      setError(null);
    }
  }, [open, editingRemainder, sections, defaultSectionId]);

  useEffect(() => {
    if (open) {
      setLoadingStages(true);
      listSectionsWithOperations()
        .then((items) => {
          setSectionsWithOps(items);
          if (editingRemainder) {
            const completedNamesOrCodes = (editingRemainder.completed_stages || []).map(
              (cs: any) => cs.operation_code || cs.operation_name
            );
            const initialKeys: string[] = [];
            items.forEach((s) => {
              s.operations.forEach((op) => {
                if (
                  completedNamesOrCodes.includes(op.operation_code) ||
                  completedNamesOrCodes.includes(op.operation_name)
                ) {
                  initialKeys.push(`stage_${s.id}_op_${op.operation_code || "default"}`);
                }
              });
            });
            setCompletedOperationKeys(initialKeys);
          } else {
            setCompletedOperationKeys([]);
          }
        })
        .catch(() => setSectionsWithOps([]))
        .finally(() => setLoadingStages(false));
    } else {
      setSectionsWithOps([]);
      setCompletedOperationKeys([]);
    }
  }, [open, editingRemainder]);

  const filteredProducts = productSearch.trim()
    ? products.filter(
        (p) =>
          p.sku.toLowerCase().includes(productSearch.toLowerCase()) ||
          p.name.toLowerCase().includes(productSearch.toLowerCase()),
      )
    : products.slice(0, 50);

  const saveMutation = useMutation({
    mutationFn: async (input: { kind: "create" | "update"; payload: ManualRemainderCreateInput | ManualRemainderUpdateInput }) => {
      const actualSpgId = spgs.find(s => s.sections.some(sec => sec.section_id === input.payload.section_id))?.id || spgId;
      if (input.kind === "create") {
        await createManualRemainder(actualSpgId, input.payload as ManualRemainderCreateInput);
      } else {
        await updateManualRemainder(
          actualSpgId,
          (editingRemainder as SpgRemainder).id,
          input.payload as ManualRemainderUpdateInput,
        );
      }
    },
    onSuccess: (_, variables) => {
      const actualSpgId = spgs.find(s => s.sections.some(sec => sec.section_id === variables.payload.section_id))?.id || spgId;
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.snapshot(actualSpgId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.remainders(actualSpgId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.remainderHistory(actualSpgId) });
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
    if (!selectedProductId || !selectedSectionId || !quantity) {
      setError("Заполните все поля");
      return;
    }
    const qty = parseFloat(quantity);
    if (isNaN(qty) || qty <= 0) {
      setError("Количество должно быть положительным");
      return;
    }

    const completed_stages = flatOperations
      .filter((op) => completedOperationKeys.includes(op.uniqueKey))
      .map((op) => ({
        section_id: op.sectionId,
        operation_code: op.operationCode,
        operation_name: op.operationName,
        sequence: op.sequence,
      }));

    if (editingRemainder) {
      const payload: ManualRemainderUpdateInput = {
        quantity: qty,
        section_id: selectedSectionId,
        completed_stages,
      };
      saveMutation.mutate({ kind: "update", payload });
    } else {
      const payload: ManualRemainderCreateInput = {
        product_id: selectedProductId as number,
        section_id: selectedSectionId,
        quantity: qty,
        completed_stages,
      };
      saveMutation.mutate({ kind: "create", payload });
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[760px]">
        <DialogHeader>
          <DialogTitle>
            {editingRemainder ? "Редактировать остаток" : "Добавить остаток"}
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
            <SectionSelect
              sections={sectionsForSelect}
              value={selectedSectionId}
              onValueChange={setSelectedSectionId}
              placeholder="Выберите участок"
              className="w-full h-10 text-sm font-normal bg-background border rounded-md px-3"
              hideCode={true}
            />
          </div>

          {/* Completed stages checkboxes */}
          <div className="space-y-2 border-t pt-2">
            <label className="text-sm font-medium text-foreground">Завершенные этапы производства</label>
            {loadingStages ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Загрузка этапов...
              </div>
            ) : sectionsWithOps.length === 0 ? (
              <div className="text-xs text-muted-foreground bg-muted p-2 rounded">
                Участки и операции не найдены.
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-h-[340px] overflow-y-auto border rounded-md p-3 bg-muted/5">
                {sectionsWithOps.map((sec) => {
                  if (sec.operations.length === 0) return null;
                  return (
                    <div key={sec.id} className="border rounded-md p-2 bg-background space-y-1.5 flex flex-col justify-start">
                      <div className="flex items-center gap-1.5 border-b pb-1">
                        <span className="font-semibold text-[10px] text-primary bg-primary/10 px-1.5 py-0.5 rounded uppercase font-mono">
                          {sec.code}
                        </span>
                        {sec.icon && (
                          <span style={{ color: sec.icon_color || undefined }} className="shrink-0">
                            {renderIcon(sec.icon, "h-3.5 w-3.5")}
                          </span>
                        )}
                        <span className="font-medium text-xs text-foreground truncate">{sec.name}</span>
                      </div>
                      <div className="space-y-1">
                        {sec.operations.map((op) => {
                          const uniqueKey = `stage_${sec.id}_op_${op.operation_code || "default"}`;
                          const isChecked = completedOperationKeys.includes(uniqueKey);
                          return (
                            <label
                              key={uniqueKey}
                              className="flex items-start gap-2 text-xs hover:bg-accent/40 p-1 rounded cursor-pointer min-w-0 animate-fade-in"
                            >
                              <input
                                type="checkbox"
                                checked={isChecked}
                                onChange={(e) => {
                                  if (e.target.checked) {
                                    setCompletedOperationKeys((prev) => [...prev, uniqueKey]);
                                  } else {
                                    setCompletedOperationKeys((prev) => prev.filter((k) => k !== uniqueKey));
                                  }
                                }}
                                className="rounded border-gray-300 text-primary focus:ring-primary h-3.5 w-3.5 mt-0.5 shrink-0"
                              />
                              {op.icon ? (
                                <span style={{ color: op.icon_color || undefined }} className="shrink-0 mt-0.5">
                                  {renderIcon(op.icon, "h-3.5 w-3.5")}
                                </span>
                              ) : op.icon_color ? (
                                <span className="inline-block size-3.5 shrink-0 rounded-full bg-current mt-0.5" style={{ color: op.icon_color }} />
                              ) : null}
                              <span className="text-foreground text-xs leading-normal min-w-0 break-words">
                                {op.operation_name}
                              </span>
                            </label>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {error && <div className="text-sm text-destructive">{error}</div>}

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              Отмена
            </Button>
            <Button onClick={handleSave} disabled={saveMutation.isPending}>
              {saveMutation.isPending ? "Сохранение..." : editingRemainder ? "Обновить" : "Добавить"}
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
  spgs: SpgOut[];
  selectedSpgIds: number[];
  sections: SpgOut["sections"];
  remainders: SpgRemainder[];
  isLoading: boolean;
  onRefresh: () => void;
  searchQuery: string;
}

export function RemaindersListPanel({
  spgId,
  spgs,
  selectedSpgIds,
  sections,
  remainders,
  isLoading,
  onRefresh,
  searchQuery,
}: RemaindersListPanelProps) {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<SpgRemainder | null>(null);
  const [manualOpOpen, setManualOpOpen] = useState(false);
  const [historyRemainderId, setHistoryRemainderId] = useState<number | null>(null);
  const [importDialogOpen, setImportDialogOpen] = useState(false);

  // Состояние сворачивания
  const [isExpanded, setIsExpanded] = useState(true);

  // Состояния для inline-редактирования
  const [inlineEditingId, setInlineEditingId] = useState<number | null>(null);
  const [inlineEditingQuantity, setInlineEditingQuantity] = useState("");
  const [inlineEditingError, setInlineEditingError] = useState<string | null>(null);

  const handleAdd = () => {
    setEditing(null);
    setDialogOpen(true);
  };

  const handleEdit = (r: SpgRemainder) => {
    setInlineEditingId(r.id);
    setInlineEditingQuantity(String(r.remainder_quantity));
    setInlineEditingError(null);
  };

  const inlineSaveMutation = useMutation({
    mutationFn: (input: { remainder: SpgRemainder; quantity: number }) => {
      const actualSpgId = spgs.find(s => s.sections.some(sec => sec.section_id === input.remainder.section_id))?.id || spgId;
      return updateManualRemainder(actualSpgId, input.remainder.id, {
        quantity: input.quantity,
        section_id: input.remainder.section_id,
      });
    },
    onSuccess: (_, variables) => {
      const actualSpgId = spgs.find(s => s.sections.some(sec => sec.section_id === variables.remainder.section_id))?.id || spgId;
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.remainders(actualSpgId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.snapshot(actualSpgId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.remainderHistory(actualSpgId) });
      setInlineEditingId(null);
      setInlineEditingQuantity("");
      onRefresh();
    },
    onError: (e: unknown) => {
      const msg = e && typeof e === "object" && "response" in e
        ? (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
        : undefined;
      setInlineEditingError((msg as string | undefined) || "Ошибка сохранения");
    },
  });

  const handleInlineSave = (r: SpgRemainder) => {
    const qty = parseFloat(inlineEditingQuantity);
    if (isNaN(qty) || qty <= 0) {
      setInlineEditingError("Должно быть > 0");
      return;
    }
    setInlineEditingError(null);
    inlineSaveMutation.mutate({ remainder: r, quantity: qty });
  };

  const handleInlineCancel = () => {
    setInlineEditingId(null);
    setInlineEditingQuantity("");
    setInlineEditingError(null);
  };

  const deleteMutation = useMutation({
    mutationFn: (r: SpgRemainder) => {
      const actualSpgId = spgs.find(s => s.sections.some(sec => sec.section_id === r.section_id))?.id || spgId;
      return deleteManualRemainder(actualSpgId, r.id);
    },
    onSuccess: (_, variables) => {
      const actualSpgId = spgs.find(s => s.sections.some(sec => sec.section_id === variables.section_id))?.id || spgId;
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.remainders(actualSpgId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.snapshot(actualSpgId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.remainderHistory(actualSpgId) });
      onRefresh();
    },
  });

  const handleDelete = (r: SpgRemainder) => {
    if (!confirm(`Удалить остаток ${r.product_sku} (${r.remainder_quantity} шт.)?`)) return;
    deleteMutation.mutate(r);
  };

  // Применение фильтрации и поиска перед маппингом
  const filteredRemainders = remainders.filter((r) => {
    const matchesSearch =
      !searchQuery.trim() ||
      r.product_sku.toLowerCase().includes(searchQuery.toLowerCase()) ||
      r.product_name.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesSearch;
  });

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between border-b pb-2">
        <button
          type="button"
          onClick={() => setIsExpanded(!isExpanded)}
          className="flex items-center gap-2 hover:opacity-80 transition-opacity focus:outline-none"
        >
          {isExpanded ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
          )}
          <h3 className="text-sm font-semibold">
            Наличие на участках ({filteredRemainders.length} из {remainders.length})
          </h3>
        </button>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={() => setImportDialogOpen(true)}>
            <Upload className="h-3.5 w-3.5 mr-1" />
            Импорт Excel
          </Button>
          <Button size="sm" variant="outline" onClick={() => setManualOpOpen(true)}>
            <ArrowDownUp className="h-3.5 w-3.5 mr-1" />
            Ручная операция
          </Button>
          <Button size="sm" onClick={handleAdd}>
            <Plus className="h-3.5 w-3.5 mr-1" />
            Добавить запись
          </Button>
        </div>
      </div>

      {isExpanded && (
        <>
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Загрузка...</p>
          ) : remainders.length === 0 ? (
            <p className="text-sm text-muted-foreground">Записей о наличии нет</p>
          ) : (
            <div className="overflow-x-auto border rounded-lg">
              {filteredRemainders.length === 0 ? (
                <div className="p-8 text-center text-sm text-muted-foreground">
                  Ничего не найдено по выбранным фильтрам
                </div>
              ) : (
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
                    {filteredRemainders.map((r) => {
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
                            {inlineEditingId === r.id ? (
                              <div className="flex flex-col items-end gap-1">
                                <Input
                                  type="number"
                                  className="h-8 w-24 text-right p-1"
                                  min="0"
                                  step="any"
                                  value={inlineEditingQuantity}
                                  onChange={(e) => setInlineEditingQuantity(e.target.value)}
                                  disabled={inlineSaveMutation.isPending}
                                  autoFocus
                                />
                                {inlineEditingError && (
                                  <div className="text-[10px] text-destructive max-w-[120px] text-right leading-tight">
                                    {inlineEditingError}
                                  </div>
                                )}
                              </div>
                            ) : (
                              <>
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
                              </>
                            )}
                          </td>
                          <td className="p-2 text-center">
                            <Badge variant={r.source === "manual" ? "default" : "secondary"} className="text-xs">
                              {r.source === "manual" ? "Ручной" : "Задача"}
                            </Badge>
                          </td>
                          <td className="p-2 text-center">
                            {inlineEditingId === r.id ? (
                              <div className="flex items-center justify-center gap-1">
                                <button
                                  type="button"
                                  onClick={() => handleInlineSave(r)}
                                  disabled={inlineSaveMutation.isPending}
                                  className="p-1 rounded hover:bg-emerald-100 text-emerald-600 dark:hover:bg-emerald-950/30"
                                  title="Сохранить"
                                >
                                  <Check className="h-4 w-4" />
                                </button>
                                <button
                                  type="button"
                                  onClick={handleInlineCancel}
                                  disabled={inlineSaveMutation.isPending}
                                  className="p-1 rounded hover:bg-rose-100 text-rose-600 dark:hover:bg-rose-950/30"
                                  title="Отменить"
                                >
                                  <X className="h-4 w-4" />
                                </button>
                              </div>
                            ) : (
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
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </>
      )}

      <RemainderEditDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        spgId={spgId}
        sections={sections}
        editingRemainder={editing}
        onSaved={onRefresh}
        defaultSectionId={null}
        spgs={spgs}
      />

      <ManualOperationDialog
        open={manualOpOpen}
        onOpenChange={setManualOpOpen}
        spgId={spgId}
        sections={sections}
        onSaved={onRefresh}
        spgs={spgs}
      />

      <RemainderHistoryDrawer
        open={historyRemainderId !== null}
        onOpenChange={(open) => {
          if (!open) setHistoryRemainderId(null);
        }}
        spgId={
          historyRemainderId !== null
            ? spgs.find(s => s.sections.some(sec => sec.section_id === remainders.find(r => r.id === historyRemainderId)?.section_id))?.id || spgId
            : spgId
        }
        remainderId={historyRemainderId}
      />

      <ImportRemaindersDialog
        open={importDialogOpen}
        onOpenChange={setImportDialogOpen}
        spgId={spgId}
        spgs={spgs}
        selectedSpgIds={selectedSpgIds}
        onSaved={onRefresh}
      />
    </div>
  );
}
