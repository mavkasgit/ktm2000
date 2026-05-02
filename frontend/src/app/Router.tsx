import { createBrowserRouter } from "react-router-dom"

function HomePage() {
  return (
    <main style={{ fontFamily: "sans-serif", padding: 24 }}>
      <h1>Factoryflow</h1>
      <p>Milestone 1 bootstrap is running.</p>
    </main>
  )
}

export const router = createBrowserRouter([
  {
    path: "/",
    element: <HomePage />,
  },
])



