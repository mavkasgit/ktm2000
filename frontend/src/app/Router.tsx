import { Navigate, createBrowserRouter } from "react-router-dom"
import { Layout, DashboardPage } from "./Layout"
import { ReferencesPage, RawMaterialsPage, FinishedGoodsPage, SectionsPage, TechcardsPage, RoutesPage } from "../features/references"
import { DevPage } from "../features/references/pages/DevPage"
import { PlanPage } from "../features/planning/pages/PlanPage"
import { PlanPreviewPage } from "../features/planning/pages/PlanPreviewPage"
import { ExecutionPage } from "../features/execution/pages/ExecutionPage"
import { SectionsTasksPage } from "../features/sections/pages/SectionsTasksPage"
import { AuditLogsPage } from "../features/sections/pages/AuditLogsPage"
import { SpgSnapshotPage } from "../features/spg/pages/SpgSnapshotPage"
import { TransfersPage } from "../features/transfers/pages/TransfersPage"
import { SettingsPage } from "../features/settings/SettingsPage"
import { BackupsPage } from "../features/settings/SettingsBackupsPage"
import { DevSettingsPage } from "../features/settings/DevSettingsPage"
import { LoginPage } from "../features/auth/pages/LoginPage"
import { ProtectedRoute } from "../features/auth/components/ProtectedRoute"
import { UsersPage } from "../features/admin"

export const router = createBrowserRouter([
  {
    path: "/login",
    element: <LoginPage />,
  },
  {
    path: "/",
    element: <ProtectedRoute><Layout /></ProtectedRoute>,
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
      { path: "section-tasks", element: <SectionsTasksPage /> },
      { path: "section-tasks/:sectionId", element: <SectionsTasksPage /> },
      { path: "spg", element: <SpgSnapshotPage /> },
      { path: "spg/:spgId", element: <SpgSnapshotPage /> },
      { path: "transfers", element: <TransfersPage /> },
      { path: "audit-logs", element: <AuditLogsPage /> },
      {
        path: "settings",
        element: <SettingsPage />,
      },
      {
        path: "settings/backups",
        element: <BackupsPage />,
      },
      {
        path: "settings/users",
        element: <ProtectedRoute allowedRoles={["admin"]}><UsersPage /></ProtectedRoute>,
      },
      {
        path: "settings/dev",
        element: <ProtectedRoute allowedRoles={["admin"]}><DevSettingsPage /></ProtectedRoute>,
      },
      { path: "dev", element: <DevPage /> },
    ],
  },
])

