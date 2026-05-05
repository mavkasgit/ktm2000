import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import * as API from "shared/api";
import * as UI from "shared/ui";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/shared/ui/Dialog";
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogCancel, AlertDialogAction } from "@/shared/ui/AlertDialog";
import { ProductSearchMulti } from "../components/ProductSearchMulti";
import { toast } from "@/shared/ui/use-toast";
import { getErrorMessage } from "@/shared/api/client";

type ProcessingType = "standart_processing" | "paired_processing";

const ui = UI as Record<string, React.ComponentType<any>>;
const Button = ui.Button ?? "button";
const Input = ui.Input ?? "input";

export function TechcardsPage() {
  const api = API as Record<string, any>;
  const [rawItems, setRawItems] = useState<any[]>([]);
  const [techcards, setTechcards] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("");

  // Visibility toggles
  const [showOneToOne, setShowOneToOne] = useState(false);

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

  // Derived data
  const pairedTechcards = useMemo(() => techcards.filter((t: any) => t.product_id === null && t.processing_type === "paired_processing"), [techcards]);
  const oneToOneTechcards = useMemo(() => techcards.filter((t: any) => t.product_id !== null), [techcards]);

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
      const isPaired = viewDetail?.product_id === null;
      const detail = isPaired ? `парная (${resolvePairSkus(viewDetail).skuA}+${resolvePairSkus(viewDetail).skuB})` : `стандартная (артикул: ${rawItems.find((p) => Number(p.id) === viewDetail?.product_id)?.sku ?? "—"}`;
      await api.deleteTechcard(deleteTarget.id);
      toast({ title: "Удалено", description: `Техкарта #${deleteTarget.id} (${detail}, версия: ${viewDetail?.version ?? "—"}) успешно удалена`, variant: "success" });
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
    if (!productA.is_paired_profile || !productB.is_paired_profile) {
      const nonPair = [];
      if (!productA.is_paired_profile) nonPair.push(productA.sku);
      if (!productB.is_paired_profile) nonPair.push(productB.sku);
      toast({ title: "Непарные профили", description: `Следующие артикулы не являются парными профилями: ${nonPair.join(", ")}`, variant: "destructive" });
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

  const resolvePairSkus = (detail: any): { skuA: string; skuB: string } => {
    const lines = detail?.lines ?? [];
    const skus = lines.map((l: any) => {
      const product = rawItems.find((p) => Number(p.id) === Number(l.component_product_id));
      return product?.sku ?? String(l.component_product_id);
    });
    return { skuA: skus[0] ?? "—", skuB: skus[1] ?? "—" };
  };

  return (
    <section style={{ display: "grid", gap: 16 }}>
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Техкарты</h2>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => setBulkDialogOpen(true)}>
            <Plus className="h-4 w-4 mr-1" />
            Массовое создание
          </Button>
          <Button size="sm" variant="outline" onClick={() => setPairedDialogOpen(true)}>
            <Plus className="h-4 w-4 mr-1" />
            Создать парную
          </Button>
          <Button size="sm" variant="outline" onClick={() => setShowOneToOne(!showOneToOne)}>
            {showOneToOne ? "Скрыть стандартные" : "Показать стандартные"}
          </Button>
        </div>
      </div>

      {/* Paired techcards table */}
      <div>
        <h3 className="text-sm font-medium text-muted-foreground mb-2">Парные техкарты</h3>
        <div style={{ border: "1px solid #e5e7eb", borderRadius: 6, overflow: "auto", maxHeight: 400 }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ background: "#f9fafb", position: "sticky", top: 0 }}>
                <th style={{ textAlign: "left", padding: 8 }}>Парный артикул</th>
                <th style={{ textAlign: "left", padding: 8 }}>Кол-во</th>
                <th style={{ textAlign: "left", padding: 8, width: 80 }}></th>
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
                    <td style={{ padding: 8, borderTop: "1px solid #f3f4f6" }}>
                      <button type="button" onClick={(e) => { e.stopPropagation(); confirmDelete({ type: "techcard", id: card.id }); }} className="text-destructive hover:text-destructive/80">
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </td>
                  </tr>
                );
              })}
              {pairedTechcards.length === 0 && (
                <tr><td colSpan={3} style={{ padding: 16, textAlign: "center", color: "#9ca3af" }}>Нет парных техкарт</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* 1:1 techcards table (hidden by default) */}
      {showOneToOne && (
        <div>
          <h3 className="text-sm font-medium text-muted-foreground mb-2">Стандартные техкарты</h3>
          <div style={{ border: "1px solid #e5e7eb", borderRadius: 6, overflow: "auto", maxHeight: 400 }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ background: "#f9fafb", position: "sticky", top: 0 }}>
                  <th style={{ textAlign: "left", padding: 8 }}>Артикул</th>
                  <th style={{ textAlign: "left", padding: 8 }}>Кол-во</th>
                  <th style={{ textAlign: "left", padding: 8, width: 80 }}></th>
                </tr>
              </thead>
              <tbody>
                {oneToOneTechcards.map((card: any) => {
                  const product = rawItems.find((p) => Number(p.id) === card.product_id);
                  return (
                    <tr key={card.id} className="cursor-pointer hover:bg-muted/50" onClick={() => openView(card.id)}>
                      <td style={{ padding: 8, fontWeight: 600, borderTop: "1px solid #f3f4f6" }}>{product?.sku ?? card.product_id}</td>
                      <td style={{ padding: 8, borderTop: "1px solid #f3f4f6" }}>{card.quantity_total ?? "—"}</td>
                      <td style={{ padding: 8, borderTop: "1px solid #f3f4f6" }}>
                        <button type="button" onClick={(e) => { e.stopPropagation(); confirmDelete({ type: "techcard", id: card.id }); }} className="text-destructive hover:text-destructive/80">
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </td>
                    </tr>
                  );
                })}
                {oneToOneTechcards.length === 0 && (
                  <tr><td colSpan={3} style={{ padding: 16, textAlign: "center", color: "#9ca3af" }}>Нет 1:1 техкарт</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

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
                    .filter((p) => p.is_paired_profile !== true)
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
            <div className="flex items-center gap-3">
              <div className="w-48">
                {skuA ? (
                  <div className="flex items-center justify-between px-3 py-2 rounded-md border bg-secondary text-secondary-foreground">
                    <span className="text-sm font-medium">{skuA}</span>
                    <button type="button" onClick={() => setSkuA("")} className="text-xs text-muted-foreground hover:text-foreground cursor-pointer">Изменить</button>
                  </div>
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
            <div className="flex items-center gap-3">
              <div className="w-48">
                {skuB ? (
                  <div className="flex items-center justify-between px-3 py-2 rounded-md border bg-secondary text-secondary-foreground">
                    <span className="text-sm font-medium">{skuB}</span>
                    <button type="button" onClick={() => setSkuB("")} className="text-xs text-muted-foreground hover:text-foreground cursor-pointer">Изменить</button>
                  </div>
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
                          <Input className="w-48" type="number" min={1} value={editQuantityTotal} onChange={(e: any) => setEditQuantityTotal(Number(e.target.value || 1))} />
                        </div>
                        <>
                          {editDifferentQuantities ? (
                            <>
                              <div>
                                <label className="text-sm font-medium">Кол-во {skuA} на подвес</label>
                                <Input className="w-48" type="number" min={1} value={editQuantityAPerItem} onChange={(e: any) => setEditQuantityAPerItem(Number(e.target.value || 1))} />
                              </div>
                              <div>
                                <label className="text-sm font-medium">Кол-во {skuB} на подвес</label>
                                <Input className="w-48" type="number" min={1} value={editQuantityBPerItem} onChange={(e: any) => setEditQuantityBPerItem(Number(e.target.value || 1))} />
                              </div>
                            </>
                          ) : (
                            <div>
                              <label className="text-sm font-medium">Кол-во каждого</label>
                              <Input className="w-48" type="number" min={1} value={editQuantityAPerItem} onChange={(e: any) => {
                                const v = Number(e.target.value || 1);
                                setEditQuantityAPerItem(v);
                                setEditQuantityBPerItem(v);
                              }} />
                            </div>
                          )}
                          <div className="w-full flex items-center">
                            <label className="flex items-center gap-2 text-sm cursor-pointer">
                              <input type="checkbox" checked={editDifferentQuantities} onChange={(e) => setEditDifferentQuantities(e.target.checked)} />
                              Разное кол-во
                            </label>
                          </div>
                        </>
                      </div>
                    </div>
                  );
                })()
              ) : (
                /* 1:1 techcard edit */
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
                    <Input className="w-48" type="number" min={1} value={editQuantityTotal} onChange={(e: any) => setEditQuantityTotal(Number(e.target.value || 1))} />
                  </div>
                </div>
              )}

              <DialogFooter className="sm:justify-between">
                <div className="flex gap-2">
                  <Button variant="destructive" onClick={() => confirmDelete({ type: "techcard", id: viewDetail.id })}>
                    <Trash2 className="h-4 w-4 mr-1" />
                    Удалить
                  </Button>
                </div>
                <div className="flex gap-2">
                  <Button variant="outline" onClick={() => { setViewTechcardId(null); setViewDetail(null); }}>Отмена</Button>
                  <Button onClick={saveTechcard}>Сохранить</Button>
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
              {`Удалить техкарту #${deleteTarget?.id}?`}
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
