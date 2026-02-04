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
  mode: "auto" | "on" | "off";
  desired_state?: "on" | "off" | null;
  manual_until: number | null;
  updated_at: number | null;
  is_enabled: boolean;
  min_on_seconds?: number;
  min_off_seconds?: number;
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
  condition: Record<string, any>;
  action: Record<string, any> | string;
  cooldown_seconds: number;
  last_triggered_at: number | null;
  created_at: number;
  updated_at: number;
  // Runtime status (from backend)
  runtime_status?: {
    can_evaluate?: boolean;
    matched?: boolean;
    condition_matched?: boolean;
    can_trigger?: boolean;
    is_winner?: boolean;
    reason_code?: "ok" | "sensor_warming_up" | "sensor_stale" | "cooldown" | "disabled" | "parse_error" | "error" | "sensor_no_temp" | "sensor_no_humidity";
    message?: string;
    sensor_name?: string | null;
    snapshot_temp?: number | null;
    snapshot_humidity?: number | null;
    threshold?: number | null;
    operator?: string | null;
    min?: number | null;
    max?: number | null;
    min_inclusive?: boolean | null;
    max_inclusive?: boolean | null;
    age_seconds?: number | null;
    sample_count?: number;
    cooldown_remaining?: number | null;
    snapshot_values?: Record<string, number | null>;
  };
};

