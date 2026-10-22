import { afterEach, expect, it, vi } from "vitest";
import { setProjectSession } from "./api";
import { clearThumbnails, thumbnail } from "./thumbnails";

afterEach(() => {
  clearThumbnails();
  setProjectSession();
  vi.unstubAllGlobals();
});

it("keeps queued thumbnails bound to their original project session", async () => {
  const pending: Array<(response: Response) => void> = [];
  const fetch = vi.fn(
    () => new Promise<Response>((resolve) => pending.push(resolve)),
  );
  vi.stubGlobal("fetch", fetch);
  setProjectSession("A");
  const controller = new AbortController();
  const requests = Array.from({ length: 5 }, (_, i) =>
    thumbnail(String(i), controller.signal, "A"),
  );
  expect(fetch).toHaveBeenCalledTimes(4);
  setProjectSession("B");
  pending[0](new Response(new Blob(["image"])));
  await requests[0];
  for (let i = 0; i < 8; i++) await Promise.resolve();
  expect(fetch).toHaveBeenCalledTimes(5);
  expect((fetch.mock.calls[4] as unknown[])[0]).toBe(
    "/api/v1/images/4/thumbnail?project_session=A",
  );
  for (const resolve of pending.slice(1))
    resolve(new Response(new Blob(["image"])));
  await Promise.all(requests);
});
