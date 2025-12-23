import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Zap, Battery, Sun, PlugZap } from "lucide-react";

const EnergyDashboard = () => {
  return (
    <div className="space-y-6">
      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
        <Card className="card-hover">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <Battery className="w-4 h-4" />
              Battery
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">---%</p>
            <p className="text-xs text-muted-foreground mt-1">State of charge</p>
          </CardContent>
        </Card>

        <Card className="card-hover">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <Zap className="w-4 h-4" />
              Power
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">--- W</p>
            <p className="text-xs text-muted-foreground mt-1">Current draw</p>
          </CardContent>
        </Card>

        <Card className="card-hover">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <Sun className="w-4 h-4" />
              Solar
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">--- W</p>
            <p className="text-xs text-muted-foreground mt-1">Solar input</p>
          </CardContent>
        </Card>

        <Card className="card-hover">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <PlugZap className="w-4 h-4" />
              Shore Power
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">---</p>
            <p className="text-xs text-muted-foreground mt-1">Connection status</p>
          </CardContent>
        </Card>
      </div>

      <Card className="card-hover">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Zap className="w-5 h-5 text-primary" />
            Energy Dashboard
          </CardTitle>
        </CardHeader>
        <CardContent className="min-h-[300px] flex items-center justify-center">
          <div className="text-center">
            <div className="w-16 h-16 bg-secondary rounded-2xl flex items-center justify-center mx-auto mb-4">
              <Battery className="w-8 h-8 text-muted-foreground" />
            </div>
            <p className="text-lg font-medium">Coming Soon</p>
            <p className="text-sm text-muted-foreground mt-1">
              Victron battery data integration
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default EnergyDashboard;
