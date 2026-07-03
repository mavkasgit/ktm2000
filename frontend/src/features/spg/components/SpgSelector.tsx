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

type IconProps = { className?: string; style?: CSSProperties; title?: string };

const LUCIDE = L as unknown as Record<string, ComponentType<IconProps>>;

function pickIcon(name: string | null): ComponentType<IconProps> | null {
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
              {/* Иконки всех секций ГХП (состав группы) */}
              {spg.sections && spg.sections.length > 0 && (
                <div
                  className={cn(
                    "flex items-center gap-0.5 ml-1 pl-2 border-l",
                    active ? "border-primary-foreground/30" : "border-border",
                  )}
                >
                  {spg.sections
                    .slice()
                    .sort((a, b) => a.sort_order - b.sort_order)
                    .slice(0, 4)
                    .map((sec) => {
                      const SecIcon = pickIcon(sec.icon);
                      if (!SecIcon) return null;
                      return (
                        <SecIcon
                          key={sec.section_id}
                          className="h-3 w-3 shrink-0 opacity-80"
                          style={!active && sec.icon_color ? { color: sec.icon_color } : undefined}
                          title={sec.section_name}
                        />
                      );
                    })}
                  {spg.sections.length > 4 && (
                    <span className="text-[10px] opacity-60 ml-0.5">+{spg.sections.length - 4}</span>
                  )}
                </div>
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
