import { useMemo, useRef, useState } from "react"
import { Check, ExternalLink, Upload } from "lucide-react"
import { useNavigate } from "react-router-dom"
import { uploadExcel, uploadTestExcel, applyChangeSet } from "./api"
import { ImportDiffTable } from "./ImportDiffTable"
import { Button } from "shared/ui"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "shared/ui"

type SortConfig = { key: string; dir: "asc" | "desc" } | null

export function ImportWizard(props: {
  open: boolean
  onClose: () => void
  onSuccess: (planId: string, changeSetId: string) => void
  mode?: "normal" | "test"
}) {
  const [step, setStep] = useState<"upload" | "preview" | "result">("upload")
  const [file, setFile] = useState<File | null>(null)
  const [previewData, setPreviewData] = useState<Record<string, unknown> | null>(null)
  const [sortConfig, setSortConfig] = useState<SortConfig>(null)
  const [filterStatus, setFilterStatus] = useState<"all" | "invalid" | "warning">("all")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<Record<string, unknown> | null>(null)

  const fileInputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()

  const allRows = useMemo(() => {
    return (previewData?.items as Record<string, unknown>[]) ?? []
  }, [previewData])

  const filteredRows = useMemo(() => {
    let rows = allRows
    if (filterStatus !== "all") {
      rows = rows.filter((r) => r.status === filterStatus)
    }
    if (!sortConfig) return rows
    return [...rows].sort((a, b) => {
      let aVal: string
      let bVal: string
      if (sortConfig.key === "change_action" || sortConfig.key === "status") {
        aVal = String(a[sortConfig.key] ?? "")
        bVal = String(b[sortConfig.key] ?? "")
      } else {
        const aAfter = (a.after_data as Record<string, unknown>) || {}
        const bAfter = (b.after_data as Record<string, unknown>) || {}
        aVal = String(aAfter[sortConfig.key] ?? a[sortConfig.key] ?? "")
        bVal = String(bAfter[sortConfig.key] ?? b[sortConfig.key] ?? "")
      }
      if (aVal < bVal) return sortConfig.dir === "asc" ? -1 : 1
      if (aVal > bVal) return sortConfig.dir === "asc" ? 1 : -1
      return 0
    })
  }, [allRows, filterStatus, sortConfig])

  const summary = useMemo(() => {
    const total = allRows.length
    const invalid = allRows.filter((r) => r.status === "invalid").length
    const warning = allRows.filter((r) => r.status === "warning").length
    return { total, invalid, warning }
  }, [allRows])

  const errorBreakdown = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const row of allRows) {
      const errs = row.errors as string[] | undefined
      if (Array.isArray(errs)) {
        for (const e of errs) {
          counts[e] = (counts[e] || 0) + 1
        }
      }
    }
    return counts
  }, [allRows])

  async function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    if (!f) return
    setFile(f)
    setLoading(true)
    setError(null)
    try {
      const data = await uploadExcel(f)
      setPreviewData(data)
      setStep("preview")
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки")
    } finally {
      setLoading(false)
    }
  }

  async function handleTestImport() {
    setLoading(true)
    setError(null)
    try {
      const data = await uploadTestExcel()
      setPreviewData(data)
      setStep("preview")
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка тестового импорта")
    } finally {
      setLoading(false)
    }
  }

  async function handleApply() {
    if (!previewData) return
    const planId = String(previewData.planId ?? previewData.production_plan_id ?? "")
    const changeSetId = String(previewData.changeSetId ?? previewData.change_set_id ?? "")
    if (!planId || !changeSetId) {
      setError("Не найден planId или changeSetId")
      return
    }
    setLoading(true)
    setError(null)
    try {
      const data = await applyChangeSet(planId, changeSetId)
      setResult(data)
      setStep("result")
      props.onSuccess(planId, changeSetId)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка применения")
    } finally {
      setLoading(false)
    }
  }

  function toggleSort(key: string) {
    setSortConfig((prev) => {
      if (!prev || prev.key !== key) return { key, dir: "asc" }
      if (prev.dir === "asc") return { key, dir: "desc" }
      return null
    })
  }

  function reset() {
    setStep("upload")
    setFile(null)
    setPreviewData(null)
    setResult(null)
    setError(null)
    setSortConfig(null)
    setFilterStatus("all")
    if (fileInputRef.current) {
      fileInputRef.current.value = ""
    }
  }

  function handleClose() {
    reset()
    props.onClose()
  }

  return (
    <Dialog open={props.open} onOpenChange={(open) => { if (!open) handleClose() }}>
      <DialogContent className={`w-full max-h-[95vh] overflow-hidden flex flex-col ${step === "preview" ? "max-w-[95vw]" : "max-w-2xl"}`}>
        <DialogHeader>
          <DialogTitle>
            {props.mode === "test" ? "Тестовый импорт плана" : "Импорт производственного плана"}
          </DialogTitle>
          <DialogDescription>
            {props.mode === "test"
              ? "Загрузка тестового плана (ЮП-2630) для проверки"
              : "Загрузите файл Excel и проверьте изменения перед применением"}
          </DialogDescription>
        </DialogHeader>

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            {error}
          </div>
        )}

        {step === "upload" && (
          <div className="space-y-4">
            {props.mode === "test" ? (
              <div className="text-center py-6">
                <p className="text-sm text-muted-foreground mb-4">
                  Будет загружен тестовый план с одной позицией ЮП-2630
                </p>
                <Button onClick={handleTestImport} disabled={loading}>
                  <Upload className="h-4 w-4 mr-2" />
                  {loading ? "Загрузка…" : "Загрузить тестовый план"}
                </Button>
              </div>
            ) : (
              <div
                className="border-2 border-dashed rounded-lg p-8 text-center cursor-pointer hover:bg-accent/50 transition-colors"
                onClick={() => fileInputRef.current?.click()}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".xlsx,.xls,.xlsm,.xlsb,.ods"
                  className="hidden"
                  onChange={handleFileSelect}
                />
                <Upload className="mx-auto h-12 w-12 text-muted-foreground mb-4" />
                <p className="text-sm text-muted-foreground">
                  {loading ? "Загрузка…" : "Нажмите или перетащите заполненный файл Excel"}
                </p>
                <p className="text-xs text-muted-foreground mt-2">
                  Поддерживаются .xlsx, .xls, .xlsm, .xlsb, .ods
                </p>
                {file && !loading && (
                  <p className="text-xs text-blue-600 mt-2 font-medium">{file.name}</p>
                )}
              </div>
            )}
          </div>
        )}

        {step === "preview" && previewData && (
          <div className="flex-1 overflow-hidden flex flex-col space-y-4">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div className="flex gap-4 text-sm">
                <span><strong>Всего:</strong> {summary.total}</span>
                {summary.invalid > 0 && <span className="text-red-600"><strong>Ошибок:</strong> {summary.invalid}</span>}
                {summary.warning > 0 && <span className="text-amber-600"><strong>Предупр.:</strong> {summary.warning}</span>}
                {summary.invalid === 0 && summary.warning === 0 && <span className="text-green-600 text-xs">Без ошибок</span>}
              </div>
              <div className="flex gap-1">
                {(["all", "invalid", "warning"] as const).map((f) => (
                  <button
                    key={f}
                    onClick={() => setFilterStatus(f)}
                    className={`px-2.5 py-1 text-xs rounded-md border transition-colors ${
                      filterStatus === f
                        ? "bg-primary text-primary-foreground border-primary"
                        : "bg-background hover:bg-accent border-input"
                    }`}
                  >
                    {f === "all" ? "Все" : f === "invalid" ? "Ошибки" : "Предупр."}
                  </button>
                ))}
              </div>
            </div>

            {Object.keys(errorBreakdown).length > 0 && (
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="text-muted-foreground">Ошибки по типам:</span>
                {Object.entries(errorBreakdown).map(([code, count]) => (
                  <span key={code} className="bg-red-50 text-red-700 px-2 py-0.5 rounded border border-red-100">
                    {code}: {count}
                  </span>
                ))}
                {errorBreakdown["product_not_found"] > 0 && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="ml-auto h-7 text-xs gap-1"
                    onClick={() => { navigate("/references/raw-materials"); props.onClose() }}
                  >
                    <ExternalLink className="h-3 w-3" />
                    Открыть справочники
                  </Button>
                )}
              </div>
            )}

            <div className="flex-1 overflow-auto border rounded-lg">
              <ImportDiffTable rows={filteredRows} sortConfig={sortConfig} onSort={toggleSort} />
            </div>
          </div>
        )}

        {step === "result" && result && (
          <div className="text-center py-8">
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-green-100 mb-4">
              <Check className="h-8 w-8 text-green-600" />
            </div>
            <h3 className="text-lg font-medium mb-2">Изменения применены</h3>
            <p className="text-muted-foreground">
              Производственный план успешно обновлён.
            </p>
          </div>
        )}

        <DialogFooter className="shrink-0">
          {step === "preview" && (
            <>
              <Button variant="outline" onClick={reset} disabled={loading}>
                Назад
              </Button>
              <Button onClick={handleApply} disabled={loading}>
                {loading ? "Применение…" : "Применить изменения"}
              </Button>
            </>
          )}
          {step === "result" && (
            <Button onClick={handleClose}>Закрыть</Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
