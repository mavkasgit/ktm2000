import { NavLink, Outlet } from "react-router-dom"
import { Boxes, ClipboardList, Gauge, Factory } from "lucide-react"

const navItems = [
  { to: "/", label: "Обзор", icon: Gauge },
  { to: "/references", label: "Справочники", icon: Boxes },
  { to: "/plan", label: "План и запуск", icon: ClipboardList },
]

export function Layout() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="flex items-center gap-2">
            <Factory className="h-5 w-5" />
            <div className="brand-title">Factoryflow</div>
          </div>
          <div className="brand-caption">Планирование производства</div>
        </div>
        <nav className="nav-list" aria-label="Основная навигация">
          {navItems.map((item) => {
            const Icon = item.icon
            return (
              <NavLink key={item.to} to={item.to} end={item.to === "/"} className="nav-link">
                <Icon size={18} />
                <span>{item.label}</span>
              </NavLink>
            )
          })}
        </nav>
      </aside>
      <main className="main-area">
        <Outlet />
      </main>
    </div>
  )
}

export function DashboardPage() {
  return (
    <>
      <header className="page-header">
        <div>
          <h1 className="page-title">Производственный контур</h1>
          <p className="page-subtitle">Импорт плана, утверждение позиций и выпуск партий в производство.</p>
        </div>
      </header>
      <section className="dashboard-grid">
        <div className="metric-panel">
          <span>Текущий этап</span>
          <strong>Этап 1</strong>
        </div>
        <div className="metric-panel">
          <span>Проверки backend</span>
          <strong>14 тестов</strong>
        </div>
        <div className="metric-panel">
          <span>Порты dev</span>
          <strong>5200-5202</strong>
        </div>
      </section>
    </>
  )
}
