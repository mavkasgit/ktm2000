import type { ComponentType, CSSProperties } from "react";
import * as L from "lucide-react";

import type { SpgOut } from "@/shared/api/spg";
import { cn } from "@/shared/lib/cn";

interface SpgSelectorProps {
  spgs: SpgOut[];
  selectedIds: number[];
  onToggle: (id: number) => void;
  onSelect: (id: number) => void;
  onClear: () => void;
}

const LUCIDE = L as unknown as Record<string, ComponentType<{ className?: string; style?: CSSProperties }>>;

function pickIcon(name: string | null): ComponentType<{ className?: string; style?: CSSProperties }> | null {
  if (!name) return null;
  return LUCIDE[name] ?? null;
}

export function SpgSelector({ spgs, selectedIds, onToggle, onSelect, onClear }: SpgSelectorProps) {
  const isAllActive = selectedIds.length === 0;

  return (
    <div className="flex flex-wrap gap-2">
      {/* Кнопка "Все группы" */}
      <button
        type="button"
        onClick={onClear}
        className={cn(
          "flex items-center gap-2 rounded-lg border px-4 py-2 text-sm font-medium transition-colors",
          isAllActive
            ? "border-primary bg-primary text-primary-foreground"
            : "border-border bg-card hover:bg-accent hover:text-accent-foreground",
        )}
      >
        <L.Layers className="h-4 w-4" />
        Все группы
        <span className="text-xs opacity-60">
          ({spgs.reduce((acc, s) => acc + (s.sections?.length || 0), 0)})
        </span>
      </button>

      {/* Кнопки отдельных ГХП */}
      {spgs.map((spg) => {
        const active = selectedIds.includes(spg.id);
        const Icon = pickIcon(spg.icon);
        return (
          <div
            key={spg.id}
            className={cn(
              "flex items-center rounded-lg border text-sm font-medium transition-colors overflow-hidden",
              active
                ? "border-primary bg-primary text-primary-foreground shadow-sm"
                : "border-border bg-card hover:border-muted-foreground/30",
            )}
          >
            {/* Левая часть: Одиночный выбор */}
            <button
              type="button"
              onClick={() => onSelect(spg.id)}
              className={cn(
                "flex items-center gap-2 px-4 py-2 transition-colors text-left",
                active
                  ? "hover:bg-primary/95 text-primary-foreground"
                  : "text-foreground hover:bg-accent hover:text-accent-foreground",
              )}
            >
              {Icon && (
                <Icon
                  className="h-4 w-4 shrink-0"
                  style={spg.icon_color ? { color: active ? undefined : spg.icon_color } : undefined}
                />
              )}
              <span>{spg.name}</span>
              <span className="text-xs opacity-60 font-normal">({spg.sections?.length || 0})</span>
            </button>

            {/* Правая часть: Мультиселект (кнопка-чекбокс) */}
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onToggle(spg.id);
              }}
              title={active ? "Убрать из выбора" : "Добавить к выбору (мультиселект)"}
              className={cn(
                "px-3 py-2 border-l transition-colors flex items-center justify-center h-full",
                active
                  ? "border-primary-foreground/20 hover:bg-primary-foreground/10 text-primary-foreground"
                  : "border-border hover:bg-accent text-muted-foreground hover:text-foreground",
              )}
            >
              {active ? (
                <L.CheckSquare className="h-4 w-4" />
              ) : (
                <L.Square className="h-4 w-4" />
              )}
            </button>
          </div>
        );
      })}
    </div>
  );
}
