import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Zap, Battery, Sun, PlugZap, TrendingUp } from "lucide-react";

const EnergyDashboard = () => {
  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
          <div className="p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
            <Zap className="h-6 w-6 text-emerald-400" />
          </div>
          Energy Management
        </h1>
        <p className="text-sm text-zinc-400 mt-2">Monitor battery, solar, and power consumption</p>
      </div>

      {/* Stats Grid */}
      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
        <Card className="group relative overflow-hidden border-zinc-800/50 bg-gradient-to-br from-zinc-900/50 to-zinc-950/50 backdrop-blur-sm transition-all duration-300 hover:border-zinc-700/50 hover:shadow-xl hover:shadow-zinc-900/20">
          <div className="absolute inset-0 bg-gradient-to-br from-emerald-500/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
          <CardHeader className="pb-3 relative z-10">
            <CardTitle className="text-sm font-medium text-zinc-300 flex items-center gap-2">
              <div className="p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                <Battery className="w-4 h-4 text-emerald-400" />
              </div>
              Battery
            </CardTitle>
          </CardHeader>
          <CardContent className="relative z-10">
            <p className="text-3xl font-bold text-zinc-200">—%</p>
            <p className="text-xs text-zinc-400 mt-2">State of charge</p>
          </CardContent>
        </Card>

        <Card className="group relative overflow-hidden border-zinc-800/50 bg-gradient-to-br from-zinc-900/50 to-zinc-950/50 backdrop-blur-sm transition-all duration-300 hover:border-zinc-700/50 hover:shadow-xl hover:shadow-zinc-900/20">
          <div className="absolute inset-0 bg-gradient-to-br from-yellow-500/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
          <CardHeader className="pb-3 relative z-10">
            <CardTitle className="text-sm font-medium text-zinc-300 flex items-center gap-2">
              <div className="p-2 rounded-lg bg-yellow-500/10 border border-yellow-500/20">
                <Zap className="w-4 h-4 text-yellow-400" />
              </div>
              Power
            </CardTitle>
          </CardHeader>
          <CardContent className="relative z-10">
            <p className="text-3xl font-bold text-zinc-200">— W</p>
            <p className="text-xs text-zinc-400 mt-2">Current draw</p>
          </CardContent>
        </Card>

        <Card className="group relative overflow-hidden border-zinc-800/50 bg-gradient-to-br from-zinc-900/50 to-zinc-950/50 backdrop-blur-sm transition-all duration-300 hover:border-zinc-700/50 hover:shadow-xl hover:shadow-zinc-900/20">
          <div className="absolute inset-0 bg-gradient-to-br from-orange-500/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
          <CardHeader className="pb-3 relative z-10">
            <CardTitle className="text-sm font-medium text-zinc-300 flex items-center gap-2">
              <div className="p-2 rounded-lg bg-orange-500/10 border border-orange-500/20">
                <Sun className="w-4 h-4 text-orange-400" />
              </div>
              Solar
            </CardTitle>
          </CardHeader>
          <CardContent className="relative z-10">
            <p className="text-3xl font-bold text-zinc-200">— W</p>
            <p className="text-xs text-zinc-400 mt-2">Solar input</p>
          </CardContent>
        </Card>

        <Card className="group relative overflow-hidden border-zinc-800/50 bg-gradient-to-br from-zinc-900/50 to-zinc-950/50 backdrop-blur-sm transition-all duration-300 hover:border-zinc-700/50 hover:shadow-xl hover:shadow-zinc-900/20">
          <div className="absolute inset-0 bg-gradient-to-br from-blue-500/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
          <CardHeader className="pb-3 relative z-10">
            <CardTitle className="text-sm font-medium text-zinc-300 flex items-center gap-2">
              <div className="p-2 rounded-lg bg-blue-500/10 border border-blue-500/20">
                <PlugZap className="w-4 h-4 text-blue-400" />
              </div>
              Shore Power
            </CardTitle>
          </CardHeader>
          <CardContent className="relative z-10">
            <p className="text-3xl font-bold text-zinc-200">—</p>
            <p className="text-xs text-zinc-400 mt-2">Connection status</p>
          </CardContent>
        </Card>
      </div>

      {/* Coming Soon Card */}
      <Card className="group relative overflow-hidden border-zinc-800/50 bg-gradient-to-br from-zinc-900/50 to-zinc-950/50 backdrop-blur-sm transition-all duration-300 hover:shadow-xl hover:shadow-zinc-900/20">
        <div className="absolute inset-0 bg-gradient-to-br from-emerald-500/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
        <CardHeader className="relative z-10">
          <CardTitle className="flex items-center gap-2 text-zinc-200">
            <Zap className="w-5 h-5 text-emerald-400" />
            Energy Dashboard
          </CardTitle>
        </CardHeader>
        <CardContent className="min-h-[300px] flex items-center justify-center relative z-10">
          <div className="text-center">
            <div className="w-20 h-20 bg-zinc-800/50 rounded-2xl flex items-center justify-center mx-auto mb-4 border border-zinc-700/50">
              <Battery className="w-10 h-10 text-zinc-500" />
            </div>
            <p className="text-lg font-semibold text-zinc-200">Coming Soon</p>
            <p className="text-sm text-zinc-400 mt-2">
              Victron battery data integration
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default EnergyDashboard;
