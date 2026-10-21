import { apiBase } from "./api";
const cache = new Map<string, { url: string; size: number }>();
let active = 0,
  bytes = 0;
const queue: Array<{
  id: string;
  key: string;
  signal: AbortSignal;
  resolve: (url: string) => void;
  reject: (e: unknown) => void;
}> = [];
function drain() {
  while (active < 4 && queue.length) {
    const job = queue.shift()!;
    if (job.signal.aborted) {
      job.reject(new Error("Aborted"));
      continue;
    }
    active++;
    void fetch(apiBase + `/images/${job.id}/thumbnail`, { signal: job.signal })
      .then((r) => {
        if (!r.ok) throw new Error("Thumbnail unavailable");
        return r.blob();
      })
      .then((blob) => {
        if (job.signal.aborted) throw new Error("Aborted");
        const old = cache.get(job.key);
        if (old) {
          job.resolve(old.url);
          return;
        }
        const url = URL.createObjectURL(blob),
          size = 320 * 320 * 4;
        cache.set(job.key, { url, size });
        bytes += size;
        while (cache.size > 48 || bytes > 24 * 1024 * 1024) {
          const key = cache.keys().next().value!;
          const item = cache.get(key)!;
          URL.revokeObjectURL(item.url);
          bytes -= item.size;
          cache.delete(key);
        }
        job.resolve(url);
      })
      .catch(job.reject)
      .finally(() => {
        active--;
        drain();
      });
  }
}
export function clearThumbnails() {
  for (const item of cache.values()) URL.revokeObjectURL(item.url);
  cache.clear();
  bytes = 0;
}
export function thumbnail(
  id: string,
  signal: AbortSignal,
  namespace: string,
): Promise<string> {
  const key = apiBase + "|" + namespace + "|" + id;
  const hit = cache.get(key);
  if (hit) {
    cache.delete(key);
    cache.set(key, hit);
    return Promise.resolve(hit.url);
  }
  return new Promise((resolve, reject) => {
    queue.push({ id, key, signal, resolve, reject });
    drain();
  });
}
