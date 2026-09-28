import { Navigate, createBrowserRouter } from "react-router-dom"
import { Layout, DashboardPage } from "./Layout"
import { RouteBoundary, lazyPage } from "./lazyRoute"
import { RouteError } from "./routeError"
import { ProtectedRoute } from "../features/auth/components/ProtectedRoute"

const ReferencesPage = lazyPage(() => import("../features/references/ReferencesPage"), "ReferencesPage")
const RawMaterialsPage = lazyPage(() => import("../features/references/pages/RawMaterialsPage"), "RawMaterialsPage")
const ProductsPage = lazyPage(() => import("../features/references/pages/ProductsPage"), "ProductsPage")
const SectionsPage = lazyPage(() => import("../features/references/pages/SectionsPage"), "SectionsPage")
const RoutesPage = lazyPage(() => import("../features/references/pages/RoutesPage"), "RoutesPage")

/**
 * Страница разработчика: условие стоит на импорте, а не на маршруте. Иначе
 * `import()` попадает в прод-бандл, и после деплоя её чанк удаляется из
 * сервера вместе со старой сборкой — открытая вкладка оператора ловит ровно
 * ту ошибку загрузки, ради которой рядом стоит `errorElement`.
 */
const DevPage = import.meta.env.DEV
  ? lazyPage(() => import("../features/references/pages/DevPage"), "DevPage")
  : null

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

// Ошибка загрузки чанка — это ошибка рендера, и ловит её ближайшая граница
// маршрута. Без `errorElement` на маршруте оператор получает стандартный
// «Unexpected Application Error!» вместо экрана с кнопкой «Обновить страницу».
const routeErrorElement = <RouteError />

export const router = createBrowserRouter([
  {
    path: "/login",
    element: <RouteBoundary><LoginPage /></RouteBoundary>,
    errorElement: routeErrorElement,
  },
  {
    path: "/auth/callback",
    element: <RouteBoundary><OidcCallbackPage /></RouteBoundary>,
    errorElement: routeErrorElement,
  },
  {
    path: "/",
    element: <ProtectedRoute><Layout /></ProtectedRoute>,
    errorElement: routeErrorElement,
    children: [
      { index: true, element: <DashboardPage />, errorElement: routeErrorElement },
      {
        path: "references",
        element: <ReferencesPage />,
        errorElement: routeErrorElement,
        children: [
          { index: true, element: <Navigate to="/references/raw-materials" replace /> },
          { path: "raw-materials", element: <RawMaterialsPage />, errorElement: routeErrorElement },
          { path: "products", element: <ProductsPage />, errorElement: routeErrorElement },
          { path: "spg", element: <SectionsPage />, errorElement: routeErrorElement },
          { path: "routes", element: <RoutesPage />, errorElement: routeErrorElement },
        ],
      },
      { path: "planning", element: <PlanPage />, errorElement: routeErrorElement },
      { path: "plans/:planId/preview", element: <PlanPreviewPage />, errorElement: routeErrorElement },
      { path: "execution", element: <ExecutionPage />, errorElement: routeErrorElement },
      { path: "section-tasks", element: <SectionsTasksPage />, errorElement: routeErrorElement },
      { path: "section-tasks/:sectionId", element: <SectionsTasksPage />, errorElement: routeErrorElement },
      { path: "spg", element: <SpgSnapshotPage />, errorElement: routeErrorElement },
      { path: "spg/:spgId", element: <SpgSnapshotPage />, errorElement: routeErrorElement },
      { path: "transfers", element: <TransfersPage />, errorElement: routeErrorElement },
      { path: "audit-logs", element: <AuditLogsPage />, errorElement: routeErrorElement },
      { path: "reversal", element: <ActionsJournalPage />, errorElement: routeErrorElement },
      {
        path: "settings",
        element: <SettingsPage />,
        errorElement: routeErrorElement,
      },
      {
        path: "settings/backups",
        element: <BackupsPage />,
        errorElement: routeErrorElement,
      },
      {
        path: "settings/users",
        element: <ProtectedRoute allowedRoles={["admin"]}><UsersPage /></ProtectedRoute>,
        errorElement: routeErrorElement,
      },
      {
        path: "settings/employees",
        element: <ProtectedRoute allowedRoles={["admin"]}><EmployeesPage /></ProtectedRoute>,
        errorElement: routeErrorElement,
      },
      {
        path: "settings/dev",
        element: <ProtectedRoute allowedRoles={["admin"]}><DevSettingsPage /></ProtectedRoute>,
        errorElement: routeErrorElement,
      },
      ...(DevPage ? [{ path: "dev", element: <DevPage />, errorElement: routeErrorElement }] : []),
    ],
  },
])
