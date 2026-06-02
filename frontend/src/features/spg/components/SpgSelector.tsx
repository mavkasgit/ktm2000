import type { ComponentType, CSSProperties } from "react";
import * as L from "lucide-react";

import type { SpgOut } from "@/shared/api/spg";
import { cn } from "@/shared/lib/cn";

interface SpgSelectorProps {
  spgs: SpgOut[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}

const LUCIDE = L as unknown as Record<string, ComponentType<{ className?: string; style?: CSSProperties }>>;

function pickIcon(name: string | null): ComponentType<{ className?: string; style?: CSSProperties }> | null {
  if (!name) return null;
  return LUCIDE[name] ?? null;
}

export function SpgSelector({ spgs, selectedId, onSelect }: SpgSelectorProps) {
  return (
    <div className="flex flex-wrap gap-2">
      {spgs.map((spg) => {
        const active = spg.id === selectedId;
        const Icon = pickIcon(spg.icon);
        return (
          <button
            key={spg.id}
            type="button"
            onClick={() => onSelect(spg.id)}
            className={cn(
              "flex items-center gap-2 rounded-lg border px-4 py-2 text-sm font-medium transition-colors",
              active
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-card hover:bg-accent hover:text-accent-foreground",
            )}
          >
            {Icon && (
              <Icon
                className="h-4 w-4"
                style={spg.icon_color ? { color: active ? undefined : spg.icon_color } : undefined}
              />
            )}
            {spg.name}
            <span className="text-xs opacity-60">({spg.sections.length})</span>
          </button>
        );
      })}
    </div>
  );
}
