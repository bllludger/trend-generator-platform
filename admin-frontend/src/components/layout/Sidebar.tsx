import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Users,
  Briefcase,
  CreditCard,
  Shield,
  FileText,
  BarChart3,
  Settings,
  MessageSquare,
  Send,
  Trash2,
  Palette,
  Sparkles,
  TrendingUp,
  Gift,
  PieChart,
  Layers,
  Megaphone,
  Target,
  ImageIcon,
} from 'lucide-react'

const nav = [
  { to: '/', label: 'Дашборд', icon: LayoutDashboard },
  { to: '/users', label: 'Пользователи', icon: Users },
  { to: '/jobs', label: 'Задачи', icon: Briefcase },
  { to: '/payments', label: 'Платежи', icon: CreditCard },
  { to: '/traffic', label: 'Реклама', icon: Target },
  { to: '/security', label: 'Безопасность', icon: Shield },
  { to: '/audit', label: 'Аудит', icon: FileText },
  { to: '/telemetry', label: 'Телеметрия', icon: BarChart3 },
  { to: '/trends', label: 'Тренды', icon: TrendingUp },
  { to: '/trends-analytics', label: 'Тренды — аналитика', icon: PieChart },
  { to: '/trend-poster', label: 'Автопостер', icon: Megaphone },
  { to: '/prompt-playground', label: 'Playground', icon: Sparkles },
  { to: '/copy-style', label: 'Стиль копирования', icon: Palette },
  { to: '/settings', label: 'Настройки', icon: Settings },
  { to: '/master-prompt', label: 'Мастер промпт', icon: FileText },
  { to: '/preview-policy', label: 'Политика превью', icon: ImageIcon },
  { to: '/telegram-messages', label: 'Сообщения бота', icon: MessageSquare },
  { to: '/broadcast', label: 'Рассылка', icon: Send },
  { to: '/referrals', label: 'Рефералы', icon: Gift },
  { to: '/photo-merge', label: 'Склейка фото', icon: Layers },
  { to: '/face-id', label: 'Face ID', icon: ImageIcon },
  { to: '/cleanup', label: 'Очистка', icon: Trash2 },
]

export function Sidebar() {
  return (
    <div className="fixed inset-y-0 left-0 z-50 hidden w-64 flex-col border-r border-border bg-card lg:flex">
      <div className="flex h-16 shrink-0 items-center border-b border-border px-6">
        <span className="text-lg font-semibold">Admin</span>
      </div>
      <nav className="flex-1 space-y-1 overflow-y-auto p-4">
        {nav.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'
              }`
            }
          >
            <item.icon className="h-5 w-5 shrink-0" />
            {item.label}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
