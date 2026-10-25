import { test } from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import {
  internalPath,
  readableError,
  request,
  setCSRF,
  APIError,
  createBusinessMutation,
  passwordResetPath,
} from "../.test/api.js";

if (!globalThis.crypto) globalThis.crypto = webcrypto;

test("return targets stay inside TraceCore", () => {
  for (const path of [
    "https://example.org",
    "//example.org",
    "/app/home",
    "/tracecore/../app",
  ])
    assert.equal(internalPath(path), "/tracecore");
  assert.equal(
    internalPath("/tracecore/R01/dashboard"),
    "/tracecore/R01/dashboard"
  );
});
test("password reset redirects only to the same-origin password flow", () => {
  assert.equal(
    passwordResetPath("/update-password?key=abc", "http://localhost:8000"),
    "/update-password?key=abc"
  );
  assert.equal(
    passwordResetPath(
      "https://example.org/update-password?key=abc",
      "http://localhost:8000"
    ),
    null
  );
  assert.equal(passwordResetPath("/app", "http://localhost:8000"), null);
});
test("errors never expose raw server tracebacks", () => {
  assert.equal(readableError(500), "Máy chủ đang gặp sự cố. Thử lại sau.");
  assert.equal(readableError(403), "Không có quyền thực hiện thao tác này.");
  assert.equal(readableError(401), "Phiên đăng nhập đã hết hạn.");
});
test("mutations carry session, CSRF and a stable idempotency key", async () => {
  globalThis.window = { location: { origin: "http://localhost:8000" } };
  setCSRF("test-csrf");
  let call;
  globalThis.fetch = async (url, init) => {
    call = { url, init };
    return { ok: true, json: async () => ({ message: { ok: true } }) };
  };
  await request(
    "tracecore.v1.set_unit.create_batch",
    { count: 2 },
    true,
    false,
    "request-123"
  );
  assert.equal(call.init.credentials, "same-origin");
  assert.equal(call.init.headers["X-Frappe-CSRF-Token"], "test-csrf");
  assert.equal(call.init.headers["X-Idempotency-Key"], "request-123");
  assert.equal(call.init.body, '{"count":2}');
});
test("server errors are reduced to safe user-facing messages", async () => {
  globalThis.window = { location: { origin: "http://localhost:8000" } };
  globalThis.fetch = async () => ({
    ok: false,
    status: 500,
    text: async () => "<html>Traceback secret</html>",
  });
  await assert.rejects(
    request("test"),
    (error) => error instanceof APIError && !error.message.includes("secret")
  );
});
test("expired Frappe sessions are distinguished from permission denial", async () => {
  globalThis.fetch = async () => ({ ok: false, status: 403 });
  await assert.rejects(
    request("test"),
    (error) => error instanceof APIError && error.status === 401
  );
  globalThis.fetch = async (url) =>
    String(url).includes("get_logged_user")
      ? { ok: true, json: async () => ({ message: "operator@example.test" }) }
      : { ok: false, status: 403 };
  await assert.rejects(
    request("test"),
    (error) => error instanceof APIError && error.status === 403
  );
});
test("uncertain mutation retries preserve the exact key and timestamp", async () => {
  const calls = [];
  let first = true;
  globalThis.fetch = async (_url, init) => {
    calls.push(init);
    if (first) {
      first = false;
      throw new Error("lost response");
    }
    return { ok: true, json: async () => ({ message: { ok: true } }) };
  };
  const mutate = createBusinessMutation();
  await assert.rejects(mutate("business", { count: 2 }));
  await mutate("business", { count: 2 });
  assert.equal(calls[0].body, calls[1].body);
  assert.equal(
    calls[0].headers["X-Idempotency-Key"],
    calls[1].headers["X-Idempotency-Key"]
  );
});
test("changed payloads and operations receive new idempotency keys", async () => {
  const calls = [];
  globalThis.fetch = async (_url, init) => {
    calls.push(init);
    return { ok: false, status: 409 };
  };
  const mutate = createBusinessMutation();
  await assert.rejects(mutate("issue", { count: 2 }));
  await assert.rejects(mutate("issue", { count: 3 }));
  await assert.rejects(mutate("print", { count: 3 }));
  assert.notEqual(
    calls[0].headers["X-Idempotency-Key"],
    calls[1].headers["X-Idempotency-Key"]
  );
  assert.notEqual(
    calls[1].headers["X-Idempotency-Key"],
    calls[2].headers["X-Idempotency-Key"]
  );
});
