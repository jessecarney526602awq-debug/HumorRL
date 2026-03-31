import { NavLink } from 'react-router-dom'

const navItems = [
  { to: '/', label: '生成', icon: 'bolt' },
  { to: '/history', label: '历史记录', icon: 'history' },
  { to: '/stats', label: '统计', icon: 'bar_chart' },
  { to: '/persona', label: 'Persona', icon: 'psychology' },
  { to: '/calibration', label: '校准报告', icon: 'biotech' },
  { to: '/monitor', label: '监控', icon: 'monitoring' },
]

function itemClass(active: boolean) {
  return [
    'flex items-center gap-3 px-6 py-3 text-sm tracking-tight transition-colors duration-200',
    active
      ? 'border-l-2 border-black bg-white font-semibold text-black'
      : 'font-medium text-gray-400 hover:text-black',
  ].join(' ')
}

export default function Sidebar() {
  return (
    <aside className="fixed left-0 top-0 z-50 flex h-full w-[220px] flex-col justify-between border-r border-black/5 bg-white py-8">
      <div>
        <div className="px-6">
          <h1 className="font-headline text-2xl font-black tracking-tighter text-black">
            Only Funs
          </h1>
          <p className="mt-1 text-[10px] font-bold uppercase tracking-[0.2em] text-gray-400">
            Researcher Portal
          </p>
        </div>
        <nav className="mt-8 space-y-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) => itemClass(isActive)}
            >
              <span className="material-symbols-outlined text-[20px]">{item.icon}</span>
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="mt-8 px-6">
          <button className="w-full rounded-lg bg-black py-3 text-xs font-bold tracking-[0.15em] text-white transition-opacity hover:opacity-90">
            新建任务
          </button>
        </div>
      </div>
      <div className="px-6">
        <div className="border-t border-black/5 pt-4">
          <button className="flex w-full items-center gap-3 py-2 text-sm font-medium text-gray-400 transition-colors hover:text-black">
            <span className="material-symbols-outlined text-[18px]">settings</span>
            <span>设置</span>
          </button>
          <button className="flex w-full items-center gap-3 py-2 text-sm font-medium text-gray-400 transition-colors hover:text-black">
            <span className="material-symbols-outlined text-[18px]">help_outline</span>
            <span>帮助</span>
          </button>
        </div>
      </div>
    </aside>
  )
}
