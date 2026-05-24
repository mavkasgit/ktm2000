import { useMemo, useState } from "react";
import { AlertCircle, Search } from "lucide-react";

import type { Section } from "@/shared/api/sections";
import type { SectionSummary } from "@/shared/api/shopfloor";
import { Badge, Input, Popover, PopoverContent, PopoverTrigger, renderIcon } from "@/shared/ui";

type SectionSwitcherTilesProps = {
  sections: Section[];
  summary: SectionSummary[];
  selectedSectionId: number | null;
  onSelect: (sectionId: number) => void;
  variant?: "expanded" | "popover";
  headerContent?: React.ReactNode;
};

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
  variant = "expanded",
  headerContent,
}: SectionSwitcherTilesProps) {
  const [search, setSearch] = useState("");
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

  const filteredSections = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return allSections;
    return allSections.filter((section) => {
      const text = `${section.code} ${section.name}`.toLowerCase();
      return text.includes(term);
    });
  }, [allSections, search]);

  const gridSections = variant === "popover" ? filteredSections : allSections;

  const sectionCard = (section: Section & { sort_order: number }, onSelectCb?: (id: number) => void) => {
    const stats = totals(summaryBySectionId.get(section.id));
    const isActive = selectedSectionId === section.id;
    const iconColor = section.icon_color || "#2563EB";
    return (
      <button
        key={section.id}
        type="button"
        className={`rounded-lg border text-left transition hover:bg-accent/30 focus:outline-none focus:ring-2 focus:ring-ring ${
          isActive ? "border-primary bg-primary/5" : "border-border bg-card"
        } ${variant === "popover" ? "p-2" : "min-h-[96px] p-3"}`}
        onClick={() => onSelectCb ? onSelectCb(section.id) : onSelect(section.id)}
        aria-pressed={isActive}
      >
        <div className={`flex items-start ${variant === "popover" ? "justify-between gap-1.5" : "justify-between gap-2"}`}>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <span
                className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md"
                style={{ backgroundColor: `${iconColor}20`, color: iconColor }}
              >
                {section.icon ? renderIcon(section.icon, "h-4 w-4") : <span className="h-2 w-2 rounded-full bg-current" />}
              </span>
              <div className="min-w-0">
                <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{section.code}</div>
                <div className="truncate text-sm font-semibold">{section.name}</div>
              </div>
            </div>
          </div>
          {isActive && variant === "popover" && (
            <div className="text-[10px] font-semibold text-primary shrink-0">Текущий</div>
          )}
        </div>
        {variant === "popover" ? (
          <div className="mt-2 grid grid-cols-2 gap-1">
            <Badge variant={stats.incoming > 0 ? "destructive" : "secondary"} className="text-[11px] justify-center">
              {stats.incoming > 0 ? <>Вх: {stats.incoming}</> : <>Вх: 0</>}
            </Badge>
            <Badge variant="secondary" className="text-[11px] justify-center">ОЖ: {stats.waiting}</Badge>
            <Badge variant="secondary" className="text-[11px] justify-center">ВР: {stats.inProgress}</Badge>
            <Badge variant="secondary" className="text-[11px] justify-center">Г: {stats.ready}</Badge>
          </div>
        ) : (
          <div className="mt-2 flex flex-wrap gap-1">
            {stats.incoming > 0 && (
              <Badge variant="destructive" className="text-[11px]">
                <AlertCircle className="mr-1 h-3 w-3" />
                Вх: {stats.incoming}
              </Badge>
            )}
            <Badge variant="secondary" className="text-[11px]">ОЖ: {stats.waiting}</Badge>
            <Badge variant="secondary" className="text-[11px]">ВР: {stats.inProgress}</Badge>
            <Badge variant="secondary" className="text-[11px]">Г: {stats.ready}</Badge>
          </div>
        )}
      </button>
    );
  };

  const sectionGrid = (
    <div className={`gap-2 ${variant === "popover" ? "grid grid-cols-3" : "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6"}`}>
      {gridSections.map((section) => sectionCard(section))}
      {gridSections.length === 0 && (
        <div className={`rounded-lg border p-3 text-center text-sm text-muted-foreground ${variant === "popover" ? "col-span-3" : "col-span-full"}`}>
          Ничего не найдено
        </div>
      )}
    </div>
  );

  if (variant === "popover") {
    const [open, setOpen] = useState(false);

    const handleSelect = (sectionId: number) => {
      setOpen(false);
      setSearch("");
      onSelect(sectionId);
    };

    return (
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <div className="flex items-center gap-3 min-w-0 cursor-pointer hover:opacity-80 transition-opacity">
            {headerContent}
            <svg className="h-5 w-5 text-muted-foreground shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </div>
        </PopoverTrigger>
        <PopoverContent side="bottom" avoidCollisions={false} sideOffset={8} className="w-[min(50vw,700px)]" align="start">
          <div className="space-y-3">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Поиск участка"
                className="pl-8"
              />
            </div>
            <div className="max-h-[400px] overflow-auto pr-1">
              <div className="gap-2 grid grid-cols-4">
                {gridSections.map((section) => sectionCard(section, handleSelect))}
                {gridSections.length === 0 && (
                  <div className="col-span-4 rounded-lg border p-3 text-center text-sm text-muted-foreground">
                    Ничего не найдено
                  </div>
                )}
              </div>
            </div>
          </div>
        </PopoverContent>
      </Popover>
    );
  }

  return (
    <div className="space-y-3">
      {sectionGrid}
    </div>
  );
}
