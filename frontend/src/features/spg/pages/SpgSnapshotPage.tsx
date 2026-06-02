import { useCallback, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import {
  getSpgList,
  getSpgSnapshot,
  listSpgRemainders,
  type SpgOut,
  type SpgSnapshotResponse,
  type SpgRemainder,
} from "@/shared/api/spg";
import { SpgSelector } from "../components/SpgSelector";
import { SpgSnapshotTable } from "../components/SpgSnapshotTable";
import { RemaindersListPanel } from "../components/RemainderEditDialog";
import { ProductRemaindersDialog } from "../components/ProductRemaindersDialog";
import { ManualOperationDialog } from "../components/ManualOperationDialog";

type Tab = "snapshot" | "remainders";

export function SpgSnapshotPage() {
  const [spgs, setSpgs] = useState<SpgOut[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [snapshot, setSnapshot] = useState<SpgSnapshotResponse | null>(null);
  const [remainders, setRemainders] = useState<SpgRemainder[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingSnapshot, setLoadingSnapshot] = useState(false);
  const [loadingRemainders, setLoadingRemainders] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("snapshot");
  const [productRemaindersFor, setProductRemaindersFor] = useState<number | null>(null);
  const [manualOpProductId, setManualOpProductId] = useState<number | null>(null);

  useEffect(() => {
    setLoadingList(true);
    getSpgList()
      .then((items) => {
        setSpgs(items);
        if (items.length > 0 && selectedId === null) {
          setSelectedId(items[0].id);
        }
      })
      .catch(() => setError("Не удалось загрузить список групп"))
      .finally(() => setLoadingList(false));
  }, []);

  const loadSnapshot = useCallback(async (spgId: number) => {
    setLoadingSnapshot(true);
    setError(null);
    try {
      const data = await getSpgSnapshot(spgId);
      setSnapshot(data);
    } catch {
      setError("Не удалось загрузить данные");
      setSnapshot(null);
    } finally {
      setLoadingSnapshot(false);
    }
  }, []);

  const loadRemainders = useCallback(async (spgId: number) => {
    setLoadingRemainders(true);
    try {
      const data = await listSpgRemainders(spgId);
      setRemainders(data);
    } catch {
      // silently fail
    } finally {
      setLoadingRemainders(false);
    }
  }, []);

  useEffect(() => {
    if (selectedId !== null) {
      loadSnapshot(selectedId);
      loadRemainders(selectedId);
    }
  }, [selectedId, loadSnapshot, loadRemainders]);

  const handleRefresh = () => {
    if (selectedId !== null) {
      loadSnapshot(selectedId);
      loadRemainders(selectedId);
    }
  };

  const selectedSpg = spgs.find((s) => s.id === selectedId);

  return (
    <div className="space-y-6 p-4">
      <div>
        <h1 className="text-2xl font-bold">Группы хранения и производства</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Срез данных по остаткам, завершению и текущему состоянию
        </p>
      </div>

      {loadingList ? (
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Загрузка групп...
        </div>
      ) : (
        <SpgSelector spgs={spgs} selectedId={selectedId} onSelect={setSelectedId} />
      )}

      {selectedSpg && (
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold">{selectedSpg.name}</h2>
            {selectedSpg.description && (
              <p className="text-sm text-muted-foreground">{selectedSpg.description}</p>
            )}
          </div>
          <button
            type="button"
            onClick={handleRefresh}
            disabled={loadingSnapshot}
            className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent disabled:opacity-50"
          >
            {loadingSnapshot ? "Обновление..." : "Обновить"}
          </button>
        </div>
      )}

      {error && <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">{error}</div>}

      {/* Tabs */}
      {selectedId !== null && (
        <div className="flex gap-1 border-b">
          <button
            type="button"
            onClick={() => setTab("snapshot")}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === "snapshot"
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            Срез данных
          </button>
          <button
            type="button"
            onClick={() => setTab("remainders")}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === "remainders"
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            Остатки (инвентаризация)
          </button>
        </div>
      )}

      {/* Tab content */}
      {tab === "snapshot" && (
        loadingSnapshot ? (
          <div className="flex items-center gap-2 py-12 text-muted-foreground justify-center">
            <Loader2 className="h-5 w-5 animate-spin" />
            Загрузка данных...
          </div>
        ) : snapshot ? (
          <SpgSnapshotTable
            snapshot={snapshot}
            onShowProductRemainders={setProductRemaindersFor}
          />
        ) : null
      )}

      {tab === "remainders" && selectedSpg && (
        <RemaindersListPanel
          spgId={selectedId!}
          sections={selectedSpg.sections}
          remainders={remainders}
          isLoading={loadingRemainders}
          onRefresh={() => {
            loadRemainders(selectedId!);
            loadSnapshot(selectedId!);
          }}
        />
      )}

      {/* Drill-down dialog from snapshot table */}
      {selectedId !== null && selectedSpg && (
        <ProductRemaindersDialog
          open={productRemaindersFor !== null}
          onOpenChange={(o) => {
            if (!o) setProductRemaindersFor(null);
          }}
          spgId={selectedId}
          productId={productRemaindersFor}
          snapshot={snapshot}
          onManualOperation={(pid) => setManualOpProductId(pid)}
        />
      )}

      {/* Manual stock operation launched from product drill-down */}
      {selectedId !== null && selectedSpg && (
        <ManualOperationDialog
          open={manualOpProductId !== null}
          onOpenChange={(o) => {
            if (!o) setManualOpProductId(null);
          }}
          spgId={selectedId}
          sections={selectedSpg.sections}
          defaultProductId={manualOpProductId}
          onSaved={() => {
            loadSnapshot(selectedId);
            loadRemainders(selectedId);
          }}
        />
      )}
    </div>
  );
}
