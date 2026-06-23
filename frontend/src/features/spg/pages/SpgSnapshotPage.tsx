import { useState, useMemo } from "react";
import { useQuery, useQueries, useQueryClient } from "@tanstack/react-query";
import { Loader2, Search } from "lucide-react";

import {
  getSpgList,
  listSpgRemainders,
  type SpgRemainder,
} from "@/shared/api/spg";
import { SpgSelector } from "../components/SpgSelector";
import { RemaindersListPanel } from "../components/RemainderEditDialog";
import { DefectsListPanel } from "../components/DefectsListPanel";
import { getSpgDefects, type DefectOut } from "@/shared/api/defects";
import { queryKeys } from "@/shared/api/queryKeys";
import { Input } from "@/shared/ui";

export function SpgSnapshotPage() {
  const [selectedSpgIds, setSelectedSpgIds] = useState<number[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const queryClient = useQueryClient();

  const { data: spgs = [], isLoading: loadingList } = useQuery({
    queryKey: queryKeys.spg.all(),
    queryFn: getSpgList,
  });

  const targetSpgIds = useMemo(() => {
    return selectedSpgIds.length > 0 ? selectedSpgIds : spgs.map((s) => s.id);
  }, [selectedSpgIds, spgs]);

  const remaindersQueries = useQueries({
    queries: targetSpgIds.map((id) => ({
      queryKey: queryKeys.spg.remainders(id),
      queryFn: () => listSpgRemainders(id),
      enabled: spgs.length > 0,
    })),
  });

  const defectsQueries = useQueries({
    queries: targetSpgIds.map((id) => ({
      queryKey: queryKeys.spg.defects(id),
      queryFn: () => getSpgDefects(id),
      enabled: spgs.length > 0,
    })),
  });

  const remainders = useMemo(() => {
    return remaindersQueries.flatMap((q) => q.data ?? []);
  }, [remaindersQueries]);

  const defects = useMemo(() => {
    return defectsQueries.flatMap((q) => q.data ?? []);
  }, [defectsQueries]);

  const loadingRemainders = remaindersQueries.some((q) => q.isLoading);
  const loadingDefects = defectsQueries.some((q) => q.isLoading);

  const handleRefresh = () => {
    targetSpgIds.forEach((id) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.remainders(id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.defects(id) });
    });
  };

  const refreshAll = () => {
    targetSpgIds.forEach((id) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.remainders(id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.defects(id) });
    });
  };

  const handleToggleSpg = (id: number) => {
    setSelectedSpgIds((prev) => {
      if (prev.includes(id)) {
        return prev.filter((x) => x !== id);
      } else {
        return [...prev, id];
      }
    });
    setSearchQuery("");
  };

  const handleClearSpg = () => {
    setSelectedSpgIds([]);
    setSearchQuery("");
  };

  const combinedSections = useMemo(() => {
    const selectedSpgs = selectedSpgIds.length > 0
      ? spgs.filter((s) => selectedSpgIds.includes(s.id))
      : spgs;
    return selectedSpgs.flatMap((s) => s.sections);
  }, [spgs, selectedSpgIds]);

  const headerTitle = useMemo(() => {
    if (selectedSpgIds.length === 1) {
      const spg = spgs.find((s) => s.id === selectedSpgIds[0]);
      return spg ? spg.name : "Группа ГХП";
    }
    if (selectedSpgIds.length > 1) {
      return `Выбрано групп: ${selectedSpgIds.length}`;
    }
    return "Все группы ГХП";
  }, [spgs, selectedSpgIds]);

  const headerDescription = useMemo(() => {
    if (selectedSpgIds.length === 1) {
      const spg = spgs.find((s) => s.id === selectedSpgIds[0]);
      return spg?.description || null;
    }
    if (selectedSpgIds.length > 1) {
      return spgs
        .filter((s) => selectedSpgIds.includes(s.id))
        .map((s) => s.name)
        .join(", ");
    }
    return "Отображаются данные по всем участкам завода";
  }, [spgs, selectedSpgIds]);

  return (
    <div className="space-y-6 p-4">
      <div>
        <h1 className="text-2xl font-bold">Группы хранения и производства</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Наличие запасов на участках и зарегистрированный брак
        </p>
      </div>

      {loadingList ? (
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Загрузка групп...
        </div>
      ) : (
        <SpgSelector
          spgs={spgs}
          selectedIds={selectedSpgIds}
          onToggle={handleToggleSpg}
          onSelect={(id) => setSelectedSpgIds([id])}
          onClear={handleClearSpg}
        />
      )}

      {spgs.length > 0 && (
        <div className="flex items-center justify-between border-b pb-4">
          <div>
            <h2 className="text-lg font-semibold">{headerTitle}</h2>
            {headerDescription && (
              <p className="text-sm text-muted-foreground">{headerDescription}</p>
            )}
          </div>
          <button
            type="button"
            onClick={handleRefresh}
            disabled={loadingRemainders || loadingDefects}
            className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent disabled:opacity-50"
          >
            {loadingRemainders || loadingDefects ? "Обновление..." : "Обновить"}
          </button>
        </div>
      )}

      {/* Global Filters Panel */}
      {spgs.length > 0 && (
        <div className="bg-muted/10 p-4 rounded-xl border">
          <div className="relative w-full">
            <Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Глобальный поиск по артикулу или названию..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-background pl-10 h-10"
            />
          </div>
        </div>
      )}

      {/* Panels */}
      {spgs.length > 0 && (
        <div className="space-y-8">
          <div className="bg-background rounded-xl border p-6 shadow-sm">
            <RemaindersListPanel
              spgId={selectedSpgIds.length === 1 ? selectedSpgIds[0] : (spgs[0]?.id || 0)}
              spgs={spgs}
              selectedSpgIds={selectedSpgIds}
              sections={combinedSections}
              remainders={remainders as SpgRemainder[]}
              isLoading={loadingRemainders}
              onRefresh={refreshAll}
              searchQuery={searchQuery}
            />
          </div>

          <div className="bg-background rounded-xl border p-6 shadow-sm">
            <DefectsListPanel
              spgId={selectedSpgIds.length === 1 ? selectedSpgIds[0] : (spgs[0]?.id || 0)}
              spgs={spgs}
              selectedSpgIds={selectedSpgIds}
              sections={combinedSections}
              remainders={remainders as SpgRemainder[]}
              defects={defects as DefectOut[]}
              isLoading={loadingDefects}
              onRefresh={refreshAll}
              searchQuery={searchQuery}
            />
          </div>
        </div>
      )}
    </div>
  );
}
