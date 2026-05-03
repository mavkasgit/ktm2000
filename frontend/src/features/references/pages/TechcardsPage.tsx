import React, { useEffect, useMemo, useState } from "react";
import * as API from "shared/api";
import * as UI from "shared/ui";

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
  const [pairProfileSku, setPairProfileSku] = useState("");
  const [pairProfileName, setPairProfileName] = useState("");

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
        if (!existing) {
          const card = await api.createTechcard({
            product_id: productId,
            version: "A",
            processing_type: processingType,
            is_active: true,
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
          await api.patchTechcard(Number(existing.id), { processing_type: processingType });
          updated += 1;
        }
      }
      setStatus(`Готово: создано ${created}, обновлено ${updated}`);
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
    if (!pairProfileSku.trim() || !pairProfileName.trim()) {
      setStatus("Укажите артикул и название парного профиля");
      return;
    }
    setLoading(true);
    setStatus("Создание парного профиля...");
    try {
      const product = await api.createProduct({
        sku: pairProfileSku.trim(),
        name: pairProfileName.trim(),
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
      setPairProfileSku("");
      setPairProfileName("");
      await loadData();
      clearSelection();
    } catch (e) {
      setStatus(e instanceof Error ? e.message : "Ошибка создания парного профиля");
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

      <div style={{ display: "grid", gap: 8, gridTemplateColumns: "2fr 1fr auto auto auto", alignItems: "center" }}>
        <Input value={search} placeholder="Поиск по артикулу/названию" onChange={(e: any) => setSearch(e.target.value)} />
        <select
          value={processingType}
          onChange={(e: any) => setProcessingType(e.target.value)}
          className="h-10 rounded-md border border-input bg-background px-3 text-sm"
        >
          <option value="standart_processing">standart_processing</option>
          <option value="paired_processing">paired_processing</option>
        </select>
        <Button type="button" variant="outline" onClick={selectVisible}>Выбрать видимые</Button>
        <Button type="button" variant="outline" onClick={clearSelection}>Сбросить</Button>
        <Button type="button" onClick={applyBulk} disabled={loading || selectedIds.size === 0}>
          Применить к выбранным ({selectedIds.size})
        </Button>
      </div>

      {processingType === "paired_processing" && (
        <div style={{ display: "grid", gap: 8, gridTemplateColumns: "2fr 2fr 1fr auto", alignItems: "center" }}>
          <Input placeholder="Артикул парного профиля (например: ЮП-2616+ЮП-2604)" value={pairProfileSku} onChange={(e: any) => setPairProfileSku(e.target.value)} />
          <Input placeholder="Название парного профиля" value={pairProfileName} onChange={(e: any) => setPairProfileName(e.target.value)} />
          <div className="text-sm text-muted-foreground">Выбрано: {selectedIds.size}</div>
          <Button type="button" onClick={createPairedProfile} disabled={loading || selectedIds.size < 2}>
            Создать парный профиль
          </Button>
        </div>
      )}

      {status ? <div>{status}</div> : null}

      <div style={{ border: "1px solid #e5e7eb", borderRadius: 6, overflow: "auto", maxHeight: 520 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "#f9fafb", position: "sticky", top: 0 }}>
              <th style={{ textAlign: "left", padding: 8, width: 40 }}>✓</th>
              <th style={{ textAlign: "left", padding: 8 }}>Артикул</th>
              <th style={{ textAlign: "left", padding: 8 }}>Текущая техкарта</th>
              <th style={{ textAlign: "left", padding: 8 }}>Тип</th>
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
