export type TimePreset = "24h" | "48h" | "3d" | "7d" | "30d" | "custom";

export const TIME_PRESET_OPTIONS: Array<{
  label: string;
  value: TimePreset;
  hours: number;
}> = [
  { label: "24 Jam", value: "24h", hours: 24 },
  { label: "48 Jam", value: "48h", hours: 48 },
  { label: "3 Hari", value: "3d", hours: 72 },
  { label: "7 Hari", value: "7d", hours: 168 },
  { label: "30 Hari", value: "30d", hours: 720 },
  { label: "Custom", value: "custom", hours: 0 }
];
