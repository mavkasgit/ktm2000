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
  showCode?: boolean;
  allLabel?: string;
  isAllSelected?: boolean;
  onAllSelect?: () => void;
};

export function SpgSelect({
  spgs,
  value,
  onValueChange,
  placeholder = "ГХП",
  className,
  emptyLabel,
  showCode = false,
  allLabel,
  isAllSelected = false,
  onAllSelect,
}: SpgSelectProps) {
  const activeSpgs = useMemo(() => spgs.filter((s) => s.is_active), [spgs]);

  const selectedSpg = activeSpgs.find((s) => s.id === value);
  const iconColor = selectedSpg?.icon_color || "#3B82F6";

  const handleValueChange = (v: string) => {
    if (v === "__all__") {
      onAllSelect?.();
      return;
    }
    onValueChange(v === "empty" ? null : Number(v));
  };

  const selectValue = isAllSelected ? "__all__" : value ? String(value) : "empty";

  return (
    <Select value={selectValue} onValueChange={handleValueChange}>
      <SelectTrigger className={className ?? "h-6 text-xs"}>
        {isAllSelected && allLabel ? (
          <span className="truncate">{allLabel}</span>
        ) : selectedSpg && selectedSpg.icon ? (
          <div className="flex items-center gap-1.5">
            <span
              className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded"
              style={{ backgroundColor: `${iconColor}20`, color: iconColor }}
            >
              {renderIcon(selectedSpg.icon, "h-3 w-3")}
            </span>
            <span className="truncate">
              {showCode ? `${selectedSpg.code} · ${selectedSpg.name}` : selectedSpg.name}
            </span>
          </div>
        ) : (
          <SelectValue placeholder={placeholder} />
        )}
      </SelectTrigger>
      <SelectContent>
        {allLabel && (
          <SelectItem value="__all__">
            <span className="font-medium">{allLabel}</span>
          </SelectItem>
        )}
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
                <span className="truncate">
                  {showCode ? `${spg.code} · ${spg.name}` : spg.name}
                </span>
              </div>
            </SelectItem>
          );
        })}
      </SelectContent>
    </Select>
  );
}
