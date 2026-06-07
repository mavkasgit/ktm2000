import { useState, useEffect, useRef } from "react"
import { NavLink, Outlet, useLocation } from "react-router-dom"
import { Boxes, ClipboardList, Gauge, Factory, Cog, Wrench, Layers, Menu, X, ArrowRightLeft, History } from "lucide-react"

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
              return (
                <NavLink key={item.to} to={item.to} end={item.to === "/"} className="nav-link">
                  <Icon className="nav-link-icon" aria-hidden="true" />
                  <span>{item.label}</span>
                </NavLink>
              )
            })}
          </nav>
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
