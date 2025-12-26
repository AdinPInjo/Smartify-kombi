import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ToggleLeft, Power, Plus, Trash2, Edit2, Clock, Pause, Play } from "lucide-react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { apiFetch } from "@/lib/utils";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

type Relay = {
  id: string;
  name: string;
  pin: number;
  state: "on" | "off";
  mode: "auto" | "manual";
  manual_until: number | null;
  updated_at: number | null;
  is_enabled: boolean;
  pending?: boolean;
  pending_reason?: string;
  pending_message?: string;
  cooldown_remaining?: number | null;
  sensor_age_seconds?: number | null;
  sensor_sample_count?: number | null;
  sensor_is_ready?: boolean | null;
  sensor_is_stale?: boolean | null;
  source?: string;
};

type Rule = {
  id: string;
  relay_id: string;
  name: string;
  is_enabled: boolean;
  priority: number;
  condition: {
    type: string;
    sensor: string;
    operator: string;
    value: number;
  };
  action: "turn_on" | "turn_off";
  cooldown_seconds: number;
  last_triggered_at: number | null;
  created_at: number;
  updated_at: number;
  // Runtime status (from backend)
  runtime_status?: {
    can_evaluate?: boolean;
    matched?: boolean;
    reason_code?: "ok" | "sensor_warming_up" | "sensor_stale" | "cooldown" | "disabled" | "parse_error" | "error";
    message?: string;
    sensor_name?: string | null;
    snapshot_temp?: number | null;
    threshold?: number | null;
    operator?: string | null;
    age_seconds?: number | null;
    sample_count?: number;
    cooldown_remaining?: number | null;
  };
};

