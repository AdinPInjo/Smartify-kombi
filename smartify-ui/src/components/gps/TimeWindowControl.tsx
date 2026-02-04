import { Clock } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Slider } from "@/components/ui/slider";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface TimeWindowControlProps {
  minutes: number;
  onMinutesChange: (minutes: number) => void;
}

const presets = [
  { label: "15m", value: 15 },
  { label: "1h", value: 60 },
  { label: "6h", value: 360 },
  { label: "Today", value: 1440 },
];

const TimeWindowControl = ({ minutes, onMinutesChange }: TimeWindowControlProps) => {
  const formatDuration = (mins: number) => {
    if (mins < 60) return `${mins} min`;
    if (mins < 1440) return `${(mins / 60).toFixed(1)} hours`;
    return `${(mins / 1440).toFixed(1)} days`;
  };

  // Logarithmic scale for better UX: 5 min to 24 hours (1440 min)
  const minLog = Math.log(5);
  const maxLog = Math.log(1440);
  
  const valueToSlider = (value: number) => {
    const log = Math.log(value);
    return ((log - minLog) / (maxLog - minLog)) * 100;
  };

  const sliderToValue = (slider: number) => {
    const log = minLog + (slider / 100) * (maxLog - minLog);
    return Math.round(Math.exp(log));
  };

  return (
    <Card className="glass-card p-0">
      <CardHeader className="pb-2 px-4 pt-4">
        <CardTitle className="text-base font-medium flex items-center gap-2">
          <div className="p-2 rounded-lg bg-primary/20 border border-glass">
            <Clock className="w-4 h-4 text-primary" />
          </div>
          History Window
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 px-4 pb-4 pt-0">
        <div className="flex items-center justify-between">
          <span className="text-2xl font-bold">{formatDuration(minutes)}</span>
          <span className="text-sm text-muted-foreground">of track history</span>
        </div>

        <Slider
          value={[valueToSlider(minutes)]}
          onValueChange={([value]) => onMinutesChange(sliderToValue(value))}
          max={100}
          step={1}
          className="py-2"
        />

        <div className="flex flex-wrap gap-2">
          {presets.map((preset) => (
            <Button
              key={preset.value}
              variant={minutes === preset.value ? "default" : "outline"}
              size="sm"
              onClick={() => onMinutesChange(preset.value)}
              className={cn(
                "flex-1 min-w-[60px]",
                minutes === preset.value && "bg-primary text-primary-foreground"
              )}
            >
              {preset.label}
            </Button>
          ))}
        </div>
      </CardContent>
    </Card>
  );
};

export default TimeWindowControl;
