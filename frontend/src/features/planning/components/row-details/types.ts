import { type ProductionPlanningStage } from "@/shared/api/productionPlans"

export type RowDetailsData = {
  id: string | number
  sourceRowNumber: number | null
  sku: string
  name: string | null
  quantity: string | number
  status: string
  routeName: string | null
  routeError: string | null
  routeMeta: string
  errors: string[]
  warnings: string[]
  productionPlanId: number
  stages?: ProductionPlanningStage[]
  routeCheckIssues?: string[]
  rawExcelRows?: { rowNumber: string; text: string }[]
  duplicateConflictIds?: number[]
  currentStageSectionId?: number | null
  currentStageSectionName?: string | null
  currentStageSectionCode?: string | null
  currentStageSequence?: number | null
  currentStageOperation?: string | null
  currentStageTaskStatus?: string | null
  quantityPerHanger?: number | null
  productId?: number | null
  originalQuantity?: string | number | null
}
