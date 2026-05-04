import { Navigate, createBrowserRouter } from "react-router-dom"
import { Layout, DashboardPage } from "./Layout"
import { ReferencesPage, RawMaterialsPage, FinishedGoodsPage, SectionsPage, TechcardsPage, RoutesPage } from "../features/references"
import { DevPage } from "../features/references/pages/DevPage"
import { PlanPage } from "../features/plan-flow/pages/PlanPage"

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
      { path: "dev", element: <DevPage /> },
    ],
  },
])
