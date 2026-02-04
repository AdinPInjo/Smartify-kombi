import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  MapPin,
  BatteryCharging,
  ToggleLeft,
  Settings,
  Thermometer,
  Database,
} from "lucide-react";

const BrandMark = ({ className = "" }: { className?: string }) => (
  <svg viewBox="0 0 24 24" className={className} fill="none" aria-hidden="true">
    <path
      d="M12 2.5c5.25 0 9.5 4.25 9.5 9.5s-4.25 9.5-9.5 9.5S2.5 17.25 2.5 12 6.75 2.5 12 2.5Z"
      stroke="currentColor"
      strokeWidth="1.8"
      opacity="0.7"
    />
    <path
      d="M7.5 12a4.5 4.5 0 0 1 9 0"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
    />
    <path
      d="M12 12l3.7-3.7"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
    />
    <circle cx="12" cy="12" r="1.3" fill="currentColor" />
  </svg>
);

const nav = [
  { to: "/dashboard", label: "Overview", Icon: LayoutDashboard },
  { to: "/dashboard/gps", label: "GPS", Icon: MapPin },
  { to: "/dashboard/energy", label: "Energy", Icon: BatteryCharging },
  { to: "/dashboard/relays", label: "Relays", Icon: ToggleLeft },
  { to: "/dashboard/temperature", label: "Temperature", Icon: Thermometer },
  { to: "/dashboard/settings", label: "Settings", Icon: Settings },
];

const systemNav = [
  { to: "/dashboard/system/db", label: "DB Integrity", Icon: Database },
];

export default function Sidebar() {
  return (
    <aside className="flex h-svh w-64 flex-col border-r border-zinc-800/50 bg-zinc-950/50 backdrop-blur-xl">
      {/* Brand */}
      <div className="flex items-center gap-3 px-5 py-5 border-b border-zinc-800/50">
        <div className="p-2 rounded-lg bg-gradient-to-br from-blue-500/10 to-blue-600/5 border border-blue-500/20">
          <BrandMark className="h-6 w-6 text-blue-400" />
        </div>
        <div className="leading-tight">
          <div className="text-sm font-bold text-zinc-200">Smartify</div>
          <div className="text-xs text-zinc-400">Van dashboard</div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4">
        <ul className="space-y-1.5">
          {nav.map(({ to, label, Icon }) => (
            <li key={to}>
              <NavLink
                to={to}
                end={to === "/dashboard"}
                className={({ isActive }) =>
                  [
                    "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-all duration-200 relative group",
                    isActive
                      ? "bg-gradient-to-r from-blue-500/10 to-blue-600/5 text-blue-400 font-medium border border-blue-500/20 shadow-lg shadow-blue-500/5"
                      : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/30",
                  ].join(" ")
                }
              >
                {({ isActive }) => (
                  <>
                    <Icon className="h-4 w-4 relative z-10" />
                    <span className="relative z-10">{label}</span>
                    {isActive && (
                      <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-6 bg-blue-400 rounded-r-full" />
                    )}
                  </>
                )}
              </NavLink>
            </li>
          ))}
        </ul>

        <div className="mt-6 px-2 text-xs font-semibold uppercase tracking-[0.2em] text-zinc-500/80">
          System
        </div>
        <ul className="mt-2 space-y-1.5">
          {systemNav.map(({ to, label, Icon }) => (
            <li key={to}>
              <NavLink
                to={to}
                className={({ isActive }) =>
                  [
                    "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-all duration-200 relative group",
                    isActive
                      ? "bg-gradient-to-r from-emerald-500/10 to-emerald-600/5 text-emerald-300 font-medium border border-emerald-500/20 shadow-lg shadow-emerald-500/5"
                      : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/30",
                  ].join(" ")
                }
              >
                {({ isActive }) => (
                  <>
                    <Icon className="h-4 w-4 relative z-10" />
                    <span className="relative z-10">{label}</span>
                    {isActive && (
                      <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-6 bg-emerald-400 rounded-r-full" />
                    )}
                  </>
                )}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      {/* Footer */}
      <div className="px-5 py-4 text-xs text-zinc-500 border-t border-zinc-800/50">
        <div className="flex items-center gap-2">
          <div className="h-2 w-2 rounded-full bg-emerald-500/50 animate-pulse" />
          <span>Local only • Raspberry Pi</span>
        </div>
      </div>
    </aside>
  );
}
