declare module 'leaflet-velocity' {
  import * as L from 'leaflet';
  
  interface VelocityLayerOptions {
    displayValues?: boolean;
    displayOptions?: {
      velocityType?: string;
      position?: string;
      emptyString?: string;
      speedUnit?: string;
    };
    data?: unknown[];
    maxVelocity?: number;
    minVelocity?: number;
    velocityScale?: number;
    particleAge?: number;
    lineWidth?: number;
    particleMultiplier?: number;
    frameRate?: number;
    colorScale?: string[];
    opacity?: number;
  }

  export function velocityLayer(options: VelocityLayerOptions): L.Layer;
}
