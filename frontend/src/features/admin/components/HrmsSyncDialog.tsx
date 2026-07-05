import { useMemo, useState } from "react"
import {
  AlertTriangle,
  ArrowLeft,
  Calendar,
  CheckCircle2,
  Link2,
  Loader2,
  RefreshCw,
  Search,
  Settings2,
  UserMinus,
  UserPlus,
} from "lucide-react"

import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  toast,
} from "@/shared/ui"
import {
  getHrmsSettings,
  previewHrmsSync,
  saveHrmsSettings,
  syncHrmsEmployees,
  testHrmsConnection,
  type HrmsEmployee,
  type HrmsEmployeesCacheResponse,
  type HrmsSyncDiffEntry,
  type HrmsSyncPreviewResponse,
} from "../api"
import {
  buildHrmsServerAddress,
  findHrmsConnectionPreset,
  getHrmsConnectionPresets,
} from "../lib/hrmsConnectionPresets"
import {
  computeHrmsSyncDiff,
  getHrmsFieldLabel,
  hasHrmsSyncDiff,
  type HrmsSyncDiff,
} from "../lib/hrmsSyncDiff"
import { HrmsEmployeesTable } from "./HrmsEmployeesTable"

type DialogStep = "settings" | "preview" | "diff"

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—"
  return new Date(value).toLocaleString("ru-RU")
}

function StatusCard({
  label,
  value,
  hint,
}: {
  label: string
  value: string
  hint?: string
}) {
  return (
    <div className="rounded-lg border bg-muted/20 px-3 py-2.5">
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="text-sm font-medium mt-0.5">{value}</div>
      {hint ? <div className="text-[11px] text-muted-foreground mt-1">{hint}</div> : null}
    </div>
  )
}

function CacheStatusStrip({
  employeesCount,
  syncedAt,
  settingsUpdatedAt,
  linkedCount,
}: {
  employeesCount: number
  syncedAt: string | null
  settingsUpdatedAt: string | null
  linkedCount: number
}) {
  const items = [
    {
      label: "В кеше",
      value: employeesCount > 0 ? `${employeesCount} сотрудников` : "Пусто",
    },
    { label: "Синхр.", value: formatDateTime(syncedAt) },
    { label: "Настройки", value: formatDateTime(settingsUpdatedAt) },
    { label: "Учётных записей", value: String(linkedCount) },
  ]

  return (
    <div className="rounded-md border bg-muted/20 px-3 py-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
      {items.map((item) => (
        <span key={item.label} className="inline-flex items-center gap-1 whitespace-nowrap">
          <span className="text-muted-foreground">{item.label}:</span>
          <span className="font-medium text-foreground">{item.value}</span>
        </span>
      ))}
    </div>
  )
}

function DiffSection({
  title,
  count,
  tone,
  icon,
  children,
}: {
  title: string
  count: number
  tone: "emerald" | "red" | "amber" | "slate"
  icon: React.ReactNode
  children: React.ReactNode
}) {
  const styles = {
    emerald: {
      container: "border-emerald-500/20 bg-emerald-500/5",
      header: "border-emerald-500/20 text-emerald-700",
    },
    red: {
      container: "border-red-500/20 bg-red-500/5",
      header: "border-red-500/20 text-red-700",
    },
    amber: {
      container: "border-amber-500/20 bg-amber-500/5",
      header: "border-amber-500/20 text-amber-700",
    },
    slate: {
      container: "border-border bg-muted/20",
      header: "border-border text-foreground",
    },
  }[tone]

  if (count === 0) return null

  return (
    <div className={`rounded-lg border ${styles.container}`}>
      <div className={`flex items-center gap-2 px-3 py-2 border-b ${styles.header}`}>
        {icon}
        <span className="text-sm font-medium">{title}</span>
        <Badge variant="outline" className="ml-auto text-[11px] py-0">
          {count}
        </Badge>
      </div>
      <div className="max-h-44 overflow-y-auto divide-y">{children}</div>
    </div>
  )
}

