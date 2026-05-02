import { useState } from "react"
import { BOMsScreen, ProductsScreen, RoutesScreen, SectionsScreen } from "."

const tabs = [
  { id: "products", label: "Изделия", component: ProductsScreen },
  { id: "sections", label: "Участки", component: SectionsScreen },
  { id: "boms", label: "BOM", component: BOMsScreen },
  { id: "routes", label: "Маршруты", component: RoutesScreen },
]

export function MasterDataPage() {
  const [active, setActive] = useState(tabs[0].id)
  const ActiveComponent = tabs.find((tab) => tab.id === active)?.component ?? ProductsScreen

  return (
    <>
      <header className="page-header">
        <div>
          <h1 className="page-title">Справочники</h1>
          <p className="page-subtitle">Минимальная настройка изделий, участков, BOM и маршрутов для запуска плана.</p>
        </div>
      </header>
      <div className="tab-row">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={active === tab.id ? "tab-button active" : "tab-button"}
            onClick={() => setActive(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div className="work-panel">
        <ActiveComponent />
      </div>
    </>
  )
}
