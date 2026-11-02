import { Gauge, Map, Settings, SunMedium, Thermometer, ToggleRight } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";
import { Topo } from "./instruments";

const NAV = [
  { to: "/", label: "Overview", Icon: Gauge, end: true },
  { to: "/energy", label: "Energy", Icon: SunMedium },
  { to: "/climate", label: "Climate", Icon: Thermometer },
  { to: "/switches", label: "Switches", Icon: ToggleRight },
  { to: "/map", label: "Map", Icon: Map },
];

export function AppShell() {
  return (
    <div className="shell">
      <Topo />
      <Outlet />
      <nav className="bottom-nav" aria-label="Main">
        <div className="nav-brand">SMARTIFY · KOMBI</div>
        {NAV.map(({ to, label, Icon, end }) => (
          <NavLink key={to} to={to} end={end}>
            <Icon size={22} strokeWidth={2} aria-hidden="true" />
            {label}
          </NavLink>
        ))}
        <NavLink to="/settings" className="desktop-only">
          <Settings size={22} strokeWidth={2} aria-hidden="true" />
          Settings
        </NavLink>
      </nav>
    </div>
  );
}
