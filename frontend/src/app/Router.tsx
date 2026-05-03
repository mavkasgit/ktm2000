import { Navigate, createBrowserRouter } from "react-router-dom"
import { Layout, DashboardPage } from "./Layout"
import { TechcardsScreen, ReferencesPage, ProductsScreen, RoutesScreen, SectionsScreen } from "../features/references"
import { PlanFlowScreen } from "../features/plan-flow"

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
          { path: "raw-materials", element: <ProductsScreen forcedType="component" title="Справочник сырья" /> },
          { path: "products", element: <ProductsScreen forcedType="finished_good" title="Справочник продуктов" /> },
          { path: "sections", element: <SectionsScreen /> },
          { path: "techcards", element: <TechcardsScreen /> },
          { path: "routes", element: <RoutesScreen /> },
        ],
      },
      { path: "plan", element: <PlanFlowScreen /> },
    ],
  },
])
