/** Binary image-coordinate geometry. COCO RLE traverses columns, buffers traverse rows. */
import type { Instance } from "./api";
export interface PixelPoint {
  x: number;
  y: number;
}
export interface MaskRle {
  size: number[];
  counts: string;
}
export const manualTools = ["brush", "eraser", "polygon"];
export function decodeRle(
  encoded: unknown,
  width: number,
  height: number,
): Uint8Array {
  const rle = encoded as MaskRle;
  if (
    !rle ||
    rle.size?.[0] !== height ||
    rle.size?.[1] !== width ||
    typeof rle.counts !== "string"
  )
    throw new Error("Mask size differs from the image");
  const counts: number[] = [];
  let p = 0,
    total = 0;
  while (p < rle.counts.length) {
    let x = 0,
      shift = 0,
      c = 0;
    do {
      if (p >= rle.counts.length || shift > 50)
        throw new Error("Invalid mask encoding");
      c = rle.counts.charCodeAt(p++) - 48;
      if (c < 0 || c > 63) throw new Error("Invalid mask encoding");
      x += (c & 31) * 2 ** shift;
      shift += 5;
    } while (c & 32);
    if (c & 16) x -= 2 ** shift;
    if (counts.length > 2) x += counts[counts.length - 2];
    if (!Number.isSafeInteger(x) || x < 0 || total + x > width * height)
      throw new Error("Invalid mask encoding");
    counts.push(x);
    total += x;
  }
  if (total !== width * height) throw new Error("Invalid mask encoding");
  const pixels = new Uint8Array(total);
  let offset = 0;
  counts.forEach((count, index) => {
    if (index % 2)
      for (let i = offset; i < offset + count; i++)
        pixels[(i % height) * width + Math.floor(i / height)] = 1;
    offset += count;
  });
  return pixels;
}
export function encodeRle(
  pixels: Uint8Array,
  width: number,
  height: number,
): MaskRle {
  if (pixels.length !== width * height)
    throw new Error("Mask size differs from the image");
  const counts: number[] = [];
  let last = 0,
    count = 0;
  for (let x = 0; x < width; x++)
    for (let y = 0; y < height; y++) {
      const value = pixels[y * width + x] ? 1 : 0;
      if (value === last) count++;
      else {
        counts.push(count);
        count = 1;
        last = value;
      }
    }
  counts.push(count);
  const chunks: string[] = [];
  counts.forEach((value, i) => {
    let x = value - (i > 2 ? counts[i - 2] : 0);
    let more: boolean;
    do {
      let c = x & 31;
      x = Math.floor(x / 32);
      more = c & 16 ? x !== -1 : x !== 0;
      if (more) c |= 32;
      chunks.push(String.fromCharCode(c + 48));
    } while (more);
  });
  return { size: [height, width], counts: chunks.join("") };
}
export function paintSegment(
  pixels: Uint8Array,
  width: number,
  height: number,
  a: PixelPoint,
  b: PixelPoint,
  diameter: number,
  add: boolean,
): boolean {
  const r = diameter / 2,
    dx = b.x - a.x,
    dy = b.y - a.y,
    length = dx * dx + dy * dy;
  const left = Math.max(0, Math.floor(Math.min(a.x, b.x) - r));
  const right = Math.min(width, Math.ceil(Math.max(a.x, b.x) + r));
  const top = Math.max(0, Math.floor(Math.min(a.y, b.y) - r));
  const bottom = Math.min(height, Math.ceil(Math.max(a.y, b.y) + r));
  let changed = false;
  for (let y = top; y < bottom; y++)
    for (let x = left; x < right; x++) {
      const t = length
        ? Math.max(
            0,
            Math.min(1, ((x + 0.5 - a.x) * dx + (y + 0.5 - a.y) * dy) / length),
          )
        : 0;
      if ((x + 0.5 - a.x - t * dx) ** 2 + (y + 0.5 - a.y - t * dy) ** 2 > r * r)
        continue;
      const i = y * width + x,
        value = add ? 1 : 0;
      if (pixels[i] !== value) {
        pixels[i] = value;
        changed = true;
      }
    }
  return changed;
}
export function fillPolygon(
  pixels: Uint8Array,
  width: number,
  height: number,
  points: number[][],
  add: boolean,
): boolean {
  if (points.length < 3) return false;
  let changed = false;
  const top = Math.max(0, Math.floor(Math.min(...points.map((p) => p[1]))));
  const bottom = Math.min(
    height,
    Math.ceil(Math.max(...points.map((p) => p[1]))),
  );
  for (let y = top; y < bottom; y++) {
    const xs: number[] = [];
    for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
      const [ax, ay] = points[j],
        [bx, by] = points[i];
      if (ay > y + 0.5 !== by > y + 0.5)
        xs.push(ax + ((y + 0.5 - ay) * (bx - ax)) / (by - ay));
    }
    xs.sort((a, b) => a - b);
    for (let i = 0; i + 1 < xs.length; i += 2) {
      const left = Math.max(0, Math.ceil(xs[i] - 0.5)),
        right = Math.min(width, Math.ceil(xs[i + 1] - 0.5));
      for (let x = left; x < right; x++) {
        const index = y * width + x,
          value = add ? 1 : 0;
        if (pixels[index] !== value) {
          pixels[index] = value;
          changed = true;
        }
      }
    }
  }
  return changed;
}
export function instancePixels(
  obj: Instance | null,
  width: number,
  height: number,
): Uint8Array {
  if (obj?.mask) return decodeRle(obj.mask, width, height);
  const pixels = new Uint8Array(width * height);
  for (const polygon of obj?.polygons ?? [])
    fillPolygon(pixels, width, height, polygon, true);
  return pixels;
}
export function maskCanvas(
  pixels: Uint8Array,
  width: number,
  height: number,
  color: string,
): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d")!;
  const image = ctx.createImageData(width, height);
  const rgb = [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16));
  for (let i = 0; i < pixels.length; i++)
    if (pixels[i]) {
      const j = i * 4;
      image.data[j] = rgb[0];
      image.data[j + 1] = rgb[1];
      image.data[j + 2] = rgb[2];
      image.data[j + 3] = 90;
    }
  ctx.putImageData(image, 0, 0);
  return canvas;
}