function EmployeeRow({ employee }: { employee: HrmsEmployee }) {
  return (
    <div className="px-3 py-2 text-sm">
      <div className="font-medium">{employee.name}</div>
      <div className="text-xs text-muted-foreground mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5">
        <span>ID: {employee.id}</span>
        {employee.tab_number ? <span>Таб. № {employee.tab_number}</span> : null}
        {employee.position ? <span>{employee.position}</span> : null}
        {employee.department ? <span>{employee.department}</span> : null}
      </div>
    </div>
  )
}

function PreviewEmployeeRow({ employee }: { employee: HrmsSyncDiffEntry }) {
  return (
    <div className="px-3 py-2 text-sm">
      <div className="font-medium">{employee.name}</div>
      <div className="text-xs text-muted-foreground mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5">
        <span>ID: {employee.id}</span>
        {employee.tab_number ? <span>Таб. № {employee.tab_number}</span> : null}
        {employee.position ? <span>{employee.position}</span> : null}
        {employee.department ? <span>{employee.department}</span> : null}
      </div>
    </div>
  )
}

export interface HrmsSyncDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  employees: HrmsEmployee[]
  employeesSyncedAt: string | null
  linkedHrmsIds: Set<number>
  onEmployeesChange: (cache: HrmsEmployeesCacheResponse) => void
}

