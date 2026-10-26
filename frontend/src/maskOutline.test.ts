import { expect, it } from "vitest";
import { maskOutline } from "./maskOutline";
it("highlights lossless outer edges, holes and disconnected regions while leaving deep interiors transparent", () => {
  const width = 40,
    height = 40,
    alpha = new Uint8Array(width * height);
  for (let y = 3; y < 30; y++)
    for (let x = 3; x < 30; x++) alpha[y * width + x] = 110;
  for (let y = 14; y < 20; y++)
    for (let x = 14; x < 20; x++) alpha[y * width + x] = 0;
  alpha[35 * width + 35] = 110;
  const out = maskOutline(alpha, width, height, 1);
  const pixel = (x: number, y: number) =>
    Array.from(out.slice((y * width + x) * 4, (y * width + x) * 4 + 4));
  expect(pixel(3, 10)).toEqual([49, 95, 233, 255]);
  expect(pixel(1, 10)).toEqual([255, 255, 255, 255]);
  expect(pixel(13, 16)).toEqual([49, 95, 233, 255]);
  expect(pixel(35, 35)).toEqual([49, 95, 233, 255]);
  expect(pixel(8, 8)[3]).toBe(0);
  expect(pixel(39, 0)[3]).toBe(0);
});
