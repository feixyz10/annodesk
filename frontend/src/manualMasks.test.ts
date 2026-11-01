import { expect, it } from "vitest";
import {
  decodeRle,
  encodeRle,
  paintSegment,
  fillPolygon,
  instancePixels,
} from "./manualMasks";
import { instance } from "./api";
it("roundtrips pycocotools compressed column-major RLE with holes and disconnected pixels", () => {
  const rle = { size: [5, 7], counts: "632NO010O0128N" };
  const expected = [
    0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 1, 1, 1,
    1, 0, 0, 0, 0, 0, 0, 0, 0, 1,
  ];
  expect([...decodeRle(rle, 7, 5)]).toEqual(expected);
  expect(encodeRle(Uint8Array.from(expected), 7, 5)).toEqual(rle);
  for (const value of [0, 1]) {
    const pixels = new Uint8Array(35).fill(value);
    expect(decodeRle(encodeRle(pixels, 7, 5), 7, 5)).toEqual(pixels);
  }
});
it("rejects malformed counts, sizes and decoded lengths", () => {
  for (const counts of ["", "P", "!", "O", "Z9"])
    expect(() => decodeRle({ size: [2, 2], counts }, 2, 2)).toThrow();
  expect(() => decodeRle({ size: [2, 3], counts: "6" }, 2, 2)).toThrow();
});
it("paints continuous pixel-center capsules, clips and erases without affecting other pixels", () => {
  const pixels = new Uint8Array(100);
  expect(
    paintSegment(pixels, 10, 10, { x: -5, y: 4.5 }, { x: 15, y: 4.5 }, 1, true),
  ).toBe(true);
  expect([...pixels.slice(40, 50)]).toEqual(Array(10).fill(1));
  expect(pixels.reduce((a, b) => a + b)).toBe(10);
  expect(
    paintSegment(pixels, 10, 10, { x: -5, y: 4.5 }, { x: 15, y: 4.5 }, 1, true),
  ).toBe(false);
  paintSegment(
    pixels,
    10,
    10,
    { x: 4.5, y: 4.5 },
    { x: 4.5, y: 4.5 },
    1,
    false,
  );
  expect(pixels[44]).toBe(0);
  expect(pixels[45]).toBe(1);
});
it("adds and subtracts polygon regions, including self-intersection and degenerate paths", () => {
  const pixels = new Uint8Array(36);
  const box = [
    [1, 1],
    [5, 1],
    [5, 5],
    [1, 5],
  ];
  expect(fillPolygon(pixels, 6, 6, box, true)).toBe(true);
  expect(pixels.reduce((a, b) => a + b)).toBe(16);
  fillPolygon(
    pixels,
    6,
    6,
    [
      [2, 2],
      [4, 2],
      [4, 4],
      [2, 4],
    ],
    false,
  );
  expect(pixels.reduce((a, b) => a + b)).toBe(12);
  expect(
    fillPolygon(
      pixels,
      6,
      6,
      [
        [1, 1],
        [2, 2],
      ],
      true,
    ),
  ).toBe(false);
  const obj = instance(null);
  obj.polygons = [box];
  expect(instancePixels(obj, 6, 6).reduce((a, b) => a + b)).toBe(16);
  const cross = new Uint8Array(36);
  fillPolygon(
    cross,
    6,
    6,
    [
      [0, 0],
      [6, 6],
      [0, 6],
      [6, 0],
    ],
    true,
  );
  expect(cross[0]).toBe(1);
  expect(cross[3 * 6]).toBe(0);
});
