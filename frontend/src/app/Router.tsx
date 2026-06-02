import { Navigate, createBrowserRouter } from "react-router-dom"
import { Layout, DashboardPage } from "./Layout"
import { ReferencesPage, RawMaterialsPage, FinishedGoodsPage, SectionsPage, TechcardsPage, RoutesPage } from "../features/references"
import { DevPage } from "../features/references/pages/DevPage"
import { PlanPage } from "../features/planning/pages/PlanPage"
import { PlanPreviewPage } from "../features/planning/pages/PlanPreviewPage"
import { ExecutionPage } from "../features/execution/pages/ExecutionPage"
import { SectionsTasksPage } from "../features/sections/pages/SectionsTasksPage"
import { SpgSnapshotPage } from "../features/spg/pages/SpgSnapshotPage"
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
      { path: "planning", element: <PlanPage /> },
      { path: "plans/:planId/preview", element: <PlanPreviewPage /> },
      { path: "execution", element: <ExecutionPage /> },
      { path: "shopfloor-tasks", element: <SectionsTasksPage /> },
      { path: "shopfloor-tasks/:sectionId", element: <SectionsTasksPage /> },
      { path: "spg", element: <SpgSnapshotPage /> },
      { path: "spg/:spgId", element: <SpgSnapshotPage /> },
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
