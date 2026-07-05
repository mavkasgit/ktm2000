import { useCallback, useEffect, useState, useMemo } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Users, Plus, Shield, MapPin, CheckCircle2, XCircle, Search, Edit2, Key, Power, Loader2, ArrowLeft, Ticket, Link, Settings2 } from "lucide-react"
import { useNavigate } from "react-router-dom"
import { useAuth } from "@/features/auth/hooks/useAuth"
import {
  listUsers,
  createUser,
  updateUser,
  resetPassword,
  getCachedHrmsEmployees,
  type CreateUserInput,
  type UpdateUserInput,
  type HrmsEmployee,
} from "../api"
import { HrmsSyncDialog } from "../components/HrmsSyncDialog"
import { listSections, type Section } from "@/shared/api/sections"
import type { User, UserRole } from "@/features/auth/api"
import { generateOTPApi } from "@/features/auth/api"
import {
  Button,
  Input,
  Badge,
  Card,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  SectionSelect,
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
  toast,
  SortableFilterHeader,
  TableCornerResetHeader,
  TableCornerResetCell,
  TablePaginationFooter,
  DATA_TABLE_STYLES,
} from "@/shared/ui"
import { useFilterableTable } from "@/shared/hooks/useFilterableTable"
import { usePaginatedTableQuery } from "@/shared/hooks/usePaginatedTableQuery"
import { pickColumnApiValue } from "@/shared/lib/columnFilterSearch"
import { queryKeys } from "@/shared/api/queryKeys"

const ROLE_LABELS: Record<UserRole, string> = {
  admin: "Администратор",
  planner: "Планировщик",
  section_manager: "Начальник участка",
  operator: "Оператор",
  viewer: "Наблюдатель",
  transporter: "Транспортировщик",
}

const ROLE_COLORS: Record<UserRole, string> = {
  admin: "bg-red-500/10 text-red-500 border-red-500/20",
  planner: "bg-blue-500/10 text-blue-500 border-blue-500/20",
  section_manager: "bg-purple-500/10 text-purple-500 border-purple-500/20",
  operator: "bg-amber-500/10 text-amber-500 border-amber-500/20",
  viewer: "bg-slate-500/10 text-slate-500 border-slate-500/20",
  transporter: "bg-teal-500/10 text-teal-500 border-teal-500/20",
}

const ROLE_LABEL_TO_API: Record<string, UserRole> = Object.fromEntries(
  Object.entries(ROLE_LABELS).map(([role, label]) => [label, role as UserRole]),
) as Record<string, UserRole>

type UserFilterField = "fullName" | "email" | "role" | "section" | "status"

function mapUserSortFieldToApi(field: UserFilterField): string {
  switch (field) {
    case "fullName":
      return "full_name"
    case "status":
      return "is_active"
    default:
      return field
  }
}

function buildUsersColumnApiParams(
  columnFilters: Partial<Record<UserFilterField, Set<string>>>,
  columnSearchQueries: Partial<Record<UserFilterField, string>>,
): {
  full_name?: string
  email?: string
  role?: string
  section?: string
  is_active?: boolean
} {
  const params: {
    full_name?: string
    email?: string
    role?: string
    section?: string
    is_active?: boolean
  } = {}

  const fullName = pickColumnApiValue(columnFilters, columnSearchQueries, "fullName")
  if (fullName) params.full_name = fullName

  const email = pickColumnApiValue(columnFilters, columnSearchQueries, "email")
  if (email) params.email = email

  const roleLabel = pickColumnApiValue(columnFilters, columnSearchQueries, "role")
  if (roleLabel && ROLE_LABEL_TO_API[roleLabel]) {
    params.role = ROLE_LABEL_TO_API[roleLabel]
  }

  const section = pickColumnApiValue(columnFilters, columnSearchQueries, "section", (value) =>
    value === "—" ? undefined : value,
  )
  if (section) params.section = section

  const statusLabel = pickColumnApiValue(columnFilters, columnSearchQueries, "status")
  if (statusLabel === "Активен") params.is_active = true
  if (statusLabel === "Заблокирован") params.is_active = false

  return params
}

function getUserSectionLabel(user: User, sectionMap: Map<number, Section>): string {
  const ids = user.section_ids?.length
    ? user.section_ids
    : user.section_id
      ? [user.section_id]
      : []
  if (ids.length === 0) return "—"
  return ids
    .map((id) => sectionMap.get(id)?.code ?? String(id))
    .sort((a, b) => a.localeCompare(b, "ru"))
    .join(", ")
}

const getSessionDurationLabel = (seconds: number | null) => {
  if (seconds === null) return "30 мин"
  if (seconds === -1) return "Бессрочно"
  if (seconds === 1800) return "30 мин"
  if (seconds === 28800) return "8 ч"
  if (seconds === 86400) return "24 ч"
  if (seconds === 604800) return "7 дн"
  return `${Math.round(seconds / 3600)} ч`
}

