import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { MapPin } from "lucide-react";
import { apiFetch } from "@/lib/utils";

type MeResp = { user?: string };
type GpsCurrent = {
  ts?: number | null;
  lat?: number | null;
  lon?: number | null;
  speed_kmh?: number | null;
  course?: number | null;
  altitude_m?: number | null;
  satellites?: number | null;
  ok?: boolean;
  error?: string | null;
  source?: string;
  device?: string;
};

function gpsLabel(gps: GpsCurrent): { text: string; cls: string; satellites?: number } {
  // If GPS is not ok or has error, show disconnected
  if (!gps.ok || gps.error) {
    return { text: "NO GPS", cls: "bg-red-500/15 text-red-400 border-red-500/30" };
  }
  
  // If we have valid coordinates, we have a fix
  if (gps.lat != null && gps.lon != null) {
    return { 
      text: "FIX OK", 
      cls: "bg-green-500/15 text-green-400 border-green-500/30",
      satellites: gps.satellites ?? undefined
    };
  }
  
  // GPS is ok but no coordinates yet
  return { text: "NO FIX", cls: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30" };
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
      const rMe = await apiFetch("/api/me");
      if (rMe.ok) setMe(await rMe.json());

      const rGps = await apiFetch("/api/gps/current");
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
      await apiFetch("/logout", { method: "POST" });
    } finally {
      window.location.href = "/login";
    }
  };

  const badge = gpsLabel(gps);
  const hasFix = gps.ok && gps.lat != null && gps.lon != null;

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

        <div className={`text-xs px-2 py-1 rounded-md border ${badge.cls} flex items-center gap-1.5`}>
          <MapPin className="h-3.5 w-3.5" />
          <span>{badge.text}</span>
          {hasFix && badge.satellites !== undefined && (
            <span className="opacity-70">({badge.satellites} sat)</span>
          )}
        </div>
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
