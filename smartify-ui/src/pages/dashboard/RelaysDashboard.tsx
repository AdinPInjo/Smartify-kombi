import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ToggleLeft, Lightbulb, Fan, Heater, Power } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";

const relays = [
  { id: 1, name: "Interior Lights", icon: Lightbulb },
  { id: 2, name: "Ventilation Fan", icon: Fan },
  { id: 3, name: "Water Heater", icon: Heater },
  { id: 4, name: "Aux Power", icon: Power },
];

const RelaysDashboard = () => {
  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {relays.map((relay) => {
          const Icon = relay.icon;
          return (
            <Card key={relay.id} className="card-hover">
              <CardContent className="pt-6">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 bg-secondary rounded-lg flex items-center justify-center">
                      <Icon className="w-5 h-5 text-muted-foreground" />
                    </div>
                    <div>
                      <Label htmlFor={`relay-${relay.id}`} className="font-medium">
                        {relay.name}
                      </Label>
                      <p className="text-xs text-muted-foreground">Relay {relay.id}</p>
                    </div>
                  </div>
                  <Switch id={`relay-${relay.id}`} disabled />
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <Card className="card-hover">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ToggleLeft className="w-5 h-5 text-primary" />
            Relay Control
          </CardTitle>
        </CardHeader>
        <CardContent className="min-h-[300px] flex items-center justify-center">
          <div className="text-center">
            <div className="w-16 h-16 bg-secondary rounded-2xl flex items-center justify-center mx-auto mb-4">
              <ToggleLeft className="w-8 h-8 text-muted-foreground" />
            </div>
            <p className="text-lg font-medium">Coming Soon</p>
            <p className="text-sm text-muted-foreground mt-1">
              Hardware relay control interface
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default RelaysDashboard;
