import { Navigate, createBrowserRouter } from "react-router-dom"
import { Layout, DashboardPage } from "./Layout"
import { RouteBoundary, lazyPage } from "./lazyRoute"
import { ProtectedRoute } from "../features/auth/components/ProtectedRoute"

const ReferencesPage = lazyPage(() => import("../features/references/ReferencesPage"), "ReferencesPage")
const RawMaterialsPage = lazyPage(() => import("../features/references/pages/RawMaterialsPage"), "RawMaterialsPage")
const ProductsPage = lazyPage(() => import("../features/references/pages/ProductsPage"), "ProductsPage")
const SectionsPage = lazyPage(() => import("../features/references/pages/SectionsPage"), "SectionsPage")
const RoutesPage = lazyPage(() => import("../features/references/pages/RoutesPage"), "RoutesPage")
const DevPage = lazyPage(() => import("../features/references/pages/DevPage"), "DevPage")
const PlanPage = lazyPage(() => import("../features/planning/pages/PlanPage"), "PlanPage")
const PlanPreviewPage = lazyPage(() => import("../features/planning/pages/PlanPreviewPage"), "PlanPreviewPage")
const ExecutionPage = lazyPage(() => import("../features/execution/pages/ExecutionPage"), "ExecutionPage")
const SectionsTasksPage = lazyPage(() => import("../features/sections/pages/SectionsTasksPage"), "SectionsTasksPage")
const AuditLogsPage = lazyPage(() => import("../features/sections/pages/AuditLogsPage"), "AuditLogsPage")
const ActionsJournalPage = lazyPage(() => import("../features/reversal/pages/ActionsJournalPage"), "ActionsJournalPage")
const SpgSnapshotPage = lazyPage(() => import("../features/spg/pages/SpgSnapshotPage"), "SpgSnapshotPage")
const TransfersPage = lazyPage(() => import("../features/transfers/pages/TransfersPage"), "TransfersPage")
const SettingsPage = lazyPage(() => import("../features/settings/SettingsPage"), "SettingsPage")
const BackupsPage = lazyPage(() => import("../features/settings/SettingsBackupsPage"), "BackupsPage")
const DevSettingsPage = lazyPage(() => import("../features/settings/DevSettingsPage"), "DevSettingsPage")
const UsersPage = lazyPage(() => import("../features/admin/pages/UsersPage"), "UsersPage")
const EmployeesPage = lazyPage(() => import("../features/admin/pages/EmployeesPage"), "EmployeesPage")
const LoginPage = lazyPage(() => import("../features/auth/pages/LoginPage"), "LoginPage")
const OidcCallbackPage = lazyPage(() => import("../features/auth/pages/OidcCallbackPage"), "OidcCallbackPage")

export const router = createBrowserRouter([
  {
    path: "/login",
    element: <RouteBoundary><LoginPage /></RouteBoundary>,
  },
  {
    path: "/auth/callback",
    element: <RouteBoundary><OidcCallbackPage /></RouteBoundary>,
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
          { path: "products", element: <ProductsPage /> },
          { path: "spg", element: <SectionsPage /> },
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
      { path: "reversal", element: <ActionsJournalPage /> },
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
        path: "settings/employees",
        element: <ProtectedRoute allowedRoles={["admin"]}><EmployeesPage /></ProtectedRoute>,
      },
      {
        path: "settings/dev",
        element: <ProtectedRoute allowedRoles={["admin"]}><DevSettingsPage /></ProtectedRoute>,
      },
      ...(import.meta.env.DEV ? [{ path: "dev", element: <DevPage /> }] : []),
    ],
  },
])
