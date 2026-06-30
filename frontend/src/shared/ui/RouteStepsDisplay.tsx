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
            ({groupedSteps.map(g => g[0].operation_name || g[0].section_name).join(" → ")})
          </span>
        </div>

        {expanded && (
          <div className="mt-2 p-2 bg-muted/30 rounded border text-[11px] font-mono">
            {groupedSteps.map((group, idx) => {
              const isCombined = group.length > 1
              const sectionName = group[0].section_name

              return (
                <div key={idx} className="mb-1 last:mb-0">
                  <div className="font-semibold text-muted-foreground">
                    {sectionName}
                    {isCombined && <span className="text-orange-600 ml-1">(совмещено)</span>}
                  </div>
                  <div className="pl-2">
                    {group.map((step, opIdx) => (
                      <div
                        key={opIdx}
                        className={step.is_significant ? "font-medium" : "text-muted-foreground"}
                      >
                        {step.operation_name || step.section_name}
                        {opIdx < group.length - 1 && <span className="text-muted-foreground"> / </span>}
                      </div>
                    ))}
                  </div>
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

        return (
          <div key={idx} className="flex items-start gap-2">
            <div className="flex-shrink-0 w-6 h-6 rounded-full bg-primary/10 text-primary text-xs font-bold flex items-center justify-center">
              {group[0].sequence}
            </div>
            <div className="flex-1">
              <div className="font-medium text-sm">
                {sectionName}
                {isCombined && (
                  <span className="ml-1 text-xs text-orange-600">(совмещено)</span>
                )}
              </div>
              <div className="text-xs text-muted-foreground">
                {group.map((step, opIdx) => (
                  <span key={opIdx}>
                    <span className={step.is_significant ? "font-medium" : ""}>
                      {step.operation_name || step.section_name}
                    </span>
                    {opIdx < group.length - 1 && <span className="mx-1">/</span>}
                  </span>
                ))}
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
