import { afterEach, describe, expect, it, vi } from "vitest";
import { projectResource, request, setProjectSession } from "./api";

afterEach(() => {
  setProjectSession();
  vi.unstubAllGlobals();
});

describe("project request identity", () => {
  it("binds JSON requests to the session visible when they start", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response("{}"));
    vi.stubGlobal("fetch", fetch);
    setProjectSession("session-A");
    const pending = request("/images/a/annotation", "PUT", { notes: "A" });
    setProjectSession("session-B");
    await pending;
    expect(fetch.mock.calls[0][1].headers).toMatchObject({
      "X-AnnoDesk-Project": "session-A",
    });
  });
  it("binds image URLs to their original session, including existing query parameters", () => {
    setProjectSession("session-A");
    const url = projectResource("/images/a/masks/object?revision=1");
    setProjectSession("session-B");
    expect(url).toBe(
      "/api/v1/images/a/masks/object?revision=1&project_session=session-A",
    );
    expect(projectResource("/images/a/file")).toContain(
      "?project_session=session-B",
    );
  });
});
