import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { MapPin } from "lucide-react";

type MeResp = { user?: string };
type GpsCurrent = {
  ts?: string | null;
  mode?: number;
  lat?: number | null;
  lon?: number | null;
  speed_m_s?: number | null;
};

function gpsLabel(mode?: number) {
  if (!mode) return { text: "NO GPS", cls: "bg-red-500/15 text-red-400 border-red-500/30" };
  if (mode >= 3) return { text: "3D FIX", cls: "bg-green-500/15 text-green-400 border-green-500/30" };
  if (mode >= 2) return { text: "2D FIX", cls: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30" };
  return { text: "NO FIX", cls: "bg-red-500/15 text-red-400 border-red-500/30" };
}

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

const TopBar = () => {
  const [me, setMe] = useState<MeResp>({});
  const [gps, setGps] = useState<GpsCurrent>({});

  const load = async () => {
    try {
      const rMe = await fetch("/api/me", { credentials: "include" });
      if (rMe.ok) setMe(await rMe.json());

      const rGps = await fetch("/api/gps/current", { credentials: "include" });
      if (rGps.ok) setGps(await rGps.json());
    } catch {
      // ignore (wifi switching etc.)
    }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  const doLogout = async () => {
    try {
      await fetch("/logout", { method: "POST", credentials: "include" });
    } finally {
      window.location.href = "/login";
    }
  };

  const badge = gpsLabel(gps.mode);
  const ts = gps.ts ? String(gps.ts).replace("T", " ").replace("Z", " UTC") : null;

  return (
    <header className="h-14 border-b flex items-center justify-between px-4 bg-background">
      <div className="flex items-center gap-3 min-w-0">
        <div className="md:hidden h-8 w-8 rounded-lg border flex items-center justify-center bg-muted">
          <BrandMark className="h-5 w-5" />
        </div>

        <div className="font-semibold tracking-tight flex items-center gap-2">
          <BrandMark className="h-5 w-5 hidden md:block" />
          Smartify
        </div>

        <div className={`text-xs px-2 py-1 rounded-md border ${badge.cls} flex items-center gap-1`}>
          <MapPin className="h-3.5 w-3.5" />
          {badge.text}
        </div>

        {ts && (
          <div className="text-xs opacity-70 hidden lg:block truncate">
            Last GPS: {ts}
          </div>
        )}
      </div>

      <div className="flex items-center gap-3">
        <div className="text-sm opacity-80 hidden sm:block">
          {me.user ? me.user : ""}
        </div>
        <Button variant="secondary" size="sm" onClick={doLogout}>
          Logout
        </Button>
      </div>
    </header>
  );
};

export default TopBar;
