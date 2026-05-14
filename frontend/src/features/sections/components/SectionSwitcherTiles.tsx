import { useEffect, useMemo, useState } from "react";
import { AlertCircle, Search, Star } from "lucide-react";

import type { Section } from "@/shared/api/sections";
import type { SectionSummary } from "@/shared/api/shopfloor";
import { Badge, Button, Input, Popover, PopoverContent, PopoverTrigger, renderIcon } from "@/shared/ui";

type SectionSwitcherTilesProps = {
  sections: Section[];
  summary: SectionSummary[];
  selectedSectionId: number | null;
  onSelect: (sectionId: number) => void;
};

const QUICK_ACCESS_STORAGE_KEY = "shopfloor.quickAccessSectionIds.v2";

function totals(summary: SectionSummary | undefined) {
  return {
    ready: summary?.ready_count ?? 0,
    inProgress: summary?.in_progress_count ?? 0,
    waiting: summary?.waiting_count ?? 0,
    incoming: summary?.incoming_transfers_count ?? 0,
  };
}

export function SectionSwitcherTiles({
  sections,
  summary,
  selectedSectionId,
  onSelect,
}: SectionSwitcherTilesProps) {
  const [search, setSearch] = useState("");
  const [quickAccessIdsSet, setQuickAccessIdsSet] = useState<Set<number>>(new Set());
  const [quickAccessInitialized, setQuickAccessInitialized] = useState(false);

  const summaryBySectionId = useMemo(() => {
    const map = new Map<number, SectionSummary>();
    summary.forEach((row) => map.set(row.section_id, row));
    return map;
  }, [summary]);

  const allSections = useMemo(() => {
    const ids = new Set<number>();
    const rows: Array<Section & { sort_order: number }> = [];
    sections.forEach((section) => {
      if (ids.has(section.id)) return;
      ids.add(section.id);
      const fromSummary = summaryBySectionId.get(section.id);
      rows.push({ ...section, sort_order: fromSummary?.sort_order ?? 0 });
    });
    return rows.sort((a, b) => a.sort_order - b.sort_order || a.id - b.id);
  }, [sections, summaryBySectionId]);

  useEffect(() => {
    if (quickAccessInitialized || allSections.length === 0) return;
    if (typeof window === "undefined") {
      setQuickAccessIdsSet(new Set(allSections.map((s) => s.id)));
      setQuickAccessInitialized(true);
      return;
    }
    try {
      const raw = window.localStorage.getItem(QUICK_ACCESS_STORAGE_KEY);
      if (!raw) {
        setQuickAccessIdsSet(new Set(allSections.map((s) => s.id)));
        setQuickAccessInitialized(true);
        return;
      }
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) {
        setQuickAccessIdsSet(new Set(allSections.map((s) => s.id)));
        setQuickAccessInitialized(true);
        return;
      }
      const allowedIds = new Set(allSections.map((s) => s.id));
      const filtered = parsed.filter((id: number) => allowedIds.has(Number(id)));
      setQuickAccessIdsSet(new Set(filtered.length > 0 ? filtered : allSections.map((s) => s.id)));
    } catch {
      setQuickAccessIdsSet(new Set(allSections.map((s) => s.id)));
    } finally {
      setQuickAccessInitialized(true);
    }
  }, [allSections, quickAccessInitialized]);

  useEffect(() => {
    if (!quickAccessInitialized || typeof window === "undefined") return;
    window.localStorage.setItem(QUICK_ACCESS_STORAGE_KEY, JSON.stringify([...quickAccessIdsSet]));
  }, [quickAccessInitialized, quickAccessIdsSet]);

  const quickAccessSections = useMemo(() => {
    return allSections.filter((section) => quickAccessIdsSet.has(section.id));
  }, [allSections, quickAccessIdsSet]);

  const orderedSectionsForList = useMemo(() => {
    return allSections;
  }, [allSections]);

  const filteredSections = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return orderedSectionsForList;
    return orderedSectionsForList.filter((section) => {
      const text = `${section.code} ${section.name}`.toLowerCase();
      return text.includes(term);
    });
  }, [orderedSectionsForList, search]);

  const toggleQuickAccess = (sectionId: number) => {
    setQuickAccessIdsSet((prev) => {
      const next = new Set(prev);
      if (next.has(sectionId)) {
        next.delete(sectionId);
      } else {
        next.add(sectionId);
      }
      return next;
    });
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <Popover>
          <PopoverTrigger asChild>
            <Button variant="outline" className="min-h-[36px]">
              Все участки ({allSections.length})
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-[460px]" align="start">
            <div className="space-y-3">
              <div className="relative">
                <Search className="pointer-events-none absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Поиск по коду или названию"
                  className="pl-8"
                />
              </div>
              <div className="max-h-[320px] space-y-1 overflow-auto pr-1">
                {filteredSections.map((section) => {
                  const stats = totals(summaryBySectionId.get(section.id));
                  const isActive = selectedSectionId === section.id;
                  const inQuickAccess = quickAccessIdsSet.has(section.id);
                  const iconColor = section.icon_color || "#2563EB";
                  return (
                    <button
                      key={section.id}
                      type="button"
                      className={`w-full rounded-md border px-3 py-2 text-left transition hover:bg-accent/30 ${
                        isActive ? "border-primary bg-primary/5" : "border-border bg-card"
                      }`}
                      onClick={() => onSelect(section.id)}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex min-w-0 items-center gap-1.5">
                          <button
                            type="button"
                            className={`inline-flex min-h-6 min-w-6 shrink-0 items-center justify-center rounded border px-1.5 text-[11px] transition ${
                              inQuickAccess ? "border-primary text-primary" : "border-border text-muted-foreground hover:text-foreground"
                            }`}
                            onClick={(event) => {
                              event.preventDefault();
                              event.stopPropagation();
                              toggleQuickAccess(section.id);
                            }}
                            aria-label={inQuickAccess ? "Убрать из быстрого доступа" : "Добавить в быстрый доступ"}
                          >
                            <Star className={`h-3.5 w-3.5 ${inQuickAccess ? "fill-current" : ""}`} />
                          </button>
                          <span
                            className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md"
                            style={{ backgroundColor: `${iconColor}20`, color: iconColor }}
                          >
                            {section.icon ? renderIcon(section.icon, "h-4 w-4") : <span className="h-2 w-2 rounded-full bg-current" />}
                          </span>
                          <div className="min-w-0">
                            <div className="text-xs text-muted-foreground">{section.code}</div>
                            <div className="truncate text-sm font-medium">{section.name}</div>
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <div className="text-xs text-muted-foreground">
                            {stats.ready}/{stats.inProgress}/{stats.waiting}
                          </div>
                        </div>
                      </div>
                    </button>
                  );
                })}
                {filteredSections.length === 0 && (
                  <div className="rounded-md border p-3 text-center text-sm text-muted-foreground">
                    Ничего не найдено
                  </div>
                )}
              </div>
            </div>
          </PopoverContent>
        </Popover>
        <div className="text-xs text-muted-foreground">
          Быстрый доступ: {quickAccessSections.length}
        </div>
      </div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8">
        {quickAccessSections.map((section) => {
          const isActive = selectedSectionId === section.id;
          const stats = totals(summaryBySectionId.get(section.id));
          const tileColor = section.icon_color || "#2563EB";
          return (
            <button
              key={section.id}
              type="button"
              className={`min-h-[96px] rounded-lg border p-3 text-left transition hover:bg-accent/30 focus:outline-none focus:ring-2 focus:ring-ring ${
                isActive ? "border-primary bg-primary/5" : "border-border bg-card"
              }`}
              onClick={() => onSelect(section.id)}
              aria-pressed={isActive}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{section.code}</div>
                  <div className="truncate text-sm font-semibold">{section.name}</div>
                </div>
                <span
                  className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md"
                  style={{ backgroundColor: `${tileColor}20`, color: tileColor }}
                >
                  {section.icon ? renderIcon(section.icon, "h-4 w-4") : <span className="h-2 w-2 rounded-full bg-current" />}
                </span>
              </div>
              <div className="mt-2 flex flex-wrap gap-1">
                <Badge variant="secondary" className="text-[11px]">Г: {stats.ready}</Badge>
                <Badge variant="secondary" className="text-[11px]">ВР: {stats.inProgress}</Badge>
                <Badge variant="secondary" className="text-[11px]">ОЖ: {stats.waiting}</Badge>
                {stats.incoming > 0 && (
                  <Badge variant="destructive" className="text-[11px]">
                    <AlertCircle className="mr-1 h-3 w-3" />
                    Вх: {stats.incoming}
                  </Badge>
                )}
              </div>
            </button>
          );
        })}
        {quickAccessSections.length === 0 && (
          <div className="col-span-full rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
            Быстрый доступ пуст. Добавьте участки из списка «Все участки».
          </div>
        )}
      </div>

    </div>
  );
}
