import { useEffect, useMemo, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiFetch } from "@/lib/utils";
import { toast } from "sonner";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

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

      {/* Water Level Calibration Card */}
      <WaterLevelSettingsCard />
    </div>
  );
};

type WaterLevelSettings = {
  ok: boolean;
  full_voltage: number;
  empty_voltage: number;
  use_supply_normalization?: boolean;
  adc_channel_signal?: number;
  adc_channel_supply?: number;
  divider_r_top?: number;
  divider_r_bottom?: number;
  full_ratio?: number | null;
  empty_ratio?: number | null;
  full_supply_voltage?: number | null;
  empty_supply_voltage?: number | null;
  updated_at: number;
};

type WaterLevelLive = {
  ok: boolean;
  signal_voltage: number | null;
  supply_div_voltage: number | null;
  supply_voltage_est: number | null;
  ratio: number | null;
  level_percent: number | null;
  address: string | null;
  status: string;
  message: string;
};

type WaterLevelLatest = {
  ok: boolean;
  level_percent: number | null;
  avg_voltage: number | null;
  signal_voltage?: number | null;
  supply_div_voltage?: number | null;
  supply_voltage_est?: number | null;
  ratio?: number | null;
  status: string;
  age_seconds: number;
  message: string;
  calibration_full_voltage?: number | null;
  calibration_empty_voltage?: number | null;
  use_supply_normalization?: boolean;
};

