import { renderIcon } from "./EntityDialog"
import { cn } from "@/shared/utils/cn"
import type { Section } from "@/shared/api/sections"

export type SectionLocationBadgeProps = {
  sections: Section[]
  sectionId?: number | null
  sectionName?: string | null
  invalid?: boolean
  size?: "sm" | "md"
  className?: string
}

export function SectionLocationBadge({
  sections,
  sectionId,
  sectionName,
  invalid = false,
  size = "sm",
  className,
}: SectionLocationBadgeProps) {
  const section =
    (sectionId != null ? sections.find((s) => s.id === sectionId) : undefined) ??
    (sectionName
      ? sections.find(
          (s) => s.name.trim().toLowerCase() === sectionName.trim().toLowerCase(),
        )
      : undefined)

  const color = section?.icon_color ?? (invalid ? "#D97706" : "#2563EB")
  const label = sectionName ?? section?.name ?? "—"
  const textSize = size === "sm" ? "text-[10px]" : "text-xs"
  const iconSize = size === "sm" ? "h-3 w-3" : "h-3.5 w-3.5"

  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center gap-1 rounded px-1.5 py-0.5 font-semibold leading-5 whitespace-nowrap",
        textSize,
        className,
      )}
      style={{
        backgroundColor: `${color}18`,
        color,
      }}
      title={section ? `${section.code} · ${section.name}` : label}
    >
      {section?.icon ? (
        <span className="shrink-0" style={{ color }}>
          {renderIcon(section.icon, iconSize)}
        </span>
      ) : (
        <span
          className="inline-block size-2 shrink-0 rounded-full bg-current"
          style={{ color }}
        />
      )}
      <span className="truncate">{label}</span>
    </span>
  )
}