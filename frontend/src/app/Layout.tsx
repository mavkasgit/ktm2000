import { useState, useEffect, useRef } from "react"
import { NavLink, Outlet, useLocation } from "react-router-dom"
import { Boxes, ClipboardList, Gauge, Factory, Cog, Wrench, Layers, Menu, X, ArrowRightLeft, History, LogOut, Terminal } from "lucide-react"
import { useAuth } from "@/features/auth/hooks/useAuth"
import { toast } from "@/shared/ui"
import { UserAvatar, getUserSeed } from "@user/ui"
import { KtmUserSettingsDialog } from "@/features/user-settings/KtmUserSettingsDialog"
import { KtmNotificationBell } from "@/features/notifications"

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
  const { user, logout, refreshUser, rolesCatalog, roleLabel, roleSections } = useAuth()
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

  /** Проверяет, разрешён ли текущему пользователю доступ к пункту меню.
   *  Допустимость считается строго по списку секций из справочника ролей (/auth/roles). */
  const canAccess = (path: string): boolean => {
    if (!user) return false
    return roleSections(user.role).includes(path)
  }

  const rolesReady = rolesCatalog.length > 0

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
          <a
            href={`${window.location.protocol}//${window.location.hostname}:9000`}
            className="mobile-header-brand flex items-center gap-2 hover:opacity-80 transition-opacity"
            title="Панель приложений"
          >
            <img src="/logo.svg" alt="" className="h-7 w-7 rounded-md" width={28} height={28} />
            <span className="mobile-header-title">KTM-2000</span>
          </a>
        </div>
      )}

      {/* Overlay */}
      {!hideSidebar && mobileMenuOpen && <div className="sidebar-overlay" aria-hidden="true" />}

      {!hideSidebar && (
        <aside ref={sidebarRef} className={`sidebar ${mobileMenuOpen ? "sidebar--mobile-open" : ""}`}>
          <div className="sidebar-top-bar">
            <div className="sidebar-brand">
              <div className="flex items-center gap-3">
                <a
                  href={`${window.location.protocol}//${window.location.hostname}:9000`}
                  className="shrink-0 hover:opacity-80 transition-opacity"
                  title="Панель приложений"
                >
                  <img src="/logo.svg" alt="" className="h-10 w-10 rounded-xl" width={40} height={40} />
                </a>
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

              // Fallback до загрузки справочника ролей: пустая допустимость → пункт скрыт.
              if (!allowed && !rolesReady) {
                return null
              }

              if (!allowed) {
                const allowedRoles: string[] = rolesCatalog
                  .filter((r) => r.sections.includes(item.to))
                  .map((r) => r.code)
                const roleNames = allowedRoles.map(r => roleLabel(r)).join(", ")

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
            <div className="mt-auto p-3 border-t flex flex-col gap-2">
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => setProfileOpen(true)}
                  className="flex items-center justify-center p-1.5 rounded-xl hover:bg-accent transition-all group"
                  title="Настройки профиля"
                >
                  <UserAvatar seed={getUserSeed(user)} size={32} className="group-hover:scale-105 transition-transform" />
                </button>
                <KtmNotificationBell />
              </div>
              <button
                type="button"
                onClick={() => setProfileOpen(true)}
                className="flex w-full items-center gap-3 px-3 py-1.5 rounded-xl text-left hover:bg-accent transition-all group"
                title="Настройки профиля"
              >
                <div className="flex-1 min-w-0">
                  <div className="font-semibold text-foreground text-sm truncate group-hover:text-primary transition-colors">
                    {user.full_name}
                  </div>
                  <div className="text-[10px] text-muted-foreground truncate">
                    Настройки профиля
                  </div>
                </div>
              </button>
              <button
                type="button"
                onClick={logout}
                className="flex w-full items-center gap-3 px-3 py-2 rounded-md text-sm text-destructive hover:bg-destructive/10 transition-colors"
              >
                <LogOut className="h-4 w-4" />
                Выйти
              </button>
              <KtmUserSettingsDialog
                open={profileOpen}
                onOpenChange={setProfileOpen}
                onProfileUpdated={refreshUser}
                onLogoutRequest={logout}
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

