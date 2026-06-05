import { useMemo } from "react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue, renderIcon } from "@/shared/ui";

export type SpgSelectItem = {
  id: number;
  code: string;
  name: string;
  icon?: string | null;
  icon_color?: string | null;
  is_active: boolean;
};

export type SpgSelectProps = {
  spgs: SpgSelectItem[];
  value: number | null | undefined;
  onValueChange: (value: number | null) => void;
  placeholder?: string;
  className?: string;
  emptyLabel?: string;
};

export function SpgSelect({
  spgs,
  value,
  onValueChange,
  placeholder = "ГХП",
  className,
  emptyLabel,
}: SpgSelectProps) {
  const activeSpgs = useMemo(() => spgs.filter((s) => s.is_active), [spgs]);

  const selectedSpg = activeSpgs.find((s) => s.id === value);
  const iconColor = selectedSpg?.icon_color || "#3B82F6";

  return (
    <Select value={value ? String(value) : "empty"} onValueChange={(v) => onValueChange(v === "empty" ? null : Number(v))}>
      <SelectTrigger className={className ?? "h-6 text-xs"}>
        {selectedSpg && selectedSpg.icon ? (
          <div className="flex items-center gap-1.5">
            <span
              className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded"
              style={{ backgroundColor: `${iconColor}20`, color: iconColor }}
            >
              {renderIcon(selectedSpg.icon, "h-3 w-3")}
            </span>
            <span className="truncate">{selectedSpg.code} · {selectedSpg.name}</span>
          </div>
        ) : (
          <SelectValue placeholder={placeholder} />
        )}
      </SelectTrigger>
      <SelectContent>
        {emptyLabel && (
          <SelectItem value="empty">
            <span className="text-muted-foreground">{emptyLabel}</span>
          </SelectItem>
        )}
        {activeSpgs.map((spg) => {
          const color = spg.icon_color || "#3B82F6";
          return (
            <SelectItem key={spg.id} value={String(spg.id)}>
              <div className="flex items-center gap-1.5">
                {spg.icon && (
                  <span
                    className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded"
                    style={{ backgroundColor: `${color}20`, color: color }}
                  >
                    {renderIcon(spg.icon, "h-3 w-3")}
                  </span>
                )}
                <span className="truncate">{spg.code} · {spg.name}</span>
              </div>
            </SelectItem>
          );
        })}
      </SelectContent>
    </Select>
  );
}
