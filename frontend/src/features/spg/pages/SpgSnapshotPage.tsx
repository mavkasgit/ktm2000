import { useState, useMemo } from "react";
import { useQuery, useQueries, useQueryClient } from "@tanstack/react-query";
import { Loader2, Search, Layers, Warehouse, Factory } from "lucide-react";

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
import { Input, renderIcon, Badge } from "@/shared/ui";

const STOCK_KINDS = new Set(["raw_stock", "wip_stock", "finished_stock"]);

type SpgPanelGroup = {
  spgId: number | "no-spg";
  spgName: string;
  spgIcon: string | null;
  spgIconColor: string | null;
  sections: {
    stocks: number[];
    productions: number[];
  };
  stocksRemainders: SpgRemainder[];
  prodRemainders: SpgRemainder[];
  stocksDefects: DefectOut[];
  prodDefects: DefectOut[];
};

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

  const refreshAll = handleRefresh;

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

  const sectionKindById = useMemo(() => {
    const map = new Map<number, string>();
    spgs.forEach((spg) => {
      spg.sections.forEach((sec) => {
        if (sec.kind) map.set(sec.section_id, sec.kind);
      });
    });
    return map;
  }, [spgs]);

  const sectionToSpgId = useMemo(() => {
    const map = new Map<number, number>();
    spgs.forEach((spg) => {
      spg.sections.forEach((sec) => {
        map.set(sec.section_id, spg.id);
      });
    });
    return map;
  }, [spgs]);

  const groups = useMemo<SpgPanelGroup[]>(() => {
    const spgGroups: Record<string | number, SpgPanelGroup> = {};
    const activeSpgs = selectedSpgIds.length > 0
      ? spgs.filter((s) => selectedSpgIds.includes(s.id))
      : spgs;

    activeSpgs.forEach((spg) => {
      spgGroups[spg.id] = {
        spgId: spg.id,
        spgName: spg.name,
        spgIcon: spg.icon,
        spgIconColor: spg.icon_color,
        sections: {
          stocks: spg.sections
            .filter((sec) => STOCK_KINDS.has(sec.kind))
            .map((sec) => sec.section_id),
          productions: spg.sections
            .filter((sec) => sec.kind === "production")
            .map((sec) => sec.section_id),
        },
        stocksRemainders: [],
        prodRemainders: [],
        stocksDefects: [],
        prodDefects: [],
      };
    });

    const showNoSpg = selectedSpgIds.length === 0;
    if (showNoSpg) {
      spgGroups["no-spg"] = {
        spgId: "no-spg",
        spgName: "Без ГХП",
        spgIcon: null,
        spgIconColor: null,
        sections: { stocks: [], productions: [] },
        stocksRemainders: [],
        prodRemainders: [],
        stocksDefects: [],
        prodDefects: [],
      };
    }

    const resolveGroupKey = (spgId: number | null | undefined, sectionId: number | null | undefined): string | number => {
      if (spgId && spgGroups[spgId]) return spgId;
      if (sectionId) {
        const viaSection = sectionToSpgId.get(sectionId);
        if (viaSection && spgGroups[viaSection]) return viaSection;
      }
      return "no-spg";
    };

    remainders.forEach((r) => {
      const group = spgGroups[resolveGroupKey(r.spg_id, r.section_id)];
      if (!group) return;
      const kind = r.section_id ? sectionKindById.get(r.section_id) : undefined;
      const isStock = !kind || STOCK_KINDS.has(kind);
      if (isStock) group.stocksRemainders.push(r);
      else group.prodRemainders.push(r);
    });

    defects.forEach((d) => {
      const group = spgGroups[resolveGroupKey(null, d.section_id)];
      if (!group) return;
      const kind = d.section_id ? sectionKindById.get(d.section_id) : undefined;
      const isStock = !kind || STOCK_KINDS.has(kind);
      if (isStock) group.stocksDefects.push(d);
      else group.prodDefects.push(d);
    });

    return Object.values(spgGroups);
  }, [spgs, remainders, defects, sectionKindById, sectionToSpgId, selectedSpgIds]);

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

      {spgs.length > 0 && (
        <div className="space-y-6">
          {groups.map((group) => {
            const hasStocks = group.sections.stocks.length > 0 || group.stocksRemainders.length > 0 || group.stocksDefects.length > 0;
            const hasProductions = group.sections.productions.length > 0 || group.prodRemainders.length > 0 || group.prodDefects.length > 0;
            if (!hasStocks && !hasProductions) return null;

            const totalRemCount = group.stocksRemainders.length + group.prodRemainders.length;
            const totalDefCount = group.stocksDefects.length + group.prodDefects.length;

            return (
              <details
                key={group.spgId}
                open
                className="border rounded-xl bg-card overflow-hidden shadow-sm transition-all"
              >
                <summary className="cursor-pointer select-none px-4 py-3 flex items-center gap-3 bg-muted/30 hover:bg-muted/50 border-b transition-colors font-medium">
                  {group.spgIcon ? (
                    <span style={{ color: group.spgIconColor || undefined }}>
                      {renderIcon(group.spgIcon, "h-5 w-5")}
                    </span>
                  ) : group.spgIconColor ? (
                    <span className="inline-block size-5 rounded-full bg-current" style={{ color: group.spgIconColor }} />
                  ) : (
                    <Layers className="h-5 w-5 text-muted-foreground" />
                  )}
                  <span className="text-base font-semibold flex-1 text-foreground">{group.spgName}</span>
                  <div className="flex items-center gap-2">
                    <Badge variant="secondary" className="text-xs bg-blue-50 text-blue-700 dark:bg-blue-950/30 border border-blue-200">
                      Остатки: {totalRemCount}
                    </Badge>
                    {totalDefCount > 0 ? (
                      <Badge variant="destructive" className="text-xs bg-rose-50 text-rose-700 dark:bg-rose-950/30 border border-rose-200">
                        Брак: {totalDefCount}
                      </Badge>
                    ) : (
                      <Badge variant="secondary" className="text-xs bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 border border-emerald-200">
                        Брак: 0
                      </Badge>
                    )}
                  </div>
                </summary>

                <div className="p-6 space-y-8 bg-card">
                  {hasStocks && (
                    <div className="space-y-4 border-b pb-6">
                      <h3 className="text-md font-semibold text-muted-foreground flex items-center gap-2">
                        <Warehouse className="h-4 w-4" />
                        <span>Склады</span>
                        <Badge variant="outline" className="text-xs">{group.sections.stocks.length} уч.</Badge>
                      </h3>

                      {group.stocksRemainders.length === 0 && group.stocksDefects.length === 0 ? (
                        <div className="py-6 text-center text-sm text-muted-foreground italic bg-muted/5 border rounded-lg">
                          Нет данных по остаткам и браку на складах
                        </div>
                      ) : (
                        <div className="space-y-6">
                          <RemaindersListPanel
                            spgId={typeof group.spgId === "number" ? group.spgId : (spgs[0]?.id || 0)}
                            spgs={spgs}
                            selectedSpgIds={selectedSpgIds}
                            sections={combinedSections}
                            sectionIds={group.sections.stocks}
                            remainders={group.stocksRemainders}
                            isLoading={loadingRemainders}
                            onRefresh={refreshAll}
                            searchQuery={searchQuery}
                          />
                          <DefectsListPanel
                            spgId={typeof group.spgId === "number" ? group.spgId : (spgs[0]?.id || 0)}
                            spgs={spgs}
                            selectedSpgIds={selectedSpgIds}
                            sections={combinedSections}
                            sectionIds={group.sections.stocks}
                            remainders={group.stocksRemainders}
                            defects={group.stocksDefects}
                            isLoading={loadingDefects}
                            onRefresh={refreshAll}
                            searchQuery={searchQuery}
                          />
                        </div>
                      )}
                    </div>
                  )}

                  {hasProductions && (
                    <div className="space-y-4">
                      <h3 className="text-md font-semibold text-muted-foreground flex items-center gap-2">
                        <Factory className="h-4 w-4" />
                        <span>Производственные участки</span>
                        <Badge variant="outline" className="text-xs">{group.sections.productions.length} уч.</Badge>
                      </h3>

                      {group.prodRemainders.length === 0 && group.prodDefects.length === 0 ? (
                        <div className="py-6 text-center text-sm text-muted-foreground italic bg-muted/5 border rounded-lg">
                          Нет данных по остаткам и браку на производственных участках
                        </div>
                      ) : (
                        <div className="space-y-6">
                          <RemaindersListPanel
                            spgId={typeof group.spgId === "number" ? group.spgId : (spgs[0]?.id || 0)}
                            spgs={spgs}
                            selectedSpgIds={selectedSpgIds}
                            sections={combinedSections}
                            sectionIds={group.sections.productions}
                            remainders={group.prodRemainders}
                            isLoading={loadingRemainders}
                            onRefresh={refreshAll}
                            searchQuery={searchQuery}
                          />
                          <DefectsListPanel
                            spgId={typeof group.spgId === "number" ? group.spgId : (spgs[0]?.id || 0)}
                            spgs={spgs}
                            selectedSpgIds={selectedSpgIds}
                            sections={combinedSections}
                            sectionIds={group.sections.productions}
                            remainders={group.prodRemainders}
                            defects={group.prodDefects}
                            isLoading={loadingDefects}
                            onRefresh={refreshAll}
                            searchQuery={searchQuery}
                          />
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </details>
            );
          })}
        </div>
      )}
    </div>
  );
}
