import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './auth'
import Layout from './components/Layout'
import { useVisibleNav } from './nav'
import Login from './pages/Login'

export default function App() {
  const { user } = useAuth()
  const nav = useVisibleNav()

  if (user === undefined) return null // checking the session; avoids flashing the login screen
  if (user === null) return <Login />

  return (
    <Layout>
      <Routes>
        {nav.flatMap((group) =>
          group.items.map((item) => (
            <Route key={item.path} path={item.path} element={item.element} />
          )),
        )}
        {/* Unknown or not-permitted paths (e.g. a viewer opening /accounts) go to the dashboard. */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  )
}
