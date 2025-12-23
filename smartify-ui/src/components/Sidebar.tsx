import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  MapPin,
  BatteryCharging,
  ToggleLeft,
  Settings,
  Thermometer,
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

export default function Sidebar() {
  return (
    <aside className="flex h-svh w-64 flex-col border-r bg-background">
      {/* Brand */}
      <div className="flex items-center gap-3 px-4 py-4">
        <BrandMark className="h-8 w-8" />
        <div className="leading-tight">
          <div className="text-sm font-semibold">Smartify</div>
          <div className="text-xs opacity-70">Van dashboard</div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-2">
        <ul className="space-y-1">
          {nav.map(({ to, label, Icon }) => (
            <li key={to}>
              <NavLink
                to={to}
                end={to === "/dashboard"}
                className={({ isActive }) =>
                  [
                    "flex items-center gap-3 rounded-xl px-3 py-2 text-sm transition",
                    isActive
                      ? "bg-muted font-medium"
                      : "opacity-80 hover:opacity-100 hover:bg-muted/60",
                  ].join(" ")
                }
              >
                <Icon className="h-4 w-4" />
                <span>{label}</span>
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      {/* Footer */}
      <div className="px-4 py-3 text-xs opacity-60">
        Local only • Raspberry Pi
      </div>
    </aside>
  );
}