function RelaysDashboard() {
  const queryClient = useQueryClient();
  const [editingRule, setEditingRule] = useState<Rule | null>(null);
  const [isRuleDialogOpen, setIsRuleDialogOpen] = useState(false);
  const [selectedRelayId, setSelectedRelayId] = useState<string | null>(null);

  // Fetch all relays
  const { data: relaysResponse, isLoading: isLoadingRelays, error: relaysError } = useQuery({
    queryKey: ["relays"],
    queryFn: async () => {
      const r = await apiFetch("/api/relays", { cache: "no-store" });
      if (!r.ok) {
        const errorText = await r.text();
        console.error("[RelaysDashboard] API error:", r.status, errorText);
        throw new Error(`Relays API returned ${r.status}`);
      }
      const data = await r.json();
      console.log("[RelaysDashboard] API response:", data);
      // Check if response indicates error
      if (data.ok === false) {
        throw new Error(data.error || data.message || "Failed to load relays");
      }
      // Ensure we have a valid relays array - harden parsing to prevent .some() crash
      if (!data || typeof data !== "object") {
        console.error("[RelaysDashboard] Invalid response format:", data);
        console.warn("[RelaysDashboard] Received invalid response shape, expected object with 'relays' array");
        throw new Error("Invalid API response format");
      }
      // Harden array parsing: handle both {relays: [...]} and direct array
      const relaysArr = Array.isArray(data?.relays) ? data.relays : (Array.isArray(data) ? data : []);
      if (!Array.isArray(relaysArr)) {
        console.warn("[RelaysDashboard] relays is not an array:", typeof relaysArr, relaysArr);
        throw new Error("Invalid relays array format");
      }
      console.log("[RelaysDashboard] Parsed relays:", relaysArr.length, "relays");
      return relaysArr as Relay[];
    },
    retry: 1,
    refetchInterval: (query) => {
      // Poll more frequently (1.5s) when any relay is pending, otherwise 5s
      // Harden: never call .some() on non-array
      const data = query.state.data;
      if (!data || !Array.isArray(data)) {
        return 5000;  // Default interval if data is invalid
      }
      const relays = data as Relay[];
      const hasPending = relays.some(r => r.pending === true);
      return hasPending ? 1500 : 5000;
    },
  });

  // Harden: ensure relays is always an array
  const relays = Array.isArray(relaysResponse) ? relaysResponse : [];

  // Fetch rules for all relays - aggregate all rules
  const { data: rulesResponse, isLoading: isLoadingRules } = useQuery({
    queryKey: ["relay-rules", relays.map(r => r.id).sort().join(",")],
    queryFn: async () => {
      if (relays.length === 0) return { rules: [] };
      
      const allRules: any[] = [];
      for (const relay of relays) {
        try {
          const r = await apiFetch(`/api/relays/${relay.id}/rules`, { cache: "no-store" });
          if (r.ok) {
            const data = await r.json();
            if (data.rules && Array.isArray(data.rules)) {
              allRules.push(...data.rules);
            }
          }
        } catch (err) {
          console.error(`[RelaysDashboard] Failed to fetch rules for relay ${relay.id}:`, err);
        }
      }
      return { rules: allRules };
    },
    enabled: relays.length > 0,
    retry: 1,
  });

  const rules = rulesResponse?.rules || [];

  // Mutation to toggle relay state
  // NEVER optimistically update - always wait for backend confirmation
  const toggleRelayMutation = useMutation({
    mutationFn: async ({ relayId, state }: { relayId: string; state: "on" | "off" }) => {
      // Send logical state (user intent) - backend will handle hardware inversion
      const r = await apiFetch(`/api/relays/${relayId}/state`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ state: state, mode: "manual" }),
        cache: "no-store",
      });
      
      // Backend always returns 200, but may have ok: false for pending state
      const result = await r.json();
      if (!result.ok) {
        throw new Error(result.message || "Failed to set relay state");
      }
      
      // Refetch to get updated state (never update UI optimistically)
      await queryClient.invalidateQueries({ queryKey: ["relays"] });
      return result;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["relays"] });
      toast.success("Relay state updated");
    },
    onError: (error) => {
      toast.error("Failed to update relay", {
        description: error instanceof Error ? error.message : "Unknown error",
      });
      // Refetch to get current state from backend
      queryClient.invalidateQueries({ queryKey: ["relays"] });
    },
  });

  // Mutation to set auto mode
  const setAutoMutation = useMutation({
    mutationFn: async (relayId: string) => {
      const r = await apiFetch(`/api/relays/${relayId}/auto`, {
        method: "POST",
        cache: "no-store",
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ error: "unknown" }));
        throw new Error(err.message || `Failed to set auto: ${r.status}`);
      }
      return await r.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["relays"] });
      toast.success("Returned to auto mode");
    },
    onError: (error) => {
      toast.error("Failed to set auto mode", {
        description: error instanceof Error ? error.message : "Unknown error",
      });
    },
  });

  // Mutation to delete rule
  const deleteRuleMutation = useMutation({
    mutationFn: async (ruleId: string) => {
      const r = await apiFetch(`/api/rules/${ruleId}`, {
        method: "DELETE",
        cache: "no-store",
      });
      if (!r.ok) throw new Error(`Failed to delete rule: ${r.status}`);
      return await r.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["relay-rules"] });
      toast.success("Rule deleted");
    },
    onError: (error) => {
      toast.error("Failed to delete rule", {
        description: error instanceof Error ? error.message : "Unknown error",
      });
    },
  });

  // Mutation to toggle rule enabled (pause/resume)
  const toggleRuleMutation = useMutation({
    mutationFn: async ({ ruleId, isEnabled }: { ruleId: string; isEnabled: boolean }) => {
      const r = await apiFetch(`/api/rules/${ruleId}/toggle`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_enabled: isEnabled }),
        cache: "no-store",
      });
      if (!r.ok) throw new Error(`Failed to toggle rule: ${r.status}`);
      return await r.json();
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["relay-rules"] });
      toast.success(variables.isEnabled ? "Rule resumed" : "Rule paused");
    },
    onError: (error) => {
      toast.error("Failed to toggle rule", {
        description: error instanceof Error ? error.message : "Unknown error",
      });
    },
  });

  const formatRuleDescription = (rule: Rule) => {
    const cond = rule.condition || {};
    const sensor = cond.sensor || "unknown";
    const operator = cond.operator === "below" ? "<" : ">";
    const value = cond.value;
    const action = rule.action === "turn_on" ? "Turn ON" : "Turn OFF";
    return `${sensor.charAt(0).toUpperCase() + sensor.slice(1)} temp ${operator} ${value}°C → ${action}`;
  };

  const formatTimeAgo = (timestamp: number | null) => {
    if (!timestamp) return "Never";
    const seconds = Math.floor(Date.now() / 1000) - timestamp;
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
  };

  const handleRelayToggle = (relay: Relay, checked: boolean) => {
    // Guard: prevent undefined relay_id calls
    if (!relay?.id || relay.id === "undefined" || relay.id === "null") {
      toast.error("Relay ID missing", {
        description: "Relay data not loaded yet. Please wait and try again.",
      });
      return;
    }
    const newState: "on" | "off" = checked ? "on" : "off";
    toggleRelayMutation.mutate({ relayId: relay.id, state: newState });
  };

  const handleAddRule = (relayId: string) => {
    // Guard: prevent undefined relay_id calls
    if (!relayId || relayId === "undefined" || relayId === "null") {
      toast.error("Relay ID missing", {
        description: "Relay data not loaded yet. Please wait and try again.",
      });
      return;
    }
    setSelectedRelayId(relayId);
    setEditingRule(null);
    setIsRuleDialogOpen(true);
  };

  const handleEditRule = (rule: Rule) => {
    setEditingRule(rule);
    setIsRuleDialogOpen(true);
  };

  if (isLoadingRelays) {
    return (
      <div className="space-y-6">
        <div className="text-zinc-400">Loading relays...</div>
      </div>
    );
  }

  if (relaysError) {
    return (
      <div className="space-y-6">
        <div className="text-red-400">
          Error loading relays: {relaysError instanceof Error ? relaysError.message : "Unknown error"}
        </div>
        <Button onClick={() => queryClient.invalidateQueries({ queryKey: ["relays"] })}>Retry</Button>
      </div>
    );
  }

  // Handle empty relays array - show error banner if there was an error, otherwise "no relays"
  if (relays.length === 0) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
            <div className="p-2 rounded-lg bg-blue-500/10 border border-blue-500/20">
              <ToggleLeft className="h-6 w-6 text-blue-400" />
            </div>
            Relay Control
          </h1>
          <p className="text-sm text-zinc-400 mt-2">Manage connected devices and automation rules</p>
        </div>
        {relaysError ? (
          <Card className="border-red-500/50 bg-gradient-to-br from-red-900/20 to-zinc-950/50">
            <CardContent className="py-12 text-center">
              <p className="text-red-400 font-medium mb-2">Error loading relays</p>
              <p className="text-sm text-zinc-400 mb-4">
                {relaysError instanceof Error ? relaysError.message : "Unknown error occurred"}
              </p>
              <Button 
                onClick={() => queryClient.invalidateQueries({ queryKey: ["relays"] })} 
                className="mt-4"
                variant="outline"
              >
                Retry
              </Button>
            </CardContent>
          </Card>
        ) : (
          <Card className="border-zinc-800/50 bg-gradient-to-br from-zinc-900/50 to-zinc-950/50">
            <CardContent className="py-12 text-center">
              <p className="text-zinc-400">No relays found</p>
              <Button 
                onClick={() => queryClient.invalidateQueries({ queryKey: ["relays"] })} 
                className="mt-4"
              >
                Refresh
              </Button>
            </CardContent>
          </Card>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
          <div className="p-2 rounded-lg bg-blue-500/10 border border-blue-500/20">
            <ToggleLeft className="h-6 w-6 text-blue-400" />
          </div>
          Relay Control
        </h1>
        <p className="text-sm text-zinc-400 mt-2">Manage connected devices and automation rules</p>
      </div>

      {/* Relays */}
        {relays.map((relay) => {
        const isOn = relay.state === "on"; // Logical state: "on" means relay should be ON
        const isManual = relay.mode === "manual";
        const relayRules = rules.filter((r) => r.relay_id === relay.id);
        
        // Use pending state from API response (backend calculates cooldown/reconciling/startup)
        // Only used to disable toggle/mode switch, NOT for display (cooldown/warming shown per-rule)
        const isPending = relay.pending === true;

          return (
          <Card
            key={relay.id}
            className="group relative overflow-hidden border-zinc-800/50 bg-gradient-to-br from-zinc-900/50 to-zinc-950/50 backdrop-blur-sm transition-all duration-300 hover:shadow-xl hover:shadow-zinc-900/20"
          >
            <div className="absolute inset-0 bg-gradient-to-br from-orange-500/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
            <CardHeader className="pb-4 relative z-10">
                {/* Header row: Relay name (left) + Status badge (right) */}
                <div className="flex items-center justify-between mb-3">
                  <CardTitle className="text-lg font-semibold text-zinc-200 flex items-center gap-2">
                    <Power className="h-5 w-5 text-orange-400" />
                    {relay.name.charAt(0).toUpperCase() + relay.name.slice(1)}
                  </CardTitle>
                  {/* Status badge (top-right) - simplified, no cooldown/warming (shown per-rule) */}
                  <div className="flex items-center gap-2 text-xs max-w-[60%] text-right flex-shrink-0">
                    {isPending && relay.pending_reason === "reconciling" ? (
                      <div className="flex items-center gap-1.5">
                        <div className="h-3 w-3 border-2 border-zinc-500 border-t-transparent rounded-full animate-spin flex-shrink-0" />
                        <span className="text-zinc-400">Reconciling...</span>
                      </div>
                    ) : (
                      <span className="text-zinc-500">
                        {isManual ? (
                          <>MANUAL: {isOn ? "ON" : "OFF"}</>
                        ) : (
                          <>AUTO: monitoring {relayRules.length > 0 ? `${relayRules.length} rule${relayRules.length !== 1 ? "s" : ""}` : "no rules"}</>
                        )}
                      </span>
                    )}
                  </div>
                </div>
                {/* Controls row: Mode badge + State + Toggle */}
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                    {isManual ? (
                      <span className="text-xs px-2 py-0.5 rounded bg-orange-500/10 text-orange-400 border border-orange-500/20">
                        Manual
                      </span>
                    ) : (
                      <span className="text-xs px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20">
                        Auto
                      </span>
                    )}
                    <span className={`text-xs ${isOn ? "text-emerald-400" : "text-zinc-400"}`}>
                      {isOn ? "ON" : "OFF"}
                    </span>
                  </div>
                  <div className="flex items-center gap-3">
                  <Button
                    size="sm"
                    variant={isManual ? "default" : "outline"}
                    className={
                      isManual
                        ? "bg-orange-500/20 hover:bg-orange-500/30 border border-orange-500/50 text-orange-300"
                        : "bg-blue-500/20 hover:bg-blue-500/30 border border-blue-500/50 text-blue-300"
                    }
                    onClick={() => {
                      // Guard: prevent undefined relay_id calls
                      if (!relay?.id || relay.id === "undefined" || relay.id === "null") {
                        toast.error("Relay ID missing", {
                          description: "Relay data not loaded yet. Please wait and try again.",
                        });
                        return;
                      }
                      // Never allow mode change when pending
                      if (isPending) return;
                      if (isManual) {
                        // Return to auto mode
                        setAutoMutation.mutate(relay.id);
                      } else {
                        // Switch to manual mode - toggle current state to force manual mode
                        const newState = isOn ? "off" : "on";
                        toggleRelayMutation.mutate({ relayId: relay.id, state: newState });
                      }
                    }}
                    disabled={setAutoMutation.isPending || toggleRelayMutation.isPending || isPending}
                    title={isManual ? "Click to return to Auto mode" : "Click to switch to Manual mode"}
                  >
                    {isManual ? "Manual" : "Auto"}
                  </Button>
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <div className="flex items-center gap-2">
                          {isPending && !toggleRelayMutation.isPending && (
                            <div className="h-3 w-3 border-2 border-zinc-500 border-t-transparent rounded-full animate-spin opacity-50" />
                          )}
                          <Switch
                            checked={isOn}
                            onCheckedChange={(checked) => {
                              // Never allow toggle when pending - backend will reject anyway
                              if (isPending) return;
                              handleRelayToggle(relay, checked);
                            }}
                            disabled={toggleRelayMutation.isPending || isPending}
                            className="data-[state=checked]:bg-orange-500 data-[state=unchecked]:bg-zinc-700"
                          />
                        </div>
                      </TooltipTrigger>
                      {isPending && (
                        <TooltipContent>
                          <p className="text-sm font-medium">
                            {relay.pending_message || "Relay is reconciling state"}
                          </p>
                          <p className="text-xs text-zinc-400 mt-1">
                            Manual control is disabled during this period.
                          </p>
                        </TooltipContent>
                      )}
                    </Tooltip>
                  </TooltipProvider>
                </div>
                    </div>
            </CardHeader>
            <CardContent className="space-y-4 relative z-10">
              {/* Rules Section */}
                    <div>
                <div className="flex items-center justify-between mb-3">
                  <Label className="text-sm font-semibold text-zinc-200">Rules</Label>
                  <Button
                    size="sm"
                    className="bg-purple-500/10 hover:bg-purple-500/20 border border-purple-500/20 text-purple-400"
                    onClick={() => handleAddRule(relay.id)}
                  >
                    <Plus className="h-4 w-4 mr-1.5" />
                    Add Rule
                  </Button>
                </div>

                {isLoadingRules ? (
                  <div className="text-sm text-zinc-400 py-4">Loading rules...</div>
                ) : relayRules.length === 0 ? (
                  <div className="rounded-lg border-2 border-dashed border-zinc-700/30 p-6 text-center">
                    <p className="text-sm text-zinc-500">No rules configured</p>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {relayRules.map((rule) => (
                      <div
                        key={rule.id}
                        className="rounded-lg bg-zinc-800/30 border border-zinc-700/30 p-4 backdrop-blur-sm relative"
                      >
                        <div className="flex items-start justify-between">
                          <div className="flex-1">
                            <div className="flex items-center gap-2 mb-2">
                              <span className="text-sm font-semibold text-zinc-200">{rule.name}</span>
                              {rule.is_enabled ? (
                                <span className="text-xs px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                                  Active
                                </span>
                              ) : (
                                <span className="text-xs px-2 py-0.5 rounded bg-zinc-500/10 text-zinc-400 border border-zinc-500/20">
                                  Disabled
                                </span>
                              )}
                              <span className="text-xs text-zinc-500">Priority: {rule.priority}</span>
                            </div>
                            <p className="text-xs text-zinc-400 mb-2">{formatRuleDescription(rule)}</p>
                            <div className="flex items-center gap-3 text-xs text-zinc-500">
                              <span>Cooldown: {rule.cooldown_seconds}s</span>
                              {rule.last_triggered_at && (
                                <span className="flex items-center gap-1">
                                  <Clock className="h-3 w-3" />
                                  {formatTimeAgo(rule.last_triggered_at)}
                                </span>
                              )}
                            </div>
                          </div>
                          <div className="flex items-center gap-2">
                            <Switch
                              checked={rule.is_enabled}
                              onCheckedChange={(checked) =>
                                toggleRuleMutation.mutate({ ruleId: rule.id, isEnabled: checked })
                              }
                              disabled={toggleRuleMutation.isPending}
                              className="data-[state=checked]:bg-emerald-500"
                            />
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-8 w-8 p-0 text-zinc-400 hover:text-amber-400"
                              onClick={() => {
                                toggleRuleMutation.mutate({ ruleId: rule.id, isEnabled: !rule.is_enabled });
                              }}
                              disabled={toggleRuleMutation.isPending}
                              title={rule.is_enabled ? "Pause rule" : "Resume rule"}
                            >
                              {rule.is_enabled ? (
                                <Pause className="h-4 w-4" />
                              ) : (
                                <Play className="h-4 w-4" />
                              )}
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-8 w-8 p-0 text-zinc-400 hover:text-blue-400"
                              onClick={() => handleEditRule(rule)}
                              title="Edit rule"
                            >
                              <Edit2 className="h-4 w-4" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-8 w-8 p-0 text-zinc-400 hover:text-red-400"
                              onClick={() => {
                                if (confirm(`Delete rule "${rule.name}"?`)) {
                                  deleteRuleMutation.mutate(rule.id);
                                }
                              }}
                              disabled={deleteRuleMutation.isPending}
                              title="Delete rule"
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          </div>
                        </div>
                        {/* Rule runtime status (bottom-right) */}
                        {rule.runtime_status?.message && (
                          <div className="absolute bottom-2 right-2 text-xs">
                            <span className={
                              rule.runtime_status.reason_code === "sensor_stale" || rule.runtime_status.reason_code === "error" || rule.runtime_status.reason_code === "parse_error"
                                ? "text-amber-400"
                                : rule.runtime_status.reason_code === "sensor_warming_up" || rule.runtime_status.reason_code === "cooldown"
                                ? "text-zinc-400"
                                : rule.runtime_status.reason_code === "ok" && rule.runtime_status.matched
                                ? "text-emerald-400"
                                : "text-zinc-500"
                            }>
                              {rule.runtime_status.message}
                            </span>
                          </div>
                        )}
                    </div>
                    ))}
                  </div>
                )}
                </div>
              </CardContent>
            </Card>
          );
        })}

      {/* Rule Dialog */}
      <RuleDialog
        isOpen={isRuleDialogOpen}
        onClose={() => {
          setIsRuleDialogOpen(false);
          setEditingRule(null);
          setSelectedRelayId(null);
        }}
        rule={editingRule}
        relayId={selectedRelayId || editingRule?.relay_id || ""}
      />
    </div>
  );
}

