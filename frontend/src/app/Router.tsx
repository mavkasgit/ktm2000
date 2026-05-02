import { createBrowserRouter } from "react-router-dom"
import { Layout, DashboardPage } from "./Layout"
import { MasterDataPage } from "../features/master-data"
import { PlanFlowScreen } from "../features/plan-flow"

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: "master-data", element: <MasterDataPage /> },
      { path: "plan-flow", element: <PlanFlowScreen /> },
    ],
  },
])
