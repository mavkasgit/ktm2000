import { useMemo } from "react";
import type { Section } from "@/shared/api/sections";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue, renderIcon } from "@/shared/ui";

type SectionSelectProps = {
  sections: Section[];
  value: number | undefined;
  onValueChange: (value: number) => void;
  placeholder?: string;
  className?: string;
};

export function SectionSelect({
  sections,
  value,
  onValueChange,
  placeholder = "Участок",
  className,
}: SectionSelectProps) {
  const activeSections = useMemo(() => sections.filter((s) => s.is_active), [sections]);

  const selectedSection = activeSections.find((s) => s.id === value);
  const iconColor = selectedSection?.icon_color || "#2563EB";

  return (
    <Select value={value ? String(value) : undefined} onValueChange={(v) => onValueChange(Number(v))}>
      <SelectTrigger className={className ?? "h-6 text-xs"}>
        {selectedSection && selectedSection.icon ? (
          <div className="flex items-center gap-1.5">
            <span
              className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded"
              style={{ backgroundColor: `${iconColor}20`, color: iconColor }}
            >
              {renderIcon(selectedSection.icon, "h-3 w-3")}
            </span>
            <span className="truncate">{selectedSection.code} · {selectedSection.name}</span>
          </div>
        ) : (
          <SelectValue placeholder={placeholder} />
        )}
      </SelectTrigger>
      <SelectContent>
        {activeSections.map((section) => {
          const color = section.icon_color || "#2563EB";
          return (
            <SelectItem key={section.id} value={String(section.id)}>
              <div className="flex items-center gap-1.5">
                {section.icon && (
                  <span
                    className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded"
                    style={{ backgroundColor: `${color}20`, color: color }}
                  >
                    {renderIcon(section.icon, "h-3 w-3")}
                  </span>
                )}
                <span className="truncate">{section.code} · {section.name}</span>
              </div>
            </SelectItem>
          );
        })}
      </SelectContent>
    </Select>
  );
}
