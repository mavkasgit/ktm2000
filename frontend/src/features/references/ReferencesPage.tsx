import { NavLink, Outlet } from "react-router-dom"

const tabs = [
  { to: "/references/raw-materials", label: "Сырьё" },
  { to: "/references/sections", label: "Участки" },
  { to: "/references/techcards", label: "Техкарты" },
  { to: "/references/routes", label: "Маршруты" },
  { to: "/references/products", label: "Продукты" },
]

export function ReferencesPage() {
  return (
    <>
      <header className="page-header">
        <div>
          <h1 className="page-title">Справочники</h1>
          <p className="page-subtitle">Минимальная настройка изделий, участков, техкарт и маршрутов для запуска плана.</p>
        </div>
      </header>
      <div className="tab-row">
        {tabs.map((tab) => (
          <NavLink key={tab.to} to={tab.to} className={({ isActive }) => (isActive ? "tab-button active" : "tab-button")}>
            {tab.label}
          </NavLink>
        ))}
      </div>
      <div className="work-panel">
        <Outlet />
      </div>
    </>
  )
}
