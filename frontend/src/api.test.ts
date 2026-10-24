import { afterEach, describe, expect, it, vi } from "vitest";
import { homeApi, PermissionError, SessionExpiredError } from "./api";
import type { HomeContext } from "./api";

afterEach(() => vi.unstubAllGlobals());

describe("homeApi.context", () => {
  it("reads the Frappe message using the same-origin session", async () => {
    const context = {
      user: { name: "operator@example.test", full_name: "Operator", roles: [], stations: [] },
      capabilities: ["search"],
      navigation: [{ key: "search", label: "Scan or search", route_key: "search" }],
      attention: [],
      metrics: [],
      shortcuts: [{
        key: "search", label: "Scan or search", description: "Find a resource.",
        route_key: "search", badge: null,
      }],
      system: { api_version: 1, server_time: "2026-10-24T12:00:00+07:00" },
      etag: "0123456789abcdef",
    } satisfies HomeContext;
    const fetch = vi.fn().mockResolvedValue(Response.json({ message: context }));
    vi.stubGlobal("fetch", fetch);

    await expect(homeApi.context()).resolves.toEqual(context);
    expect(fetch).toHaveBeenCalledWith("/api/method/tracecore.v1.home.context", {
      method: "GET",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
  });

  it.each([
    [401, SessionExpiredError],
    [403, PermissionError],
  ])("maps HTTP %s without requiring a JSON error body", async (status, ErrorClass) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status })));
    await expect(homeApi.context()).rejects.toBeInstanceOf(ErrorClass);
  });

  it("rejects unsuccessful responses without exposing their body", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("private detail", { status: 500 })));
    await expect(homeApi.context()).rejects.toThrow("Home context request failed (500)");
  });

  it("rejects responses missing the Frappe message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({})));
    await expect(homeApi.context()).rejects.toThrow("Invalid Home context response");
  });
});
