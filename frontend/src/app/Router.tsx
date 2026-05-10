import { Navigate, createBrowserRouter } from "react-router-dom"
import { Layout, DashboardPage } from "./Layout"
import { ReferencesPage, RawMaterialsPage, FinishedGoodsPage, SectionsPage, TechcardsPage, RoutesPage } from "../features/references"
import { DevPage } from "../features/references/pages/DevPage"
import { PlanPage } from "../features/plan-flow/pages/PlanPage"
import { PlanPreviewPage } from "../features/plan-flow/pages/PlanPreviewPage"
import { ProductionPlanningPage } from "../features/production-planning/pages/ProductionPlanningPage"
import { SettingsPage } from "../features/settings/SettingsPage"
import { BackupsPage } from "../features/settings/SettingsBackupsPage"

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <DashboardPage /> },
      {
        path: "references",
        element: <ReferencesPage />,
        children: [
          { index: true, element: <Navigate to="/references/raw-materials" replace /> },
          { path: "raw-materials", element: <RawMaterialsPage /> },
          { path: "products", element: <FinishedGoodsPage /> },
          { path: "sections", element: <SectionsPage /> },
          { path: "techcards", element: <TechcardsPage /> },
          { path: "routes", element: <RoutesPage /> },
        ],
      },
      { path: "plan", element: <PlanPage /> },
      { path: "plans/:planId/preview", element: <PlanPreviewPage /> },
      { path: "production-planning", element: <ProductionPlanningPage /> },
      {
        path: "settings",
        element: <SettingsPage />,
      },
      {
        path: "settings/backups",
        element: <BackupsPage />,
      },
      { path: "dev", element: <DevPage /> },
    ],
  },
])
