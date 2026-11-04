// Which climate sensor is the cabin and which is outside, by name, so a van with
// one sensor (or only an outside one) is shown correctly everywhere.
import type { ClimateSnapshot } from "@/api/types";

export const isOutside = (name: string) => /out|ext|aussen|vani/i.test(name);

export function cabinAndOutside(sensors: ClimateSnapshot[] | undefined): {
  inside: ClimateSnapshot | undefined;
  outside: ClimateSnapshot | undefined;
} {
  const list = sensors ?? [];
  return {
    inside: list.find((s) => !isOutside(s.sensor)),
    outside: list.find((s) => isOutside(s.sensor)),
  };
}
