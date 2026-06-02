export const SATELLITE_OPTIONS = [
  { value: "MODIS", label: "MODIS" },
  { value: "VIIRS_SNPP", label: "VIIRS S-NPP" },
  { value: "VIIRS_NOAA20", label: "VIIRS NOAA-20" },
  { value: "VIIRS_NOAA21", label: "VIIRS NOAA-21" }
] as const;

export type SatelliteValue = (typeof SATELLITE_OPTIONS)[number]["value"];
