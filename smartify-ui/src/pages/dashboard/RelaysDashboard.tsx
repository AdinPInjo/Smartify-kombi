import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ToggleLeft, Lightbulb, Fan, Heater, Power } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";

const relays = [
  { id: 1, name: "Interior Lights", icon: Lightbulb, color: "yellow" },
  { id: 2, name: "Ventilation Fan", icon: Fan, color: "blue" },
  { id: 3, name: "Water Heater", icon: Heater, color: "orange" },
  { id: 4, name: "Aux Power", icon: Power, color: "emerald" },
];

const RelaysDashboard = () => {
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
        <p className="text-sm text-zinc-400 mt-2">Manage connected devices and systems</p>
      </div>

      {/* Relays Grid */}
      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
        {relays.map((relay) => {
          const Icon = relay.icon;
          const colorClasses = {
            yellow: "from-yellow-500/10 to-yellow-600/5 border-yellow-500/20 text-yellow-400",
            blue: "from-blue-500/10 to-blue-600/5 border-blue-500/20 text-blue-400",
            orange: "from-orange-500/10 to-orange-600/5 border-orange-500/20 text-orange-400",
            emerald: "from-emerald-500/10 to-emerald-600/5 border-emerald-500/20 text-emerald-400",
          };
          return (
            <Card key={relay.id} className="group relative overflow-hidden border-zinc-800/50 bg-gradient-to-br from-zinc-900/50 to-zinc-950/50 backdrop-blur-sm transition-all duration-300 hover:border-zinc-700/50 hover:shadow-xl hover:shadow-zinc-900/20">
              <div className={`absolute inset-0 bg-gradient-to-br ${colorClasses[relay.color as keyof typeof colorClasses].split(' ')[0]} to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300`} />
              <CardContent className="pt-6 relative z-10">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className={`w-12 h-12 bg-gradient-to-br ${colorClasses[relay.color as keyof typeof colorClasses]} rounded-lg flex items-center justify-center border`}>
                      <Icon className="w-6 h-6" />
                    </div>
                    <div>
                      <Label htmlFor={`relay-${relay.id}`} className="font-semibold text-zinc-200 cursor-pointer">
                        {relay.name}
                      </Label>
                      <p className="text-xs text-zinc-400">Relay {relay.id}</p>
                    </div>
                  </div>
                  <Switch id={`relay-${relay.id}`} disabled className="data-[state=checked]:bg-zinc-600" />
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Coming Soon Card */}
      <Card className="group relative overflow-hidden border-zinc-800/50 bg-gradient-to-br from-zinc-900/50 to-zinc-950/50 backdrop-blur-sm transition-all duration-300 hover:shadow-xl hover:shadow-zinc-900/20">
        <div className="absolute inset-0 bg-gradient-to-br from-blue-500/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
        <CardHeader className="relative z-10">
          <CardTitle className="flex items-center gap-2 text-zinc-200">
            <ToggleLeft className="w-5 h-5 text-blue-400" />
            Relay Control Interface
          </CardTitle>
        </CardHeader>
        <CardContent className="min-h-[300px] flex items-center justify-center relative z-10">
          <div className="text-center">
            <div className="w-20 h-20 bg-zinc-800/50 rounded-2xl flex items-center justify-center mx-auto mb-4 border border-zinc-700/50">
              <ToggleLeft className="w-10 h-10 text-zinc-500" />
            </div>
            <p className="text-lg font-semibold text-zinc-200">Coming Soon</p>
            <p className="text-sm text-zinc-400 mt-2">
              Hardware relay control interface
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default RelaysDashboard;
