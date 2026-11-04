// The Raspberry Pi's 40-pin header as seen from above (pin 1 at the top left, next
// to the SD card side): which pin does what, which are taken, where to connect.

import { GPIO_TO_PIN } from "@/lib/sensorCatalog";

const POWER: Record<number, string> = { 1: "3.3V", 17: "3.3V", 2: "5V", 4: "5V" };
const GROUND = new Set([6, 9, 14, 20, 25, 30, 34, 39]);
const PIN_TO_GPIO = Object.fromEntries(Object.entries(GPIO_TO_PIN).map(([gpio, pin]) => [pin, Number(gpio)])) as Record<number, number>;

export interface PinUse {
  gpio: number;
  free: boolean;
  used_by: string | null;
}

export function PiHeader({
  highlight = [],
  dataGpio,
  pins,
  onPick,
}: {
  /** Physical pins to highlight (power, ground, I2C...). */
  highlight?: number[];
  /** The chosen data GPIO (BCM). */
  dataGpio?: number | null;
  pins?: PinUse[];
  /** Tap a free GPIO to choose it. */
  onPick?: (gpio: number) => void;
}) {
  const usage = new Map((pins ?? []).map((p) => [p.gpio, p]));
  const dataPin = dataGpio != null ? GPIO_TO_PIN[dataGpio] : null;

  const cell = (pin: number) => {
    const gpio = PIN_TO_GPIO[pin];
    const use = gpio !== undefined ? usage.get(gpio) : undefined;
    const label = POWER[pin] ?? (GROUND.has(pin) ? "GND" : gpio !== undefined ? `GPIO ${gpio}` : "");
    const kind = POWER[pin] ? (POWER[pin] === "5V" ? "v5" : "v3") : GROUND.has(pin) ? "gnd" : "gpio";
    const chosen = pin === dataPin;
    const lit = chosen || highlight.includes(pin);
    const taken = use && !use.free && !chosen;
    const pickable = Boolean(onPick && gpio !== undefined && use?.free);
    const title = `Pin ${pin}: ${label}${use?.used_by ? ` (${use.used_by})` : ""}`;
    const content = (
      <>
        <span className={`pin-dot ${kind}`} />
        <span className="pin-text">
          <span className="pin-num">{pin}</span> {label}
          {taken && <span className="pin-use"> · {use?.used_by}</span>}
        </span>
      </>
    );
    const className = `pin ${lit ? "lit" : ""} ${chosen ? "chosen" : ""} ${taken ? "taken" : ""} ${pin % 2 === 0 ? "right" : ""}`;
    return pickable ? (
      <button key={pin} type="button" className={className} title={title} onClick={() => onPick?.(gpio)}>
        {content}
      </button>
    ) : (
      <div key={pin} className={className} title={title}>
        {content}
      </div>
    );
  };

  return (
    <div className="pi-header" role="group" aria-label="Raspberry Pi GPIO header">
      {Array.from({ length: 20 }, (_, row) => (
        <div key={row} className="pin-row">
          {cell(row * 2 + 1)}
          {cell(row * 2 + 2)}
        </div>
      ))}
      <span className="tiny faint" style={{ gridColumn: "1 / -1" }}>
        Pin 1 is at the end of the header nearest the SD card slot, in the inner row. Even numbers (2, 4, 6…) are the row
        along the board's edge.
      </span>
    </div>
  );
}
