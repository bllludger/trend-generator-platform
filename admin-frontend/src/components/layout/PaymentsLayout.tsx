import { NavLink, Outlet } from 'react-router-dom'
import { CreditCard, Package, Receipt } from 'lucide-react'

const tabs = [
  { to: '/payments', end: true, label: 'Сводка', icon: CreditCard },
  { to: '/payments/packs', end: false, label: 'Пакеты', icon: Package },
  { to: '/payments/bank-transfer', end: false, label: 'Оплата переводом', icon: Receipt },
]

export function PaymentsLayout() {
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-2 border-b border-border pb-3">
        {tabs.map(({ to, end, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              `flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'
              }`
            }
          >
            <Icon className="h-4 w-4 shrink-0" />
            {label}
          </NavLink>
        ))}
      </div>
      <Outlet />
    </div>
  )
}
