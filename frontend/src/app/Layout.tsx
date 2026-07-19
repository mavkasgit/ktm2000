import { useState, useEffect, useRef } from "react"
import { NavLink, Outlet, useLocation } from "react-router-dom"
import { Boxes, ClipboardList, Gauge, Factory, Cog, Wrench, Layers, Menu, X, ArrowRightLeft, History, LogOut, Terminal } from "lucide-react"
import { useAuth } from "@/features/auth/hooks/useAuth"
import type { UserRole } from "@/features/auth/api"
import { toast } from "@/shared/ui"
import { UserAvatar, getUserSeed } from "@user/ui"
import { UserProfileModal } from "@/features/profile/UserProfileModal"

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
  "/references": ["admin", "planner", "section_manager", "operator", "viewer", "transporter"],
  "/planning": ["admin", "planner"],
  "/execution": ["admin", "planner", "section_manager"],
  "/section-tasks": ["admin", "planner", "section_manager", "operator", "viewer", "transporter"],
  "/transfers": ["admin", "planner", "section_manager", "operator", "transporter"],
  "/spg": ["admin", "planner", "section_manager", "operator", "viewer", "transporter"],
  "/audit-logs": ["admin", "planner", "section_manager", "operator", "viewer", "transporter"],
  "/settings": ["admin", "planner", "section_manager", "operator", "viewer", "transporter"],
  "/settings/dev": ["admin"],
  "/dev": ["admin", "planner", "section_manager", "operator", "viewer", "transporter"],
}

const navItems = [
  { to: "/", label: "Обзор", icon: Gauge },
  { to: "/references", label: "Справочники", icon: Boxes },
  { to: "/planning", label: "План", icon: ClipboardList },
  { to: "/execution", label: "Контроль выполнения", icon: Factory },
  { to: "/section-tasks", label: "Участки", icon: Wrench },
  { to: "/transfers", label: "Передачи", icon: ArrowRightLeft },
  { to: "/spg", label: "ГХП", icon: Layers },
  { to: "/audit-logs", label: "Журнал действий", icon: History },
  { to: "/settings", label: "Настройки", icon: Cog },
  ...(import.meta.env.DEV ? [{ to: "/dev", label: "Разработка (Dev)", icon: Terminal }] : []),
]

export function Layout() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [profileOpen, setProfileOpen] = useState(false)
  const location = useLocation()
  const sidebarRef = useRef<HTMLDivElement>(null)
  const { user, logout, refreshUser } = useAuth()
  const isSingleWindowShopfloor =
    location.pathname.startsWith("/section-tasks") &&
    new URLSearchParams(location.search).get("singleWindow") === "1"
  const isBulkMode =
    location.pathname.startsWith("/section-tasks") &&
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
          <NavLink to="/" className="mobile-header-brand flex items-center gap-2 hover:opacity-80 transition-opacity">
            <img src="/logo.svg" alt="" className="h-7 w-7 rounded-md" width={28} height={28} />
            <span className="mobile-header-title">KTM-2000</span>
          </NavLink>
        </div>
      )}

      {/* Overlay */}
      {!hideSidebar && mobileMenuOpen && <div className="sidebar-overlay" aria-hidden="true" />}

      {!hideSidebar && (
        <aside ref={sidebarRef} className={`sidebar ${mobileMenuOpen ? "sidebar--mobile-open" : ""}`}>
          <div className="sidebar-top-bar">
            <div className="sidebar-brand">
              <div className="flex items-center gap-3">
                <NavLink
                  to="/"
                  className="shrink-0 hover:opacity-80 transition-opacity"
                  title="На главную"
                >
                  <img src="/logo.svg" alt="" className="h-10 w-10 rounded-xl" width={40} height={40} />
                </NavLink>
                <div className="min-w-0">
                  <div className="brand-title">KTM-2000</div>
                  <div className="brand-caption">Планирование производства</div>
                </div>
              </div>
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

          {/* Блок пользователя + единый профиль */}
          {user && (
            <div className="mt-auto border-t px-4 py-4 space-y-2">
              <button
                type="button"
                onClick={() => setProfileOpen(true)}
                className="flex w-full items-center gap-3 rounded-md px-2 py-2 text-left transition-colors hover:bg-accent"
                title="Настройки профиля"
              >
                <UserAvatar seed={getUserSeed(user)} size={36} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{user.full_name}</div>
                  <div className="text-[10px] text-muted-foreground truncate">
                    Настройки профиля
                  </div>
                </div>
              </button>
              <div className="px-2 text-xs text-muted-foreground">{ROLE_LABELS[user.role]}</div>
              <button
                type="button"
                onClick={logout}
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              >
                <LogOut className="h-4 w-4" />
                Выход
              </button>
              <UserProfileModal
                open={profileOpen}
                onOpenChange={setProfileOpen}
                currentUser={user}
                onUpdated={refreshUser}
              />
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

