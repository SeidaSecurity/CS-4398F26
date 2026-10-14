import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import { nav } from './nav'

export default function App() {
  return (
    <Layout>
      <Routes>
        {nav.flatMap((group) =>
          group.items.map((item) => (
            <Route key={item.path} path={item.path} element={item.element} />
          )),
        )}
      </Routes>
    </Layout>
  )
}
