import React, { useEffect, useMemo, useState } from "react";
import * as API from "shared/api";
import * as UI from "shared/ui";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/shared/ui/Dialog";
import { ProductSearchMulti } from "../components/ProductSearchMulti";

type ProcessingType = "standart_processing" | "paired_processing";

const ui = UI as Record<string, React.ComponentType<any>>;
const Button = ui.Button ?? "button";
const Input = ui.Input ?? "input";

export function TechcardsPage() {
  const api = API as Record<string, any>;
  const [rawItems, setRawItems] = useState<any[]>([]);
  const [techcards, setTechcards] = useState<any[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [processingType, setProcessingType] = useState<ProcessingType>("standart_processing");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("");
  const [selectedTechcardId, setSelectedTechcardId] = useState<number | null>(null);
  const [pairName, setPairName] = useState("");
  const [pairPriority, setPairPriority] = useState(100);
  const [selectedPairId, setSelectedPairId] = useState<number | null>(null);
  const [pairLinesSku, setPairLinesSku] = useState("");
  const [pairLinesQty, setPairLinesQty] = useState(1);
  const [pairDetails, setPairDetails] = useState<any[]>([]);

  const [skuA, setSkuA] = useState("");
  const [skuB, setSkuB] = useState("");
  const [quantityTotal, setQuantityTotal] = useState(1);
  const [quantityPerItem, setQuantityPerItem] = useState<string>("");
  const [quantityAPerItem, setQuantityAPerItem] = useState<string>("");
  const [quantityBPerItem, setQuantityBPerItem] = useState<string>("");
  const [differentQuantities, setDifferentQuantities] = useState(false);
  const [quantityTotalBulk, setQuantityTotalBulk] = useState(1);
  const [pairedDialogOpen, setPairedDialogOpen] = useState(false);
  const [bulkDialogOpen, setBulkDialogOpen] = useState(false);

  const loadData = async () => {
    setLoading(true);
    try {
      const [products, cards] = await Promise.all([
        api.listProducts({ type: "component", limit: 2000 }),
        api.listTechcards(),
      ]);
      setRawItems(products ?? []);
      setTechcards(cards ?? []);
    } catch (e) {
      setStatus(e instanceof Error ? e.message : "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData().catch(() => {});
  }, []);

  const techcardByProductId = useMemo(() => {
    const map = new Map<number, any>();
    for (const card of techcards) {
      if (card.is_active) {
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

  const hangerCalc = useMemo(() => {
    if (!skuA.trim() || !skuB.trim()) return null;
    const qtyA = parseInt(quantityAPerItem) || 1;
    const qtyB = parseInt(quantityBPerItem) || 1;
    const productA = rawItems.find((item) => String(item.sku).toLowerCase() === skuA.trim().toLowerCase());
    const productB = rawItems.find((item) => String(item.sku).toLowerCase() === skuB.trim().toLowerCase());
    if (!productA || !productB) return null;
    const qtyAPerHanger = productA.quantity_per_hanger || 1;
    const qtyBPerHanger = productB.quantity_per_hanger || 1;
    const totalA = quantityTotal * qtyA;
    const totalB = quantityTotal * qtyB;
    const hangersA = Math.ceil(totalA / qtyAPerHanger);
    const hangersB = Math.ceil(totalB / qtyBPerHanger);
    return {
      productA,
      productB,
      qtyAPerHanger,
      qtyBPerHanger,
      totalA,
      totalB,
      hangersA,
      hangersB,
      hangersTotal: hangersA + hangersB,
    };
  }, [skuA, skuB, rawItems, quantityTotal, quantityAPerItem, quantityBPerItem]);

  const { pairProfileSku, pairProfileName } = useMemo(() => {
    const a = skuA.trim();
    const b = skuB.trim();
    if (!a || !b) return { pairProfileSku: "", pairProfileName: "" };
    const sorted = [a, b].sort();
    return {
      pairProfileSku: sorted.join("+"),
      pairProfileName: sorted.join(" + "),
    };
  }, [skuA, skuB]);

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
        const qtyPerHanger = product?.quantity_per_hanger || 1;
        const hangersTotal = processingType === "standart_processing" ? Math.ceil(quantityTotalBulk / qtyPerHanger) : null;
        if (!existing) {
          const card = await api.createTechcard({
            product_id: productId,
            version: "A",
            processing_type: processingType,
            is_active: true,
            quantity_total: processingType === "standart_processing" ? quantityTotalBulk : null,
            hangers_total: hangersTotal,
          });
          if (processingType === "standart_processing") {
            await api.createTechcardLine(Number(card.id), {
              component_product_id: productId,
              quantity: 1,
              unit: "pcs",
            });
          }
          created += 1;
        } else {
          await api.patchTechcard(Number(existing.id), {
            processing_type: processingType,
            quantity_total: processingType === "standart_processing" ? quantityTotalBulk : null,
            hangers_total: hangersTotal,
          });
          updated += 1;
        }
      }
      setStatus(`Готово: создано ${created}, обновлено ${updated}`);
      setBulkDialogOpen(false);
      await loadData();
      clearSelection();
    } catch (e) {
      setStatus(e instanceof Error ? e.message : "Ошибка обработки");
    } finally {
      setLoading(false);
    }
  };

  const createPairedProfile = async () => {
    if (selectedIds.size < 2) {
      setStatus("Выберите минимум 2 артикула сырья");
      return;
    }
    const selectedSkus = Array.from(selectedIds)
      .map((id) => rawItems.find((i) => Number(i.id) === id)?.sku)
      .filter(Boolean)
      .sort() as string[];
    const generatedSku = selectedSkus.join("+");
    const generatedName = selectedSkus.join(" + ");
    setLoading(true);
    setStatus("Создание парного профиля...");
    try {
      const product = await api.createProduct({
        sku: generatedSku,
        name: generatedName,
        type: "component",
        is_paired_profile: true,
      });
      const card = await api.createTechcard({
        product_id: product.id,
        version: "A",
        processing_type: "paired_processing",
        is_active: true,
      });
      const pair = await api.createTechcardPair(Number(card.id), {
        name: "Базовая",
        priority: 100,
        is_active: true,
      });
      for (const productId of selectedIds) {
        await api.createTechcardPairLine(Number(card.id), Number(pair.id), {
          component_product_id: Number(productId),
          quantity: 1,
          unit: "pcs",
        });
      }
      setStatus(`Парный профиль создан: ${product.sku} (#${card.id})`);
      setBulkDialogOpen(false);
      await loadData();
      clearSelection();
    } catch (e) {
      setStatus(e instanceof Error ? e.message : "Ошибка создания парного профиля");
    } finally {
      setLoading(false);
    }
  };

  const createPairedTechcard = async () => {
    if (!skuA.trim() || !skuB.trim()) {
      setStatus("Выберите 2 артикула профиля");
      return;
    }
    const productA = rawItems.find((item) => String(item.sku).toLowerCase() === skuA.trim().toLowerCase());
    const productB = rawItems.find((item) => String(item.sku).toLowerCase() === skuB.trim().toLowerCase());
    if (!productA || !productB) {
      setStatus("Один или оба артикула не найдены");
      return;
    }
    if (productA.id === productB.id) {
      setStatus("Артикулы должны быть разными");
      return;
    }
    setLoading(true);
    setStatus("Создание парной техкарты...");
    try {
      const card = await api.createTechcard({
        product_id: null,
        version: "A",
        processing_type: "paired_processing",
        is_active: true,
        quantity_total: quantityTotal,
        quantity_a_per_item: parseInt(quantityAPerItem) || 1,
        quantity_b_per_item: parseInt(quantityBPerItem) || 1,
        hangers_a: hangerCalc?.hangersA ?? null,
        hangers_b: hangerCalc?.hangersB ?? null,
        hangers_total: hangerCalc?.hangersTotal ?? null,
      });
      const pair = await api.createTechcardPair(Number(card.id), {
        name: "Базовая",
        priority: 100,
        is_active: true,
      });
      await api.createTechcardPairLine(Number(card.id), Number(pair.id), {
        component_product_id: Number(productA.id),
        quantity: parseInt(quantityAPerItem) || 1,
        unit: "pcs",
      });
      await api.createTechcardPairLine(Number(card.id), Number(pair.id), {
        component_product_id: Number(productB.id),
        quantity: parseInt(quantityBPerItem) || 1,
        unit: "pcs",
      });
      setStatus(`Парная техкарта создана: ${pairProfileSku} (#${card.id}), общее кол-во: ${quantityTotal}`);
      setSkuA("");
      setSkuB("");
      setQuantityTotal(1);
      setQuantityPerItem("");
      setQuantityAPerItem("");
      setQuantityBPerItem("");
      setDifferentQuantities(false);
      setPairedDialogOpen(false);
      await loadData();
    } catch (e) {
      setStatus(e instanceof Error ? e.message : "Ошибка создания парной техкарты");
    } finally {
      setLoading(false);
    }
  };

  const openPairs = async (techcardId: number) => {
    setSelectedTechcardId(techcardId);
    setSelectedPairId(null);
    setPairDetails([]);
    const detail = await api.getTechcard(techcardId);
    const pairs = detail.techcard_pairs ?? [];
    const full = await Promise.all(pairs.map((p: any) => api.getTechcardPair(techcardId, Number(p.id))));
    setPairDetails(full);
  };

  const createPair = async () => {
    if (!selectedTechcardId || !pairName.trim()) return;
    await api.createTechcardPair(selectedTechcardId, { name: pairName.trim(), priority: pairPriority, is_active: true });
    setPairName("");
    await openPairs(selectedTechcardId);
  };

  const addPairLine = async () => {
    if (!selectedTechcardId || !selectedPairId || !pairLinesSku.trim()) return;
    const found = rawItems.find((item) => String(item.sku).toLowerCase() === pairLinesSku.trim().toLowerCase());
    if (!found) {
      setStatus(`Сырье не найдено: ${pairLinesSku}`);
      return;
    }
    await api.createTechcardPairLine(selectedTechcardId, selectedPairId, {
      component_product_id: Number(found.id),
      quantity: pairLinesQty,
      unit: "pcs",
    });
    setPairLinesSku("");
    setPairLinesQty(1);
    await openPairs(selectedTechcardId);
  };

  return (
    <section style={{ display: "grid", gap: 12 }}>
      <h2 className="text-lg font-semibold">Техкарты: массовое назначение</h2>

      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <Input className="w-52" value={search} placeholder="Поиск по артикулу/названию" onChange={(e: any) => setSearch(e.target.value)} />
        <Button type="button" variant="outline" onClick={selectVisible}>Выбрать видимые</Button>
        <Button type="button" variant="outline" onClick={clearSelection}>Сбросить</Button>
        <Button type="button" disabled={selectedIds.size === 0} onClick={() => setBulkDialogOpen(true)}>
          Массовое назначение ({selectedIds.size})
        </Button>
      </div>

      <Dialog open={bulkDialogOpen} onOpenChange={setBulkDialogOpen}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Массовое назначение техкарт</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-sm font-medium">Тип обработки</label>
                <select
                  value={processingType}
                  onChange={(e: any) => setProcessingType(e.target.value)}
                  className="h-10 w-52 rounded-md border border-input bg-background px-3 text-sm"
                >
                  <option value="standart_processing">standart_processing</option>
                  <option value="paired_processing">paired_processing</option>
                </select>
              </div>
              {processingType === "standart_processing" && (
                <div className="space-y-1">
                  <label className="text-sm font-medium">Общее кол-во</label>
                  <Input className="w-52" type="number" placeholder="Общее кол-во" min={1} value={quantityTotalBulk} onChange={(e: any) => setQuantityTotalBulk(Number(e.target.value || 1))} />
                </div>
              )}
            </div>

            <div className="text-sm font-medium">Будет создано/обновлено:</div>
            <div className="border rounded-md overflow-auto max-h-60">
              <table className="w-full text-sm">
                <thead className="bg-muted sticky top-0">
                  <tr>
                    <th className="px-3 py-2 text-left">Артикул</th>
                    <th className="px-3 py-2 text-left">Действие</th>
                    <th className="px-3 py-2 text-left">Тип</th>
                    <th className="px-3 py-2 text-left">Кол-во</th>
                    <th className="px-3 py-2 text-left">Подвесы</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {Array.from(selectedIds).map((productId) => {
                    const product = rawItems.find((item) => Number(item.id) === productId);
                    const existing = techcardByProductId.get(productId);
                    const qtyPerHanger = product?.quantity_per_hanger || 1;
                    const hangersTotal = processingType === "standart_processing" ? Math.ceil(quantityTotalBulk / qtyPerHanger) : null;
                    return (
                      <tr key={productId}>
                        <td className="px-3 py-2 font-medium">{product?.sku ?? productId}</td>
                        <td className="px-3 py-2">{existing ? "Обновление" : "Создание"}</td>
                        <td className="px-3 py-2">{processingType}</td>
                        <td className="px-3 py-2">{processingType === "standart_processing" ? quantityTotalBulk : "—"}</td>
                        <td className="px-3 py-2">{hangersTotal ?? "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {processingType === "paired_processing" && selectedIds.size >= 2 && (
              <div className="text-sm text-muted-foreground">
                Парный профиль: <span className="font-medium">{Array.from(selectedIds).map((id) => rawItems.find((i) => Number(i.id) === id)?.sku).filter(Boolean).sort().join(" + ")}</span>
              </div>
            )}

            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => setBulkDialogOpen(false)}>Отмена</Button>
              {processingType === "paired_processing" ? (
                <Button type="button" onClick={createPairedProfile} disabled={loading || selectedIds.size < 2}>
                  Создать парный профиль
                </Button>
              ) : (
                <Button type="button" onClick={applyBulk} disabled={loading || selectedIds.size === 0}>
                  Применить
                </Button>
              )}
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <div>
        <Button type="button" variant="outline" onClick={() => setPairedDialogOpen(true)}>
          Создать парную техкарту
        </Button>
      </div>

      <Dialog open={pairedDialogOpen} onOpenChange={setPairedDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Создание парной техкарты</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            {/* Row 1: SKU A + qty 1 */}
            <div className="flex items-center gap-3">
              <div className="w-48">
                {skuA ? (
                  <div className="flex items-center justify-between px-3 py-2 rounded-md border border-input bg-secondary text-secondary-foreground">
                    <span className="text-sm font-medium">{skuA}</span>
                    <button type="button" onClick={() => setSkuA("")} className="text-xs text-muted-foreground hover:text-foreground cursor-pointer">
                      Изменить
                    </button>
                  </div>
                ) : (
                  <ProductSearchMulti
                    values={[]}
                    onChange={(v) => { if (v[0]) setSkuA(v[0]); }}
                    excludeValues={skuB ? [skuB] : []}
                    pairedOnly
                    placeholder="Поиск по артикулу"
                  />
                )}
              </div>
              <div className="w-48">
                {differentQuantities ? (
                  <div className="relative">
                    <Input type="number" className="w-48 pr-6" placeholder="—" min={1} value={quantityAPerItem} onChange={(e: any) => setQuantityAPerItem(e.target.value)} />
                    {quantityAPerItem && (
                      <button type="button" onClick={() => setQuantityAPerItem("")} className="absolute right-1 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground cursor-pointer text-xs">
                        ×
                      </button>
                    )}
                  </div>
                ) : skuA && skuB ? (
                  <div className="relative">
                    <Input type="number" className="w-48 pr-6" placeholder="Кол-во каждого" min={1} value={quantityPerItem} onChange={(e: any) => {
                      setQuantityPerItem(e.target.value);
                      setQuantityAPerItem(e.target.value);
                      setQuantityBPerItem(e.target.value);
                    }} />
                    {quantityPerItem && (
                      <button type="button" onClick={() => {
                        setQuantityPerItem("");
                        setQuantityAPerItem("");
                        setQuantityBPerItem("");
                      }} className="absolute right-1 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground cursor-pointer text-xs">
                        ×
                      </button>
                    )}
                  </div>
                ) : (
                  <div className="w-48 h-10" />
                )}
              </div>
            </div>

            {/* Row 2: SKU B + qty 2 */}
            <div className="flex items-center gap-3">
              <div className="w-48">
                {skuB ? (
                  <div className="flex items-center justify-between px-3 py-2 rounded-md border border-input bg-secondary text-secondary-foreground">
                    <span className="text-sm font-medium">{skuB}</span>
                    <button type="button" onClick={() => setSkuB("")} className="text-xs text-muted-foreground hover:text-foreground cursor-pointer">
                      Изменить
                    </button>
                  </div>
                ) : (
                  <ProductSearchMulti
                    values={[]}
                    onChange={(v) => { if (v[0]) setSkuB(v[0]); }}
                    excludeValues={skuA ? [skuA] : []}
                    pairedOnly
                    placeholder="Поиск по артикулу"
                  />
                )}
              </div>
              <div className="w-48">
                {differentQuantities ? (
                  <div className="relative">
                    <Input type="number" className="w-48 pr-6" placeholder="—" min={1} value={quantityBPerItem} onChange={(e: any) => setQuantityBPerItem(e.target.value)} />
                    {quantityBPerItem && (
                      <button type="button" onClick={() => setQuantityBPerItem("")} className="absolute right-1 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground cursor-pointer text-xs">
                        ×
                      </button>
                    )}
                  </div>
                ) : (
                  <div className="w-48 h-10" />
                )}
              </div>
            </div>

            {/* Checkbox + total */}
            <div className="flex items-center justify-between">
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="checkbox" checked={differentQuantities} onChange={(e) => setDifferentQuantities(e.target.checked)} />
                Разное кол-во
              </label>
              {skuA && skuB && quantityAPerItem && quantityBPerItem && (
                <div className="text-sm">
                  {(parseInt(quantityAPerItem) || 1) + (parseInt(quantityBPerItem) || 1)} шт/подв.
                </div>
              )}
            </div>

            {/* Create button */}
            <div className="flex justify-end">
              <Button type="button" onClick={createPairedTechcard} disabled={loading || !skuA.trim() || !skuB.trim()}>
                {pairProfileSku ? `Создать ${pairProfileSku}` : "Создать парную техкарту"}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {status ? <div>{status}</div> : null}

      <div style={{ border: "1px solid #e5e7eb", borderRadius: 6, overflow: "auto", maxHeight: 520 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "#f9fafb", position: "sticky", top: 0 }}>
              <th style={{ textAlign: "left", padding: 8, width: 40 }}>✓</th>
              <th style={{ textAlign: "left", padding: 8 }}>Артикул</th>
              <th style={{ textAlign: "left", padding: 8 }}>Текущая техкарта</th>
              <th style={{ textAlign: "left", padding: 8 }}>Тип</th>
              <th style={{ textAlign: "left", padding: 8 }}>Кол-во</th>
              <th style={{ textAlign: "left", padding: 8 }}>Парный профиль</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((item) => {
              const id = Number(item.id);
              const card = techcardByProductId.get(id);
              return (
                <tr key={id}>
                  <td style={{ padding: 8, borderTop: "1px solid #f3f4f6" }}>
                    <input type="checkbox" checked={selectedIds.has(id)} onChange={() => toggleSelect(id)} />
                  </td>
                  <td style={{ padding: 8, borderTop: "1px solid #f3f4f6", fontWeight: 600 }}>{item.sku}</td>
                  <td style={{ padding: 8, borderTop: "1px solid #f3f4f6" }}>{card ? `#${card.id} / v${card.version}` : "—"}</td>
                  <td style={{ padding: 8, borderTop: "1px solid #f3f4f6" }}>{card?.processing_type ?? "—"}</td>
                  <td style={{ padding: 8, borderTop: "1px solid #f3f4f6" }}>
                    {card?.quantity_total != null
                      ? `${card.quantity_total} шт. (${card.hangers_total ?? "?"} подв.)`
                      : "—"}
                  </td>
                  <td style={{ padding: 8, borderTop: "1px solid #f3f4f6" }}>
                    {card?.processing_type === "paired_processing" ? (
                      <Button type="button" variant="outline" onClick={() => openPairs(Number(card.id))}>Открыть пары</Button>
                    ) : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {selectedTechcardId ? (
        <div style={{ border: "1px solid #e5e7eb", borderRadius: 8, padding: 12, display: "grid", gap: 8 }}>
          <h3 className="text-base font-semibold">Парный профиль (techcard_pair) для техкарты #{selectedTechcardId}</h3>
          <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr auto", gap: 8 }}>
            <Input placeholder="Название пары" value={pairName} onChange={(e: any) => setPairName(e.target.value)} />
            <Input type="number" value={pairPriority} onChange={(e: any) => setPairPriority(Number(e.target.value || 100))} />
            <Button type="button" onClick={createPair}>Создать пару</Button>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div>
              <div className="mb-2 font-medium">Список пар</div>
              <div style={{ display: "grid", gap: 6 }}>
                {pairDetails.map((pair) => (
                  <button
                    key={pair.id}
                    type="button"
                    onClick={() => setSelectedPairId(Number(pair.id))}
                    style={{ textAlign: "left", padding: 8, border: "1px solid #e5e7eb", borderRadius: 6, background: selectedPairId === pair.id ? "#eef2ff" : "#fff" }}
                  >
                    {pair.name} (prio {pair.priority}) - входов: {pair.lines?.length ?? 0}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <div className="mb-2 font-medium">Добавить артикул в пару</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 120px auto", gap: 8 }}>
                <Input placeholder="Артикул сырья" value={pairLinesSku} onChange={(e: any) => setPairLinesSku(e.target.value)} />
                <Input type="number" min={1} value={pairLinesQty} onChange={(e: any) => setPairLinesQty(Number(e.target.value || 1))} />
                <Button type="button" onClick={addPairLine} disabled={!selectedPairId}>Добавить</Button>
              </div>
              <div style={{ marginTop: 8 }}>
                {(pairDetails.find((p) => Number(p.id) === selectedPairId)?.lines ?? []).map((line: any) => {
                  const product = rawItems.find((item) => Number(item.id) === Number(line.component_product_id));
                  return (
                    <div key={line.id} style={{ fontSize: 13 }}>
                      {product?.sku ?? line.component_product_id}: {line.quantity} {line.unit}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
