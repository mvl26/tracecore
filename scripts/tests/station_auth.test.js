const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function harness() {
	const store = new Map();
	const calls = [];
	const sandbox = {
		frappe: { pages: { station: {} }, utils: { escape_html: String }, csrf_token: "csrf" },
		__: (s) => s,
		AbortController,
		URLSearchParams,
		Uint8Array,
		Date,
		TypeError,
		performance,
		setTimeout: () => 1,
		clearTimeout() {},
		setInterval: () => 1,
		clearInterval() {},
		navigator: { onLine: true },
		sessionStorage: {
			getItem: (key) => store.get(key) || null,
			setItem: (key, value) => store.set(key, value),
			removeItem: (key) => store.delete(key),
		},
		fetch: async (url, options) => {
			calls.push({ url, ...options });
			return { ok: true, json: async () => ({ message: { ok: true } }) };
		},
	};
	vm.createContext(sandbox);
	for (const file of [
		"tracecore/ui/page/station/station.js",
		"tracecore/public/js/station_t4.js",
	])
		vm.runInContext(fs.readFileSync(path.resolve(__dirname, "../..", file), "utf8"), sandbox);
	const station = vm.runInContext("Object.create(TraceCoreStation.prototype)", sandbox);
	Object.assign(station, {
		station: "TR-004",
		session: { token: "private-bearer", employee: "EMP-1" },
		sessionVersion: 1,
		authGeneration: 0,
		visible: true,
		disposed: false,
		listeners: [],
		controllers: new Set(),
		lastActivity: Date.now(),
		heartbeatActivity: 0,
		pending: { raw: "SET" },
		lastRaw: "SET",
		authBusy: false,
		input: { value: "SET" },
		cardInput: { value: "CARD" },
		root: { dataset: {}, querySelector: () => ({ textContent: "" }) },
		authForm: { hidden: true },
		work: { hidden: false },
		sessionBar: { hidden: false },
		authResult: { innerHTML: "", dataset: {} },
		result: { innerHTML: "SET", dataset: {} },
		form: { classList: { remove() {}, toggle() {} } },
		focus() {},
	});
	sandbox.frappe.tc_station = station;
	return { station, sandbox, calls, store };
}

test("protected RPC carries bearer in JSON only and preserves idempotency/timestamp", async () => {
	const { station, calls } = harness();
	await station.rpc("tracecore.v1.pack.scan", { raw: "SET", client_ts: "original" }, "same-key");
	assert.equal(JSON.parse(calls[0].body).token, "private-bearer");
	assert.equal(JSON.parse(calls[0].body).client_ts, "original");
	assert.equal(calls[0].headers["X-Idempotency-Key"], "same-key");
	assert.ok(!JSON.stringify(calls[0].headers).includes("private-bearer"));
	assert.ok(!calls[0].url.includes("private-bearer"));
});

test("protected RPC without a session never reaches network", async () => {
	const { station, calls } = harness();
	station.session = null;
	await assert.rejects(station.rpc("tracecore.v1.pack.scan", {}), (error) => error.sessionEnded);
	assert.equal(calls.length, 0);
});

test("session rejection clears token, pending scans, packing state and dialogs", async () => {
	const { station, sandbox, store } = harness();
	let cleared = false;
	station.t4 = {
		clearSession() {
			cleared = true;
		},
	};
	assert.equal(typeof station.storageKey, "function", "session token storage is missing");
	store.set(station.storageKey(), "private-bearer");
	sandbox.fetch = async () => ({
		ok: false,
		status: 401,
		json: async () => ({
			message: {
				ok: false,
				error: {
					code: "SESSION_EXPIRED",
					title: "Expired",
					reason: "Ended",
					action: "Scan card",
				},
			},
		}),
	});
	await assert.rejects(station.rpc("tracecore.v1.pack.scan", {}), (error) => error.sessionEnded);
	assert.equal(station.session, null);
	assert.equal(store.size, 0);
	assert.equal(station.pending, null);
	assert.equal(station.lastRaw, null);
	assert.equal(station.result.innerHTML, "");
	assert.equal(station.work.hidden, true);
	assert.ok(cleared);
	assert.match(station.authResult.innerHTML, /Expired[\s\S]*Ended[\s\S]*Scan card/);
});

test("late protected response cannot repopulate an ended session", async () => {
	const { station, sandbox } = harness();
	assert.equal(typeof station.clearSession, "function", "session clearing is missing");
	let finish;
	sandbox.fetch = () =>
		new Promise((resolve) => {
			finish = resolve;
		});
	const response = station.rpc("tracecore.v1.pack.scan", {});
	station.clearSession();
	finish({ ok: true, json: async () => ({ message: { ok: true, kind: "context" } }) });
	await assert.rejects(response, (error) => error.sessionEnded);
});

test("ten minutes of local inactivity ends session; timer heartbeat does not manufacture activity", async () => {
	const { station, calls } = harness();
	assert.equal(typeof station.checkSession, "function", "idle session checking is missing");
	station.heartbeatActivity = station.lastActivity;
	await station.checkSession();
	assert.equal(calls.length, 0);
	station.lastActivity = Date.now() - 600000;
	await station.checkSession();
	assert.equal(station.session, null);
	assert.equal(calls.length, 1);
	assert.match(calls[0].url, /station.logout$/);
});

