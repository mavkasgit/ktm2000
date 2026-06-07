import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
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
import { DefectsListPanel } from "../components/DefectsListPanel";
import { getSpgDefects, type DefectOut } from "@/shared/api/defects";
import { queryKeys } from "@/shared/api/queryKeys";

type Tab = "snapshot" | "remainders" | "defects";

export function SpgSnapshotPage() {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [tab, setTab] = useState<Tab>("snapshot");
  const [productRemaindersFor, setProductRemaindersFor] = useState<number | null>(null);
  const [manualOpProductId, setManualOpProductId] = useState<number | null>(null);
  const queryClient = useQueryClient();

  const { data: spgs = [], isLoading: loadingList } = useQuery({
    queryKey: queryKeys.spg.all(),
    queryFn: getSpgList,
  });

  const effectiveSpgId = selectedId ?? spgs[0]?.id ?? null;

  const { data: snapshot = null, isLoading: loadingSnapshot } = useQuery({
    queryKey: effectiveSpgId ? queryKeys.spg.snapshot(effectiveSpgId) : ["spg-snapshot", "none"],
    queryFn: () => getSpgSnapshot(effectiveSpgId as number),
    enabled: effectiveSpgId !== null,
  });

  const { data: remainders = [], isLoading: loadingRemainders } = useQuery({
    queryKey: effectiveSpgId ? queryKeys.spg.remainders(effectiveSpgId) : ["spg-remainders", "none"],
    queryFn: () => listSpgRemainders(effectiveSpgId as number),
    enabled: effectiveSpgId !== null,
  });

  const { data: defects = [], isLoading: loadingDefects } = useQuery({
    queryKey: effectiveSpgId ? queryKeys.spg.defects(effectiveSpgId) : ["spg-defects", "none"],
    queryFn: () => getSpgDefects(effectiveSpgId as number),
    enabled: effectiveSpgId !== null,
  });

  const handleRefresh = () => {
    if (effectiveSpgId === null) return;
    void queryClient.invalidateQueries({ queryKey: queryKeys.spg.snapshot(effectiveSpgId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.spg.remainders(effectiveSpgId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.spg.defects(effectiveSpgId) });
  };

  const refreshAll = () => {
    if (effectiveSpgId === null) return;
    void queryClient.invalidateQueries({ queryKey: queryKeys.spg.snapshot(effectiveSpgId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.spg.remainders(effectiveSpgId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.spg.defects(effectiveSpgId) });
  };

  const selectedSpg: SpgOut | undefined = spgs.find((s) => s.id === effectiveSpgId);

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
        <SpgSelector spgs={spgs} selectedId={effectiveSpgId} onSelect={setSelectedId} />
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

      {/* Tabs */}
      {effectiveSpgId !== null && (
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
            Остатки
          </button>
          <button
            type="button"
            onClick={() => setTab("defects")}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === "defects"
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            Брак (дефекты)
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
            snapshot={snapshot as SpgSnapshotResponse}
            onShowProductRemainders={setProductRemaindersFor}
          />
        ) : null
      )}

      {tab === "remainders" && selectedSpg && effectiveSpgId !== null && (
        <RemaindersListPanel
          spgId={effectiveSpgId}
          sections={selectedSpg.sections}
          remainders={remainders as SpgRemainder[]}
          isLoading={loadingRemainders}
          onRefresh={refreshAll}
        />
      )}

      {tab === "defects" && selectedSpg && effectiveSpgId !== null && (
        <DefectsListPanel
          spgId={effectiveSpgId}
          sections={selectedSpg.sections}
          remainders={remainders as SpgRemainder[]}
          defects={defects as DefectOut[]}
          isLoading={loadingDefects}
          onRefresh={refreshAll}
        />
      )}

      {/* Drill-down dialog from snapshot table */}
      {effectiveSpgId !== null && selectedSpg && (
        <ProductRemaindersDialog
          open={productRemaindersFor !== null}
          onOpenChange={(o) => {
            if (!o) setProductRemaindersFor(null);
          }}
          spgId={effectiveSpgId}
          productId={productRemaindersFor}
          snapshot={snapshot as SpgSnapshotResponse | null}
          onManualOperation={(pid) => setManualOpProductId(pid)}
        />
      )}

      {/* Manual stock operation launched from product drill-down */}
      {effectiveSpgId !== null && selectedSpg && (
        <ManualOperationDialog
          open={manualOpProductId !== null}
          onOpenChange={(o) => {
            if (!o) setManualOpProductId(null);
          }}
          spgId={effectiveSpgId}
          sections={selectedSpg.sections}
          defaultProductId={manualOpProductId}
          onSaved={refreshAll}
        />
      )}
    </div>
  );
}