export function HrmsSyncDialog({
  open,
  onOpenChange,
  employees,
  employeesSyncedAt,
  linkedHrmsIds,
  onEmployeesChange,
}: HrmsSyncDialogProps) {
  const [step, setStep] = useState<DialogStep>("settings")
  const [baseUrl, setBaseUrl] = useState("")
  const [apiToken, setApiToken] = useState("admin")
  const [employeesUrl, setEmployeesUrl] = useState<string | null>(null)
  const [settingsUpdatedAt, setSettingsUpdatedAt] = useState<string | null>(null)
  const [loadingSavedSettings, setLoadingSavedSettings] = useState(false)
  const [savingSettings, setSavingSettings] = useState(false)
  const [testing, setTesting] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [lastTestCount, setLastTestCount] = useState<number | null>(null)
  const [lastTestUrl, setLastTestUrl] = useState<string | null>(null)
  const [syncDiff, setSyncDiff] = useState<HrmsSyncDiff | null>(null)
  const [syncedAt, setSyncedAt] = useState<string | null>(null)
  const [preview, setPreview] = useState<HrmsSyncPreviewResponse | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [applying, setApplying] = useState(false)

  const linkedRemovedCount = useMemo(() => {
    if (!syncDiff) return 0
    return syncDiff.removed.filter((employee) => linkedHrmsIds.has(employee.id)).length
  }, [syncDiff, linkedHrmsIds])

  const previewLinkedRemovedCount = useMemo(() => {
    if (!preview) return 0
    return preview.diff.removed.filter((employee) => linkedHrmsIds.has(employee.id)).length
  }, [preview, linkedHrmsIds])

  const handleLoadSavedSettings = async () => {
    setLoadingSavedSettings(true)
    try {
      const settings = await getHrmsSettings()
      setBaseUrl(settings.base_url ?? "")
      setApiToken(settings.api_token || "admin")
      setEmployeesUrl(settings.employees_url)
      setSettingsUpdatedAt(settings.updated_at)
      toast({
        variant: "success",
        title: "Настройки загружены",
        description: settings.employees_url
          ? `Сохранённый адрес: ${settings.employees_url}`
          : "Адрес HRMS в базе не задан",
      })
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (err instanceof Error ? err.message : "Не удалось загрузить настройки HRMS")
      toast({
        variant: "destructive",
        title: "Ошибка загрузки",
        description: detail,
      })
    } finally {
      setLoadingSavedSettings(false)
    }
  }

  const handleSaveSettings = async () => {
    setSavingSettings(true)
    try {
      const settings = await saveHrmsSettings({
        base_url: baseUrl.trim() || null,
        api_token: apiToken.trim() || null,
      })
      setBaseUrl(settings.base_url ?? "")
      setApiToken(settings.api_token || "admin")
      setEmployeesUrl(settings.employees_url)
      setSettingsUpdatedAt(settings.updated_at)
      toast({
        variant: "success",
        title: "Настройки сохранены",
        description: settings.employees_url
          ? `Адрес запроса: ${settings.employees_url}`
          : "Адрес HRMS очищен",
      })
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (err instanceof Error ? err.message : "Не удалось сохранить настройки")
      toast({
        variant: "destructive",
        title: "Ошибка сохранения",
        description: detail,
      })
    } finally {
      setSavingSettings(false)
    }
  }

  const handleTestConnection = async () => {
    const trimmed = baseUrl.trim()
    if (!trimmed) {
      toast({
        variant: "destructive",
        title: "Адрес не указан",
        description: "Введите адрес HRMS или выберите один из пресетов",
      })
      return
    }

    setTesting(true)
    try {
      const result = await testHrmsConnection({
        base_url: trimmed,
        api_token: apiToken.trim() || undefined,
      })
      const settings = await getHrmsSettings()
      setBaseUrl(settings.base_url ?? trimmed)
      setApiToken(settings.api_token || apiToken)
      setEmployeesUrl(settings.employees_url ?? result.request_url)
      setSettingsUpdatedAt(settings.updated_at)
      setLastTestCount(result.employee_count)
      setLastTestUrl(result.request_url)
      toast({
        variant: "success",
        title: "HRMS доступен",
        description: `Найдено ${result.employee_count} сотрудников`,
      })
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (err instanceof Error ? err.message : "Не удалось подключиться к HRMS")
      toast({
        variant: "destructive",
        title: "HRMS недоступен",
        description: detail,
      })
    } finally {
      setTesting(false)
    }
  }

  const handleApply = async () => {
    const snapshot = [...employees]
    setApplying(true)
    try {
      const cache = await syncHrmsEmployees()
      onEmployeesChange(cache)
      setSyncedAt(cache.synced_at)
      const diff = computeHrmsSyncDiff(snapshot, cache.employees)
      setSyncDiff(diff)
      setStep("diff")
      setPreview(null)
      toast({
        variant: "success",
        title: "Синхронизация завершена",
        description: hasHrmsSyncDiff(diff)
          ? `Загружено ${cache.employees.length} сотрудников, есть расхождения с предыдущим кешем`
          : `Загружено ${cache.employees.length} сотрудников, изменений нет`,
      })
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (err instanceof Error ? err.message : "HRMS недоступен или вернул пустой список")
      toast({
        variant: "destructive",
        title: "Синхронизация не выполнена",
        description: detail,
      })
      setStep("settings")
      setPreview(null)
    } finally {
      setApplying(false)
    }
  }

  const handlePreview = async () => {
    setPreviewing(true)
    try {
      const result = await previewHrmsSync()
      setPreview(result)
      setStep("preview")
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (err instanceof Error ? err.message : "Не удалось выполнить предпросмотр синхронизации")
      toast({
        variant: "destructive",
        title: "Предпросмотр не выполнен",
        description: detail,
      })
      setStep("settings")
      setPreview(null)
    } finally {
      setPreviewing(false)
    }
  }

  const handleCancelPreview = () => {
    setStep("settings")
    setPreview(null)
  }

  const busy = loadingSavedSettings || savingSettings || testing || syncing || previewing || applying
  const cacheSyncedAt = syncedAt ?? employeesSyncedAt
  const connectionPresets = useMemo(() => getHrmsConnectionPresets(), [])
  const activeConnectionPreset = findHrmsConnectionPreset(baseUrl, connectionPresets)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[95vw] lg:max-w-5xl max-h-[90vh] overflow-hidden flex flex-col p-0">
        <DialogHeader className="px-4 pt-4 pb-3 border-b shrink-0">
          <DialogTitle className="flex items-center gap-2 text-base">
            <Settings2 className="h-4 w-4 text-emerald-600" />
            {step === "settings" ? "Синхронизация HRMS" : step === "preview" ? "Предпросмотр синхронизации" : "Результат синхронизации"}
          </DialogTitle>
          <DialogDescription className="text-xs">
            {step === "settings"
              ? "Без автозапросов. Действия — вручную."
              : step === "preview"
                ? "Проверьте изменения перед применением."
                : "Сравнение кеша до и после синхронизации."}
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
          {step === "settings" ? (
            <>
              <section className="space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Подключение</h3>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-7 text-xs px-2"
                    onClick={() => void handleLoadSavedSettings()}
                    disabled={busy}
                  >
                    {loadingSavedSettings ? (
                      <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
                    ) : null}
                    Загрузить из БД
                  </Button>
                </div>
                <div className="space-y-2">
                  <div className="grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_7rem_minmax(0,1fr)] gap-x-2 gap-y-2 items-start">
                    <div className="space-y-1 min-w-0">
                      <label className="text-xs font-medium">Адрес HRMS</label>
                      <Input
                        value={baseUrl}
                        onChange={(e) => setBaseUrl(e.target.value)}
                        placeholder={buildHrmsServerAddress()}
                        className="bg-card h-8 text-sm"
                        disabled={busy}
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="text-xs font-medium">Токен</label>
                      <Input
                        value={apiToken}
                        onChange={(e) => setApiToken(e.target.value)}
                        placeholder="admin"
                        className="bg-card font-mono h-8 text-sm"
                        disabled={busy}
                      />
                    </div>
                    <div className="space-y-1 min-w-0">
                      <label className="text-xs font-medium">URL сотрудников</label>
                      <Input
                        value={employeesUrl ?? ""}
                        readOnly
                        placeholder="После сохранения или проверки"
                        className="bg-muted/30 text-muted-foreground h-8 text-sm"
                      />
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-[11px] text-muted-foreground">Основные:</span>
                    {connectionPresets.map((preset) => {
                      const isActive = activeConnectionPreset?.id === preset.id
                      return (
                        <Button
                          key={preset.id}
                          type="button"
                          variant={isActive ? "default" : "outline"}
                          size="sm"
                          className="h-6 px-2 text-[11px]"
                          title={preset.hint}
                          disabled={busy}
                          onClick={() => setBaseUrl(preset.value)}
                        >
                          {preset.label}
                        </Button>
                      )
                    })}
                  </div>
                </div>
              </section>

              <section className="space-y-2">
                <CacheStatusStrip
                  employeesCount={employees.length}
                  syncedAt={cacheSyncedAt}
                  settingsUpdatedAt={settingsUpdatedAt}
                  linkedCount={linkedHrmsIds.size}
                />
                {lastTestCount !== null ? (
                  <div className="rounded-md border border-emerald-500/20 bg-emerald-500/5 px-2.5 py-1.5 text-xs flex items-center gap-2 text-emerald-700">
                    <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
                    <span>
                      Проверка: <strong>{lastTestCount}</strong> сотрудников · {lastTestUrl}
                    </span>
                  </div>
                ) : null}
              </section>

              <section className="space-y-1.5 min-h-0 flex-1 flex flex-col">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Сотрудники в кеше</h3>
                <p className="text-[11px] text-muted-foreground">
                  Колонка «Учётная запись» — есть ли пользователь в системе.
                </p>
                <HrmsEmployeesTable />
              </section>
            </>
          ) : step === "preview" && preview ? (
            <>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <StatusCard label="Добавлено" value={String(preview.diff.added.length)} />
                <StatusCard label="Удалено" value={String(preview.diff.removed.length)} />
                <StatusCard label="Изменено" value={String(preview.diff.changed.length)} />
                <StatusCard label="Без изменений" value={String(preview.diff.unchanged_count)} />
              </div>

              {previewLinkedRemovedCount > 0 ? (
                <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2.5 text-sm flex items-start gap-2">
                  <AlertTriangle className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" />
                  <div>
                    <div className="font-medium text-amber-800">
                      Будет удалено {previewLinkedRemovedCount} привязанных сотрудников
                    </div>
                    <div className="text-xs text-amber-700 mt-0.5">
                      Связь с KTM-пользователями сохранится по hrms_employee_id, но карточка исчезнет из списка.
                    </div>
                  </div>
                </div>
              ) : null}

              {preview.diff.added.length === 0 && preview.diff.removed.length === 0 && preview.diff.changed.length === 0 ? (
                <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-4 py-6 text-center">
                  <CheckCircle2 className="h-8 w-8 text-emerald-600 mx-auto mb-2" />
                  <div className="font-medium">Расхождений нет</div>
                  <div className="text-sm text-muted-foreground mt-1">
                    Данные в HRMS совпадают с кешем — синхронизация не требуется.
                  </div>
                </div>
              ) : (
                <div className="space-y-3">
                  <DiffSection
                    title="Новые сотрудники"
                    count={preview.diff.added.length}
                    tone="emerald"
                    icon={<UserPlus className="h-4 w-4" />}
                  >
                    {preview.diff.added.map((employee) => (
                      <PreviewEmployeeRow key={employee.id} employee={employee} />
                    ))}
                  </DiffSection>

                  <DiffSection
                    title="Удалены из HRMS"
                    count={preview.diff.removed.length}
                    tone="red"
                    icon={<UserMinus className="h-4 w-4" />}
                  >
                    {preview.diff.removed.map((employee) => (
                      <div key={employee.id} className="px-3 py-2">
                        <PreviewEmployeeRow employee={employee} />
                        {linkedHrmsIds.has(employee.id) ? (
                          <div className="mt-1 flex items-center gap-1 text-[11px] text-amber-700">
                            <Link2 className="h-3 w-3" />
                            Привязан к пользователю KTM
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </DiffSection>

                  <DiffSection
                    title="Изменённые данные"
                    count={preview.diff.changed.length}
                    tone="amber"
                    icon={<RefreshCw className="h-4 w-4" />}
                  >
                    {preview.diff.changed.map(({ before, after, fields }) => (
                      <div key={after.id} className="px-3 py-2 text-sm">
                        <div className="font-medium">{after.name}</div>
                        <div className="text-xs text-muted-foreground mt-0.5">ID: {after.id}</div>
                        <div className="mt-2 space-y-1">
                          {fields.map((field) => (
                            <div key={field} className="flex flex-wrap items-center gap-2 text-xs">
                              <span className="text-muted-foreground min-w-28">{getHrmsFieldLabel(field)}:</span>
                              <span className="line-through text-red-500/80">
                                {(before[field] as string | undefined) || "—"}
                              </span>
                              <span>→</span>
                              <span className="text-emerald-700 font-medium">
                                {(after[field] as string | undefined) || "—"}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </DiffSection>
                </div>
              )}
            </>
          ) : syncDiff ? (
            <>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <StatusCard
                  label="Добавлено"
                  value={String(syncDiff.added.length)}
                />
                <StatusCard
                  label="Удалено"
                  value={String(syncDiff.removed.length)}
                />
                <StatusCard
                  label="Изменено"
                  value={String(syncDiff.changed.length)}
                />
                <StatusCard
                  label="Без изменений"
                  value={String(syncDiff.unchangedCount)}
                />
              </div>

              <div className="rounded-lg border bg-muted/20 px-3 py-2 text-sm flex items-center gap-2">
                <Calendar className="h-4 w-4 text-muted-foreground shrink-0" />
                <span>
                  Кеш обновлён: <strong>{formatDateTime(cacheSyncedAt)}</strong>
                </span>
              </div>

              {linkedRemovedCount > 0 ? (
                <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2.5 text-sm flex items-start gap-2">
                  <AlertTriangle className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" />
                  <div>
                    <div className="font-medium text-amber-800">Есть привязанные пользователи</div>
                    <div className="text-xs text-amber-700 mt-0.5">
                      {linkedRemovedCount} сотрудник(ов) исчезли из HRMS, но остаются привязанными к учётным записям KTM.
                    </div>
                  </div>
                </div>
              ) : null}

              {!hasHrmsSyncDiff(syncDiff) ? (
                <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-4 py-6 text-center">
                  <CheckCircle2 className="h-8 w-8 text-emerald-600 mx-auto mb-2" />
                  <div className="font-medium">Расхождений нет</div>
                  <div className="text-sm text-muted-foreground mt-1">
                    Данные в кеше полностью совпадают с предыдущей версией.
                  </div>
                </div>
              ) : (
                <div className="space-y-3">
                  <section className="space-y-2">
                    <h3 className="text-sm font-semibold">Обновлённый кеш</h3>
                    <HrmsEmployeesTable maxHeightClass="max-h-56" />
                  </section>
                  <DiffSection
                    title="Новые сотрудники"
                    count={syncDiff.added.length}
                    tone="emerald"
                    icon={<UserPlus className="h-4 w-4" />}
                  >
                    {syncDiff.added.map((employee) => (
                      <EmployeeRow key={employee.id} employee={employee} />
                    ))}
                  </DiffSection>

                  <DiffSection
                    title="Удалены из HRMS"
                    count={syncDiff.removed.length}
                    tone="red"
                    icon={<UserMinus className="h-4 w-4" />}
                  >
                    {syncDiff.removed.map((employee) => (
                      <div key={employee.id} className="px-3 py-2">
                        <EmployeeRow employee={employee} />
                        {linkedHrmsIds.has(employee.id) ? (
                          <div className="mt-1 flex items-center gap-1 text-[11px] text-amber-700">
                            <Link2 className="h-3 w-3" />
                            Привязан к пользователю KTM
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </DiffSection>

                  <DiffSection
                    title="Изменённые данные"
                    count={syncDiff.changed.length}
                    tone="amber"
                    icon={<RefreshCw className="h-4 w-4" />}
                  >
                    {syncDiff.changed.map(({ before, after, fields }) => (
                      <div key={after.id} className="px-3 py-2 text-sm">
                        <div className="font-medium">{after.name}</div>
                        <div className="text-xs text-muted-foreground mt-0.5">ID: {after.id}</div>
                        <div className="mt-2 space-y-1">
                          {fields.map((field) => (
                            <div key={field} className="flex flex-wrap items-center gap-2 text-xs">
                              <span className="text-muted-foreground min-w-28">{getHrmsFieldLabel(field)}:</span>
                              <span className="line-through text-red-500/80">
                                {(before[field] as string | undefined) || "—"}
                              </span>
                              <span>→</span>
                              <span className="text-emerald-700 font-medium">
                                {(after[field] as string | undefined) || "—"}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </DiffSection>
                </div>
              )}
            </>
          ) : null}
        </div>

        <DialogFooter className="px-4 py-3 border-t shrink-0 flex flex-col-reverse sm:flex-row sm:justify-between gap-2">
          {step === "diff" ? (
            <>
              <Button
                type="button"
                variant="outline"
                onClick={() => setStep("settings")}
                className="w-full sm:w-auto"
              >
                <ArrowLeft className="h-4 w-4 mr-1.5" />
                К настройкам
              </Button>
              <Button
                type="button"
                onClick={() => onOpenChange(false)}
                className="w-full sm:w-auto bg-violet-600 hover:bg-violet-500"
              >
                Готово
              </Button>
            </>
          ) : step === "preview" ? (
            <>
              <Button
                type="button"
                variant="outline"
                onClick={handleCancelPreview}
                disabled={applying}
                className="w-full sm:w-auto"
              >
                <ArrowLeft className="h-4 w-4 mr-1.5" />
                Отмена
              </Button>
              <Button
                type="button"
                onClick={() => void handleApply()}
                disabled={applying}
                className="w-full sm:w-auto bg-emerald-600 hover:bg-emerald-500"
              >
                {applying ? (
                  <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4 mr-1.5" />
                )}
                Применить
              </Button>
            </>
          ) : (
            <>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={busy}
                className="w-full sm:w-auto"
              >
                Закрыть
              </Button>
              <div className="flex flex-col sm:flex-row gap-2 w-full sm:w-auto">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => void handleSaveSettings()}
                  disabled={busy}
                  className="w-full sm:w-auto"
                >
                  {savingSettings ? <Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> : null}
                  Сохранить
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => void handleTestConnection()}
                  disabled={busy}
                  className="w-full sm:w-auto"
                >
                  {testing ? (
                    <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
                  ) : (
                    <Search className="h-4 w-4 mr-1.5" />
                  )}
                  Проверить
                </Button>
                <Button
                  type="button"
                  onClick={() => void handlePreview()}
                  disabled={busy}
                  className="w-full sm:w-auto bg-emerald-600 hover:bg-emerald-500"
                >
                  {previewing ? (
                    <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
                  ) : (
                    <RefreshCw className="h-4 w-4 mr-1.5" />
                  )}
                  Синхронизировать
                </Button>
              </div>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}