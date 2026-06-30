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
  SpgSelect,
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
  AlertDialogAction,
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
import type { Product, LastCompletedOperation } from "@/shared/api/products";
import { listProducts, getProductLastCompletedOperation } from "@/shared/api/products";
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
  const [quantity, setQuantity] = useState("");
  const [selectedSpgId, setSelectedSpgId] = useState<number>(spgId);
  const [error, setError] = useState<string | null>(null);

  // Completed stages states
  const [sectionsWithOps, setSectionsWithOps] = useState<SectionWithOperations[]>([]);
  const [completedOperationKeys, setCompletedOperationKeys] = useState<string[]>([]);
  const [loadingStages, setLoadingStages] = useState(false);
  const [lastCompletedOp, setLastCompletedOp] = useState<LastCompletedOperation | null>(null);

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
        setQuantity(String(editingRemainder.remainder_quantity));
        setProductSearch(editingRemainder.product_sku);
        setSelectedSpgId(editingRemainder.spg_id);
      } else {
        setSelectedProductId(null);
        setQuantity("");
        setProductSearch("");
        setSelectedSpgId(spgId);
      }
      setError(null);
    }
  }, [open, editingRemainder, sections, defaultSectionId, spgId]);

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

  useEffect(() => {
    if (!open || selectedProductId == null || editingRemainder != null) {
      setLastCompletedOp(null);
      return;
    }

    getProductLastCompletedOperation(selectedProductId)
      .then((data) => {
        setLastCompletedOp(data);
      })
      .catch(() => {
        setLastCompletedOp(null);
      });
  }, [selectedProductId, open, editingRemainder, defaultSectionId, sections]);

  useEffect(() => {
    if (!open || editingRemainder != null || flatOperations.length === 0) return;

    if (lastCompletedOp && lastCompletedOp.section_id) {
      const targetOpIndex = flatOperations.findIndex(
        (op) =>
          op.sectionId === lastCompletedOp.section_id &&
          (op.operationCode === lastCompletedOp.operation_code || op.operationName === lastCompletedOp.operation_name)
      );
      if (targetOpIndex !== -1) {
        const keysToSelect = flatOperations
          .slice(0, targetOpIndex + 1)
          .map((op) => op.uniqueKey);
        setCompletedOperationKeys(keysToSelect);
      } else {
        const sectionOps = flatOperations.filter((op) => op.sectionId === lastCompletedOp.section_id);
        if (sectionOps.length > 0) {
          const lastSecOp = sectionOps[sectionOps.length - 1];
          const idx = flatOperations.findIndex((op) => op.uniqueKey === lastSecOp.uniqueKey);
          if (idx !== -1) {
            const keysToSelect = flatOperations
              .slice(0, idx + 1)
              .map((op) => op.uniqueKey);
            setCompletedOperationKeys(keysToSelect);
          }
        }
      }
    } else {
      setCompletedOperationKeys([]);
    }
  }, [lastCompletedOp, flatOperations, open, editingRemainder]);

  const filteredProducts = productSearch.trim()
    ? products.filter(
        (p) =>
          p.sku.toLowerCase().includes(productSearch.toLowerCase()) ||
          p.name.toLowerCase().includes(productSearch.toLowerCase()),
      )
    : products.slice(0, 50);

  const saveMutation = useMutation({
    mutationFn: async (input: { kind: "create" | "update"; payload: ManualRemainderCreateInput | ManualRemainderUpdateInput }) => {
      const actualSpgId = editingRemainder?.spg_id || spgId;
      if (input.kind === "create") {
        await createManualRemainder(selectedSpgId, input.payload as ManualRemainderCreateInput);
      } else {
        await updateManualRemainder(
          actualSpgId,
          (editingRemainder as SpgRemainder).id,
          input.payload as ManualRemainderUpdateInput,
        );
      }
    },
    onSuccess: () => {
      const oldSpgId = editingRemainder?.spg_id || spgId;
      const newSpgId = selectedSpgId;
      
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.snapshot(oldSpgId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.remainders(oldSpgId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.remainderHistory(oldSpgId) });

      if (newSpgId !== oldSpgId) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.spg.snapshot(newSpgId) });
        void queryClient.invalidateQueries({ queryKey: queryKeys.spg.remainders(newSpgId) });
        void queryClient.invalidateQueries({ queryKey: queryKeys.spg.remainderHistory(newSpgId) });
      }

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

  const deleteMutation = useMutation({
    mutationFn: async () => {
      if (!editingRemainder) return;
      const actualSpgId = editingRemainder.spg_id || spgId;
      await deleteManualRemainder(actualSpgId, editingRemainder.id);
    },
    onSuccess: () => {
      const actualSpgId = editingRemainder ? editingRemainder.spg_id || spgId : spgId;
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
      setError((msg as string | undefined) || "Ошибка удаления");
    },
  });

  const handleDelete = () => {
    if (window.confirm("Вы действительно хотите удалить этот остаток?")) {
      deleteMutation.mutate();
    }
  };

  const handleSave = () => {
    if (!selectedProductId || !quantity) {
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
        completed_stages,
        spg_id: selectedSpgId,
      };
      saveMutation.mutate({ kind: "update", payload });
    } else {
      const payload: ManualRemainderCreateInput = {
        product_id: selectedProductId as number,
        quantity: qty,
        completed_stages,
        spg_id: selectedSpgId,
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
          {/* Product search & Quantity */}
          <div className="grid grid-cols-4 gap-4">
            <div className="col-span-2 space-y-1">
              <label className="text-sm font-medium">Артикул / Продукт</label>
              {editingRemainder ? (
                <div className="text-sm font-semibold h-10 flex items-center">
                  {editingRemainder.product_sku} — {editingRemainder.product_name}
                </div>
              ) : (
                <div className="relative">
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
                    <div className="absolute z-10 w-full max-h-[150px] overflow-auto border bg-popover text-popover-foreground rounded-md mt-1 shadow-md">
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
              )}
            </div>

            <div className="col-span-1 space-y-1">
              <label className="text-sm font-medium">Количество</label>
              <Input
                type="number"
                placeholder="0"
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
                min="0"
                step="any"
                className="w-full"
              />
            </div>

            <div className="col-span-1 space-y-1">
              <label className="text-sm font-medium">ГХП (Хранение)</label>
              {spgs && spgs.length > 0 ? (
                <SpgSelect
                  spgs={spgs}
                  value={selectedSpgId}
                  onValueChange={(val) => {
                    if (val !== null) {
                      setSelectedSpgId(val);
                    }
                  }}
                  className="w-full h-10"
                />
              ) : (
                <div className="text-xs text-muted-foreground pt-3">Нет списка ГХП</div>
              )}
            </div>
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

          <div className="flex justify-end gap-2 pt-2 w-full">
            {editingRemainder && (
              <Button
                variant="destructive"
                onClick={handleDelete}
                disabled={deleteMutation.isPending || saveMutation.isPending}
                className="mr-auto"
              >
                {deleteMutation.isPending ? "Удаление..." : "Удалить"}
              </Button>
            )}
            <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saveMutation.isPending || deleteMutation.isPending}>
              Отмена
            </Button>
            <Button onClick={handleSave} disabled={saveMutation.isPending || deleteMutation.isPending}>
              {saveMutation.isPending ? "Сохранение..." : editingRemainder ? "Сохранить" : "Добавить"}
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
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [remainderToDelete, setRemainderToDelete] = useState<SpgRemainder | null>(null);

  // Состояние сворачивания
  const [isExpanded, setIsExpanded] = useState(true);

  const handleAdd = () => {
    setEditing(null);
    setDialogOpen(true);
  };

  const handleEdit = (r: SpgRemainder) => {
    setEditing(r);
    setDialogOpen(true);
  };

  const deleteMutation = useMutation({
    mutationFn: (r: SpgRemainder) => {
      const actualSpgId = r.spg_id || spgId;
      return deleteManualRemainder(actualSpgId, r.id);
    },
    onSuccess: (_, variables) => {
      const actualSpgId = variables.spg_id || spgId;
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.remainders(actualSpgId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.snapshot(actualSpgId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.remainderHistory(actualSpgId) });
      onRefresh();
    },
  });

  const handleDelete = (r: SpgRemainder) => {
    setRemainderToDelete(r);
    setDeleteConfirmOpen(true);
  };

  const handleConfirmDelete = () => {
    if (remainderToDelete) {
      deleteMutation.mutate(remainderToDelete);
      setRemainderToDelete(null);
    }
  };

  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [bulkDeleteConfirmOpen, setBulkDeleteConfirmOpen] = useState(false);

  useEffect(() => {
    setSelectedIds([]);
  }, [spgId, remainders]);

  const bulkDeleteMutation = useMutation({
    mutationFn: async () => {
      for (const id of selectedIds) {
        const r = remainders.find((item) => item.id === id);
        if (r) {
          const actualSpgId = r.spg_id || spgId;
          await deleteManualRemainder(actualSpgId, id);
        }
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.remainders(spgId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.snapshot(spgId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.remainderHistory(spgId) });
      setSelectedIds([]);
      onRefresh();
      setBulkDeleteConfirmOpen(false);
    },
  });

  const handleConfirmBulkDelete = () => {
    bulkDeleteMutation.mutate();
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
            Наличие на ГХП ({filteredRemainders.length} из {remainders.length})
          </h3>
        </button>
        <div className="flex items-center gap-2">
          {selectedIds.length > 0 && (
            <Button
              size="sm"
              variant="destructive"
              onClick={() => setBulkDeleteConfirmOpen(true)}
              disabled={bulkDeleteMutation.isPending}
            >
              <Trash2 className="h-3.5 w-3.5 mr-1" />
              Удалить выбранные ({selectedIds.length})
            </Button>
          )}
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
                      <th className="p-2 w-[40px] text-center">
                        <input
                          type="checkbox"
                          className="rounded border-gray-300 text-primary focus:ring-primary h-4 w-4 cursor-pointer"
                          checked={
                            filteredRemainders.length > 0 &&
                            filteredRemainders.every((r) => selectedIds.includes(r.id))
                          }
                          onChange={(e) => {
                            if (e.target.checked) {
                              setSelectedIds(filteredRemainders.map((r) => r.id));
                            } else {
                              setSelectedIds([]);
                            }
                          }}
                        />
                      </th>
                      <th className="p-2 pr-0 text-left font-medium w-[130px]">Артикул</th>
                      <th className="p-2 pl-0 text-left font-medium w-[70px]">Кол-во</th>
                      <th className="p-2 text-left font-medium">Пройденные операции</th>
                      <th className="p-2 text-left font-medium">ГХП</th>
                      <th className="p-2 text-center font-medium">Источник</th>
                      <th className="p-2 text-center font-medium">Действия</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredRemainders.map((r) => {
                      const isNegative = r.remainder_quantity < 0;
                      return (
                        <tr key={r.id} className="border-b hover:bg-muted/30">
                          <td className="p-2 text-center w-[40px]">
                            <input
                              type="checkbox"
                              className="rounded border-gray-300 text-primary focus:ring-primary h-4 w-4 cursor-pointer"
                              checked={selectedIds.includes(r.id)}
                              onChange={(e) => {
                                if (e.target.checked) {
                                  setSelectedIds((prev) => [...prev, r.id]);
                                } else {
                                  setSelectedIds((prev) => prev.filter((id) => id !== r.id));
                                }
                              }}
                            />
                          </td>
                          {/* 1. Артикул */}
                          <td className="p-2 pr-0">
                            <div className="font-medium">{r.product_sku}</div>
                            <div className="text-xs text-muted-foreground truncate max-w-[120px]" title={r.product_name}>
                              {r.product_name}
                            </div>
                          </td>
                          {/* 2.  Кол-во */}
                          <td className="p-2 pl-0 text-left">
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
                          {/* 3. Пройденные операции */}
                          <td className="p-2">
                            <div className="text-xs text-muted-foreground max-w-[250px] truncate" title={
                              r.completed_stages && r.completed_stages.length > 0
                                ? [...r.completed_stages].reverse().map((cs: any) => cs.operation_name || cs.operation_code).join(", ")
                                : "Нет пройденных операций"
                            }>
                              {r.completed_stages && r.completed_stages.length > 0
                                ? [...r.completed_stages].reverse().map((cs: any) => cs.operation_name || cs.operation_code).join(", ")
                                : "—"}
                            </div>
                          </td>
                          {/* 4. ГХП */}
                          <td className="p-2">
                            <div className="text-xs font-medium text-foreground">{r.spg_name || "—"}</div>
                          </td>
                          {/* 5. Источник */}
                          <td className="p-2 text-center">
                            <Badge variant={r.source === "manual" ? "default" : "secondary"} className="text-xs">
                              {r.source === "manual" ? "Ручной" : "Задача"}
                            </Badge>
                          </td>
                          {/* 6. Действия */}
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
            ? remainders.find(r => r.id === historyRemainderId)?.spg_id || spgId
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

      <AlertDialog open={deleteConfirmOpen} onOpenChange={setDeleteConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Подтверждение удаления остатка</AlertDialogTitle>
            <AlertDialogDescription asChild>
              {remainderToDelete && (
                <div className="space-y-3 mt-2 text-foreground text-left">
                  <p>Вы действительно хотите удалить этот остаток?</p>
                  <div className="bg-muted/40 p-3 rounded-md border text-sm space-y-1.5 font-normal">
                    <div>
                      <span className="font-semibold text-muted-foreground mr-1">Продукт:</span>
                      <span className="font-medium text-foreground">{remainderToDelete.product_sku}</span>
                      {remainderToDelete.product_name && ` — ${remainderToDelete.product_name}`}
                    </div>
                    <div>
                      <span className="font-semibold text-muted-foreground mr-1">ГХП:</span>
                      <span className="font-medium text-foreground">{remainderToDelete.spg_name || "—"}</span>
                    </div>
                    <div>
                      <span className="font-semibold text-muted-foreground mr-1">Количество:</span>
                      <span className="font-bold text-foreground">{remainderToDelete.remainder_quantity} шт.</span>
                    </div>
                    <div>
                      <span className="font-semibold text-muted-foreground mr-1">Завершенные этапы:</span>
                      <span className="font-medium text-foreground text-xs">
                        {remainderToDelete.completed_stages && remainderToDelete.completed_stages.length > 0
                          ? remainderToDelete.completed_stages.map((cs: any) => cs.operation_name || cs.operation_code).join(", ")
                          : "Нет"}
                      </span>
                    </div>
                    <div>
                      <span className="font-semibold text-muted-foreground mr-1">Источник:</span>
                      <Badge variant={remainderToDelete.source === "manual" ? "default" : "secondary"} className="text-[10px] h-4 py-0 ml-1">
                        {remainderToDelete.source === "manual" ? "Вручную" : "Из задачи"}
                      </Badge>
                    </div>
                  </div>
                  <p className="text-xs text-destructive font-medium border-l-2 border-destructive pl-2">
                    Внимание: Данное действие безвозвратно удалит запись о наличии. Это количество больше не будет автоматически списываться при выполнении задач на этом участке.
                  </p>
                </div>
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmDelete}
              className="bg-destructive hover:bg-destructive/90 text-destructive-foreground"
            >
              Удалить
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={bulkDeleteConfirmOpen} onOpenChange={setBulkDeleteConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Подтверждение группового удаления</AlertDialogTitle>
            <AlertDialogDescription>
              Вы действительно хотите удалить выбранные остатки в количестве {selectedIds.length} шт.?
              Данное действие безвозвратно удалит выбранные записи о наличии.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmBulkDelete}
              className="bg-destructive hover:bg-destructive/90 text-destructive-foreground"
              disabled={bulkDeleteMutation.isPending}
            >
              {bulkDeleteMutation.isPending ? "Удаление..." : "Удалить выбранные"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
