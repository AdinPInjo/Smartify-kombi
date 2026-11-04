// The sensors Smartify knows, with what they're for and how to wire them.
// Pin numbers in the wiring steps are the physical pins of the Pi's 40-pin header.

export type SensorKind =
  | "dht22"
  | "dht11"
  | "ds18b20"
  | "bme280"
  | "sht31"
  | "aht20"
  | "gps"
  | "water_tank"
  | "door"
  | "motion";

export type Category = "climate" | "position" | "water" | "security";

export interface CatalogEntry {
  kind: SensorKind;
  name: string;
  short: string;
  category: Category;
  /** What the dashboard field needs: a GPIO pin, an I2C address, a 1-Wire probe, a serial port, nothing. */
  setting: "pin" | "address" | "probe" | "serial" | "none";
  addresses?: number[];
  suggestedName: string;
  wiring: string[];
  /** Physical header pins this sensor uses besides its data pin. */
  pins: number[];
  note?: string;
  restart?: boolean;
  single?: boolean;
}

export const CATEGORY_NAMES: Record<Category, string> = {
  climate: "Temperature & humidity",
  position: "Position",
  water: "Water",
  security: "Doors & motion",
};

export const CATALOG: CatalogEntry[] = [
  {
    kind: "dht22",
    name: "DHT22 / AM2302",
    short: "Temperature and humidity. The classic, cheap and good enough for the cabin.",
    category: "climate",
    setting: "pin",
    suggestedName: "inside",
    pins: [1, 6],
    wiring: [
      "+ (VCC) → pin 1 (3.3 V)",
      "OUT (data) → the GPIO you choose below",
      "− (GND) → pin 6 (ground)",
      "A bare sensor (4 legs) also needs a 10 kΩ resistor between data and 3.3 V. Modules with 3 pins have it built in.",
    ],
    note: "Up to about 20 m of cable. Read every 5 seconds; a failed read now and then is normal.",
  },
  {
    kind: "dht11",
    name: "DHT11",
    short: "Like the DHT22 but less accurate (±2 °C, only above 0 °C). Fine if you already have one.",
    category: "climate",
    setting: "pin",
    suggestedName: "inside",
    pins: [1, 6],
    wiring: ["+ (VCC) → pin 1 (3.3 V)", "OUT (data) → the GPIO you choose below", "− (GND) → pin 6 (ground)"],
  },
  {
    kind: "ds18b20",
    name: "DS18B20 probe",
    short: "Waterproof temperature probe on a cable: fridge, water tank, outside, battery box. Several probes on one pin.",
    category: "climate",
    setting: "probe",
    suggestedName: "fridge",
    pins: [1, 9],
    wiring: [
      "Red → pin 1 (3.3 V)",
      "Black → pin 9 (ground)",
      "Yellow (data) → the 1-Wire pin (GPIO 22 = pin 15 recommended)",
      "One 4.7 kΩ resistor between yellow and red (only once, not per probe).",
      "More probes: connect them to the same three wires.",
    ],
    note: "Temperature only, no humidity. The Pi's 1-Wire bus has to be switched on once (the next step shows how).",
  },
  {
    kind: "bme280",
    name: "BME280",
    short: "Accurate temperature, humidity and air pressure, over I2C. Shares the wires with the water tank's ADS1115.",
    category: "climate",
    setting: "address",
    addresses: [0x76, 0x77],
    suggestedName: "cabin",
    pins: [1, 3, 5, 9],
    wiring: ["VIN / VCC → pin 1 (3.3 V)", "GND → pin 9 (ground)", "SDA → pin 3", "SCL → pin 5"],
    note: "Most boards answer at 0x76; some at 0x77. Not a BMP280: that one has no humidity.",
  },
  {
    kind: "sht31",
    name: "SHT31",
    short: "Very accurate temperature and humidity over I2C, robust in damp places.",
    category: "climate",
    setting: "address",
    addresses: [0x44, 0x45],
    suggestedName: "cabin",
    pins: [1, 3, 5, 9],
    wiring: ["VIN → pin 1 (3.3 V)", "GND → pin 9 (ground)", "SDA → pin 3", "SCL → pin 5"],
  },
  {
    kind: "aht20",
    name: "AHT20 / AHT10",
    short: "Small, cheap temperature and humidity sensor over I2C.",
    category: "climate",
    setting: "address",
    addresses: [0x38],
    suggestedName: "cabin",
    pins: [1, 3, 5, 9],
    wiring: ["VIN → pin 1 (3.3 V)", "GND → pin 9 (ground)", "SDA → pin 3", "SCL → pin 5"],
  },
  {
    kind: "gps",
    name: "GPS module",
    short: "NEO-6M or another u-blox/NMEA module: map, trips, anti-theft, local weather.",
    category: "position",
    setting: "serial",
    suggestedName: "gps",
    pins: [4, 6, 8, 10],
    wiring: [
      "VCC → pin 4 (5 V)",
      "GND → pin 6 (ground)",
      "TX → pin 10 (the Pi's RX)",
      "RX → pin 8 (the Pi's TX)",
      "Put the antenna where it sees the sky (under a plastic roof vent works).",
    ],
    note: "The first position can take a few minutes outdoors.",
    restart: true,
    single: true,
  },
  {
    kind: "water_tank",
    name: "Water tank sender",
    short: "The tank's level sender, read through an ADS1115 converter. Also measures the battery voltage.",
    category: "water",
    setting: "none",
    suggestedName: "tank",
    pins: [1, 3, 5, 9],
    wiring: [
      "ADS1115: VDD → pin 1 (3.3 V), GND → pin 9, SDA → pin 3, SCL → pin 5",
      "Sender signal → ADS1115 A0; battery through the 47k/10k divider → A1",
      "Full wiring with the divider: docs/wiring.md in the project",
    ],
    note: "After adding it: Sensors tab → the ruler icon next to the tank → mark it empty and full.",
    restart: true,
    single: true,
  },
  {
    kind: "door",
    name: "Door contact (reed switch)",
    short: "Knows when a door, window or locker opens: anti-theft alerts while you're away or asleep.",
    category: "security",
    setting: "pin",
    suggestedName: "side_door",
    pins: [14],
    wiring: [
      "One wire → the GPIO you choose below",
      "Other wire → pin 14 (ground)",
      "Magnet on the door, switch on the frame, about 1 cm apart when closed.",
      "No resistor needed: the Pi's own pull-up is used.",
    ],
  },
  {
    kind: "motion",
    name: "Motion sensor (PIR)",
    short: "HC-SR501 or similar: notices someone moving inside the van.",
    category: "security",
    setting: "pin",
    suggestedName: "motion",
    pins: [2, 6],
    wiring: [
      "VCC → pin 2 (5 V)",
      "GND → pin 6 (ground)",
      "OUT → the GPIO you choose below (its 3.3 V output is safe for the Pi)",
      "Turn its time knob to the shortest setting.",
    ],
  },
];

export const catalogEntry = (kind: string) => CATALOG.find((c) => c.kind === kind);

/** BCM GPIO number → physical pin on the 40-pin header. */
export const GPIO_TO_PIN: Record<number, number> = {
  2: 3, 3: 5, 4: 7, 17: 11, 27: 13, 22: 15, 10: 19, 9: 21, 11: 23, 0: 27, 5: 29, 6: 31, 13: 33, 19: 35, 26: 37,
  14: 8, 15: 10, 18: 12, 23: 16, 24: 18, 25: 22, 8: 24, 7: 26, 1: 28, 12: 32, 16: 36, 20: 38, 21: 40,
};
