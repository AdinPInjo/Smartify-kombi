import { Bell, Cpu, Gauge, Map, Settings, SunMedium, Thermometer, ToggleRight } from "lucide-react";
import { Link, NavLink, Outlet } from "react-router-dom";
import { useHealth, useMode, useNotificationSettings } from "@/api/hooks";
import { Topo } from "./instruments";

const NAV = [
  { to: "/", label: "Overview", Icon: Gauge, end: true },
  { to: "/energy", label: "Energy", Icon: SunMedium },
  { to: "/climate", label: "Climate", Icon: Thermometer },
  { to: "/switches", label: "Switches", Icon: ToggleRight },
  { to: "/map", label: "Map", Icon: Map },
  { to: "/sensors", label: "Sensors", Icon: Cpu },
  { to: "/notifications", label: "Alerts", Icon: Bell },
];

export function AppShell() {
  const { cloud, ready } = useMode();
  const version = useHealth().data?.version ?? __APP_VERSION__;
  const notifications = useNotificationSettings(ready && !cloud);
  // A dot on the Alerts tab until the van can reach a phone.
  const needsSetup = notifications.data !== undefined && notifications.data.active_channels.length === 0;
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
            {to === "/notifications" && needsSetup && <span className="nav-dot" aria-label="not set up" />}
          </NavLink>
        ))}
        <NavLink to="/settings" className="desktop-only">
          <Settings size={22} strokeWidth={2} aria-hidden="true" />
          Settings
        </NavLink>
        <Link to="/changelog" className="nav-version" title="What's new">
          Smartify {version}
          {cloud ? " · remote" : ""}
        </Link>
      </nav>
    </div>
  );
}
