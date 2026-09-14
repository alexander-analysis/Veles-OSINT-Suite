import { NavLink } from 'react-router-dom';
import { LayoutDashboard, TrendingUp, Ship, ShieldAlert, Settings } from 'lucide-react';
import clsx from 'clsx';

const LINKS = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/market', label: 'Market', icon: TrendingUp },
  { to: '/maritime', label: 'Maritime', icon: Ship },
  { to: '/sanctions', label: 'Sanctions', icon: ShieldAlert },
  { to: '/settings', label: 'Settings', icon: Settings },
];

export default function Navigation() {
  return (
    <header className="bg-white border-b border-gray-200 no-print">
      <div className="container mx-auto px-6 h-14 flex items-center justify-between">
        <NavLink to="/" className="flex items-baseline gap-3">
          <span className="text-lg font-bold tracking-[0.2em] text-steel-700">VELES</span>
          <span className="hidden sm:inline text-xs text-gray-500">OSINT Intelligence Platform</span>
        </NavLink>
        <nav className="flex gap-1" aria-label="Primary">
          {LINKS.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                clsx(
                  'flex items-center gap-2 px-3 py-2 rounded text-sm transition-colors',
                  isActive ? 'bg-steel-50 text-steel-700 font-medium' : 'text-gray-700 hover:bg-gray-100',
                )
              }
            >
              <Icon size={16} aria-hidden="true" />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
      </div>
    </header>
  );
}
