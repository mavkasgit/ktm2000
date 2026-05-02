import { useMemo, useState } from "react"
import * as SharedUI from "shared/ui"
import {
  applyChangeSet,
  approvePositions,
  createReleaseBatch,
  previewDiff,
  previewProductionPlan,
  releaseBatch,
  uploadExcel,
} from "./api"
import { DenseCard, ErrorBanner, InlineBadge } from "./components/primitives"
import type { BackendIssue, FlowIds } from "./types"

type UnknownRecord = Record<string, unknown>

const Button = ((SharedUI as UnknownRecord).Button ?? "button") as any

const issueLabels: Record<string, string> = {
  product_not_found: "изделие не найдено",
  paired_profile_product_unmapped: "парный профиль не сопоставлен с готовым изделием",
  active_bom_not_found: "нет активного BOM",
  active_route_not_found: "нет активного маршрута",
}

function readId(payload: unknown, keys: string[]): string | undefined {
  if (!payload || typeof payload !== "object") return undefined
  const asRecord = payload as UnknownRecord
  for (const key of keys) {
    const value = asRecord[key]
    if (typeof value === "string" && value.trim() !== "") return value
  }
  return undefined
}

function readArray(payload: unknown, keys: string[]) {
  if (!payload || typeof payload !== "object") return []
  const asRecord = payload as UnknownRecord
  for (const key of keys) {
    const value = asRecord[key]
    if (Array.isArray(value)) return value
  }
  return []
}

function collectIssues(payload: unknown): string[] {
  const issueItems = readArray(payload, ["issues", "warnings", "errors"]) as BackendIssue[]
  return issueItems.map((issue) => {
    if (issue.code === "product_not_found") {
      return `${issueLabels.product_not_found}: ${issue.productCode ?? "неизвестно"}`
    }
    if (issue.code === "paired_profile_product_unmapped") {
      return `${issueLabels.paired_profile_product_unmapped}: ${issue.profileCode ?? "неизвестно"}`
    }
    const code = issue.code ?? "issue"
    return `${issueLabels[String(code)] ?? code}: ${issue.message ?? "нет деталей"}`
  })
}

