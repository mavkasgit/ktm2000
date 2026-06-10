import { useState, useEffect, useRef } from "react"
import { NavLink, Outlet, useLocation } from "react-router-dom"
import { Boxes, ClipboardList, Gauge, Factory, Cog, Wrench, Layers, Menu, X, ArrowRightLeft, History, LogOut } from "lucide-react"
import { useAuth } from "@/features/auth/hooks/useAuth"
import type { UserRole } from "@/features/auth/api"
import { toast } from "@/shared/ui"

/** Перевод ролей на русский */
const ROLE_LABELS: Record<UserRole, string> = {
  admin: "Администратор",
  planner: "Планировщик",
  section_manager: "Начальник участка",
  operator: "Оператор",
  viewer: "Наблюдатель",
  transporter: "Транспортировщик",
}

/** Карта доступа: какие роли имеют доступ к каждому пункту меню */
const NAV_ACCESS: Record<string, UserRole[]> = {
  "/": ["admin", "planner", "section_manager", "operator", "viewer", "transporter"],
  "/references": ["admin", "planner"],
  "/planning": ["admin", "planner"],
  "/execution": ["admin", "planner", "section_manager"],
  "/shopfloor-tasks": ["admin", "planner", "section_manager", "operator", "viewer", "transporter"],
  "/transfers": ["admin", "planner", "section_manager", "operator", "transporter"],
  "/spg": ["admin", "planner", "section_manager", "operator", "viewer", "transporter"],
  "/audit-logs": ["admin"],
  "/settings": ["admin"],
}

const navItems = [
  { to: "/", label: "Обзор", icon: Gauge },
  { to: "/references", label: "Справочники", icon: Boxes },
  { to: "/planning", label: "План", icon: ClipboardList },
  { to: "/execution", label: "Контроль выполнения", icon: Factory },
  { to: "/shopfloor-tasks", label: "Участки", icon: Wrench },
  { to: "/transfers", label: "Передачи", icon: ArrowRightLeft },
  { to: "/spg", label: "ГХП", icon: Layers },
  { to: "/audit-logs", label: "Журнал действий", icon: History },
  { to: "/settings", label: "Настройки", icon: Cog },
]

export function Layout() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const location = useLocation()
  const sidebarRef = useRef<HTMLDivElement>(null)
  const { user, logout } = useAuth()
  const isSingleWindowShopfloor =
    location.pathname.startsWith("/shopfloor-tasks") &&
    new URLSearchParams(location.search).get("singleWindow") === "1"
  const isBulkMode =
    location.pathname.startsWith("/shopfloor-tasks") &&
    new URLSearchParams(location.search).get("bulk") === "1"
  const hideSidebar = isSingleWindowShopfloor || isBulkMode

  // Close mobile menu when route changes
  useEffect(() => {
    setMobileMenuOpen(false)
  }, [location])

  // Close mobile menu when clicking outside
  useEffect(() => {
    if (!mobileMenuOpen) return

    function handleClick(e: MouseEvent) {
      if (sidebarRef.current && !sidebarRef.current.contains(e.target as Node)) {
        setMobileMenuOpen(false)
      }
    }

    document.addEventListener("mousedown", handleClick)
    return () => document.removeEventListener("mousedown", handleClick)
  }, [mobileMenuOpen])

  /** Проверяет, разрешён ли текущему пользователю доступ к пункту меню */
  const canAccess = (path: string): boolean => {
    if (!user) return false
    const roles = NAV_ACCESS[path]
    if (!roles) return true
    return roles.includes(user.role)
  }

  return (
    <div className="app-shell">
      {/* Mobile header with hamburger */}
      {!hideSidebar && (
        <div className="mobile-header">
          <button
            type="button"
            className="mobile-menu-btn"
            onClick={() => setMobileMenuOpen(true)}
            aria-label="Открыть меню"
          >
            <Menu size={24} />
          </button>
          <div className="mobile-header-brand">
            <Factory className="h-5 w-5" />
            <span className="mobile-header-title">KTM-2000</span>
          </div>
        </div>
      )}

      {/* Overlay */}
      {!hideSidebar && mobileMenuOpen && <div className="sidebar-overlay" aria-hidden="true" />}

      {!hideSidebar && (
        <aside ref={sidebarRef} className={`sidebar ${mobileMenuOpen ? "sidebar--mobile-open" : ""}`}>
          <div className="sidebar-top-bar">
            <div className="sidebar-brand">
              <div className="flex items-center gap-2">
                <Factory className="h-5 w-5" />
                <div className="brand-title">KTM-2000</div>
              </div>
              <div className="brand-caption">Планирование производства</div>
            </div>
            <button
              type="button"
              className="sidebar-close-btn"
              onClick={() => setMobileMenuOpen(false)}
              aria-label="Закрыть меню"
            >
              <X size={24} />
            </button>
          </div>
          <nav className="nav-list" aria-label="Основная навигация">
            {navItems.map((item) => {
              const Icon = item.icon
              const allowed = canAccess(item.to)

              if (!allowed) {
                const allowedRoles = NAV_ACCESS[item.to] || []
                const roleNames = allowedRoles.map(r => ROLE_LABELS[r]).join(", ")

                const handleDisabledClick = () => {
                  toast({
                    variant: "destructive",
                    title: "Доступ ограничен",
                    description: `Раздел "${item.label}" доступен только для ролей: ${roleNames}`,
                  })
                }

                return (
                  <button
                    key={item.to}
                    type="button"
                    onClick={handleDisabledClick}
                    className="nav-link w-full text-left opacity-50 cursor-pointer hover:bg-accent/50"
                    title={`Доступно только для: ${roleNames}`}
                  >
                    <Icon className="nav-link-icon" aria-hidden="true" />
                    <span>{item.label}</span>
                  </button>
                )
              }

              return (
                <NavLink key={item.to} to={item.to} end={item.to === "/"} className="nav-link">
                  <Icon className="nav-link-icon" aria-hidden="true" />
                  <span>{item.label}</span>
                </NavLink>
              )
            })}
          </nav>

          {/* Блок пользователя */}
          {user && (
            <div className="mt-auto border-t px-4 py-4">
              <div className="mb-2">
                <div className="truncate text-sm font-medium">{user.full_name}</div>
                <div className="text-xs text-muted-foreground">{ROLE_LABELS[user.role]}</div>
              </div>
              <button
                type="button"
                onClick={logout}
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              >
                <LogOut className="h-4 w-4" />
                Выход
              </button>
            </div>
          )}
        </aside>
      )}
      <main className={hideSidebar ? "main-area !pt-6 md:!pt-6" : "main-area"}>
        <Outlet />
      </main>
    </div>
  )
}

export function DashboardPage() {
  return (
    <header className="page-header">
      <div>
        <h1 className="page-title">Производственный контур</h1>
        <p className="page-subtitle">Импорт плана, утверждение позиций и выпуск партий в производство.</p>
      </div>
    </header>
  )
}

