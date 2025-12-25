import { useState } from "react";
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
      // Ensure we have a valid relays array
      if (!data || typeof data !== "object") {
        console.error("[RelaysDashboard] Invalid response format:", data);
        throw new Error("Invalid API response format");
      }
      const relays = Array.isArray(data.relays) ? data.relays : [];
      console.log("[RelaysDashboard] Parsed relays:", relays);
      return relays as Relay[];
    },
    retry: 1,
  });

  const relays = Array.isArray(relaysResponse) ? relaysResponse : [];
  const heaterRelay = relays.find((r) => r.name === "heater");

  // Fetch rules for heater relay
  const { data: rulesResponse, isLoading: isLoadingRules } = useQuery({
    queryKey: ["relay-rules", heaterRelay?.id],
    queryFn: async () => {
      if (!heaterRelay) return { rules: [] };
      const r = await apiFetch(`/api/relays/${heaterRelay.id}/rules`, { cache: "no-store" });
      if (!r.ok) throw new Error(`Rules API returned ${r.status}`);
      return await r.json();
    },
    enabled: !!heaterRelay,
    retry: 1,
  });

  const rules = rulesResponse?.rules || [];

  // Mutation to toggle relay state
  const toggleRelayMutation = useMutation({
    mutationFn: async ({ relayId, state }: { relayId: string; state: "on" | "off" }) => {
      // Invert for hardware
      const hardwareState = state === "on" ? "off" : "on";
      const r = await apiFetch(`/api/relays/${relayId}/state`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ state: hardwareState, mode: "manual" }),
        cache: "no-store",
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ error: "unknown" }));
        throw new Error(err.message || `Failed to set relay: ${r.status}`);
      }
      return await r.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["relays"] });
      toast.success("Relay state updated");
    },
    onError: (error) => {
      toast.error("Failed to update relay", {
        description: error instanceof Error ? error.message : "Unknown error",
      });
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
    const newState: "on" | "off" = checked ? "on" : "off";
    toggleRelayMutation.mutate({ relayId: relay.id, state: newState });
  };

  const handleAddRule = (relayId: string) => {
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
        const isOn = relay.state === "off"; // Inverted display
        const isManual = relay.mode === "manual";
        const relayRules = rules.filter((r) => r.relay_id === relay.id);

          return (
          <Card
            key={relay.id}
            className="group relative overflow-hidden border-zinc-800/50 bg-gradient-to-br from-zinc-900/50 to-zinc-950/50 backdrop-blur-sm transition-all duration-300 hover:shadow-xl hover:shadow-zinc-900/20"
          >
            <div className="absolute inset-0 bg-gradient-to-br from-orange-500/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
            <CardHeader className="pb-4 relative z-10">
                <div className="flex items-center justify-between">
                    <div>
                  <CardTitle className="text-lg font-semibold text-zinc-200 flex items-center gap-2">
                    <Power className="h-5 w-5 text-orange-400" />
                    {relay.name.charAt(0).toUpperCase() + relay.name.slice(1)}
                  </CardTitle>
                  <div className="flex items-center gap-2 mt-1">
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
                </div>
                <div className="flex items-center gap-3">
                  {isManual && (
                    <Button
                      size="sm"
                      variant="outline"
                      className="bg-zinc-800/50 border-zinc-700/50 text-zinc-300 hover:bg-zinc-700/50"
                      onClick={() => setAutoMutation.mutate(relay.id)}
                      disabled={setAutoMutation.isPending}
                    >
                      Return to Auto
                    </Button>
                  )}
                  <Switch
                    checked={isOn}
                    onCheckedChange={(checked) => handleRelayToggle(relay, checked)}
                    disabled={toggleRelayMutation.isPending}
                    className="data-[state=checked]:bg-orange-500 data-[state=unchecked]:bg-zinc-700"
                  />
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
                        className="rounded-lg bg-zinc-800/30 border border-zinc-700/30 p-4 backdrop-blur-sm"
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