export function PlanFlowScreen() {
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState<string | null>(null)
  const [flowIds, setFlowIds] = useState<FlowIds>({})
  const [diffRows, setDiffRows] = useState<UnknownRecord[]>([])
  const [planRows, setPlanRows] = useState<UnknownRecord[]>([])
  const [selectedPositionIds, setSelectedPositionIds] = useState<Set<string>>(new Set())
  const [issues, setIssues] = useState<string[]>([])

  const canUpload = !!file && !loading
  const canPreviewDiff = !!flowIds.importId && !loading
  const canApply = !!flowIds.changeSetId && !loading
  const canPreviewPlan = !!flowIds.changeSetId && !loading
  const canApprove = !!flowIds.planId && selectedPositionIds.size > 0 && !loading
  const canCreateBatch = !!flowIds.planId && !loading
  const canRelease = !!flowIds.releaseBatchId && !loading

  const rowsSummary = useMemo(() => {
    return {
      diff: diffRows.length,
      plan: planRows.length,
      approved: selectedPositionIds.size,
    }
  }, [diffRows.length, planRows.length, selectedPositionIds.size])

  async function runStep(name: string, action: () => Promise<unknown>, onSuccess: (payload: unknown) => void) {
    setLoading(name)
    try {
      const payload = await action()
      setIssues(collectIssues(payload))
      onSuccess(payload)
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown error"
      setIssues([message])
    } finally {
      setLoading(null)
    }
  }

  function togglePosition(positionId: string) {
    setSelectedPositionIds((prev) => {
      const next = new Set(prev)
      if (next.has(positionId)) {
        next.delete(positionId)
      } else {
        next.add(positionId)
      }
      return next
    })
  }

  return (
    <main style={{ fontFamily: "sans-serif", padding: 12, maxWidth: 1400, margin: "0 auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <h2 style={{ margin: 0 }}>Импорт плана и запуск в производство</h2>
        <InlineBadge>{loading ? `Выполняется: ${loading}` : "Готово"}</InlineBadge>
      </div>

      <ErrorBanner lines={issues} />

      <DenseCard title="Идентификаторы процесса">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 6, fontSize: 13 }}>
          {Object.entries(flowIds).map(([key, value]) => (
            <div key={key} style={{ background: "#f9fafb", borderRadius: 6, padding: 6 }}>
              <div style={{ color: "#4b5563" }}>{key}</div>
              <div style={{ fontWeight: 700 }}>{value ?? "-"}</div>
            </div>
          ))}
        </div>
      </DenseCard>

      <DenseCard title="1. Загрузка Excel">
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input type="file" accept=".xlsx,.xls,.xlsm,.xlsb,.ods" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <Button disabled={!canUpload} onClick={() => runStep("upload_excel", () => uploadExcel(file!), (payload) => {
            setFlowIds((prev) => ({
              ...prev,
              importId: readId(payload, ["importId", "jobId", "id"]),
              changeSetId: readId(payload, ["changeSetId"]),
              planId: readId(payload, ["planId"]),
            }))
          })}>Загрузить</Button>
        </div>
      </DenseCard>

      <DenseCard title="2. Preview изменений">
        <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
          <Button disabled={!canPreviewDiff} onClick={() => runStep("preview_diff", () => previewDiff(), (payload) => {
            const rows = readArray(payload, ["rows", "changes", "diff"]) as UnknownRecord[]
            setDiffRows(rows)
            setFlowIds((prev) => ({
              ...prev,
              diffId: readId(payload, ["diffId", "previewId"]),
              changeSetId: readId(payload, ["changeSetId", "id"]),
            }))
          })}>Показать diff</Button>
          <span style={{ alignSelf: "center", fontSize: 13 }}>Строк: {rowsSummary.diff}</span>
        </div>
        <div style={{ maxHeight: 160, overflow: "auto", fontSize: 12, border: "1px solid #e5e7eb", borderRadius: 6 }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <tbody>
              {diffRows.map((row, idx) => (
                <tr key={idx}>
                  <td style={{ borderBottom: "1px solid #f3f4f6", padding: 4 }}>{JSON.stringify(row)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </DenseCard>

      <DenseCard title="3. Применить change set">
          <Button disabled={!canApply} onClick={() => runStep("apply_change_set", () => applyChangeSet(), (payload) => {
            setFlowIds((prev) => ({
              ...prev,
              applyJobId: readId(payload, ["applyJobId", "jobId", "id"]),
              planId: readId(payload, ["planId"]) ?? prev.planId,
            }))
          })}>Применить</Button>
      </DenseCard>

      <DenseCard title="4. Preview производственного плана">
        <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
          <Button disabled={!canPreviewPlan} onClick={() => runStep("preview_plan", () => previewProductionPlan(flowIds.planId), (payload) => {
            const rows = readArray(payload, ["positions", "rows", "plan"]) as UnknownRecord[]
            setPlanRows(rows)
            const planId = readId(payload, ["planId", "id"])
            setFlowIds((prev) => ({ ...prev, planId }))
            setSelectedPositionIds(new Set(rows.map((row) => String(row.positionId ?? row.id ?? "")).filter(Boolean)))
          })}>Показать план</Button>
          <span style={{ alignSelf: "center", fontSize: 13 }}>Позиции: {rowsSummary.plan}</span>
        </div>

        <div style={{ maxHeight: 240, overflow: "auto", fontSize: 12, border: "1px solid #e5e7eb", borderRadius: 6 }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left", padding: 4 }}>Утвердить</th>
                <th style={{ textAlign: "left", padding: 4 }}>Позиция</th>
                <th style={{ textAlign: "left", padding: 4 }}>Данные</th>
              </tr>
            </thead>
            <tbody>
              {planRows.map((row, idx) => {
                const positionId = String(row.positionId ?? row.id ?? `row-${idx}`)
                return (
                  <tr key={positionId}>
                    <td style={{ borderBottom: "1px solid #f3f4f6", padding: 4 }}>
                      <input
                        type="checkbox"
                        checked={selectedPositionIds.has(positionId)}
                        onChange={() => togglePosition(positionId)}
                      />
                    </td>
                    <td style={{ borderBottom: "1px solid #f3f4f6", padding: 4 }}>{positionId}</td>
                    <td style={{ borderBottom: "1px solid #f3f4f6", padding: 4 }}>{JSON.stringify(row)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </DenseCard>

      <DenseCard title="5. Утвердить позиции">
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <Button disabled={!canApprove} onClick={() => runStep("approve_positions", () => approvePositions(flowIds.planId!, Array.from(selectedPositionIds)), (payload) => {
            setFlowIds((prev) => ({
              ...prev,
              approvalId: readId(payload, ["approvalId", "jobId", "id"]),
            }))
          })}>Утвердить выбранные</Button>
          <span style={{ fontSize: 13 }}>Выбрано: {rowsSummary.approved}</span>
        </div>
      </DenseCard>

      <DenseCard title="6. Создать пакет запуска">
        <Button disabled={!canCreateBatch} onClick={() => runStep("create_release_batch", () => createReleaseBatch(flowIds.planId!), (payload) => {
          setFlowIds((prev) => ({
            ...prev,
            releaseBatchId: readId(payload, ["releaseBatchId", "batchId", "id"]),
          }))
          })}>Создать пакет</Button>
      </DenseCard>

      <DenseCard title="7. Выпустить в производство">
        <Button disabled={!canRelease} onClick={() => runStep("release_batch", () => releaseBatch(flowIds.releaseBatchId!), (payload) => {
          setFlowIds((prev) => ({
            ...prev,
            releaseJobId: readId(payload, ["releaseJobId", "jobId", "id"]),
          }))
          })}>Выпустить</Button>
      </DenseCard>
    </main>
  )
}
