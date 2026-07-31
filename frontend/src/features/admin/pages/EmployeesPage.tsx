import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { RefreshCw, Users } from "lucide-react"
import { Button } from "@/shared/ui"
import { syncEmployees } from "../api"
import { HrmsEmployeesTable } from "../components/HrmsEmployeesTable"

export function EmployeesPage() {
  const queryClient = useQueryClient()
  const [syncedAt, setSyncedAt] = useState<string | null>(null)

  const syncMutation = useMutation({
    mutationFn: syncEmployees,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["employees"] })
      setSyncedAt(data.synced_at)
    },
  })

  return (
    <div className="space-y-4 p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Users className="h-5 w-5 text-violet-600" />
          <h1 className="text-lg font-bold">Сотрудники HRMS</h1>
          {syncedAt && (
            <span className="text-xs text-muted-foreground">
              Синк: {new Date(syncedAt).toLocaleString("ru-RU")}
            </span>
          )}
        </div>
        <Button
          size="sm"
          onClick={() => syncMutation.mutate()}
          disabled={syncMutation.isPending}
        >
          <RefreshCw className={`h-4 w-4 mr-1 ${syncMutation.isPending ? "animate-spin" : ""}`} />
          {syncMutation.isPending ? "Синхронизация..." : "Синхронизировать"}
        </Button>
      </div>

      {syncMutation.isError && (
        <div className="text-sm text-red-600 bg-red-500/10 rounded-lg p-3">
          {(syncMutation.error as Error).message || "Ошибка синхронизации"}
        </div>
      )}

      <HrmsEmployeesTable
        emptyMessage="Нет данных. Нажмите «Синхронизировать» для загрузки из HRMS."
      />
    </div>
  )
}
