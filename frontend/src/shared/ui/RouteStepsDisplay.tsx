import { ChevronRight, ChevronDown } from "lucide-react"
import { useState } from "react"

type RouteStep = {
  sequence: number
  section_code: string
  section_name: string
  operation_code: string | null
  operation_name: string
  is_significant: boolean
}

export type RouteStepsDisplayProps = {
  steps: RouteStep[]
  compact?: boolean
}

/**
 * Displays route steps with visual grouping for combined operations.
 * Steps with the same sequence are shown together.
 */
export function RouteStepsDisplay({ steps, compact = true }: RouteStepsDisplayProps) {
  const [expanded, setExpanded] = useState(false)

  if (!steps || steps.length === 0) {
    return <span className="text-muted-foreground">—</span>
  }

  // Group steps by sequence
  const groupedSteps: RouteStep[][] = []
  const seenSequences = new Set<number>()
  
  for (const step of steps) {
    if (!seenSequences.has(step.sequence)) {
      seenSequences.add(step.sequence)
      groupedSteps.push(steps.filter(s => s.sequence === step.sequence))
    }
  }

  // Count total operations
  const totalOps = steps.length

  const formatGroupLabel = (group: RouteStep[]) =>
    group.map((step) => step.operation_name || step.section_name).join(" / ")

  if (compact) {
    return (
      <div className="text-xs">
        <div
          className="flex items-center gap-1 cursor-pointer hover:text-foreground transition-colors"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? (
            <ChevronDown className="h-3 w-3 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-3 w-3 text-muted-foreground" />
          )}
          <span className="font-medium">{totalOps} опер.</span>
          <span className="text-muted-foreground">
            ({groupedSteps.map(formatGroupLabel).join(" → ")})
          </span>
        </div>

        {expanded && (
          <div className="mt-1 py-1 px-1.5 bg-muted/30 rounded border text-[11px] leading-tight space-y-0.5">
            {groupedSteps.map((group, idx) => {
              const isCombined = group.length > 1
              const sectionName = group[0].section_name
              const opsLabel = formatGroupLabel(group)

              return (
                <div key={idx} className="flex flex-wrap items-baseline gap-x-1">
                  <span className="text-muted-foreground shrink-0">
                    {sectionName}
                    {isCombined && (
                      <span className="text-orange-600 ml-1">(совмещено)</span>
                    )}
                    <span className="mx-0.5">·</span>
                  </span>
                  <span className="font-medium">{opsLabel}</span>
                </div>
              )
            })}
          </div>
        )}
      </div>
    )
  }

  // Expanded view
  return (
    <div className="space-y-1">
      {groupedSteps.map((group, idx) => {
        const isCombined = group.length > 1
        const sectionName = group[0].section_name
        const opsLabel = formatGroupLabel(group)

        return (
          <div key={idx} className="flex items-baseline gap-2 text-sm leading-tight">
            <div className="flex-shrink-0 w-6 h-6 rounded-full bg-primary/10 text-primary text-xs font-bold flex items-center justify-center">
              {group[0].sequence}
            </div>
            <div className="flex flex-wrap items-baseline gap-x-1 min-w-0">
              <span className="font-medium">
                {sectionName}
                {isCombined && (
                  <span className="ml-1 text-xs text-orange-600">(совмещено)</span>
                )}
              </span>
              <span className="text-muted-foreground">·</span>
              <span className="text-xs">{opsLabel}</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}
