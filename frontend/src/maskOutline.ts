/** A contrasting outline of the lossless raster, including holes and components. */
export function maskOutline(
  alpha: Uint8Array,
  width: number,
  height: number,
  scale: number,
) {
  const output = new Uint8ClampedArray(width * height * 4);
  const edge: number[] = [];
  const outer = Math.max(1, Math.min(8, Math.ceil(2 / Math.max(scale, 0.01))));
  const inner = Math.max(0, Math.floor(outer / 2));
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = y * width + x;
      if (
        alpha[i] &&
        (x === 0 ||
          y === 0 ||
          x === width - 1 ||
          y === height - 1 ||
          !alpha[i - 1] ||
          !alpha[i + 1] ||
          !alpha[i - width] ||
          !alpha[i + width])
      )
        edge.push(i);
    }
  }
  function paint(radius: number, color: number[]) {
    for (const i of edge) {
      const x = i % width,
        y = Math.floor(i / width);
      for (
        let py = Math.max(0, y - radius);
        py <= Math.min(height - 1, y + radius);
        py++
      ) {
        for (
          let px = Math.max(0, x - radius);
          px <= Math.min(width - 1, x + radius);
          px++
        ) {
          const index = (py * width + px) * 4;
          output[index] = color[0];
          output[index + 1] = color[1];
          output[index + 2] = color[2];
          output[index + 3] = 255;
        }
      }
    }
  }
  paint(outer, [255, 255, 255]);
  paint(inner, [49, 95, 233]);
  return output;
}
