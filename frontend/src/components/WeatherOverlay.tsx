import { useEffect, useState } from "react";
import { Rectangle, Tooltip, useMap } from "react-leaflet";

type WeatherGridData = {
  header: {
    parameterName: string;
    lo1: number;
    la1: number;
    lo2: number;
    la2: number;
    dx: number;
    dy: number;
    nx: number;
    ny: number;
  };
  data: number[];
};

type WeatherOverlayProps = {
  parameter: "temperature" | "humidity" | "precipitation" | "soil_moisture" | "fwi" | null;
};

// Color mapping functions
function getTemperatureColor(val: number): string {
  if (val < 20) return "#3b82f6"; // Blue
  if (val < 25) return "#06b6d4"; // Cyan
  if (val < 30) return "#eab308"; // Yellow
  if (val < 35) return "#f97316"; // Orange
  return "#ef4444"; // Red
}

function getHumidityColor(val: number): string {
  if (val < 30) return "#7f1d1d"; // Dark Red (Critically Dry)
  if (val < 45) return "#f97316"; // Orange (Dry)
  if (val < 60) return "#eab308"; // Yellow (Moderate)
  if (val < 80) return "#86efac"; // Light Green (Humid)
  return "#22c55e"; // Green (Wet)
}

function getPrecipitationColor(val: number): string {
  if (val <= 0.05) return "transparent"; // No rain
  if (val < 1.0) return "#93c5fd"; // Light blue
  if (val < 5.0) return "#3b82f6"; // Blue
  return "#1d4ed8"; // Dark Blue
}

function getSoilMoistureColor(val: number): string {
  if (val < 0.15) return "#ef4444"; // Red (Very Dry)
  if (val < 0.25) return "#eab308"; // Yellow (Moderate)
  return "#22c55e"; // Green (Aman)
}

function getFWIColor(val: number): string {
  if (val < 50) return "#22c55e"; // Rendah
  if (val < 75) return "#eab308"; // Sedang
  if (val < 90) return "#f97316"; // Tinggi
  if (val < 97.5) return "#ef4444"; // Sangat Tinggi
  return "#7f1d1d"; // Ekstrem
}

function getColor(parameter: string, val: number): string {
  switch (parameter) {
    case "temperature":
      return getTemperatureColor(val);
    case "humidity":
      return getHumidityColor(val);
    case "precipitation":
      return getPrecipitationColor(val);
    case "soil_moisture":
      return getSoilMoistureColor(val);
    case "fwi":
      return getFWIColor(val);
    default:
      return "transparent";
  }
}

function getLabel(parameter: string, val: number): string {
  switch (parameter) {
    case "temperature":
      return `${val.toFixed(1)} °C`;
    case "humidity":
      return `${val.toFixed(0)}% RH`;
    case "precipitation":
      return `${val.toFixed(1)} mm`;
    case "soil_moisture":
      return `${(val * 100).toFixed(1)}% m³/m³`;
    case "fwi":
      return `${val.toFixed(1)} (CBI)`;
    default:
      return `${val}`;
  }
}

export function WeatherOverlay({ parameter }: WeatherOverlayProps) {
  const [gridData, setGridData] = useState<WeatherGridData | null>(null);
  const [loading, setLoading] = useState(false);
  const map = useMap();

  useEffect(() => {
    if (!parameter) {
      setGridData(null);
      return;
    }

    let active = true;
    setLoading(true);

    fetch(`/api/weather/grid?parameter=${parameter}`)
      .then((res) => {
        if (!res.ok) throw new Error("Failed to fetch weather grid");
        return res.json() as Promise<WeatherGridData>;
      })
      .then((data) => {
        if (active) {
          setGridData(data);
        }
      })
      .catch((err) => {
        console.error(err);
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [parameter]);

  if (!parameter || !gridData) return null;

  const { lo1, la1, dx, dy, nx, ny } = gridData.header;
  const cells: { bounds: [[number, number], [number, number]]; value: number; color: string }[] = [];

  for (let r = 0; r < ny; r++) {
    const lat = la1 - r * dy;
    for (let c = 0; c < nx; c++) {
      const lon = lo1 + c * dx;
      const idx = r * nx + c;
      const val = gridData.data[idx];

      if (val !== undefined && val !== null) {
        // Calculate cell bounding box
        const halfX = dx / 2;
        const halfY = dy / 2;
        const bounds: [[number, number], [number, number]] = [
          [lat - halfY, lon - halfX],
          [lat + halfY, lon + halfX],
        ];

        const color = getColor(parameter, val);
        if (color !== "transparent") {
          cells.push({ bounds, value: val, color });
        }
      }
    }
  }

  return (
    <>
      {cells.map((cell, idx) => (
        <Rectangle
          key={idx}
          bounds={cell.bounds}
          pathOptions={{
            color: "transparent",
            fillColor: cell.color,
            fillOpacity: 0.35,
            weight: 0,
          }}
        >
          <Tooltip sticky>
            <div style={{ fontSize: "12px", fontFamily: "sans-serif" }}>
              <strong>{parameter.toUpperCase()}</strong>
              <div>{getLabel(parameter, cell.value)}</div>
            </div>
          </Tooltip>
        </Rectangle>
      ))}
    </>
  );
}