function RelaysDashboard() {
  const queryClient = useQueryClient();
  const [editingRule, setEditingRule] = useState<Rule | null>(null);
  const [isRuleDialogOpen, setIsRuleDialogOpen] = useState(false);
  const [selectedRelayId, setSelectedRelayId] = useState<string | null>(null);
  const [editingRelayId, setEditingRelayId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

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

  const setModeMutation = useMutation({
    mutationFn: async ({ relayId, mode }: { relayId: string; mode: "off" | "on" | "auto" }) => {
      const r = await apiFetch(`/api/relays/${relayId}/mode`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode }),
        cache: "no-store",
      });
      const result = await r.json();
      if (!result.ok) {
        throw new Error(result.message || "Failed to set relay mode");
      }
      await queryClient.invalidateQueries({ queryKey: ["relays"] });
      return result;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["relays"] });
    },
    onError: (error) => {
      toast.error("Failed to update relay mode", {
        description: error instanceof Error ? error.message : "Unknown error",
      });
      queryClient.invalidateQueries({ queryKey: ["relays"] });
    },
  });

  const renameRelayMutation = useMutation({
    mutationFn: async ({ relayId, name }: { relayId: string; name: string }) => {
      const r = await apiFetch(`/api/relays/${relayId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
        cache: "no-store",
      });
      const result = await r.json();
      if (!result.ok) {
        throw new Error(result.message || "Failed to rename relay");
      }
      await queryClient.invalidateQueries({ queryKey: ["relays"] });
      return result;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["relays"] });
      toast.success("Relay renamed");
      setEditingRelayId(null);
    },
    onError: (error) => {
      toast.error("Failed to rename relay", {
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

  const formatCondition = (cond: Record<string, any>): string => {
    if (!cond) return "always";
    if (cond.op === "and" || cond.op === "or") {
      const joiner = cond.op.toUpperCase();
      const parts = (cond.conditions || []).map((c: any) => formatCondition(c));
      return parts.length ? `(${parts.join(` ${joiner} `)})` : "always";
    }
    if (cond.op === "not") {
      return `NOT (${formatCondition(cond.condition)})`;
    }
    if (cond.type === "temperature") {
      const sensor = cond.sensor || "sensor";
      const cmp = cond.cmp || cond.operator || "?";
      return `${sensor} ${cmp} ${cond.value}°C`;
    }
    if (cond.type === "temperature_between") {
      const sensor = cond.sensor || "sensor";
      const minSym = cond.min_inclusive === false ? ">" : "≥";
      const maxSym = cond.max_inclusive === true ? "≤" : "<";
      return `${sensor} ${minSym} ${cond.min}°C AND ${sensor} ${maxSym} ${cond.max}°C`;
    }
    if (cond.type === "humidity") {
      const sensor = cond.sensor || "sensor";
      const cmp = cond.cmp || cond.operator || "?";
      return `${sensor} ${cmp} ${cond.value}%`;
    }
    if (cond.type === "humidity_between") {
      const sensor = cond.sensor || "sensor";
      const minSym = cond.min_inclusive === false ? ">" : "≥";
      const maxSym = cond.max_inclusive === true ? "≤" : "<";
      return `${sensor} ${minSym} ${cond.min}% AND ${sensor} ${maxSym} ${cond.max}%`;
    }
    if (cond.type === "always") {
      return "always";
    }
    return "condition";
  };

  const formatAction = (action: Record<string, any> | string): string => {
    if (!action) return "set";
    if (typeof action === "string") {
      return action === "turn_on" ? "Set ON" : action === "turn_off" ? "Set OFF" : action;
    }
    if (action.type === "set_state") {
      return `Set ${action.state?.toUpperCase()}`;
    }
    if (action.type === "temperature_band") {
      const sensor = action.sensor || "sensor";
      const minSym = action.min_inclusive === false ? ">" : "≥";
      const maxSym = action.max_inclusive === true ? "≤" : "<";
      return `${sensor} ${minSym} ${action.min}°C AND ${sensor} ${maxSym} ${action.max}°C → ${action.on_state?.toUpperCase() || "ON"}`;
    }
    return "action";
  };

  const formatRuleDescription = (rule: Rule) => {
    const cond = rule.condition || {};
    return `${formatCondition(cond)} → ${formatAction(rule.action)}`;
  };

  const formatTimeAgo = (timestamp: number | null) => {
    if (!timestamp) return "Never";
    const seconds = Math.floor(Date.now() / 1000) - timestamp;
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
  };

  const handleRelayMode = (relay: Relay, mode: "off" | "on" | "auto") => {
    // Guard: prevent undefined relay_id calls
    if (!relay?.id || relay.id === "undefined" || relay.id === "null") {
      toast.error("Relay ID missing", {
        description: "Relay data not loaded yet. Please wait and try again.",
      });
      return;
    }
    setModeMutation.mutate({ relayId: relay.id, mode });
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
            <div className="p-2 rounded-lg bg-primary/20 border border-glass">
              <ToggleLeft className="h-6 w-6 text-primary icon-glow" />
            </div>
            Relay Control
          </h1>
          <p className="text-sm text-muted-foreground mt-2">Manage connected devices and automation rules</p>
        </div>
        {relaysError ? (
          <Card className="glass-card">
            <CardContent className="py-12 text-center">
              <p className="text-destructive font-medium mb-2">Error loading relays</p>
              <p className="text-sm text-muted-foreground mb-4">
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
          <Card className="glass-card">
            <CardContent className="py-12 text-center">
              <p className="text-muted-foreground">No relays found</p>
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
          <div className="p-2 rounded-lg bg-primary/20 border border-glass">
            <ToggleLeft className="h-6 w-6 text-primary icon-glow" />
          </div>
          Relay Control
        </h1>
        <p className="text-sm text-muted-foreground mt-2">Manage connected devices and automation rules</p>
      </div>

      {/* Relays */}
        {relays.map((relay) => {
        const isOn = relay.state === "on";
        const isAuto = relay.mode === "auto";
        const relayRules = rules.filter((r) => r.relay_id === relay.id);
        
        // Use pending state from API response (backend calculates cooldown/reconciling/startup)
        // Only used to disable toggle/mode switch, NOT for display (cooldown/warming shown per-rule)
        const isPending = relay.pending === true;

          return (
          <Card
            key={relay.id}
            className="glass-card group relative overflow-hidden transition-all duration-300 hover:shadow-glow"
          >
            <div className="absolute inset-0 bg-gradient-to-br from-primary/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
            <CardHeader className="pb-4 relative z-10">
                {/* Header row: Relay name (left) + Status badge (right) */}
                <div className="flex items-center justify-between mb-3">
                  <CardTitle className="text-lg font-semibold text-foreground flex items-center gap-2">
                    <Power className="h-5 w-5 text-primary" />
                    {editingRelayId === relay.id ? (
                      <div className="flex items-center gap-2">
                        <Input
                          value={renameValue}
                          onChange={(e) => setRenameValue(e.target.value)}
                          className="h-8"
                        />
                        <Button
                          size="sm"
                          onClick={() => renameRelayMutation.mutate({ relayId: relay.id, name: renameValue.trim() })}
                          disabled={renameRelayMutation.isPending || !renameValue.trim()}
                        >
                          Save
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setEditingRelayId(null)}
                        >
                          Cancel
                        </Button>
                      </div>
                    ) : (
                      <>
                        {relay.name.charAt(0).toUpperCase() + relay.name.slice(1)}
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={() => {
                            setEditingRelayId(relay.id);
                            setRenameValue(relay.name);
                          }}
                        >
                          <Edit2 className="h-4 w-4" />
                        </Button>
                      </>
                    )}
                  </CardTitle>
                  {/* Status badge (top-right) - simplified, no cooldown/warming (shown per-rule) */}
                  <div className="flex items-center gap-2 text-xs max-w-[60%] text-right flex-shrink-0">
                    {isPending && relay.pending_reason === "reconciling" ? (
                      <div className="flex items-center gap-1.5">
                        <div className="h-3 w-3 border-2 border-muted border-t-transparent rounded-full animate-spin flex-shrink-0" />
                        <span className="text-muted-foreground">Reconciling...</span>
                      </div>
                    ) : (
                      <span className="text-muted-foreground">
                        {isAuto ? (
                          <>AUTO: monitoring {relayRules.length > 0 ? `${relayRules.length} rule${relayRules.length !== 1 ? "s" : ""}` : "no rules"}</>
                        ) : (
                          <>MANUAL: {relay.mode.toUpperCase()}</>
                        )}
                      </span>
                    )}
                  </div>
                </div>
                {/* Controls row: Mode badge + State + Toggle */}
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                    <span
                      className={`text-xs px-2 py-0.5 rounded border ${
                        isAuto
                          ? "bg-primary/20 text-primary border-primary/30"
                          : "bg-secondary/40 text-foreground/80 border-glass"
                      }`}
                    >
                      {relay.mode.toUpperCase()}
                    </span>
                    <span className={`text-xs ${isOn ? "text-success" : "text-muted-foreground"}`}>
                      {isOn ? "ON" : "OFF"}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      size="sm"
                      variant={relay.mode === "off" ? "default" : "outline"}
                      onClick={() => !isPending && handleRelayMode(relay, "off")}
                      disabled={setModeMutation.isPending || isPending}
                    >
                      OFF
                    </Button>
                    <Button
                      size="sm"
                      variant={relay.mode === "auto" ? "default" : "outline"}
                      onClick={() => !isPending && handleRelayMode(relay, "auto")}
                      disabled={setModeMutation.isPending || isPending}
                    >
                      AUTO
                    </Button>
                    <Button
                      size="sm"
                      variant={relay.mode === "on" ? "default" : "outline"}
                      onClick={() => !isPending && handleRelayMode(relay, "on")}
                      disabled={setModeMutation.isPending || isPending}
                    >
                      ON
                    </Button>
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <div className="flex items-center gap-2">
                            {isPending && (
                              <div className="h-3 w-3 border-2 border-muted border-t-transparent rounded-full animate-spin opacity-50" />
                            )}
                          </div>
                        </TooltipTrigger>
                        {isPending && (
                          <TooltipContent>
                            <p className="text-sm font-medium">
                              {relay.pending_message || "Relay is reconciling state"}
                            </p>
                            <p className="text-xs text-muted-foreground mt-1">
                              Controls are disabled during this period.
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
                  <Label className="text-sm font-semibold text-foreground">Rules</Label>
                  <Button
                    size="sm"
                    className="bg-primary/20 hover:bg-primary/30 border border-glass text-primary"
                    onClick={() => handleAddRule(relay.id)}
                  >
                    <Plus className="h-4 w-4 mr-1.5" />
                    Add Rule
                  </Button>
                </div>

                {isLoadingRules ? (
                  <div className="text-sm text-muted-foreground py-4">Loading rules...</div>
                ) : relayRules.length === 0 ? (
                  <div className="rounded-lg border-2 border-dashed border-glass p-6 text-center">
                    <p className="text-sm text-muted-foreground">No rules configured</p>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {relayRules.map((rule) => (
                      <div
                        key={rule.id}
                        className="rounded-lg bg-secondary/40 border border-glass p-4 backdrop-blur-sm relative"
                      >
                        <div className="flex items-start justify-between">
                          <div className="flex-1">
                            <div className="flex items-center gap-2 mb-2">
                              <span className="text-sm font-semibold text-foreground">{rule.name}</span>
                              {rule.is_enabled ? (
                                <span className="text-xs px-2 py-0.5 rounded bg-success/15 text-success border border-success/20">
                                  Active
                                </span>
                              ) : (
                                <span className="text-xs px-2 py-0.5 rounded bg-secondary/40 text-muted-foreground border border-glass">
                                  Disabled
                                </span>
                              )}
                              {rule.runtime_status?.is_winner && (
                                <span className="text-xs px-2 py-0.5 rounded bg-primary/20 text-primary border border-primary/30">
                                  Winner
                                </span>
                              )}
                              <span className="text-xs text-muted-foreground">Priority: {rule.priority}</span>
                            </div>
                            <p className="text-xs text-muted-foreground mb-2">{formatRuleDescription(rule)}</p>
                            <div className="flex items-center gap-3 text-xs text-muted-foreground">
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
                              className="data-[state=checked]:bg-success"
                            />
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-8 w-8 p-0 text-muted-foreground hover:text-warning"
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
                              className="h-8 w-8 p-0 text-muted-foreground hover:text-primary"
                              onClick={() => handleEditRule(rule)}
                              title="Edit rule"
                            >
                              <Edit2 className="h-4 w-4" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-8 w-8 p-0 text-muted-foreground hover:text-destructive"
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
                                ? "text-warning"
                                : rule.runtime_status.reason_code === "sensor_warming_up" || rule.runtime_status.reason_code === "cooldown"
                                ? "text-muted-foreground"
                                : rule.runtime_status.reason_code === "ok" && rule.runtime_status.matched
                                ? "text-success"
                                : "text-muted-foreground"
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
    ((rule?.condition?.cmp === ">" || rule?.condition?.operator === "above") ? "above" : "below")
  );
  const [value, setValue] = useState(rule?.condition?.value?.toString() || "5");
  const [actionState, setActionState] = useState<"on" | "off">(
    typeof rule?.action === "object" && rule?.action?.type === "set_state"
      ? (rule.action.state as "on" | "off")
      : "on"
  );
  const [ruleType, setRuleType] = useState<"temp_threshold" | "temp_range" | "humidity_threshold" | "humidity_range">(
    typeof rule?.condition === "object" && rule?.condition?.type === "humidity_between"
      ? "humidity_range"
      : typeof rule?.condition === "object" && rule?.condition?.type === "humidity"
      ? "humidity_threshold"
      : typeof rule?.condition === "object" && rule?.condition?.type === "temperature_between"
      ? "temp_range"
      : "temp_threshold"
  );
  const [minValue, setMinValue] = useState(
    typeof rule?.condition === "object" && (rule?.condition?.type === "temperature_between" || rule?.condition?.type === "humidity_between")
      ? rule.condition.min?.toString() || "5"
      : "5"
  );
  const [maxValue, setMaxValue] = useState(
    typeof rule?.condition === "object" && (rule?.condition?.type === "temperature_between" || rule?.condition?.type === "humidity_between")
      ? rule.condition.max?.toString() || "20"
      : "20"
  );
  const [minInclusive, setMinInclusive] = useState(
    typeof rule?.condition === "object" && (rule?.condition?.type === "temperature_between" || rule?.condition?.type === "humidity_between")
      ? rule.condition.min_inclusive !== false
      : true
  );
  const [maxInclusive, setMaxInclusive] = useState(
    typeof rule?.condition === "object" && (rule?.condition?.type === "temperature_between" || rule?.condition?.type === "humidity_between")
      ? rule.condition.max_inclusive === true
      : false
  );
  const [priority, setPriority] = useState(rule?.priority?.toString() || "100");
  const [cooldown, setCooldown] = useState(rule?.cooldown_seconds?.toString() || "60");
  const [isEnabled, setIsEnabled] = useState(rule?.is_enabled ?? true);

  // Update form fields when rule prop changes (for editing)
  useEffect(() => {
    if (rule) {
      setName(rule.name || "");
      setSensor(rule.condition?.sensor || "kombi");
      setOperator((rule.condition?.cmp === ">" || rule.condition?.operator === "above") ? "above" : "below");
      setValue(rule.condition?.value?.toString() || "5");
      if (rule.condition?.type === "humidity_between") {
        setRuleType("humidity_range");
      } else if (rule.condition?.type === "humidity") {
        setRuleType("humidity_threshold");
      } else if (rule.condition?.type === "temperature_between") {
        setRuleType("temp_range");
      } else {
        setRuleType("temp_threshold");
      }
      if (rule.condition?.type === "temperature_between" || rule.condition?.type === "humidity_between") {
        setMinValue(rule.condition.min?.toString() || "5");
        setMaxValue(rule.condition.max?.toString() || "20");
        setMinInclusive(rule.condition.min_inclusive !== false);
        setMaxInclusive(rule.condition.max_inclusive === true);
      }
      if (typeof rule.action === "object" && rule.action?.type === "set_state") {
        setActionState(rule.action.state === "off" ? "off" : "on");
      } else if (rule.action === "turn_off") {
        setActionState("off");
      } else {
        setActionState("on");
      }
      setPriority(rule.priority?.toString() || "100");
      setCooldown(rule.cooldown_seconds?.toString() || "60");
      setIsEnabled(rule.is_enabled ?? true);
    } else {
      // Reset to defaults when creating a new rule
      setName("");
      setSensor("kombi");
      setOperator("below");
      setValue("5");
      setActionState("on");
      setRuleType("temp_threshold");
      setMinValue("5");
      setMaxValue("20");
      setMinInclusive(true);
      setMaxInclusive(false);
      setPriority("100");
      setCooldown("60");
      setIsEnabled(true);
    }
  }, [rule, isOpen]); // Also depend on isOpen to reset when dialog closes

  const createRuleMutation = useMutation({
    mutationFn: async () => {
      const isRange = ruleType === "temp_range" || ruleType === "humidity_range";
      const isHumidity = ruleType === "humidity_range" || ruleType === "humidity_threshold";
      const endpoint = isRange
        ? `/api/relays/${relayId}/rules/${isHumidity ? "humidity-band" : "temperature-band"}`
        : `/api/relays/${relayId}/rules`;
      const payload = isRange
        ? {
            name,
            sensor,
            min: parseFloat(minValue),
            max: parseFloat(maxValue),
            min_inclusive: minInclusive,
            max_inclusive: maxInclusive,
            on_state: actionState,
            priority: parseInt(priority),
            cooldown_seconds: parseInt(cooldown),
            is_enabled: isEnabled,
          }
        : {
            name,
            condition: {
              type: isHumidity ? "humidity" : "temperature",
              sensor,
              cmp: operator === "below" ? "<" : ">",
              value: parseFloat(value),
            },
            action: {
              type: "set_state",
              state: actionState,
            },
            priority: parseInt(priority),
            cooldown_seconds: parseInt(cooldown),
            is_enabled: isEnabled,
          };
      const r = await apiFetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
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
          condition:
            ruleType === "temp_range"
              ? {
                  type: "temperature_between",
                  sensor,
                  min: parseFloat(minValue),
                  max: parseFloat(maxValue),
                  min_inclusive: minInclusive,
                  max_inclusive: maxInclusive,
                }
              : ruleType === "humidity_range"
              ? {
                  type: "humidity_between",
                  sensor,
                  min: parseFloat(minValue),
                  max: parseFloat(maxValue),
                  min_inclusive: minInclusive,
                  max_inclusive: maxInclusive,
                }
              : {
                  type: ruleType === "humidity_threshold" ? "humidity" : "temperature",
                  sensor,
                  cmp: operator === "below" ? "<" : ">",
                  value: parseFloat(value),
                },
          action: {
            type: "set_state",
            state: actionState,
          },
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
    if (ruleType === "temp_threshold" || ruleType === "humidity_threshold") {
      const val = parseFloat(value);
      if (isNaN(val)) {
        toast.error("Value must be a number");
        return;
      }
      if (ruleType === "temp_threshold" && (val < -30 || val > 60)) {
        toast.error("Temperature value must be between -30 and 60");
        return;
      }
      if (ruleType === "humidity_threshold" && (val < 0 || val > 100)) {
        toast.error("Humidity value must be between 0 and 100");
        return;
      }
    } else {
      const minVal = parseFloat(minValue);
      const maxVal = parseFloat(maxValue);
      if (isNaN(minVal) || isNaN(maxVal) || minVal >= maxVal) {
        toast.error("Range must have min < max");
        return;
      }
      if (ruleType === "temp_range" && (minVal < -30 || maxVal > 60)) {
        toast.error("Temperature range must be between -30 and 60");
        return;
      }
      if (ruleType === "humidity_range" && (minVal < 0 || maxVal > 100)) {
        toast.error("Humidity range must be between 0 and 100");
        return;
      }
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
        <DialogDescription>Configure an automation rule for sensor-based relay control</DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label>Rule Name</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g., Low Temperature Alert" />
          </div>

          <div className="space-y-2">
            <Label>Rule Type</Label>
            <Select
              value={ruleType}
              onValueChange={(v) =>
                setRuleType(v as "temp_threshold" | "temp_range" | "humidity_threshold" | "humidity_range")
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="temp_threshold">Temperature compare</SelectItem>
                <SelectItem value="temp_range">Temperature range</SelectItem>
                <SelectItem value="humidity_threshold">Humidity compare</SelectItem>
                <SelectItem value="humidity_range">Humidity range</SelectItem>
              </SelectContent>
            </Select>
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

            {ruleType === "temp_threshold" || ruleType === "humidity_threshold" ? (
              <>
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
                  <Label>{ruleType === "humidity_threshold" ? "Humidity (%)" : "Temperature (°C)"}</Label>
                  <Input
                    type="number"
                    value={value}
                    onChange={(e) => setValue(e.target.value)}
                    min={ruleType === "humidity_threshold" ? "0" : "-30"}
                    max={ruleType === "humidity_threshold" ? "100" : "60"}
                    step="0.1"
                  />
                </div>
              </>
            ) : (
              <>
                <div className="space-y-2">
                  <Label>{ruleType === "humidity_range" ? "Min Humidity (%)" : "Min Temp (°C)"}</Label>
                  <Input
                    type="number"
                    value={minValue}
                    onChange={(e) => setMinValue(e.target.value)}
                    min={ruleType === "humidity_range" ? "0" : "-30"}
                    max={ruleType === "humidity_range" ? "100" : "60"}
                    step="0.1"
                  />
                </div>

                <div className="space-y-2">
                  <Label>{ruleType === "humidity_range" ? "Max Humidity (%)" : "Max Temp (°C)"}</Label>
                  <Input
                    type="number"
                    value={maxValue}
                    onChange={(e) => setMaxValue(e.target.value)}
                    min={ruleType === "humidity_range" ? "0" : "-30"}
                    max={ruleType === "humidity_range" ? "100" : "60"}
                    step="0.1"
                  />
                </div>
              </>
            )}
          </div>

          {(ruleType === "temp_range" || ruleType === "humidity_range") && (
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Min Inclusive</Label>
                <Select value={minInclusive ? "true" : "false"} onValueChange={(v) => setMinInclusive(v === "true")}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="true">Inclusive</SelectItem>
                    <SelectItem value="false">Exclusive</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Max Inclusive</Label>
                <Select value={maxInclusive ? "true" : "false"} onValueChange={(v) => setMaxInclusive(v === "true")}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="false">Exclusive</SelectItem>
                    <SelectItem value="true">Inclusive</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          )}

          {ruleType === "temp_threshold" || ruleType === "humidity_threshold" ? (
            <div className="space-y-2">
              <Label>Action</Label>
              <Select value={actionState} onValueChange={(v) => setActionState(v as "on" | "off")}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="on">Turn Relay ON</SelectItem>
                  <SelectItem value="off">Turn Relay OFF</SelectItem>
                </SelectContent>
              </Select>
            </div>
          ) : (
            <div className="space-y-2">
              <Label>Action</Label>
              <Select value={actionState} onValueChange={(v) => setActionState(v as "on" | "off")}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="on">Turn Relay ON</SelectItem>
                  <SelectItem value="off">Turn Relay OFF</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Priority (higher = stronger)</Label>
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
