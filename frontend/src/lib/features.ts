// What this van actually has, so the overview and the tablet panel only show
// cards that mean something (no empty "–" cards for missing hardware).
import { useClimate, useEnergy, useGps, useRelays, useWater, useWeather } from "@/api/hooks";
import { useHeaters } from "@/components/Heater";
import { cabinAndOutside } from "./cabin";

export type Feature = "climate" | "cabin" | "water" | "battery" | "charging" | "map" | "weather" | "switches" | "heater";

/** Features known to be missing. Unknown (still loading) counts as present, so cards don't flicker away. */
export function useMissingFeatures(): Set<Feature> {
  const climate = useClimate();
  const water = useWater();
  const energy = useEnergy();
  const gps = useGps();
  const weather = useWeather();
  const relays = useRelays();
  const heaters = useHeaters();
  const missing = new Set<Feature>();
  if (climate.data && climate.data.length === 0) missing.add("climate");
  if (climate.data && !cabinAndOutside(climate.data).inside) missing.add("cabin");
  const noWaterSensor = Boolean(water.data?.error?.includes("Sensors tab"));
  if (noWaterSensor) missing.add("water");
  if (energy.data && !energy.data.available) {
    missing.add("charging");
    if (noWaterSensor || water.data?.battery_voltage == null) missing.add("battery");
  }
  if (gps.data?.status === "disabled") missing.add("map");
  if (gps.data?.status === "disabled" && weather.data && !weather.data.available) missing.add("weather");
  if (relays.data && relays.data.length === 0) missing.add("switches");
  if (heaters.data && heaters.data.heaters.length === 0) missing.add("heater");
  return missing;
}
