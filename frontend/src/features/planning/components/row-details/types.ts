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
  rawExcelRow?: string
}