export function UsersPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { user: currentUser } = useAuth()

  const [sections, setSections] = useState<Section[]>([])
  const [sectionsLoading, setSectionsLoading] = useState(true)
  const [error, setError] = useState("")
  const [search, setSearch] = useState("")
  const [debouncedSearch, setDebouncedSearch] = useState("")

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search), 300)
    return () => window.clearTimeout(timer)
  }, [search])

  const {
    bindColumn,
    columnFilters,
    columnSearchQueries,
    sortConfigs,
    handleSort,
    resetAll,
    hasActiveFilters: hasTableFiltersActive,
  } = useFilterableTable<UserFilterField>({
    extraHasActive: search.trim().length > 0,
    onExtraReset: () => setSearch(""),
  })

  const columnApiParams = useMemo(
    () => buildUsersColumnApiParams(columnFilters, columnSearchQueries),
    [columnFilters, columnSearchQueries],
  )

  const pagination = usePaginatedTableQuery({
    resetPageDeps: [
      debouncedSearch,
      columnFilters,
      columnSearchQueries,
      sortConfigs,
    ],
  })

  const activeSort = sortConfigs[0]
  const usersQueryParams = useMemo(
    () => ({
      limit: pagination.limit,
      offset: pagination.offset,
      search: debouncedSearch.trim() || undefined,
      sort_by: activeSort ? mapUserSortFieldToApi(activeSort.field) : "id",
      sort_order: activeSort?.order ?? "asc",
      ...columnApiParams,
    }),
    [
      pagination.limit,
      pagination.offset,
      debouncedSearch,
      activeSort,
      columnApiParams,
    ],
  )

  const { data: usersData, isLoading: usersLoading, refetch: refetchUsers } = useQuery({
    queryKey: queryKeys.users.list(usersQueryParams),
    queryFn: () => listUsers(usersQueryParams),
  })

  const users = usersData?.users ?? []
  const total = usersData?.total ?? 0
  const totalPages = pagination.getTotalPages(total)
  const linkedHrmsIds = useMemo(
    () => new Set(usersData?.linked_hrms_ids ?? []),
    [usersData?.linked_hrms_ids],
  )

  // Состояние диалога создания/редактирования
  const [dialogOpen, setDialogOpen] = useState(false)
  const [dialogMode, setDialogMode] = useState<"create" | "edit">("create")
  const [selectedUser, setSelectedUser] = useState<User | null>(null)

  // Поля формы пользователя
  const [username, setUsername] = useState("")
  const [email, setEmail] = useState("")
  const [fullName, setFullName] = useState("")
  const [password, setPassword] = useState("")
  const [role, setRole] = useState<UserRole>("viewer")
  const [sectionIds, setSectionIds] = useState<number[]>([])
  const [isActive, setIsActive] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [hrmsAccessLevel, setHrmsAccessLevel] = useState<string>("no_access")
  
  // Дополнительные состояния для привязки к сотрудникам HRMS (кеш в БД, синхронизация по кнопке)
  const [hrmsEmployeeId, setHrmsEmployeeId] = useState("")
  const [employees, setEmployees] = useState<HrmsEmployee[]>([])
  const [employeesSyncedAt, setEmployeesSyncedAt] = useState<string | null>(null)
  const [employeesLoading, setEmployeesLoading] = useState(false)
  const [hrmsSyncDialogOpen, setHrmsSyncDialogOpen] = useState(false)
  const [linkEmployee, setLinkEmployee] = useState(false)

  // Состояние диалога сброса пароля
  const [resetDialogOpen, setResetDialogOpen] = useState(false)
  const [newPassword, setNewPassword] = useState("")
  const [resettingUser, setResettingUser] = useState<User | null>(null)
  const [resetSubmitting, setResetSubmitting] = useState(false)

  // Состояния для диалога OTP
  const [otpDialogOpen, setOtpDialogOpen] = useState(false)
  const [otpUser, setOtpUser] = useState<User | null>(null)
  const [otpDuration, setOtpDuration] = useState<number | null>(28800) // 8 часов по умолчанию
  const [otpCode, setOtpCode] = useState<string | null>(null)
  const [otpLoading, setOtpLoading] = useState(false)

  const openOTPDialog = (user: User) => {
    setOtpUser(user)
    setOtpCode(null)
    setOtpDuration(28800)
    setOtpDialogOpen(true)
  }

  const handleGenerateOTP = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!otpUser) return
    setOtpLoading(true)
    try {
      const response = await generateOTPApi({
        user_id: otpUser.id,
        session_duration_seconds: otpDuration,
        code_lifetime_seconds: 600, // 10 минут
      })
      setOtpCode(response.token)
      toast({
        variant: "success",
        title: "Код входа сгенерирован",
        description: `Временный код для ${otpUser.username} успешно создан.`,
      })
    } catch (err: any) {
      toast({
        variant: "destructive",
        title: "Ошибка генерации",
        description: err?.response?.data?.detail || err.message || "Не удалось сгенерировать код",
      })
    } finally {
      setOtpLoading(false)
    }
  }

  const loadSections = async () => {
    setSectionsLoading(true)
    setError("")
    try {
      const sectionsData = await listSections()
      setSections(sectionsData)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить данные")
      toast({
        variant: "destructive",
        title: "Ошибка загрузки",
        description: "Не удалось загрузить участки.",
      })
    } finally {
      setSectionsLoading(false)
    }
  }

  const refreshUsers = async () => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.users.list() })
    await refetchUsers()
  }

  const applyEmployeesCache = useCallback((cache: { employees: HrmsEmployee[]; synced_at: string | null }) => {
    setEmployees(cache.employees)
    setEmployeesSyncedAt(cache.synced_at)
  }, [])

  const loadCachedEmployees = async () => {
    setEmployeesLoading(true)
    try {
      const cache = await getCachedHrmsEmployees()
      applyEmployeesCache(cache)
    } catch (err: any) {
      toast({
        variant: "destructive",
        title: "Ошибка загрузки кеша",
        description: err?.response?.data?.detail || err.message || "Не удалось загрузить кеш сотрудников HRMS.",
      })
    } finally {
      setEmployeesLoading(false)
    }
  }

  useEffect(() => {
    void loadSections()
    void loadCachedEmployees()
  }, [])

  // Карта участков для быстрого поиска названий
  const sectionMap = useMemo(() => {
    const map = new Map<number, Section>()
    sections.forEach((s) => map.set(s.id, s))
    return map
  }, [sections])

  const uniqueValues = useMemo(
    () => ({
      fullName: [...new Set(users.map((u) => u.full_name))].sort((a, b) =>
        a.localeCompare(b, "ru"),
      ),
      email: [...new Set(users.map((u) => u.email))].sort((a, b) =>
        a.localeCompare(b, "ru"),
      ),
      role: [...new Set(users.map((u) => ROLE_LABELS[u.role]))].sort((a, b) =>
        a.localeCompare(b, "ru"),
      ),
      section: [...new Set(users.map((u) => getUserSectionLabel(u, sectionMap)))].sort((a, b) =>
        a.localeCompare(b, "ru"),
      ),
      status: [...new Set(users.map((u) => (u.is_active ? "Активен" : "Заблокирован")))].sort(),
    }),
    [users, sectionMap],
  )

  const loading = usersLoading || sectionsLoading
  const headerCellClass = `${DATA_TABLE_STYLES.headerRow} ${DATA_TABLE_STYLES.headerCell}`

  const openCreate = () => {
    setSelectedUser(null)
    setDialogMode("create")
    setUsername("")
    setEmail("")
    setFullName("")
    setPassword("")
    setRole("viewer")
    setSectionIds([])
    setIsActive(true)
    setHrmsEmployeeId("none")
    setLinkEmployee(false)
    setHrmsAccessLevel("no_access")
    setDialogOpen(true)
  }

  const openEdit = (user: User) => {
    setSelectedUser(user)
    setDialogMode("edit")
    setUsername(user.username)
    setEmail(user.email)
    setFullName(user.full_name)
    setPassword("")
    setRole(user.role)
    setSectionIds(user.section_ids || (user.section_id ? [user.section_id] : []))
    setIsActive(user.is_active)
    setHrmsEmployeeId(user.hrms_employee_id?.toString() || "none")
    setLinkEmployee(!!user.hrms_employee_id)
    setHrmsAccessLevel(user.hrms_access_level || "no_access")
    setDialogOpen(true)
  }

  const openResetPassword = (user: User) => {
    setResettingUser(user)
    setNewPassword("")
    setResetDialogOpen(true)
  }

  const handleSaveUser = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitting(true)

    try {
      if (dialogMode === "create") {
        const payload: CreateUserInput = {
          username: username.trim(),
          email: email.trim(),
          password: password || undefined,
          full_name: fullName.trim(),
          role,
          section_id: ["section_manager", "operator"].includes(role) && sectionIds.length > 0 ? sectionIds[0] : null,
          section_ids: ["section_manager", "operator"].includes(role) ? sectionIds : [],
          hrms_employee_id: linkEmployee && hrmsEmployeeId !== "none" ? Number(hrmsEmployeeId) : null,
          hrms_access_level: hrmsAccessLevel,
        }
        await createUser(payload)
        toast({
          variant: "success",
          title: "Пользователь создан",
          description: `Учетная запись с логином ${username} успешно добавлена.`,
        })
      } else if (dialogMode === "edit" && selectedUser) {
        const payload: UpdateUserInput = {
          username: username.trim(),
          full_name: fullName.trim(),
          role: selectedUser.id === currentUser?.id ? undefined : role, // Запрет смены роли самому себе
          section_id: ["section_manager", "operator"].includes(role) && sectionIds.length > 0 ? sectionIds[0] : null,
          section_ids: ["section_manager", "operator"].includes(role) ? sectionIds : [],
          is_active: selectedUser.id === currentUser?.id ? undefined : isActive, // Запрет деактивации самого себя
          hrms_employee_id: linkEmployee && hrmsEmployeeId !== "none" ? Number(hrmsEmployeeId) : null,
          hrms_access_level: hrmsAccessLevel,
        }
        await updateUser(selectedUser.id, payload)
        toast({
          variant: "success",
          title: "Профиль обновлен",
          description: `Данные пользователя ${username} успешно сохранены.`,
        })
      }
      setDialogOpen(false)
      await refreshUsers()
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err.message || "Не удалось сохранить изменения"
      toast({
        variant: "destructive",
        title: "Ошибка сохранения",
        description: detail,
      })
    } finally {
      setSubmitting(false)
    }
  }

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!resettingUser || !newPassword.trim()) return
    setResetSubmitting(true)

    try {
      await resetPassword(resettingUser.id, newPassword.trim())
      toast({
        variant: "success",
        title: "Пароль изменен",
        description: `Пароль пользователя ${resettingUser.username} успешно изменен.`,
      })
      setResetDialogOpen(false)
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err.message || "Не удалось сбросить пароль"
      toast({
        variant: "destructive",
        title: "Ошибка смены пароля",
        description: detail,
      })
    } finally {
      setResetSubmitting(false)
    }
  }

  const handleClearPassword = async () => {
    if (!resettingUser) return
    setResetSubmitting(true)

    try {
      await resetPassword(resettingUser.id, "")
      toast({
        variant: "success",
        title: "Пароль очищен",
        description: `Пароль пользователя ${resettingUser.username} успешно очищен. Профиль переведен в статус активации.`,
      })
      setResetDialogOpen(false)
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err.message || "Не удалось очистить пароль"
      toast({
        variant: "destructive",
        title: "Ошибка очистки пароля",
        description: detail,
      })
    } finally {
      setResetSubmitting(false)
    }
  }

  const handleToggleActive = async (user: User) => {
    if (user.id === currentUser?.id) {
      toast({
        variant: "destructive",
        title: "Ошибка",
        description: "Вы не можете деактивировать собственную учетную запись.",
      })
      return
    }

    try {
      const newStatus = !user.is_active
      await updateUser(user.id, { is_active: newStatus })
      toast({
        variant: "success",
        title: newStatus ? "Пользователь активирован" : "Пользователь заблокирован",
        description: `Статус пользователя ${user.username} успешно изменен.`,
      })
      await refreshUsers()
    } catch (err: any) {
      toast({
        variant: "destructive",
        title: "Ошибка изменения статуса",
        description: err?.response?.data?.detail || err.message || "Не удалось изменить статус",
      })
    }
  }

  // Показывать ли поле "Участок" (только для начальника участка и оператора)
  const showSectionField = ["section_manager", "operator"].includes(role)

  return (
    <div className="space-y-6">
      {/* Шапка */}
      <header className="border-b pb-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <div
              className="flex items-center gap-2 text-sm text-muted-foreground mb-1 cursor-pointer hover:text-foreground transition-colors"
              onClick={() => navigate("/settings")}
            >
              <ArrowLeft className="h-4 w-4" />
              <span>Назад в настройки</span>
            </div>
            <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2.5">
              <Users className="h-6 w-6 text-violet-500" />
              Пользователи системы
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              Управление учетными записями, ролями и привязкой сотрудников к участкам.
            </p>
          </div>

          <div className="flex flex-col items-stretch sm:items-end gap-2 shrink-0">
            <p className="text-xs text-muted-foreground text-right flex items-center justify-end gap-1.5">
              <Link className="h-3.5 w-3.5 text-emerald-600 shrink-0" />
              <span>
                {employeesLoading
                  ? "Загрузка кеша HRMS..."
                  : employeesSyncedAt
                    ? `HRMS: ${employees.length} в кеше · ${new Date(employeesSyncedAt).toLocaleString("ru-RU")}`
                    : employees.length > 0
                      ? `HRMS: ${employees.length} в кеше`
                      : "Кеш HRMS пуст"}
              </span>
            </p>
            <div className="flex flex-wrap items-center justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setHrmsSyncDialogOpen(true)}
                disabled={employeesLoading}
              >
                <Settings2 className="h-4 w-4 mr-1.5" />
                HRMS
              </Button>
              <Button
                size="sm"
                onClick={openCreate}
                className="bg-violet-600 hover:bg-violet-500 shadow-md shadow-violet-600/10"
              >
                <Plus className="h-4 w-4 mr-1.5" />
                Добавить пользователя
              </Button>
            </div>
          </div>
        </div>
      </header>

      {/* Панель поиска */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 bg-card"
          />
        </div>
        <Button variant="outline" onClick={resetAll} disabled={!hasTableFiltersActive}>
          Сбросить фильтры
        </Button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* Список пользователей */}
      {loading ? (
        <div className="flex flex-col items-center justify-center py-20 gap-3">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          <span className="text-sm text-muted-foreground">Загрузка списка пользователей...</span>
        </div>
      ) : total === 0 && !debouncedSearch.trim() && !hasTableFiltersActive ? (
        <Card className="flex flex-col items-center justify-center py-16 text-center border-dashed">
          <Users className="h-10 w-10 text-muted-foreground/40 mb-3" />
          <h3 className="font-semibold text-lg">Пользователи не найдены</h3>
          <p className="text-sm text-muted-foreground max-w-sm mt-1">
            {search ? "Попробуйте изменить поисковый запрос." : "Добавьте первого пользователя, нажав кнопку выше."}
          </p>
        </Card>
      ) : (
        <div className="border rounded-xl overflow-hidden bg-card shadow-sm">
          <div className={DATA_TABLE_STYLES.container}>
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr>
                  <th className={`${headerCellClass} p-0 px-6 text-left`}>
                    <SortableFilterHeader<UserFilterField>
                      field="fullName"
                      label="ФИО / Логин"
                      currentSorts={sortConfigs}
                      onSortChange={handleSort}
                      values={uniqueValues.fullName}
                      {...bindColumn("fullName")}
                    />
                  </th>
                  <th className={`${headerCellClass} p-0 px-6 text-left`}>
                    <SortableFilterHeader<UserFilterField>
                      field="email"
                      label="Email"
                      currentSorts={sortConfigs}
                      onSortChange={handleSort}
                      values={uniqueValues.email}
                      {...bindColumn("email")}
                    />
                  </th>
                  <th className={`${headerCellClass} p-0 px-6 text-left`}>
                    <SortableFilterHeader<UserFilterField>
                      field="role"
                      label="Роль"
                      currentSorts={sortConfigs}
                      onSortChange={handleSort}
                      values={uniqueValues.role}
                      {...bindColumn("role")}
                    />
                  </th>
                  <th className={`${headerCellClass} p-0 px-6 text-left`}>
                    <SortableFilterHeader<UserFilterField>
                      field="section"
                      label="Закреплен за участком"
                      currentSorts={sortConfigs}
                      onSortChange={handleSort}
                      values={uniqueValues.section}
                      {...bindColumn("section")}
                    />
                  </th>
                  <th className={`${headerCellClass} p-0 px-6 text-left w-36`}>
                    <SortableFilterHeader<UserFilterField>
                      field="status"
                      label="Статус"
                      currentSorts={sortConfigs}
                      onSortChange={handleSort}
                      values={uniqueValues.status}
                      {...bindColumn("status")}
                    />
                  </th>
                  <th className={`${headerCellClass} px-6 text-right w-48`}>
                    <span className="text-xs font-medium text-muted-foreground">Действия</span>
                  </th>
                  <TableCornerResetHeader
                    hasActiveFilters={hasTableFiltersActive}
                    onReset={resetAll}
                    dataTableHeader
                  />
                </tr>
              </thead>
              <tbody className="divide-y">
                {users.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-6 py-8 text-center text-sm text-muted-foreground">
                      Пользователи не найдены по текущим фильтрам
                    </td>
                  </tr>
                ) : users.map((userItem) => {
                  const s = userItem.section_id ? sectionMap.get(userItem.section_id) : null
                  const isSelf = userItem.id === currentUser?.id

                  return (
                    <tr key={userItem.id} className="hover:bg-muted/30 transition-colors">
                      <td className="px-6 py-4">
                        <div className="font-medium text-foreground">
                          {userItem.full_name}
                          {isSelf && (
                            <Badge variant="secondary" className="ml-2 text-[10px] py-0 px-1.5 bg-violet-500/10 text-violet-500 border-violet-500/20">
                              Это вы
                            </Badge>
                          )}
                          {userItem.hrms_employee_id && (
                            <Badge variant="outline" className="ml-2 text-[10px] py-0.5 px-1.5 bg-emerald-500/10 text-emerald-600 border-emerald-500/20 font-medium rounded-md">
                              <Link className="h-3 w-3 mr-0.5 inline" />
                              HRMS
                            </Badge>
                          )}
                        </div>
                        <div className="text-xs text-muted-foreground mt-0.5 flex flex-wrap items-center gap-x-2">
                          <span>Логин: <strong className="text-foreground">{userItem.username}</strong></span>
                        </div>
                        {userItem.active_login_token && (
                          <div className="mt-1.5 flex items-center gap-1.5">
                            <Badge variant="outline" className="text-[10px] py-0.5 px-2 bg-violet-500/10 text-violet-600 border-violet-500/20 font-medium rounded-md">
                              Код: <span className="font-mono font-bold select-all ml-1 text-violet-700">{userItem.active_login_token.token}</span>
                            </Badge>
                            <span className="text-[10px] text-muted-foreground">
                              ({getSessionDurationLabel(userItem.active_login_token.session_duration_seconds)})
                            </span>
                          </div>
                        )}
                      </td>
                      <td className="px-6 py-4 text-muted-foreground">
                        {userItem.email}
                      </td>
                      <td className="px-6 py-4">
                        <Badge variant="outline" className={`font-normal rounded-full ${ROLE_COLORS[userItem.role]}`}>
                          <Shield className="h-3.5 w-3.5 mr-1" />
                          {ROLE_LABELS[userItem.role]}
                        </Badge>
                        <div className="mt-1">
                          <Badge variant="outline" className={`text-[10px] py-0.5 px-2 font-medium rounded-md ${
                            userItem.hrms_access_level === "admin"
                              ? "bg-red-500/10 text-red-500 border-red-500/20"
                              : userItem.hrms_access_level === "viewer"
                              ? "bg-blue-500/10 text-blue-500 border-blue-500/20"
                              : "bg-slate-500/10 text-slate-500 border-slate-500/20"
                          }`}>
                            HRMS: {
                              userItem.hrms_access_level === "admin"
                                ? "Полный доступ"
                                : userItem.hrms_access_level === "viewer"
                                ? "Только просмотр"
                                : "Нет доступа"
                            }
                          </Badge>
                        </div>
                      </td>
                      <td className="px-6 py-4 text-muted-foreground">
                        {userItem.section_ids && userItem.section_ids.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {userItem.section_ids.map((sid) => {
                              const s = sectionMap.get(sid)
                              if (!s) return null
                              return (
                                <div key={sid} className="flex items-center gap-1 text-foreground border rounded-full px-2 py-0.5 text-xs bg-muted/40">
                                  <span
                                    className="inline-flex h-3.5 w-3.5 items-center justify-center rounded-full text-[9px]"
                                    style={{
                                      backgroundColor: `${s.icon_color || "#3b82f6"}20`,
                                      color: s.icon_color || "#3b82f6",
                                    }}
                                  >
                                    <MapPin className="h-2.5 w-2.5" />
                                  </span>
                                  <span>{s.code}</span>
                                </div>
                              )
                            })}
                          </div>
                        ) : s ? (
                          <div className="flex items-center gap-1 text-foreground border rounded-full px-2 py-0.5 text-xs bg-muted/40 max-w-max">
                            <span
                              className="inline-flex h-3.5 w-3.5 items-center justify-center rounded-full text-[9px]"
                              style={{
                                backgroundColor: `${s.icon_color || "#3b82f6"}20`,
                                color: s.icon_color || "#3b82f6",
                              }}
                            >
                              <MapPin className="h-2.5 w-2.5" />
                            </span>
                            <span>{s.code}</span>
                          </div>
                        ) : (
                          <span className="text-xs text-muted-foreground/60">—</span>
                        )}
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-1.5">
                          {userItem.is_active ? (
                            <span className="inline-flex items-center text-xs font-medium text-emerald-500 gap-1 bg-emerald-500/10 py-1 px-2.5 rounded-full border border-emerald-500/20">
                              <CheckCircle2 className="h-3.5 w-3.5" />
                              Активен
                            </span>
                          ) : (
                            <span className="inline-flex items-center text-xs font-medium text-red-500 gap-1 bg-red-500/10 py-1 px-2.5 rounded-full border border-red-500/20">
                              <XCircle className="h-3.5 w-3.5" />
                              Заблокирован
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-6 py-4 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-8 w-8 p-0"
                            onClick={() => openEdit(userItem)}
                            title="Редактировать профиль"
                          >
                            <Edit2 className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-8 w-8 p-0"
                            onClick={() => openResetPassword(userItem)}
                            title="Сбросить пароль"
                          >
                            <Key className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-8 w-8 p-0 text-violet-500 hover:text-violet-600 hover:bg-violet-500/10"
                            onClick={() => openOTPDialog(userItem)}
                            title="Временный код входа"
                          >
                            <Ticket className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            className={`h-8 w-8 p-0 ${
                              userItem.is_active
                                ? "text-red-500 hover:text-red-600 hover:bg-red-500/10"
                                : "text-emerald-500 hover:text-emerald-600 hover:bg-emerald-500/10"
                            }`}
                            onClick={() => handleToggleActive(userItem)}
                            disabled={isSelf}
                            title={userItem.is_active ? "Заблокировать" : "Разблокировать"}
                          >
                            <Power className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </td>
                      <TableCornerResetCell />
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <TablePaginationFooter
            page={pagination.page}
            totalPages={totalPages}
            total={total}
            shownCount={users.length}
            limit={pagination.limit}
            onPageChange={pagination.setPage}
            onLimitChange={pagination.setLimit}
            rangeLabel={pagination.getRangeLabel(users.length, total, { onPage: true })}
          />
        </div>
      )}

      <HrmsSyncDialog
        open={hrmsSyncDialogOpen}
        onOpenChange={setHrmsSyncDialogOpen}
        employees={employees}
        employeesSyncedAt={employeesSyncedAt}
        linkedHrmsIds={linkedHrmsIds}
        onEmployeesChange={applyEmployeesCache}
      />

      {/* Диалог создания/редактирования */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>
              {dialogMode === "create" ? "Новый пользователь" : "Редактирование профиля"}
            </DialogTitle>
            <DialogDescription>
              {dialogMode === "create"
                ? "Заполните форму для создания новой учетной записи сотрудника."
                : "Внесите изменения в данные профиля сотрудника."}
            </DialogDescription>
          </DialogHeader>

          <form onSubmit={handleSaveUser} className="space-y-4 pt-2">
            {/* Опция привязки к сотруднику */}
            <div className="flex items-center gap-2 pt-1">
              <input
                type="checkbox"
                id="link-employee-chk"
                checked={linkEmployee}
                onChange={(e) => {
                  setLinkEmployee(e.target.checked)
                  if (!e.target.checked) {
                    setHrmsEmployeeId("none")
                  }
                }}
                className="h-4 w-4 rounded border-gray-300 text-violet-600 focus:ring-violet-500"
              />
              <label htmlFor="link-employee-chk" className="text-sm font-medium text-foreground cursor-pointer select-none">
                Связать с сотрудником из HRMS
              </label>
            </div>

            {/* Выбор сотрудника */}
            {linkEmployee && (
              <div className="space-y-1.5">
                <label className="text-sm font-medium">Выберите сотрудника</label>
                <p className="text-[11px] text-muted-foreground">
                  Список берётся из локального кеша HRMS
                  {employeesSyncedAt
                    ? ` (обновлён ${new Date(employeesSyncedAt).toLocaleString("ru-RU")})`
                    : employees.length > 0
                      ? ` (${employees.length} в кеше)`
                      : ". Сначала выполните синхронизацию HRMS."}
                  {" "}
                  <button
                    type="button"
                    className="text-violet-600 hover:underline"
                    onClick={() => setHrmsSyncDialogOpen(true)}
                  >
                    Открыть HRMS
                  </button>
                </p>
                <Select
                  value={hrmsEmployeeId}
                  onValueChange={(val) => {
                    setHrmsEmployeeId(val)
                    if (val !== "none") {
                      const emp = employees.find((e) => e.id.toString() === val)
                      if (emp) {
                        setFullName(emp.name)
                        // Автозаполнение
                        if (!username) {
                          setUsername(`emp_${val}`)
                        }
                        if (!email) {
                          setEmail(`emp_${val}@ktm2000.local`)
                        }
                      }
                    }
                  }}
                >
                  <SelectTrigger className="w-full bg-card">
                    <SelectValue placeholder="Сотрудник не выбран" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">Выберите сотрудника...</SelectItem>
                    {employees.map((e) => (
                      <SelectItem key={e.id} value={e.id.toString()}>
                        {e.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            {/* ФИО */}
            <div className="space-y-1.5">
              <label htmlFor="user-name" className="text-sm font-medium">ФИО сотрудника</label>
              <Input
                id="user-name"
                type="text"
                required
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                disabled={linkEmployee && hrmsEmployeeId !== "none"}
              />
            </div>

            {/* Имя пользователя (Логин) */}
            <div className="space-y-1.5">
              <label htmlFor="user-username" className="text-sm font-medium">Имя пользователя (Логин)</label>
              <Input
                id="user-username"
                type="text"
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </div>

            {/* Email */}
            <div className="space-y-1.5">
              <label htmlFor="user-email" className="text-sm font-medium">Электронная почта</label>
              <Input
                id="user-email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>

            {/* Пароль (только при создании) */}
            {dialogMode === "create" && (
              <div className="space-y-1.5">
                <label htmlFor="user-password" className="text-sm font-medium">Временный пароль</label>
                <Input
                  id="user-password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <p className="text-xs text-muted-foreground mt-1">
                  Оставьте пустым, чтобы пользователь создал пароль самостоятельно при первом входе по коду
                </p>
              </div>
            )}

            {/* Роль */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium">Роль в системе</label>
              <Select
                value={role}
                onValueChange={(v) => {
                  setRole(v as UserRole)
                  if (!["section_manager", "operator"].includes(v)) {
                    setSectionIds([])
                  }
                }}
                disabled={selectedUser?.id === currentUser?.id}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Выберите роль" />
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(ROLE_LABELS).map(([key, label]) => (
                    <SelectItem key={key} value={key}>
                      {label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Доступ к HRMS */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium">Доступ к HRMS</label>
              <Select
                value={hrmsAccessLevel}
                onValueChange={(v) => setHrmsAccessLevel(v)}
              >
                <SelectTrigger className="w-full bg-card">
                  <SelectValue placeholder="Выберите уровень доступа" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="no_access">Нет доступа</SelectItem>
                  <SelectItem value="viewer">Только просмотр</SelectItem>
                  <SelectItem value="admin">Полный доступ</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Участок (зависит от роли) */}
            {showSectionField && (
              <div className="space-y-2">
                <label className="text-sm font-medium">Участки ответственности</label>
                <div className="border rounded-lg p-3 space-y-2 max-h-48 overflow-y-auto bg-muted/10">
                  {sections.length === 0 ? (
                    <div className="text-xs text-muted-foreground text-center py-4">Нет доступных участков</div>
                  ) : (
                    sections.map((s) => {
                      const isChecked = sectionIds.includes(s.id)
                      return (
                        <label
                          key={s.id}
                          className={`flex items-center justify-between p-2 rounded-md border cursor-pointer transition-all hover:bg-muted/40 ${
                            isChecked ? "border-violet-500 bg-violet-500/5" : "border-border"
                          }`}
                        >
                          <div className="flex items-center gap-2">
                            <input
                              type="checkbox"
                              checked={isChecked}
                              onChange={(e) => {
                                if (e.target.checked) {
                                  setSectionIds([...sectionIds, s.id])
                                } else {
                                  setSectionIds(sectionIds.filter((id) => id !== s.id))
                                }
                              }}
                              className="rounded border-gray-300 text-violet-600 focus:ring-violet-500 h-4 w-4"
                            />
                            <span className="text-sm font-medium">{s.code}</span>
                            <span className="text-xs text-muted-foreground">— {s.name}</span>
                          </div>
                          <span
                            className="h-2 w-2 rounded-full"
                            style={{ backgroundColor: s.icon_color || "#3b82f6" }}
                          />
                        </label>
                      )
                    })
                  )}
                </div>
              </div>
            )}

            {/* Статус активности (только при редактировании) */}
            {dialogMode === "edit" && selectedUser?.id !== currentUser?.id && (
              <div className="flex items-center justify-between border rounded-lg p-3 bg-muted/20">
                <div>
                  <div className="text-sm font-medium">Статус аккаунта</div>
                  <div className="text-xs text-muted-foreground">Разрешен ли вход в систему</div>
                </div>
                <Button
                  type="button"
                  variant={isActive ? "outline" : "destructive"}
                  size="sm"
                  onClick={() => setIsActive(!isActive)}
                >
                  {isActive ? "Активен" : "Заблокирован"}
                </Button>
              </div>
            )}

            <DialogFooter className="pt-4 flex gap-2">
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>
                Отмена
              </Button>
              <Button type="submit" disabled={submitting} className="bg-violet-600 hover:bg-violet-500">
                {submitting && <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />}
                {dialogMode === "create" ? "Создать" : "Сохранить"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Диалог сброса пароля */}
      <Dialog open={resetDialogOpen} onOpenChange={setResetDialogOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Сброс пароля</DialogTitle>
            <DialogDescription>
              Введите новый пароль для пользователя <strong>{resettingUser?.username}</strong>.
            </DialogDescription>
          </DialogHeader>

          <form onSubmit={handleResetPassword} className="space-y-4 pt-2">
            <div className="space-y-1.5">
              <label htmlFor="new-password" className="text-sm font-medium">Новый пароль</label>
              <Input
                id="new-password"
                type="password"
                required
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                minLength={4}
              />
            </div>

            <DialogFooter className="pt-2 flex flex-col gap-2 sm:flex-row sm:justify-end">
              <Button type="button" variant="outline" onClick={() => setResetDialogOpen(false)} className="w-full sm:w-auto">
                Отмена
              </Button>
              <Button
                type="button"
                variant="destructive"
                onClick={handleClearPassword}
                disabled={resetSubmitting}
                className="w-full sm:w-auto"
              >
                Очистить пароль
              </Button>
              <Button type="submit" disabled={resetSubmitting} className="bg-violet-600 hover:bg-violet-500 w-full sm:w-auto">
                {resetSubmitting && <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />}
                Сбросить пароль
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Диалог генерации временного кода OTP */}
      <Dialog open={otpDialogOpen} onOpenChange={setOtpDialogOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Временный код входа</DialogTitle>
            <DialogDescription>
              Сгенерировать одноразовый 6-значный код авторизации для пользователя <strong>{otpUser?.username}</strong>.
            </DialogDescription>
          </DialogHeader>

          {!otpCode ? (
            <form onSubmit={handleGenerateOTP} className="space-y-4 pt-2">
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-700 block">Время активности сессии после входа</label>
                <Select
                  value={otpDuration ? String(otpDuration) : "null"}
                  onValueChange={(val) => setOtpDuration(val === "null" ? null : Number(val))}
                >
                  <SelectTrigger className="w-full bg-card">
                    <SelectValue placeholder="Выберите длительность" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="1800">По умолчанию (30 минут)</SelectItem>
                    <SelectItem value="28800">На рабочую смену (8 часов)</SelectItem>
                    <SelectItem value="86400">На день (24 часа)</SelectItem>
                    <SelectItem value="604800">На неделю (7 дней)</SelectItem>
                    <SelectItem value="-1">Без ограничений (Бессрочно)</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-[11px] text-muted-foreground">
                  После ввода кода на терминале сессия пользователя будет оставаться активной выбранное время.
                </p>
              </div>

              <DialogFooter className="pt-2 flex gap-2">
                <Button type="button" variant="outline" onClick={() => setOtpDialogOpen(false)}>
                  Отмена
                </Button>
                <Button type="submit" disabled={otpLoading} className="bg-violet-600 hover:bg-violet-500 text-white">
                  {otpLoading && <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />}
                  Сгенерировать код
                </Button>
              </DialogFooter>
            </form>
          ) : (
            <div className="space-y-5 pt-4 text-center">
              <div className="text-xs text-muted-foreground">Передайте этот код сотруднику для ввода:</div>
              <div className="text-3xl font-mono font-bold tracking-[0.25em] text-violet-600 bg-violet-500/5 py-4 rounded-xl border border-violet-500/10 select-all">
                {otpCode}
              </div>
              <div className="text-xs text-amber-600 bg-amber-500/10 py-1.5 px-3 rounded-lg border border-amber-500/20 max-w-xs mx-auto">
                Код одноразовый. Действителен до использования или создания нового.
              </div>
              <DialogFooter className="pt-2">
                <Button type="button" onClick={() => setOtpDialogOpen(false)} className="w-full bg-violet-600 hover:bg-violet-500 text-white">
                  Готово
                </Button>
              </DialogFooter>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