function WaterLevelSettingsCard() {
  const queryClient = useQueryClient();
  const [fullVoltage, setFullVoltage] = useState<string>("");
  const [emptyVoltage, setEmptyVoltage] = useState<string>("");
  const [fullRatio, setFullRatio] = useState<string>("");
  const [emptyRatio, setEmptyRatio] = useState<string>("");
  const [useNormalization, setUseNormalization] = useState<boolean>(true);
  const [dividerRTop, setDividerRTop] = useState<string>("47000");
  const [dividerRBottom, setDividerRBottom] = useState<string>("10000");
  const [liveData, setLiveData] = useState<WaterLevelLive | null>(null);
  const [loadingLive, setLoadingLive] = useState(false);

  // Fetch current settings
  const { data: settings, isLoading: loadingSettings } = useQuery<WaterLevelSettings>({
    queryKey: ["water-level-settings"],
    queryFn: async () => {
      const r = await apiFetch("/api/water/settings");
      if (!r.ok) throw new Error(`Settings API returned ${r.status}`);
      return await r.json();
    },
  });

  // Fetch snapshot data (for showing current snapshot voltage)
  const { data: snapshotData } = useQuery<WaterLevelLatest>({
    queryKey: ["water-level"],
    queryFn: async () => {
      const r = await apiFetch("/api/water/level/latest");
      if (!r.ok) throw new Error(`Water level API returned ${r.status}`);
      return await r.json();
    },
    refetchInterval: 10000, // Poll every 10 seconds
  });

  // Initialize form with current settings
  useEffect(() => {
    if (settings && settings.ok) {
      setFullVoltage(settings.full_voltage?.toFixed(3) || "");
      setEmptyVoltage(settings.empty_voltage?.toFixed(3) || "");
      setFullRatio(settings.full_ratio?.toFixed(6) || "");
      setEmptyRatio(settings.empty_ratio?.toFixed(6) || "");
      setUseNormalization(settings.use_supply_normalization ?? true);
      setDividerRTop(settings.divider_r_top?.toString() || "47000");
      setDividerRBottom(settings.divider_r_bottom?.toString() || "10000");
    }
  }, [settings]);

  // Fetch live data
  const fetchLiveData = async () => {
    setLoadingLive(true);
    // Clear live data immediately to prevent showing stale/incorrect values
    setLiveData(null);
    try {
      const r = await apiFetch("/api/water/level/live");
      if (!r.ok) {
        const errorData = await r.json().catch(() => ({}));
        throw new Error(errorData.message || errorData.error || "Failed to read live data");
      }
      const data: WaterLevelLive = await r.json();
      if (data.ok) {
        // Only set live data when we have valid response
        setLiveData(data);
        if (data.signal_voltage != null) {
          const supplyText = data.supply_voltage_est != null ? data.supply_voltage_est.toFixed(2) : "—";
          toast.success(`Live read: Signal=${data.signal_voltage.toFixed(3)}V, Supply=${supplyText}V`);
        } else {
          toast.error(data.message || "Live data read but signal voltage is missing");
        }
      } else {
        toast.error(data.message || "Failed to read live data");
        // Don't clear existing liveData on error - keep previous values
      }
    } catch (error: any) {
      toast.error(error.message || "Failed to read live data");
      // Don't clear existing liveData on error - keep previous values
    } finally {
      setLoadingLive(false);
    }
  };

  // Helper: Set FULL calibration from current live reading
  const setFullFromLive = () => {
    if (!liveData || !liveData.ok) {
      toast.error("No live data available. Please refresh first.");
      return;
    }
    if (useNormalization) {
      if (liveData.ratio != null && liveData.ratio > 0) {
        setFullRatio(liveData.ratio.toFixed(6));
        toast.success(`Set FULL ratio to ${liveData.ratio.toFixed(6)}`);
      } else {
        toast.error("Live ratio data not available");
      }
    } else {
      if (liveData.signal_voltage != null && liveData.signal_voltage > 0) {
        setFullVoltage(liveData.signal_voltage.toFixed(3));
        toast.success(`Set FULL voltage to ${liveData.signal_voltage.toFixed(3)}V`);
      } else {
        toast.error("Live signal voltage data not available");
      }
    }
  };

  // Helper: Set EMPTY calibration from current live reading
  const setEmptyFromLive = () => {
    if (!liveData || !liveData.ok) {
      toast.error("No live data available. Please refresh first.");
      return;
    }
    if (useNormalization) {
      if (liveData.ratio != null && liveData.ratio > 0) {
        setEmptyRatio(liveData.ratio.toFixed(6));
        toast.success(`Set EMPTY ratio to ${liveData.ratio.toFixed(6)}`);
      } else {
        toast.error("Live ratio data not available");
      }
    } else {
      if (liveData.signal_voltage != null && liveData.signal_voltage > 0) {
        setEmptyVoltage(liveData.signal_voltage.toFixed(3));
        toast.success(`Set EMPTY voltage to ${liveData.signal_voltage.toFixed(3)}V`);
      } else {
        toast.error("Live signal voltage data not available");
      }
    }
  };

  // Save settings mutation
  const saveMutation = useMutation({
    mutationFn: async (data: {
      full_voltage?: number;
      empty_voltage?: number;
      full_ratio?: number;
      empty_ratio?: number;
      use_supply_normalization?: boolean;
      divider_r_top?: number;
      divider_r_bottom?: number;
    }) => {
      const r = await apiFetch("/api/water/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (!r.ok) {
        const errorData = await r.json().catch(() => ({}));
        throw new Error(errorData.message || errorData.error || "Failed to save settings");
      }
      return await r.json();
    },
    onSuccess: () => {
      toast.success("Water level calibration saved successfully");
      queryClient.invalidateQueries({ queryKey: ["water-level-settings"] });
      queryClient.invalidateQueries({ queryKey: ["water-level"] }); // Refresh overview card
    },
    onError: (error: Error) => {
      toast.error(`Failed to save settings: ${error.message}`);
    },
  });

  const handleSave = () => {
    const updateData: any = {
      use_supply_normalization: useNormalization,
      divider_r_top: parseFloat(dividerRTop),
      divider_r_bottom: parseFloat(dividerRBottom),
    };

    // Validate divider values
    if (isNaN(updateData.divider_r_top) || isNaN(updateData.divider_r_bottom)) {
      toast.error("Divider resistor values must be valid numbers");
      return;
    }

    if (updateData.divider_r_top <= 0 || updateData.divider_r_bottom <= 0) {
      toast.error("Divider resistor values must be positive");
      return;
    }

    if (useNormalization) {
      // Ratio-based calibration
      const full = parseFloat(fullRatio);
      const empty = parseFloat(emptyRatio);

      if (isNaN(full) || isNaN(empty)) {
        toast.error("Both ratios must be valid numbers");
        return;
      }

      if (full <= 0 || empty <= 0) {
        toast.error("Ratios must be positive numbers");
        return;
      }

      if (Math.abs(full - empty) < 0.0001) {
        toast.error("Full and empty ratios must be different");
        return;
      }

      updateData.full_ratio = full;
      updateData.empty_ratio = empty;
    } else {
      // Voltage-based calibration (backward compatibility)
      const full = parseFloat(fullVoltage);
      const empty = parseFloat(emptyVoltage);

      if (isNaN(full) || isNaN(empty)) {
        toast.error("Both voltages must be valid numbers");
        return;
      }

      if (full <= 0 || empty <= 0) {
        toast.error("Voltages must be positive numbers");
        return;
      }

      if (Math.abs(full - empty) < 0.001) {
        toast.error("Full and empty voltages must be different");
        return;
      }

      updateData.full_voltage = full;
      updateData.empty_voltage = empty;
    }

    saveMutation.mutate(updateData);
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Water Level Calibration</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="text-sm text-zinc-400">
          Tip: Set FULL when tank is physically full and note the live voltage; same for EMPTY.
        </div>

        {/* Current Readings */}
        <div className="space-y-2 p-3 bg-zinc-900/50 rounded-lg border border-zinc-800/50">
          <div className="text-sm font-medium text-zinc-300">Current Readings</div>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <span className="text-zinc-400">Signal (A0):</span>{" "}
              <span className="font-semibold text-zinc-200">
                {liveData?.signal_voltage != null
                  ? `${liveData.signal_voltage.toFixed(3)} V`
                  : snapshotData?.signal_voltage != null
                  ? `${snapshotData.signal_voltage.toFixed(3)} V`
                  : "—"}
              </span>
            </div>
            <div>
              <span className="text-zinc-400">Supply:</span>{" "}
              <span className="font-semibold text-zinc-200">
                {liveData?.supply_voltage_est != null
                  ? `${liveData.supply_voltage_est.toFixed(2)} V`
                  : snapshotData?.supply_voltage_est != null
                  ? `${snapshotData.supply_voltage_est.toFixed(2)} V`
                  : "—"}
              </span>
            </div>
            {useNormalization && (
              <>
                <div>
                  <span className="text-zinc-400">Ratio:</span>{" "}
                  <span className="font-semibold text-zinc-200">
                    {liveData?.ratio != null
                      ? liveData.ratio.toFixed(6)
                      : snapshotData?.ratio != null
                      ? snapshotData.ratio.toFixed(6)
                      : "—"}
                  </span>
                </div>
                <div>
                  <span className="text-zinc-400">Level:</span>{" "}
                  <span className="font-semibold text-zinc-200">
                    {loadingLive
                      ? "Refreshing..."
                      : liveData?.level_percent != null
                      ? `${liveData.level_percent}%`
                      : snapshotData?.level_percent != null
                      ? `${snapshotData.level_percent}%`
                      : "—"}
                  </span>
                </div>
              </>
            )}
            <div>
              <span className="text-zinc-400">Status:</span>{" "}
              <span
                className={`font-semibold ${
                  snapshotData?.status === "error" || snapshotData?.status === "stale"
                    ? "text-amber-400"
                    : snapshotData?.status === "ok"
                    ? "text-zinc-200"
                    : "text-zinc-400"
                }`}
              >
                {snapshotData?.message ?? "—"}
              </span>
            </div>
            {snapshotData?.age_seconds != null && (
              <div className="text-xs text-zinc-500">
                Snapshot age: {snapshotData.age_seconds}s
              </div>
            )}
          </div>
          <Button
            onClick={fetchLiveData}
            disabled={loadingLive}
            variant="outline"
            size="sm"
            className="w-full"
          >
            {loadingLive ? "Reading..." : "Refresh Live Data"}
          </Button>
        </div>

        {/* Calibration Settings */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="text-sm font-medium text-zinc-300">Calibration Settings</div>
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="use-normalization"
                checked={useNormalization}
                onChange={(e) => setUseNormalization(e.target.checked)}
                disabled={loadingSettings || saveMutation.isPending}
                className="rounded"
              />
              <Label htmlFor="use-normalization" className="text-xs cursor-pointer">
                Use supply normalization
              </Label>
            </div>
          </div>

          {useNormalization ? (
            <>
              {/* Ratio-based calibration */}
              <div className="space-y-2 p-3 bg-zinc-900/30 rounded-lg border border-zinc-800/30">
                <div className="text-xs text-zinc-400 mb-2">Ratio Calibration (Signal/Supply)</div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <Label htmlFor="full-ratio" className="text-xs">Full Ratio</Label>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={setFullFromLive}
                        disabled={!liveData || loadingLive}
                        className="h-6 text-xs px-2"
                      >
                        Set from live
                      </Button>
                    </div>
                    <Input
                      id="full-ratio"
                      type="number"
                      step="0.000001"
                      value={fullRatio}
                      onChange={(e) => setFullRatio(e.target.value)}
                      placeholder="0.512"
                      disabled={loadingSettings || saveMutation.isPending}
                      className="h-8 text-sm"
                    />
                  </div>
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <Label htmlFor="empty-ratio" className="text-xs">Empty Ratio</Label>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={setEmptyFromLive}
                        disabled={!liveData || loadingLive}
                        className="h-6 text-xs px-2"
                      >
                        Set from live
                      </Button>
                    </div>
                    <Input
                      id="empty-ratio"
                      type="number"
                      step="0.000001"
                      value={emptyRatio}
                      onChange={(e) => setEmptyRatio(e.target.value)}
                      placeholder="0.693"
                      disabled={loadingSettings || saveMutation.isPending}
                      className="h-8 text-sm"
                    />
                  </div>
                </div>
              </div>
            </>
          ) : (
            <>
              {/* Voltage-based calibration (backward compatibility) */}
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label htmlFor="full-voltage">Full Tank Voltage (V)</Label>
                  <Input
                    id="full-voltage"
                    type="number"
                    step="0.001"
                    value={fullVoltage}
                    onChange={(e) => setFullVoltage(e.target.value)}
                    placeholder="0.497"
                    disabled={loadingSettings || saveMutation.isPending}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="empty-voltage">Empty Tank Voltage (V)</Label>
                  <Input
                    id="empty-voltage"
                    type="number"
                    step="0.001"
                    value={emptyVoltage}
                    onChange={(e) => setEmptyVoltage(e.target.value)}
                    placeholder="2.230"
                    disabled={loadingSettings || saveMutation.isPending}
                  />
                </div>
              </div>
            </>
          )}

          {/* Divider settings (only shown when normalization enabled) */}
          {useNormalization && (
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label htmlFor="divider-r-top" className="text-xs">Divider R_top (Ω)</Label>
                <Input
                  id="divider-r-top"
                  type="number"
                  step="100"
                  value={dividerRTop}
                  onChange={(e) => setDividerRTop(e.target.value)}
                  placeholder="47000"
                  disabled={loadingSettings || saveMutation.isPending}
                  className="h-8 text-sm"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="divider-r-bottom" className="text-xs">Divider R_bottom (Ω)</Label>
                <Input
                  id="divider-r-bottom"
                  type="number"
                  step="100"
                  value={dividerRBottom}
                  onChange={(e) => setDividerRBottom(e.target.value)}
                  placeholder="10000"
                  disabled={loadingSettings || saveMutation.isPending}
                  className="h-8 text-sm"
                />
              </div>
            </div>
          )}

          <Button
            onClick={handleSave}
            disabled={loadingSettings || saveMutation.isPending}
            className="w-full"
          >
            {saveMutation.isPending ? "Saving..." : "Save Calibration"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export default SettingsDashboard;
