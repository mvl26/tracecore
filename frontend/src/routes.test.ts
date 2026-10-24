import { describe, expect, it } from "vitest";
import { resolveRoute } from "./routes";

describe("resolveRoute", () => {
  it.each([
    ["search", "/tracecore/search"],
    ["station", "/app/station"],
    ["set-units", "/app/set-unit"],
    ["packs", "/app/pack"],
    ["equipment", "/app/equipment"],
    ["par-levels", "/app/par-level"],
    ["frappe-admin", "/app"],
  ])("resolves the registered %s route", (key, destination) => {
    expect(resolveRoute(key)).toBe(destination);
  });

  it.each([
    "unknown",
    "",
    "https://evil.example",
    "//evil.example",
    "/app/user",
    "javascript:alert(1)",
    "constructor",
    "toString",
    "__proto__",
  ])("rejects unregistered route %s", (key) => {
    expect(() => resolveRoute(key)).toThrow("Unknown TraceCore route");
  });
});