test("T4 drops a late response after auth state changes", async () => {
	const { station, sandbox } = harness();
	const t4 = vm.runInContext("Object.create(T4Packing.prototype)", sandbox);
	let finish;
	let applied = false;
	Object.assign(t4, {
		station,
		result: station.result,
		viewKey: null,
		busy: null,
		pending: null,
	});
	station.renderLoading = () => {};
	station.rpc = () =>
		new Promise((resolve) => {
			finish = resolve;
		});
	sandbox.uuid4 = () => "key";
	const request = t4.request("tracecore.v1.pack.scan", { raw: "SET" }, () => {
		applied = true;
	});
	station.sessionVersion++;
	finish({ ok: true });
	await request;
	assert.equal(applied, false);
});

test("card arriving during station handshake waits instead of being discarded", async () => {
	const { station } = harness();
	station.session = null;
	station.stationInfo = null;
	station.isOffline = () => false;
	let ready;
	let logins = 0;
	station.initialHandshake = new Promise((resolve) => {
		ready = () => {
			station.stationInfo = { name: "TR-004" };
			resolve();
		};
	});
	station.rpc = async () => {
		logins++;
		return { ok: true, session: { token: "new" } };
	};
	station.activateSession = (session) => {
		station.session = session;
	};
	const login = station.login("CARD");
	await Promise.resolve();
	assert.equal(logins, 0);
	ready();
	await login;
	assert.equal(logins, 1);
});

test("latest card is processed after an earlier pending login and the stale token is revoked", async () => {
	const { station } = harness();
	station.session = null;
	station.stationInfo = { name: "TR-004" };
	station.isOffline = () => false;
	let release;
	const cards = [];
	const revoked = [];
	station.rpc = async (method, args) => {
		if (method.endsWith("logout")) {
			revoked.push(args.token);
			return { ok: true };
		}
		cards.push(args.card_id);
		if (args.card_id === "A")
			await new Promise((resolve) => {
				release = resolve;
			});
		return { ok: true, session: { token: args.card_id } };
	};
	station.activateSession = (session) => {
		station.session = session;
	};
	const first = station.login("A");
	await new Promise(setImmediate);
	const second = station.login("B");
	release();
	await Promise.all([first, second]);
	assert.deepEqual(cards, ["A", "B"]);
	assert.equal(station.session.token, "B");
	assert.deepEqual(revoked, ["A"]);
});

test("retired page cleanup cannot erase another owner's stored token", () => {
	const { station, store } = harness();
	store.set(station.storageKey(), "new-owner-token");
	station.clearSession();
	assert.equal(store.get(station.storageKey()), "new-owner-token");
});

test("explicit end revokes the visible owner's saved token without an active restore candidate", async () => {
	const { station, store, calls } = harness();
	station.session = null;
	station.restoreCandidate = null;
	store.set(station.storageKey(), "saved-token");
	await station.endSession();
	assert.equal(store.has(station.storageKey()), false);
	assert.equal(calls.length, 1);
	assert.equal(JSON.parse(calls[0].body).token, "saved-token");
});

test("retired explicit end cannot capture a replacement's saved token", async () => {
	const { station, sandbox, store, calls } = harness();
	station.session = null;
	station.restoreCandidate = null;
	sandbox.frappe.tc_station = {};
	store.set(station.storageKey(), "replacement-token");
	await station.endSession();
	assert.equal(store.get(station.storageKey()), "replacement-token");
	assert.equal(calls.length, 0);
});

test("hide-style end preserves an unvalidated saved token", async () => {
	const { station, store, calls } = harness();
	station.session = null;
	station.restoreCandidate = null;
	store.set(station.storageKey(), "saved-token");
	await station.endSession(undefined, { keepStoredCandidate: true });
	assert.equal(store.get(station.storageKey()), "saved-token");
	assert.equal(calls.length, 0);
});

test("retired instance cannot erase replacement storage even when its old token matches", async () => {
	const { station, sandbox, store, calls } = harness();
	store.set(station.storageKey(), "private-bearer");
	sandbox.frappe.tc_station = {};
	await station.endSession();
	assert.equal(store.get(station.storageKey()), "private-bearer");
	assert.equal(calls.length, 0);
});

test("offline new-card intent clears and attempts logout of a saved-only previous token", async () => {
	const { station, store, calls } = harness();
	station.session = null;
	station.restoreCandidate = null;
	station.stationInfo = { name: "TR-004" };
	station.isOffline = () => true;
	station.setOffline = () => {};
	store.set(station.storageKey(), "saved-old-token");
	const login = station.login("NEW-CARD");
	assert.equal(store.has(station.storageKey()), false);
	await login;
	assert.equal(calls.length, 1);
	assert.match(calls[0].url, /station.logout$/);
	assert.equal(JSON.parse(calls[0].body).token, "saved-old-token");
	assert.equal(station.session, null);
});

test("retired new-card intent cannot capture or revoke replacement's equal-valued token", async () => {
	const { station, sandbox, store, calls } = harness();
	store.set(station.storageKey(), "private-bearer");
	sandbox.frappe.tc_station = {};
	await station.login("NEW-CARD");
	assert.equal(store.get(station.storageKey()), "private-bearer");
	assert.equal(calls.length, 0);
});
