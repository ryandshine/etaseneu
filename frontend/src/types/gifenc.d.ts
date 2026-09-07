declare module "gifenc" {
  export interface GIFEncoderOptions {
    auto?: boolean;
    initialCapacity?: number;
  }

  export interface WriteFrameOptions {
    palette?: number[][];
    delay?: number;
    transparent?: boolean;
    transparentIndex?: number;
    dispose?: number;
  }

  export interface GIFEncoderInstance {
    writeFrame: (
      index: Uint8Array | number[],
      width: number,
      height: number,
      opts?: WriteFrameOptions
    ) => void;
    finish: () => void;
    bytes: () => Uint8Array;
    bytesView: () => Uint8Array;
    reset: () => void;
  }

  export function GIFEncoder(opts?: GIFEncoderOptions): GIFEncoderInstance;
  export function quantize(
    rgba: Uint8Array | number[] | Uint8ClampedArray,
    maxColors?: number,
    opts?: Record<string, unknown>
  ): number[][];
  export function applyPalette(
    rgba: Uint8Array | number[] | Uint8ClampedArray,
    palette: number[][],
    format?: string
  ): Uint8Array;
  export function nearestColorIndex(
    palette: number[][],
    r: number,
    g: number,
    b: number
  ): number;
}