function RuleDialog({
  isOpen,
  onClose,
  rule,
  relayId,
}: {
  isOpen: boolean;
  onClose: () => void;
  rule: Rule | null;
  relayId: string;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(rule?.name || "");
  const [sensor, setSensor] = useState(rule?.condition?.sensor || "kombi");
  const [operator, setOperator] = useState<"below" | "above">(
    (rule?.condition?.operator as "below" | "above") || "below"
  );
  const [value, setValue] = useState(rule?.condition?.value?.toString() || "5");
  const [action, setAction] = useState<"turn_on" | "turn_off">(rule?.action || "turn_on");
  const [priority, setPriority] = useState(rule?.priority?.toString() || "100");
  const [cooldown, setCooldown] = useState(rule?.cooldown_seconds?.toString() || "60");
  const [isEnabled, setIsEnabled] = useState(rule?.is_enabled ?? true);

  // Update form fields when rule prop changes (for editing)
  useEffect(() => {
    if (rule) {
      setName(rule.name || "");
      setSensor(rule.condition?.sensor || "kombi");
      setOperator((rule.condition?.operator as "below" | "above") || "below");
      setValue(rule.condition?.value?.toString() || "5");
      setAction(rule.action || "turn_on");
      setPriority(rule.priority?.toString() || "100");
      setCooldown(rule.cooldown_seconds?.toString() || "60");
      setIsEnabled(rule.is_enabled ?? true);
    } else {
      // Reset to defaults when creating a new rule
      setName("");
      setSensor("kombi");
      setOperator("below");
      setValue("5");
      setAction("turn_on");
      setPriority("100");
      setCooldown("60");
      setIsEnabled(true);
    }
  }, [rule, isOpen]); // Also depend on isOpen to reset when dialog closes

  const createRuleMutation = useMutation({
    mutationFn: async () => {
      const r = await apiFetch(`/api/relays/${relayId}/rules`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          condition: {
            type: "temperature",
            sensor,
            operator,
            value: parseFloat(value),
          },
          action,
          priority: parseInt(priority),
          cooldown_seconds: parseInt(cooldown),
          is_enabled: isEnabled,
        }),
        cache: "no-store",
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ error: "unknown" }));
        throw new Error(err.message || `Failed to create rule: ${r.status}`);
      }
      return await r.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["relay-rules"] });
      toast.success("Rule created");
      onClose();
    },
    onError: (error) => {
      toast.error("Failed to create rule", {
        description: error instanceof Error ? error.message : "Unknown error",
      });
    },
  });

  const updateRuleMutation = useMutation({
    mutationFn: async () => {
      if (!rule) return;
      const r = await apiFetch(`/api/rules/${rule.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          condition: {
            type: "temperature",
            sensor,
            operator,
            value: parseFloat(value),
          },
          action,
          priority: parseInt(priority),
          cooldown_seconds: parseInt(cooldown),
          is_enabled: isEnabled,
        }),
        cache: "no-store",
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ error: "unknown" }));
        throw new Error(err.message || `Failed to update rule: ${r.status}`);
      }
      return await r.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["relay-rules"] });
      toast.success("Rule updated");
      onClose();
    },
    onError: (error) => {
      toast.error("Failed to update rule", {
        description: error instanceof Error ? error.message : "Unknown error",
      });
    },
  });

  const handleSubmit = () => {
    if (!name.trim()) {
      toast.error("Rule name is required");
      return;
    }
    const val = parseFloat(value);
    if (isNaN(val) || val < -30 || val > 60) {
      toast.error("Temperature value must be between -30 and 60");
      return;
    }
    const cd = parseInt(cooldown);
    if (isNaN(cd) || cd < 5) {
      toast.error("Cooldown must be at least 5 seconds");
      return;
    }

    if (rule) {
      updateRuleMutation.mutate();
    } else {
      createRuleMutation.mutate();
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>{rule ? "Edit Rule" : "Create Rule"}</DialogTitle>
          <DialogDescription>Configure an automation rule for temperature-based relay control</DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label>Rule Name</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g., Low Temperature Alert" />
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-2">
              <Label>Sensor</Label>
              <Select value={sensor} onValueChange={setSensor}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="kombi">Kombi</SelectItem>
                  <SelectItem value="garaza">Garaža</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Operator</Label>
              <Select value={operator} onValueChange={(v) => setOperator(v as "below" | "above")}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="below">Below</SelectItem>
                  <SelectItem value="above">Above</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Temperature (°C)</Label>
              <Input
                type="number"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                min="-30"
                max="60"
                step="0.1"
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label>Action</Label>
            <Select value={action} onValueChange={(v) => setAction(v as "turn_on" | "turn_off")}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="turn_on">Turn Heater ON</SelectItem>
                <SelectItem value="turn_off">Turn Heater OFF</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Priority (lower = higher priority)</Label>
              <Input
                type="number"
                value={priority}
                onChange={(e) => setPriority(e.target.value)}
                min="1"
                max="1000"
              />
      </div>

            <div className="space-y-2">
              <Label>Cooldown (seconds)</Label>
              <Input type="number" value={cooldown} onChange={(e) => setCooldown(e.target.value)} min="5" />
            </div>
          </div>

          <div className="flex items-center space-x-2">
            <Switch checked={isEnabled} onCheckedChange={setIsEnabled} id="rule-enabled" />
            <Label htmlFor="rule-enabled">Enabled</Label>
          </div>
    </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={createRuleMutation.isPending || updateRuleMutation.isPending}
          >
            {rule ? "Update" : "Create"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default RelaysDashboard;
