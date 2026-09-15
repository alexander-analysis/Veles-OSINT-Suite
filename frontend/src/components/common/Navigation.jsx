import { useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { LayoutDashboard, TrendingUp, Ship, ShieldAlert, Globe, Coins, Building2, Fuel, Layers, Eye, Network, ScrollText, Settings, Search } from 'lucide-react';
import clsx from 'clsx';

const LINKS = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/market', label: 'Market', icon: TrendingUp },
  { to: '/maritime', label: 'Maritime', icon: Ship },
  { to: '/sanctions', label: 'Sanctions', icon: ShieldAlert },
  { to: '/geopolitical', label: 'Geopolitical', icon: Globe },
  { to: '/blockchain', label: 'Blockchain', icon: Coins },
  { to: '/corporate', label: 'Corporate', icon: Building2 },
  { to: '/energy', label: 'Energy', icon: Fuel },
  { to: '/fusion', label: 'Fusion', icon: Layers },
  { to: '/monitors', label: 'Monitors', icon: Eye },
  { to: '/correlation', label: 'Linkage', icon: Network },
  { to: '/audit', label: 'Audit', icon: ScrollText },
  { to: '/settings', label: 'Settings', icon: Settings },
];

function SearchBox() {
  const [q, setQ] = useState('');
  const navigate = useNavigate();
  const submit = (e) => {
    e.preventDefault();
    if (q.trim().length >= 2) navigate(`/search?q=${encodeURIComponent(q.trim())}`);
  };
  return (
    <form onSubmit={submit} role="search" className="hidden md:flex items-center border border-gray-300 rounded px-2 h-8 bg-white focus-within:border-steel-500">
      <Search size={13} className="text-gray-400" aria-hidden="true" />
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="name, MMSI, IMO, LEI, wallet..." aria-label="Search everything" className="w-40 xl:w-56 ml-1.5 text-xs outline-none bg-transparent" />
    </form>
  );
}

export default function Navigation() {
  return (
    <header className="bg-white border-b border-gray-200 no-print">
      <div className="container mx-auto px-6 h-14 flex items-center justify-between gap-3">
        <NavLink to="/" className="flex items-baseline gap-3">
          <span className="text-lg font-bold tracking-[0.2em] text-steel-700">VELES</span>
          <span className="hidden 2xl:inline text-xs text-gray-500">OSINT Intelligence Platform</span>
        </NavLink>
        <SearchBox />
        <nav className="flex gap-0.5 overflow-x-auto" aria-label="Primary">
          {LINKS.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                clsx(
                  'flex items-center gap-1.5 px-2 xl:px-3 py-2 rounded text-sm transition-colors whitespace-nowrap',
                  isActive ? 'bg-steel-50 text-steel-700 font-medium' : 'text-gray-700 hover:bg-gray-100',
                )
              }
            >
              <Icon size={16} aria-hidden="true" />
              <span className="hidden lg:inline" title={label}>{label}</span>
            </NavLink>
          ))}
        </nav>
      </div>
    </header>
  );
}
