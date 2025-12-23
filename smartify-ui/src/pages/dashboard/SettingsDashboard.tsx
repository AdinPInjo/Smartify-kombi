import { useEffect, useMemo, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiFetch } from "@/lib/utils";

type NetItem = { ssid: string; signal: number | null; security: string };
type NetStatus = { ssid: string | null; ip: string | null };

const SettingsDashboard = () => {
  const [status, setStatus] = useState<NetStatus>({ ssid: null, ip: null });
  const [networks, setNetworks] = useState<NetItem[]>([]);
  const [selectedSsid, setSelectedSsid] = useState<string>("");
  const [password, setPassword] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string>("");

  const canConnect = useMemo(() => selectedSsid.trim().length > 0, [selectedSsid]);

  const loadStatus = async () => {
    const r = await apiFetch("/api/network/status");
    if (r.ok) setStatus(await r.json());
  };

  const scan = async () => {
    setBusy(true);
    setMsg("");
    try {
      const r = await apiFetch("/api/network/scan");
      if (!r.ok) throw new Error("Scan failed");
      const data = await r.json();
      setNetworks(data.networks || []);
    } catch (e: any) {
      setMsg(e?.message || "Scan failed");
    } finally {
      setBusy(false);
    }
  };

  const connect = async () => {
    if (!canConnect) return;
    setBusy(true);
    setMsg("");

    try {
      const r = await apiFetch("/api/network/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ssid: selectedSsid, password: password || "" }),
      });

      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data?.detail || data?.error || "Connect failed");

      setMsg("✅ Wi-Fi change triggered. If the Pi switches networks, this page may disconnect.");
      // Give it a moment, then refresh status (may fail if network changes)
      setTimeout(loadStatus, 1500);
    } catch (e: any) {
      setMsg(`❌ ${e?.message || "Connect failed"}`);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    loadStatus();
  }, []);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Network</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="text-sm">
            <div><span className="opacity-70">Connected SSID:</span> <span className="font-medium">{status.ssid ?? "—"}</span></div>
            <div><span className="opacity-70">IP:</span> <span className="font-medium">{status.ip ?? "—"}</span></div>
          </div>

          <div className="flex gap-2 flex-wrap">
            <Button onClick={scan} disabled={busy}>Scan networks</Button>
            <Button variant="secondary" onClick={loadStatus} disabled={busy}>Refresh status</Button>
          </div>

          {networks.length > 0 && (
            <div className="space-y-2">
              <div className="text-sm font-medium">Available networks</div>
              <div className="max-h-56 overflow-auto rounded-lg border">
                {networks.map((n) => (
                  <button
                    key={n.ssid}
                    onClick={() => setSelectedSsid(n.ssid)}
                    className={[
                      "w-full text-left px-3 py-2 text-sm flex items-center justify-between border-b last:border-b-0",
                      selectedSsid === n.ssid ? "bg-muted" : "hover:bg-muted/60",
                    ].join(" ")}
                  >
                    <span className="truncate">{n.ssid}</span>
                    <span className="text-xs opacity-70">
                      {n.signal ?? "—"}% · {n.security || "open"}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="space-y-1">
              <div className="text-sm font-medium">SSID</div>
              <Input value={selectedSsid} onChange={(e) => setSelectedSsid(e.target.value)} placeholder="Select from scan or type SSID" />
            </div>

            <div className="space-y-1">
              <div className="text-sm font-medium">Password</div>
              <Input value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Leave empty for open Wi-Fi" type="password" />
            </div>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <Button onClick={connect} disabled={busy || !canConnect}>
              Apply Wi-Fi
            </Button>
            <div className="text-xs opacity-70">
              ⚠️ Applying may disconnect this page if the Pi moves to another network.
            </div>
          </div>

          {msg && <div className="text-sm">{msg}</div>}
        </CardContent>
      </Card>
    </div>
  );
};

export default SettingsDashboard;
