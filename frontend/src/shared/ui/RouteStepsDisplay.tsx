import { Fragment, useMemo } from "react"

import { cn } from "@/shared/utils/cn"
import { renderIcon } from "./EntityDialog"

type RouteStep = {
  sequence: number
  section_code: string
  section_name: string
  section_icon?: string | null
  section_icon_color?: string | null
  operation_code: string | null
  operation_name: string
  op_icon?: string | null
  op_icon_color?: string | null
  is_significant: boolean
}

export type RouteStepsDisplayProps = {
  steps: RouteStep[]
  /** Справочник операций из API — подставляет icon/color, если в steps их нет. */
  referenceOps?: RouteStep[]
  compact?: boolean
  size?: "sm" | "md"
  /** Показывать иконки/точки в бейджах. По умолчанию true. */
  showIcons?: boolean
  className?: string
}

function buildVisualLookup(steps: RouteStep[]): Map<string, RouteStep> {
  const map = new Map<string, RouteStep>()
  for (const step of steps) {
    if (step.operation_name) {
      map.set(step.operation_name.trim().toLowerCase(), step)
    }
    if (step.operation_code) {
      map.set(step.operation_code.trim().toLowerCase(), step)
    }
  }
  return map
}

function mergeStepVisuals(step: RouteStep, lookup?: Map<string, RouteStep>): RouteStep {
  const ref =
    lookup?.get(step.operation_name.trim().toLowerCase()) ??
    (step.operation_code ? lookup?.get(step.operation_code.trim().toLowerCase()) : undefined)

  if (!ref) return step

  return {
    ...step,
    section_icon: step.section_icon ?? ref.section_icon,
    section_icon_color: step.section_icon_color ?? ref.section_icon_color,
    op_icon: step.op_icon ?? ref.op_icon,
    op_icon_color: step.op_icon_color ?? ref.op_icon_color,
  }
}

function groupStepsBySequence(steps: RouteStep[]): RouteStep[][] {
  const groupedSteps: RouteStep[][] = []
  const seenSequences = new Set<number>()

  for (const step of steps) {
    if (!seenSequences.has(step.sequence)) {
      seenSequences.add(step.sequence)
      groupedSteps.push(steps.filter((s) => s.sequence === step.sequence))
    }
  }

  return groupedSteps
}

function getStepAccentColor(step: RouteStep): string | null {
  return step.op_icon_color ?? step.section_icon_color ?? null
}

function OperationStepPill({
  step,
  size,
  showIcons = true,
}: {
  step: RouteStep
  size: "sm" | "md"
  showIcons?: boolean
}) {
  const accentColor = getStepAccentColor(step)
  const textSize = size === "sm" ? "text-[10px]" : "text-xs"
  const iconSize = size === "sm" ? "h-3 w-3" : "h-3.5 w-3.5"
  const label = step.operation_name || step.section_name

  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center gap-1 rounded px-1.5 py-0.5 font-medium leading-5 whitespace-nowrap",
        textSize,
        !accentColor && "border border-border/60 bg-muted/30 text-foreground",
      )}
      style={
        accentColor
          ? {
              backgroundColor: `${accentColor}18`,
              color: accentColor,
            }
          : undefined
      }
      title={`${step.section_name}: ${label}`}
    >
      {showIcons ? (
        step.op_icon && step.op_icon_color ? (
          <span className="shrink-0" style={{ color: step.op_icon_color }}>
            {renderIcon(step.op_icon, iconSize)}
          </span>
        ) : step.section_icon && step.section_icon_color ? (
          <span className="shrink-0" style={{ color: step.section_icon_color }}>
            {renderIcon(step.section_icon, iconSize)}
          </span>
        ) : step.op_icon_color || step.section_icon_color ? (
          <span
            className="inline-block size-2 shrink-0 rounded-full bg-current"
            style={{ color: step.op_icon_color ?? step.section_icon_color ?? undefined }}
          />
        ) : null
      ) : null}
      <span className="truncate">{label}</span>
    </span>
  )
}

/**
 * Displays route steps with visual grouping for combined operations.
 * Steps with the same sequence are shown together.
 */
export function RouteStepsDisplay({
  steps,
  referenceOps,
  compact = true,
  size = "sm",
  showIcons = true,
  className,
}: RouteStepsDisplayProps) {
  const visualLookup = useMemo(
    () => (referenceOps?.length ? buildVisualLookup(referenceOps) : undefined),
    [referenceOps],
  )

  const resolvedSteps = useMemo(
    () => steps.map((step) => mergeStepVisuals(step, visualLookup)),
    [steps, visualLookup],
  )

  if (!resolvedSteps.length) {
    return <span className="text-muted-foreground">—</span>
  }

  const groupedSteps = groupStepsBySequence(resolvedSteps)
  const separatorClass = size === "sm" ? "text-[10px]" : "text-xs"

  if (compact) {
    return (
      <div className={cn("flex flex-wrap items-center gap-0.5 min-w-0", className)}>
        {groupedSteps.map((group, groupIdx) => (
          <Fragment key={group[0].sequence}>
            {groupIdx > 0 ? (
              <span className={cn(separatorClass, "shrink-0 text-muted-foreground/40 px-0.5")}>
                ›
              </span>
            ) : null}
            {group.map((step, stepIdx) => (
              <Fragment key={`${step.sequence}-${step.operation_code ?? step.operation_name}-${stepIdx}`}>
                {stepIdx > 0 ? (
                  <span className={cn(separatorClass, "shrink-0 text-muted-foreground/40")}>
                    ·
                  </span>
                ) : null}
                <OperationStepPill step={step} size={size} showIcons={showIcons} />
              </Fragment>
            ))}
          </Fragment>
        ))}
      </div>
    )
  }

  return (
    <div className={cn("space-y-1", className)}>
      {groupedSteps.map((group) => {
        const isCombined = group.length > 1
        const sectionName = group[0].section_name
        const sectionColor = group[0].section_icon_color

        return (
          <div key={group[0].sequence} className="flex items-start gap-2 text-sm leading-tight">
            {group[0].section_icon && sectionColor ? (
              <div
                className="flex h-6 w-6 shrink-0 items-center justify-center rounded"
                style={{ backgroundColor: `${sectionColor}20` }}
              >
                <span style={{ color: sectionColor }}>
                  {renderIcon(group[0].section_icon, "h-3.5 w-3.5")}
                </span>
              </div>
            ) : (
              <div className="flex-shrink-0 w-6 h-6 rounded-full bg-primary/10 text-primary text-xs font-bold flex items-center justify-center">
                {group[0].sequence}
              </div>
            )}
            <div className="flex flex-wrap items-center gap-1 min-w-0">
              <span className="font-medium text-xs text-muted-foreground">
                {sectionName}
                {isCombined ? (
                  <span className="ml-1 text-orange-600">(совмещено)</span>
                ) : null}
              </span>
              <span className="text-muted-foreground/50">·</span>
              {group.map((step, stepIdx) => (
                <Fragment key={`${step.operation_code ?? step.operation_name}-${stepIdx}`}>
                  {stepIdx > 0 ? (
                    <span className="text-muted-foreground/50 text-xs">/</span>
                  ) : null}
                  <OperationStepPill step={step} size="md" showIcons={showIcons} />
                </Fragment>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}