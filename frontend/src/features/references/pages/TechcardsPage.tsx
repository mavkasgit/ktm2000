import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Plus, Trash2, ArrowUp, ArrowDown, ArrowUpDown, Search, X } from "lucide-react";
import * as API from "shared/api";
import * as UI from "shared/ui";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/shared/ui/Dialog";
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogCancel, AlertDialogAction } from "@/shared/ui/AlertDialog";
import { ProductSearchMulti } from "../components/ProductSearchMulti";
import { SortableFilterHeader } from "@/shared/ui/SortableFilterHeader";
import { toast } from "@/shared/ui/use-toast";
import { getErrorMessage } from "@/shared/api/client";
import { usePermission } from "@/features/auth/hooks/usePermission";
import { cn } from "@/shared/utils/cn";

type ProcessingType = "standart_processing" | "paired_processing";

const ui = UI as unknown as Record<string, React.ComponentType<any>>;
const Button = ui.Button ?? "button";
const Input = ui.Input ?? "input";

export function TechcardsPage() {
  const { canEditReferences } = usePermission();
  const isReadOnly = !canEditReferences;
  const api = API as Record<string, any>;
  const [rawItems, setRawItems] = useState<any[]>([]);
  const [techcards, setTechcards] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("");
  const [pageSearch, setPageSearch] = useState("");
  const [pairedSorts, setPairedSorts] = useState<Array<{ field: "sku" | "quantity"; order: "asc" | "desc" }>>([]);
  const [standardSorts, setStandardSorts] = useState<Array<{ field: "sku" | "quantity"; order: "asc" | "desc" }>>([]);
  const [pairedFilters, setPairedFilters] = useState<Record<"sku" | "quantity", Set<string>>>({
    sku: new Set(),
    quantity: new Set(),
  });
  const [standardFilters, setStandardFilters] = useState<Record<"sku" | "quantity", Set<string>>>({
    sku: new Set(),
    quantity: new Set(),
  });
  // Bulk dialog
  const [bulkDialogOpen, setBulkDialogOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [search, setSearch] = useState("");

  // Paired creation dialog
  const [pairedDialogOpen, setPairedDialogOpen] = useState(false);
  const [skuA, setSkuA] = useState("");
  const [skuB, setSkuB] = useState("");
  const [quantityPerItem, setQuantityPerItem] = useState<string>("");
  const [quantityAPerItem, setQuantityAPerItem] = useState<string>("");
  const [quantityBPerItem, setQuantityBPerItem] = useState<string>("");
  const [differentQuantities, setDifferentQuantities] = useState(false);

  // View/Edit dialog
  const [viewTechcardId, setViewTechcardId] = useState<number | null>(null);
  const [viewDetail, setViewDetail] = useState<any>(null);
  const [editQuantityTotal, setEditQuantityTotal] = useState(1);
  const [editQuantityAPerItem, setEditQuantityAPerItem] = useState(1);
  const [editQuantityBPerItem, setEditQuantityBPerItem] = useState(1);
  const [editDifferentQuantities, setEditDifferentQuantities] = useState(false);

  // Delete confirmation
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<{ type: "techcard"; id: number } | null>(null);

  const resolvePairSkus = useCallback((detail: any): { skuA: string; skuB: string } => {
    const lines = detail?.techcard_lines ?? detail?.lines ?? [];
    const skus = lines.map((l: any) => {
      const product = rawItems.find((p) => Number(p.id) === Number(l.component_product_id));
      return product?.sku ?? String(l.component_product_id);
    });
    return { skuA: skus[0] ?? "—", skuB: skus[1] ?? "—" };
  }, [rawItems]);

  // Unique values for filtering
  const pairedUniqueValues = useMemo(() => {
    const items = techcards.filter((t: any) => t.product_id === null && t.processing_type === "paired_processing");
    return {
      sku: [...new Set(items.map((card) => {
        const { skuA, skuB } = resolvePairSkus(card);
        return `${skuA} + ${skuB}`;
      }))].sort(),
      quantity: [...new Set(items.map((card) => {
        const qtyA = card.quantity_a_per_item ?? 1;
        const qtyB = card.quantity_b_per_item ?? 1;
        return `${card.quantity_total ?? "—"} шт. (${qtyA}/${qtyB} на подвес)`;
      }))].sort(),
    };
  }, [techcards, resolvePairSkus]);

  const standardUniqueValues = useMemo(() => {
    const items = techcards.filter((t: any) => t.product_id !== null);
    return {
      sku: [...new Set(items.map((card) => {
        const product = rawItems.find((p) => Number(p.id) === card.product_id);
        return product?.sku ?? String(card.product_id);
      }))].sort(),
      quantity: [...new Set(items.map((card) => {
        return String(card.quantity_total ?? "—");
      }))].sort((a, b) => Number(a) - Number(b)),
    };
  }, [techcards, rawItems]);

  // Derived data
  const pairedTechcards = useMemo(() => {
    let filtered = techcards.filter((t: any) => t.product_id === null && t.processing_type === "paired_processing");
    const q = pageSearch.trim().toLowerCase();
    if (q) {
      filtered = filtered.filter((card) => {
        const { skuA, skuB } = resolvePairSkus(card);
        return skuA.toLowerCase().includes(q) || skuB.toLowerCase().includes(q);
      });
    }
    if (pairedFilters.sku.size > 0) {
      filtered = filtered.filter((card) => {
        const { skuA, skuB } = resolvePairSkus(card);
        return pairedFilters.sku.has(`${skuA} + ${skuB}`);
      });
    }
    if (pairedFilters.quantity.size > 0) {
      filtered = filtered.filter((card) => {
        const qtyA = card.quantity_a_per_item ?? 1;
        const qtyB = card.quantity_b_per_item ?? 1;
        const label = `${card.quantity_total ?? "—"} шт. (${qtyA}/${qtyB} на подвес)`;
        return pairedFilters.quantity.has(label);
      });
    }
    const activeSort = pairedSorts[0];
    if (activeSort) {
      const { field, order } = activeSort;
      return [...filtered].sort((a, b) => {
        let aVal = "";
        let bVal = "";
        if (field === "sku") {
          const { skuA: a1, skuB: a2 } = resolvePairSkus(a);
          const { skuA: b1, skuB: b2 } = resolvePairSkus(b);
          aVal = `${a1} + ${a2}`;
          bVal = `${b1} + ${b2}`;
        } else {
          aVal = String(a.quantity_total ?? 0);
          bVal = String(b.quantity_total ?? 0);
        }
        if (field === "quantity") {
          const aNum = Number(aVal);
          const bNum = Number(bVal);
          return order === "asc" ? aNum - bNum : bNum - aNum;
        }
        return order === "asc" ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
      });
    }
    return filtered;
  }, [techcards, pageSearch, pairedFilters, pairedSorts, resolvePairSkus]);

  const oneToOneTechcards = useMemo(() => {
    let filtered = techcards.filter((t: any) => t.product_id !== null);
    const q = pageSearch.trim().toLowerCase();
    if (q) {
      filtered = filtered.filter((card) => {
        const product = rawItems.find((p) => Number(p.id) === card.product_id);
        return String(product?.sku ?? "").toLowerCase().includes(q);
      });
    }
    if (standardFilters.sku.size > 0) {
      filtered = filtered.filter((card) => {
        const product = rawItems.find((p) => Number(p.id) === card.product_id);
        const label = product?.sku ?? String(card.product_id);
        return standardFilters.sku.has(label);
      });
    }
    if (standardFilters.quantity.size > 0) {
      filtered = filtered.filter((card) => {
        const label = String(card.quantity_total ?? "—");
        return standardFilters.quantity.has(label);
      });
    }
    const activeSort = standardSorts[0];
    if (activeSort) {
      const { field, order } = activeSort;
      return [...filtered].sort((a, b) => {
        let aVal = "";
        let bVal = "";
        if (field === "sku") {
          const pA = rawItems.find((p) => Number(p.id) === a.product_id);
          const pB = rawItems.find((p) => Number(p.id) === b.product_id);
          aVal = pA?.sku ?? "";
          bVal = pB?.sku ?? "";
        } else {
          aVal = String(a.quantity_total ?? 0);
          bVal = String(b.quantity_total ?? 0);
        }
        if (field === "quantity") {
          const aNum = Number(aVal);
          const bNum = Number(bVal);
          return order === "asc" ? aNum - bNum : bNum - aNum;
        }
        return order === "asc" ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
      });
    }
    return filtered;
  }, [techcards, pageSearch, standardFilters, standardSorts, rawItems]);

  const techcardByProductId = useMemo(() => {
    const map = new Map<number, any>();
    for (const card of techcards) {
      if (card.is_active && card.product_id != null) {
        map.set(card.product_id, card);
      }
    }
    return map;
  }, [techcards]);

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rawItems.filter((item) => {
      if (!q) return true;
      return String(item.sku ?? "").toLowerCase().includes(q) || String(item.name ?? "").toLowerCase().includes(q);
    });
  }, [rawItems, search]);

  const { pairProfileSku, pairProfileName } = useMemo(() => {
    const a = skuA.trim();
    const b = skuB.trim();
    if (!a || !b) return { pairProfileSku: "", pairProfileName: "" };
    const sorted = [a, b].sort();
    return { pairProfileSku: sorted.join("+"), pairProfileName: sorted.join(" + ") };
  }, [skuA, skuB]);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [products, cards] = await Promise.all([
        api.listProducts({ limit: 2000 }),
        api.listTechcards(),
      ]);
      setRawItems(products ?? []);
      setTechcards(cards ?? []);
    } catch (e) {
      setStatus(e instanceof Error ? e.message : "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    loadData().catch(() => {});
  }, [loadData]);

  const openView = async (techcardId: number) => {
    setViewTechcardId(techcardId);
    try {
      const detail = await api.getTechcard(techcardId);
      setViewDetail(detail);
      setEditQuantityTotal(detail.quantity_total ?? 1);
      setEditQuantityAPerItem(detail.quantity_a_per_item ?? 1);
      setEditQuantityBPerItem(detail.quantity_b_per_item ?? 1);
      setEditDifferentQuantities((detail.quantity_a_per_item ?? 1) !== (detail.quantity_b_per_item ?? 1));
    } catch (e) {
      toast({ title: `Ошибка загрузки техкарты #${techcardId}`, description: getErrorMessage(e), variant: "destructive" });
    }
  };

  const saveTechcard = async () => {
    if (!viewTechcardId || !viewDetail) return;
    try {
      if (viewDetail.product_id === null) {
        await api.patchTechcard(viewTechcardId, {
          quantity_total: editQuantityTotal,
          quantity_a_per_item: editQuantityAPerItem,
          quantity_b_per_item: editQuantityBPerItem,
        });
        const { skuA: sA, skuB: sB } = resolvePairSkus(viewDetail);
        toast({ title: "Сохранено", description: `Парная техкарта #${viewTechcardId} (${sA}+${sB}): общее=${editQuantityTotal}, ${sA}=${editQuantityAPerItem}, ${sB}=${editQuantityBPerItem} на подвес`, variant: "success" });
      } else {
        await api.patchTechcard(viewTechcardId, {
          quantity_total: editQuantityTotal,
        });
        const sku = rawItems.find((p) => Number(p.id) === viewDetail.product_id)?.sku ?? viewDetail.product_id;
        toast({ title: "Сохранено", description: `Техкарта #${viewTechcardId} (артикул: ${sku}, ID: ${viewTechcardId}, кол-во: ${editQuantityTotal}) успешно обновлена`, variant: "success" });
      }
      await loadData();
      await openView(viewTechcardId);
    } catch (e) {
      toast({ title: `Ошибка сохранения: техкарта #${viewTechcardId}`, description: getErrorMessage(e), variant: "destructive" });
    }
  };

  const confirmDelete = (target: { type: "techcard"; id: number }) => {
    setDeleteTarget(target);
    setDeleteDialogOpen(true);
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      const targetCard = techcards.find((t: any) => t.id === deleteTarget.id);
      let detail = "";
      if (targetCard) {
        const isPaired = targetCard.product_id === null;
        if (isPaired) {
          const { skuA, skuB } = resolvePairSkus(targetCard);
          detail = `парная (${skuA}+${skuB})`;
        } else {
          const product = rawItems.find((p) => Number(p.id) === targetCard.product_id);
          detail = `стандартная, артикул: ${product?.sku ?? "—"}`;
        }
      } else {
        detail = `ID ${deleteTarget.id}`;
      }
      await api.deleteTechcard(deleteTarget.id);
      toast({ title: "Удалено", description: `Техкарта #${deleteTarget.id} (${detail}, версия: ${targetCard?.version ?? "—"}) успешно удалена`, variant: "success" });
      setViewTechcardId(null);
      setViewDetail(null);
      await loadData();
    } catch (e) {
      toast({ title: `Ошибка удаления: техкарта #${deleteTarget.id}`, description: getErrorMessage(e), variant: "destructive" });
    } finally {
      setDeleteDialogOpen(false);
      setDeleteTarget(null);
    }
  };

  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectVisible = () => setSelectedIds(new Set(rows.map((r) => Number(r.id))));
  const clearSelection = () => setSelectedIds(new Set());

  const applyBulk = async () => {
    if (selectedIds.size === 0) return;
    setLoading(true);
    setStatus("Обработка...");
    try {
      let created = 0;
      let updated = 0;
      for (const productId of selectedIds) {
        const existing = techcardByProductId.get(productId);
        const product = rawItems.find((item) => Number(item.id) === productId);
        const qty = product?.quantity_per_hanger || 1;
        if (!existing) {
          await api.createTechcard({
            product_id: productId,
            version: "A",
            processing_type: "standart_processing",
            is_active: true,
            quantity_total: qty,
          });
          created += 1;
        } else {
          await api.patchTechcard(Number(existing.id), {
            quantity_total: qty,
          });
          updated += 1;
        }
      }
      toast({ title: "Массовое создание завершено", description: `Выбрано ${selectedIds.size} артикулов: создано ${created} техкарт, обновлено ${updated}`, variant: "success" });
      setBulkDialogOpen(false);
      await loadData();
      clearSelection();
    } catch (e) {
      toast({ title: `Ошибка массового создания: ${selectedIds.size} артикулов`, description: getErrorMessage(e), variant: "destructive" });
    } finally {
      setLoading(false);
    }
  };

  const createPairedTechcard = async () => {
    if (!skuA.trim() || !skuB.trim()) {
      toast({ title: "Ошибка создания парной техкарты", description: `Выберите 2 артикула (текущий: "${skuA || "—"}" и "${skuB || "—"}")`, variant: "destructive" });
      return;
    }
    const productA = rawItems.find((item) => String(item.sku).toLowerCase() === skuA.trim().toLowerCase());
    const productB = rawItems.find((item) => String(item.sku).toLowerCase() === skuB.trim().toLowerCase());
    if (!productA || !productB) {
      const missing = [];
      if (!productA) missing.push(skuA);
      if (!productB) missing.push(skuB);
      toast({ title: "Артикулы не найдены", description: `Следующие артикулы не найдены в списке: ${missing.join(", ")}`, variant: "destructive" });
      return;
    }
    if (productA.id === productB.id) {
      toast({ title: "Ошибка создания парной техкарты", description: `Артикулы должны быть разными (выбран один: ${productA.sku})`, variant: "destructive" });
      return;
    }
    const qtyA = parseInt(quantityAPerItem) || 1;
    const qtyB = parseInt(quantityBPerItem) || 1;
    const calcTotal = differentQuantities ? qtyA + qtyB : (parseInt(quantityPerItem) || 1) * 2;
    if (calcTotal < 1) {
      toast({ title: "Ошибка создания парной техкарты", description: `Общее кол-во должно быть > 0 (${calcTotal} при ${qtyA}+${qtyB})`, variant: "destructive" });
      return;
    }
    setLoading(true);
    try {
      if (!productA.is_paired_profile) {
        await api.patchProduct(Number(productA.id), { is_paired_profile: true });
      }
      if (!productB.is_paired_profile) {
        await api.patchProduct(Number(productB.id), { is_paired_profile: true });
      }

      const card = await api.createTechcard({
        product_id: null,
        version: "A",
        processing_type: "paired_processing",
        is_active: true,
        quantity_total: calcTotal,
        quantity_a_per_item: qtyA,
        quantity_b_per_item: qtyB,
      });
      await api.createTechcardLine(Number(card.id), { component_product_id: Number(productA.id), quantity: qtyA, unit: "pcs" });
      await api.createTechcardLine(Number(card.id), { component_product_id: Number(productB.id), quantity: qtyB, unit: "pcs" });
      toast({ title: "Парная техкарта создана", description: `${pairProfileSku} (ID: #${card.id}): общее=${calcTotal}, ${productA.sku}=${qtyA}, ${productB.sku}=${qtyB} на подвес`, variant: "success" });
      setSkuA(""); setSkuB(""); setQuantityPerItem(""); setQuantityAPerItem(""); setQuantityBPerItem(""); setDifferentQuantities(false); setPairedDialogOpen(false);
      await loadData();
    } catch (e) {
      toast({ title: `Ошибка создания парной техкарты: ${pairProfileSku}`, description: getErrorMessage(e), variant: "destructive" });
    } finally {
      setLoading(false);
    }
  };

  const handlePairedSort = (field: "sku" | "quantity") => {
    setPairedSorts((prev) => {
      const active = prev[0];
      if (!active || active.field !== field) return [{ field, order: "asc" }];
      if (active.order === "asc") return [{ field, order: "desc" }];
      return [];
    });
  };

  const handleStandardSort = (field: "sku" | "quantity") => {
    setStandardSorts((prev) => {
      const active = prev[0];
      if (!active || active.field !== field) return [{ field, order: "asc" }];
      if (active.order === "asc") return [{ field, order: "desc" }];
      return [];
    });
  };

  return (
    <section style={{ display: "grid", gap: 16 }}>
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Техкарты</h2>
        <div className="flex gap-2">
          {!isReadOnly && (
            <>
              <Button size="sm" variant="outline" onClick={() => setBulkDialogOpen(true)}>
                <Plus className="h-4 w-4 mr-1" />
                Массовое создание
              </Button>
              <Button size="sm" variant="outline" onClick={() => setPairedDialogOpen(true)}>
                <Plus className="h-4 w-4 mr-1" />
                Создать парную
              </Button>
            </>
          )}
        </div>
      </div>

      <div className="flex flex-col sm:flex-row gap-2">
        <div className="relative w-52">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input placeholder="Поиск по артикулу" value={pageSearch} onChange={(e: any) => setPageSearch(e.target.value)} className="pl-9" />
          {pageSearch && (
            <button onClick={() => setPageSearch("")} className="absolute right-3 top-1/2 -translate-y-1/2">
              <X className="h-4 w-4 text-muted-foreground" />
            </button>
          )}
        </div>
        <Button variant="outline" size="sm" onClick={() => {
          setPageSearch("");
          setPairedSorts([]);
          setStandardSorts([]);
          setPairedFilters({ sku: new Set(), quantity: new Set() });
          setStandardFilters({ sku: new Set(), quantity: new Set() });
        }}>
          Очистить
        </Button>
      </div>

      {/* Paired techcards table */}
      <div>
        <h3 className="text-sm font-medium text-muted-foreground mb-2">Парные техкарты</h3>
        <div style={{ border: "1px solid #e5e7eb", borderRadius: 6, overflow: "auto", maxHeight: 400, width: "fit-content" }}>
          <table style={{ borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ background: "#f9fafb", position: "sticky", top: 0 }}>
                <th style={{ textAlign: "left", padding: 8, width: 300, minWidth: 300 }}>
                  <SortableFilterHeader
                    field="sku"
                    label="Парный артикул"
                    currentSorts={pairedSorts}
                    onSortChange={handlePairedSort}
                    values={pairedUniqueValues.sku}
                    selectedValues={pairedFilters.sku}
                    onFilterChange={(field, selected) => setPairedFilters(prev => ({ ...prev, [field]: selected }))}
                  />
                </th>
                <th style={{ textAlign: "left", padding: 8, width: 250, minWidth: 250 }}>
                  <SortableFilterHeader
                    field="quantity"
                    label="Кол-во"
                    currentSorts={pairedSorts}
                    onSortChange={handlePairedSort}
                    values={pairedUniqueValues.quantity}
                    selectedValues={pairedFilters.quantity}
                    onFilterChange={(field, selected) => setPairedFilters(prev => ({ ...prev, [field]: selected }))}
                  />
                </th>
                {!isReadOnly && <th style={{ textAlign: "left", padding: 8, width: 80 }}></th>}
              </tr>
            </thead>
            <tbody>
              {pairedTechcards.map((card: any) => {
                const { skuA: cardSkuA, skuB: cardSkuB } = resolvePairSkus(card);
                const qtyA = card.quantity_a_per_item ?? 1;
                const qtyB = card.quantity_b_per_item ?? 1;
                return (
                  <tr key={card.id} className="cursor-pointer hover:bg-muted/50" onClick={() => openView(card.id)}>
                    <td style={{ padding: 8, fontWeight: 600, borderTop: "1px solid #f3f4f6" }}>{cardSkuA} + {cardSkuB}</td>
                    <td style={{ padding: 8, borderTop: "1px solid #f3f4f6" }}>{card.quantity_total ?? "—"} шт. ({qtyA}/{qtyB} на подвес)</td>
                    {!isReadOnly && (
                      <td style={{ padding: 8, borderTop: "1px solid #f3f4f6" }}>
                        <button type="button" onClick={(e) => { e.stopPropagation(); confirmDelete({ type: "techcard", id: card.id }); }} className="text-destructive hover:text-destructive/80">
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </td>
                    )}
                  </tr>
                );
              })}
              {pairedTechcards.length === 0 && (
                <tr><td colSpan={isReadOnly ? 2 : 3} style={{ padding: 16, textAlign: "center", color: "#9ca3af" }}>Нет парных техкарт</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Standard techcards table */}
      <div>
        <h3 className="text-sm font-medium text-muted-foreground mb-2">Стандартные техкарты</h3>
        <div style={{ border: "1px solid #e5e7eb", borderRadius: 6, overflow: "auto", maxHeight: 400, width: "fit-content" }}>
          <table style={{ borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ background: "#f9fafb", position: "sticky", top: 0 }}>
                <th style={{ textAlign: "left", padding: 8, width: 300, minWidth: 300 }}>
                  <SortableFilterHeader
                    field="sku"
                    label="Артикул"
                    currentSorts={standardSorts}
                    onSortChange={handleStandardSort}
                    values={standardUniqueValues.sku}
                    selectedValues={standardFilters.sku}
                    onFilterChange={(field, selected) => setStandardFilters(prev => ({ ...prev, [field]: selected }))}
                  />
                </th>
                <th style={{ textAlign: "left", padding: 8, width: 250, minWidth: 250 }}>
                  <SortableFilterHeader
                    field="quantity"
                    label="Кол-во"
                    currentSorts={standardSorts}
                    onSortChange={handleStandardSort}
                    values={standardUniqueValues.quantity}
                    selectedValues={standardFilters.quantity}
                    onFilterChange={(field, selected) => setStandardFilters(prev => ({ ...prev, [field]: selected }))}
                  />
                </th>
                {!isReadOnly && <th style={{ textAlign: "left", padding: 8, width: 80 }}></th>}
              </tr>
            </thead>
            <tbody>
              {oneToOneTechcards.map((card: any) => {
                const product = rawItems.find((p) => Number(p.id) === card.product_id);
                return (
                   <tr key={card.id} className="cursor-pointer hover:bg-muted/50" onClick={() => openView(card.id)}>
                    <td style={{ padding: 8, fontWeight: 600, borderTop: "1px solid #f3f4f6" }}>{product?.sku ?? card.product_id}</td>
                    <td style={{ padding: 8, borderTop: "1px solid #f3f4f6" }}>{card.quantity_total ?? "—"}</td>
                    {!isReadOnly && (
                      <td style={{ padding: 8, borderTop: "1px solid #f3f4f6" }}>
                        <button type="button" onClick={(e) => { e.stopPropagation(); confirmDelete({ type: "techcard", id: card.id }); }} className="text-destructive hover:text-destructive/80">
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </td>
                    )}
                  </tr>
                );
              })}
              {oneToOneTechcards.length === 0 && (
                <tr><td colSpan={isReadOnly ? 2 : 3} style={{ padding: 16, textAlign: "center", color: "#9ca3af" }}>Нет стандартных техкарт</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {status ? <div className="text-sm text-muted-foreground">{status}</div> : null}

      {/* Bulk creation dialog */}
      <Dialog open={bulkDialogOpen} onOpenChange={setBulkDialogOpen}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Массовое создание техкарт</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="flex gap-2">
              <Input className="w-52" value={search} placeholder="Поиск" onChange={(e: any) => setSearch(e.target.value)} />
              <Button variant="outline" onClick={selectVisible}>Выбрать видимые</Button>
              <Button variant="outline" onClick={clearSelection}>Сбросить</Button>
            </div>
            <div className="text-sm">Выбрано: {selectedIds.size}</div>
            <div className="border rounded-md overflow-auto max-h-80">
              <table className="w-full text-sm">
                <thead className="bg-muted sticky top-0 z-10">
                  <tr><th className="px-3 py-2 text-left w-8">✓</th><th className="px-3 py-2 text-left">Артикул</th><th className="px-3 py-2 text-left">Статус</th></tr>
                </thead>
                <tbody className="divide-y">
                  {rows
                    .filter((p) => p.is_paired_profile !== true && !techcardByProductId.has(Number(p.id)))
                    .sort((a, b) => {
                      const aHas = techcardByProductId.has(Number(a.id)) ? 1 : 0;
                      const bHas = techcardByProductId.has(Number(b.id)) ? 1 : 0;
                      return aHas - bHas;
                    })
                    .map((product) => {
                      const productId = Number(product.id);
                      const selected = selectedIds.has(productId);
                      const existing = techcardByProductId.get(productId);
                      return (
                        <tr key={productId} className={!selected ? "opacity-60" : ""}>
                          <td className="px-3 py-2">
                            <input type="checkbox" checked={selected} onChange={() => toggleSelect(productId)} />
                          </td>
                          <td className="px-3 py-2 font-medium">{product.sku ?? productId}</td>
                          <td className="px-3 py-2">{existing ? <span className="text-green-700">Есть техкарта</span> : <span className="text-red-600">Нет техкарты</span>}</td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setBulkDialogOpen(false)}>Отмена</Button>
              <Button onClick={applyBulk} disabled={loading || selectedIds.size === 0}>Применить</Button>
            </DialogFooter>
          </div>
        </DialogContent>
      </Dialog>

      {/* Paired creation dialog */}
      <Dialog open={pairedDialogOpen} onOpenChange={setPairedDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Создание парной техкарты</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="flex items-start gap-3">
              <div className="w-48 min-h-[58px]">
                {skuA ? (
                  <>
                    <div className="flex items-center justify-between px-3 py-2 rounded-md border bg-secondary text-secondary-foreground">
                      <span className="text-sm font-medium">{skuA}</span>
                      <button type="button" onClick={() => setSkuA("")} className="text-xs text-muted-foreground hover:text-foreground cursor-pointer">Изменить</button>
                    </div>
                    {(() => {
                      const p = rawItems.find((item) => String(item.sku).toLowerCase() === skuA.trim().toLowerCase());
                      if (p && !p.is_paired_profile) {
                        return <div className="text-[11px] text-amber-600 font-medium mt-1">Непарный (станет парным)</div>;
                      }
                      return null;
                    })()}
                  </>
                ) : (
                  <ProductSearchMulti values={[]} onChange={(v) => { if (v[0]) setSkuA(v[0]); }} excludeValues={skuB ? [skuB] : []} placeholder="Поиск по артикулу" />
                )}
              </div>
              <div className="w-48">
                {differentQuantities ? (
                  <Input type="number" placeholder="—" min={1} value={quantityAPerItem} onChange={(e: any) => setQuantityAPerItem(e.target.value)} />
                ) : skuA && skuB ? (
                  <Input type="number" placeholder="Кол-во каждого" min={1} value={quantityPerItem} onChange={(e: any) => { setQuantityPerItem(e.target.value); setQuantityAPerItem(e.target.value); setQuantityBPerItem(e.target.value); }} />
                ) : <div className="h-10" />}
              </div>
            </div>
            <div className="flex items-start gap-3">
              <div className="w-48 min-h-[58px]">
                {skuB ? (
                  <>
                    <div className="flex items-center justify-between px-3 py-2 rounded-md border bg-secondary text-secondary-foreground">
                      <span className="text-sm font-medium">{skuB}</span>
                      <button type="button" onClick={() => setSkuB("")} className="text-xs text-muted-foreground hover:text-foreground cursor-pointer">Изменить</button>
                    </div>
                    {(() => {
                      const p = rawItems.find((item) => String(item.sku).toLowerCase() === skuB.trim().toLowerCase());
                      if (p && !p.is_paired_profile) {
                        return <div className="text-[11px] text-amber-600 font-medium mt-1">Непарный (станет парным)</div>;
                      }
                      return null;
                    })()}
                  </>
                ) : (
                  <ProductSearchMulti values={[]} onChange={(v) => { if (v[0]) setSkuB(v[0]); }} excludeValues={skuA ? [skuA] : []} placeholder="Поиск по артикулу" />
                )}
              </div>
              <div className="w-48">
                {differentQuantities ? (
                  <Input type="number" placeholder="—" min={1} value={quantityBPerItem} onChange={(e: any) => setQuantityBPerItem(e.target.value)} />
                ) : <div className="h-10" />}
              </div>
            </div>
            <div className="flex items-center justify-between">
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="checkbox" checked={differentQuantities} onChange={(e) => setDifferentQuantities(e.target.checked)} />
                Разное кол-во
              </label>
              {skuA && skuB && (
                <div className="text-sm">
                  Общее: {differentQuantities
                    ? (parseInt(quantityAPerItem) || 0) + (parseInt(quantityBPerItem) || 0)
                    : (parseInt(quantityPerItem) || 0) * 2} шт.
                </div>
              )}
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setPairedDialogOpen(false)}>Отмена</Button>
              <Button onClick={createPairedTechcard} disabled={loading || !skuA.trim() || !skuB.trim()}>
                {pairProfileSku ? `Создать ${pairProfileSku}` : "Создать парную техкарту"}
              </Button>
            </DialogFooter>
          </div>
        </DialogContent>
      </Dialog>

      {/* View/Edit dialog */}
      {viewDetail && (
        <Dialog open={!!viewTechcardId} onOpenChange={(open) => { if (!open) { setViewTechcardId(null); setViewDetail(null); } }}>
          <DialogContent className="max-h-[85vh] overflow-y-auto" onOpenAutoFocus={(e) => e.preventDefault()}>
            <DialogHeader>
              <DialogTitle>
                Техкарта #{viewDetail.id}{viewDetail.product_id === null ? " — парная" : ""}
              </DialogTitle>
            </DialogHeader>
            <div className="space-y-4">
              {viewDetail.product_id === null ? (
                /* Paired techcard edit */
                (() => {
                  const { skuA, skuB } = resolvePairSkus(viewDetail);
                  return (
                    <div className="space-y-3">
                      <div className="flex flex-wrap gap-3">
                        <div>
                          <label className="text-sm font-medium">Артикул {skuA}</label>
                          <div className="w-48 px-3 py-2 rounded-md border bg-muted text-sm">{skuA}</div>
                        </div>
                        <div>
                          <label className="text-sm font-medium">Артикул {skuB}</label>
                          <div className="w-48 px-3 py-2 rounded-md border bg-muted text-sm">{skuB}</div>
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-3">
                        <div>
                          <label className="text-sm font-medium">Общее кол-во</label>
                          <Input className="w-48" type="number" min={1} value={editQuantityTotal} onChange={(e: any) => setEditQuantityTotal(Number(e.target.value || 1))} disabled={isReadOnly} />
                        </div>
                        <>
                          {editDifferentQuantities ? (
                            <>
                              <div>
                                <label className="text-sm font-medium">Кол-во {skuA} на подвес</label>
                                <Input className="w-48" type="number" min={1} value={editQuantityAPerItem} onChange={(e: any) => setEditQuantityAPerItem(Number(e.target.value || 1))} disabled={isReadOnly} />
                              </div>
                              <div>
                                <label className="text-sm font-medium">Кол-во {skuB} на подвес</label>
                                <Input className="w-48" type="number" min={1} value={editQuantityBPerItem} onChange={(e: any) => setEditQuantityBPerItem(Number(e.target.value || 1))} disabled={isReadOnly} />
                              </div>
                            </>
                          ) : (
                            <div>
                              <label className="text-sm font-medium">Кол-во каждого</label>
                              <Input className="w-48" type="number" min={1} value={editQuantityAPerItem} onChange={(e: any) => {
                                const v = Number(e.target.value || 1);
                                setEditQuantityAPerItem(v);
                                setEditQuantityBPerItem(v);
                              }} disabled={isReadOnly} />
                            </div>
                          )}
                          <div className="w-full flex items-center">
                            <label className={cn("flex items-center gap-2 text-sm", isReadOnly ? "cursor-not-allowed opacity-50" : "cursor-pointer")}>
                              <input type="checkbox" checked={editDifferentQuantities} onChange={(e) => setEditDifferentQuantities(e.target.checked)} disabled={isReadOnly} />
                              Разное кол-во
                            </label>
                          </div>
                        </>
                      </div>
                    </div>
                  );
                })()
              ) : (
                /* Standard techcard edit */
                <div className="space-y-3">
                  <div className="flex flex-wrap gap-3">
                    <div>
                      <label className="text-sm font-medium">Артикул</label>
                      <div className="w-48 px-3 py-2 rounded-md border bg-muted text-sm">{rawItems.find((p) => Number(p.id) === viewDetail.product_id)?.sku ?? "—"}</div>
                    </div>
                    <div>
                      <label className="text-sm font-medium">Версия</label>
                      <div className="w-48 px-3 py-2 rounded-md border bg-muted text-sm">v{viewDetail.version}</div>
                    </div>
                  </div>
                  <div>
                    <label className="text-sm font-medium">Общее кол-во</label>
                    <Input className="w-48" type="number" min={1} value={editQuantityTotal} onChange={(e: any) => setEditQuantityTotal(Number(e.target.value || 1))} disabled={isReadOnly} />
                  </div>
                </div>
              )}

              <DialogFooter className="sm:justify-between">
                <div className="flex gap-2">
                  {!isReadOnly && (
                    <Button variant="destructive" onClick={() => confirmDelete({ type: "techcard", id: viewDetail.id })}>
                      <Trash2 className="h-4 w-4 mr-1" />
                      Удалить
                    </Button>
                  )}
                </div>
                <div className="flex gap-2">
                  <Button variant="outline" onClick={() => { setViewTechcardId(null); setViewDetail(null); }}>
                    {isReadOnly ? "Закрыть" : "Отмена"}
                  </Button>
                  {!isReadOnly && <Button onClick={saveTechcard}>Сохранить</Button>}
                </div>
              </DialogFooter>
            </div>
          </DialogContent>
        </Dialog>
      )}

      {/* Delete confirmation */}
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent className="max-w-sm">
          <AlertDialogHeader>
            <AlertDialogTitle>
              {(() => {
                if (!deleteTarget) return "Удалить техкарту?";
                const targetCard = techcards.find((t: any) => t.id === deleteTarget.id);
                if (!targetCard) return `Удалить техкарту #${deleteTarget.id}?`;
                if (targetCard.product_id === null) {
                  const { skuA, skuB } = resolvePairSkus(targetCard);
                  return `Удалить парную техкарту ${skuA} + ${skuB}?`;
                } else {
                  const product = rawItems.find((p) => Number(p.id) === targetCard.product_id);
                  return `Удалить техкарту ${product?.sku ?? `ID ${targetCard.product_id}`}?`;
                }
              })()}
            </AlertDialogTitle>
            <AlertDialogDescription>Это действие нельзя отменить.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter className="flex-col-reverse sm:flex-row gap-2">
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">Удалить</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}
