import { BrowserRouter, NavLink, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import CalibrationPage from './pages/CalibrationPage'
import GeneratePage from './pages/GeneratePage'
import HistoryPage from './pages/HistoryPage'
import MonitorPage from './pages/MonitorPage'
import PersonaPage from './pages/PersonaPage'
import StatsPage from './pages/StatsPage'

const pageMeta: Record<string, { badge: string; placeholder: string }> = {
  '/': {
    badge: 'Workspace / Generator',
    placeholder: '搜索任务或生成结果...',
  },
  '/history': {
    badge: 'Archive / History',
    placeholder: '搜索历史记录...',
  },
  '/stats': {
    badge: 'Analytics / Overview',
    placeholder: '搜索统计指标...',
  },
  '/persona': {
    badge: 'Persona / Studio',
    placeholder: '搜索 Persona...',
  },
  '/calibration': {
    badge: 'Calibration / Judge',
    placeholder: '搜索校准报告...',
  },
  '/monitor': {
    badge: 'Monitor Console / Node_04',
    placeholder: '搜索监控指标...',
  },
}

function AppShell() {
  const location = useLocation()
  const meta = pageMeta[location.pathname] ?? pageMeta['/']

  return (
    <div className="min-h-screen bg-surface text-on-surface">
      <Sidebar />
      <div className="ml-[220px] min-h-screen">
        <header className="fixed left-[220px] right-0 top-0 z-40 flex h-16 items-center justify-between border-b border-black/5 bg-white/80 px-8 backdrop-blur-md">
          <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-outline">{meta.badge}</span>
          <div className="flex items-center gap-6">
            <div className="relative hidden md:block">
              <span className="material-symbols-outlined absolute inset-y-0 left-3 flex items-center text-gray-400">
                search
              </span>
              <input
                placeholder={meta.placeholder}
                className="w-64 rounded-full border-none bg-surface-container-low py-1.5 pl-10 pr-4 text-xs outline-none ring-0 transition-all focus:ring-1 focus:ring-black"
              />
            </div>
            <NavLink to="/monitor" className="relative text-gray-500 transition-colors hover:text-black">
              <span className="material-symbols-outlined">notifications</span>
              <span className="absolute right-0 top-0 h-1.5 w-1.5 rounded-full bg-black" />
            </NavLink>
            <button className="flex items-center gap-2 text-xs font-semibold tracking-tight text-black">
              <span>Researcher_01</span>
              <span className="material-symbols-outlined">account_circle</span>
            </button>
          </div>
        </header>
        <main className="min-h-screen pt-16">
          <div className="mx-auto max-w-[1400px] p-8 lg:p-10">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<GeneratePage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/stats" element={<StatsPage />} />
          <Route path="/persona" element={<PersonaPage />} />
          <Route path="/calibration" element={<CalibrationPage />} />
          <Route path="/monitor" element={<MonitorPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
