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
  if (!gps.ok || gps.error) {
    return { text: "NO GPS", cls: "bg-red-500/10 text-red-400 border-red-500/30" };
  }
  
  if (gps.lat != null && gps.lon != null) {
    return { 
      text: "FIX OK", 
      cls: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
      satellites: gps.satellites ?? undefined
    };
  }
  
  return { text: "NO FIX", cls: "bg-amber-500/10 text-amber-400 border-amber-500/30" };
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
    <header className="h-16 border-b border-zinc-800/50 flex items-center justify-between px-6 bg-zinc-950/50 backdrop-blur-xl">
      <div className="flex items-center gap-4 min-w-0">
        <div className="md:hidden h-9 w-9 rounded-lg border border-zinc-800/50 flex items-center justify-center bg-zinc-900/50">
          <BrandMark className="h-5 w-5 text-zinc-300" />
        </div>

        <div className="font-semibold tracking-tight flex items-center gap-2.5 text-zinc-200">
          <BrandMark className="h-5 w-5 hidden md:block text-zinc-300" />
          <span className="text-lg">Smartify</span>
        </div>

        <div className={`text-xs px-3 py-1.5 rounded-lg border backdrop-blur-sm font-medium flex items-center gap-2 transition-all ${badge.cls}`}>
          <MapPin className="h-3.5 w-3.5" />
          <span>{badge.text}</span>
          {hasFix && badge.satellites !== undefined && (
            <span className="opacity-70 text-xs">({badge.satellites} sat)</span>
          )}
        </div>
      </div>

      <div className="flex items-center gap-4">
        <div className="text-sm text-zinc-400 hidden sm:block font-medium">
          {me.user ? me.user : ""}
        </div>
        <Button 
          variant="secondary" 
          size="sm" 
          onClick={doLogout}
          className="bg-zinc-800/50 hover:bg-zinc-700/50 border-zinc-700/50 text-zinc-200"
        >
          Logout
        </Button>
      </div>
    </header>
  );
};

export default TopBar;
