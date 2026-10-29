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
		"tracecore/public/js/station_t6.js",
		"tracecore/public/js/station_t2.js",
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
	// màn riêng của bước (T4 đóng gói, T6 kho vô khuẩn, T2 lô rửa) nằm ở station.screen
	station.screen = {
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

function t6Screen(station, sandbox) {
	const t6 = vm.runInContext("Object.create(T6Storage.prototype)", sandbox);
	Object.assign(t6, {
		station,
		result: station.result,
		input: { value: "", placeholder: "", setAttribute() {} },
		pending: null,
		busy: null,
		offline: false,
		overview: null,
		pack: null,
		notice: null,
		damaging: false,
		reasonError: false,
	});
	return t6;
}

test("T6 putaway and mark_damaged RPCs carry the station bearer in JSON only", async () => {
	const { station, calls } = harness();
	for (const method of [
		"tracecore.v1.putaway.scan",
		"tracecore.v1.putaway.overview",
		"tracecore.v1.pack.mark_damaged",
	]) {
		await station.rpc(method, { client_ts: "original" }, "key");
	}
	for (const call of calls) {
		assert.equal(JSON.parse(call.body).token, "private-bearer");
		assert.ok(!JSON.stringify(call.headers).includes("private-bearer"));
		assert.ok(!call.url.includes("private-bearer"));
	}
	station.session = null;
	await assert.rejects(
		station.rpc("tracecore.v1.putaway.scan", {}),
		(error) => error.sessionEnded
	);
	assert.equal(calls.length, 3);
});

test("T6 clearSession drops the previous operator's pack, stock and pending request", () => {
	const { station, sandbox } = harness();
	const t6 = t6Screen(station, sandbox);
	Object.assign(t6, {
		pending: { key: "k" },
		busy: "tracecore.v1.putaway.scan",
		overview: { by_set_type: [] },
		pack: { cycle_id: "CY-1" },
		notice: { title: "x" },
		damaging: true,
		reasonError: true,
		offline: true,
	});
	t6.clearSession();
	assert.equal(t6.pending, null);
	assert.equal(t6.busy, null);
	assert.equal(t6.overview, null);
	assert.equal(t6.pack, null);
	assert.equal(t6.notice, null);
	assert.equal(t6.damaging, false);
	assert.equal(t6.dialogOpen, false);
});

test("T6 drops a late response after auth state changes", async () => {
	const { station, sandbox } = harness();
	const t6 = t6Screen(station, sandbox);
	let finish;
	let applied = false;
	station.rpc = () =>
		new Promise((resolve) => {
			finish = resolve;
		});
	sandbox.uuid4 = () => "key";
	const request = t6.request("tracecore.v1.putaway.scan", { raw: "CY-1" }, () => {
		applied = true;
	});
	station.sessionVersion++;
	finish({ ok: true, kind: "pack", pack: { cycle_id: "CY-1" } });
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

function t2Screen(station, sandbox) {
	const t2 = vm.runInContext("Object.create(T2Wash.prototype)", sandbox);
	Object.assign(t2, {
		station,
		result: station.result,
		input: { value: "", placeholder: "", setAttribute() {} },
		pending: null,
		busy: null,
		offline: false,
		overview: null,
		overviewBusy: false,
	});
	t2.reset();
	return t2;
}

test("T2 wash RPCs carry the station bearer in JSON only", async () => {
	const { station, calls } = harness();
	for (const method of [
		"tracecore.v1.wash.start",
		"tracecore.v1.wash.add_set",
		"tracecore.v1.wash.complete",
		"tracecore.v1.wash.result",
	]) {
		await station.rpc(method, { client_ts: "original" }, "key");
	}
	for (const call of calls) {
		assert.equal(JSON.parse(call.body).token, "private-bearer");
		assert.ok(!JSON.stringify(call.headers).includes("private-bearer"));
		assert.ok(!call.url.includes("private-bearer"));
	}
	station.session = null;
	await assert.rejects(
		station.rpc("tracecore.v1.wash.start", {}),
		(error) => error.sessionEnded
	);
	assert.equal(calls.length, 4);
});

test("T2 clearSession drops the previous operator's load list, batch and stored list", () => {
	const { station, sandbox, store } = harness();
	const t2 = t2Screen(station, sandbox);
	Object.assign(t2, {
		load: { machine: { name: "TB-0001" }, programs: [], lots: [], sets: [{ set_id: "S1" }] },
		unload: { batch: "LR-261022-01" },
		done: { batch: "LR-261022-02" },
		pending: { key: "k" },
		busy: "tracecore.v1.wash.add_set",
		overview: { sets: [], running: [] },
		mode: "unload",
	});
	t2.saveLoad();
	assert.ok(store.get(t2.storageKey()));
	t2.clearSession();
	assert.equal(t2.load, null);
	assert.equal(t2.unload, null);
	assert.equal(t2.done, null);
	assert.equal(t2.pending, null);
	assert.equal(t2.busy, null);
	assert.equal(t2.overview, null);
	assert.equal(t2.mode, "load");
	assert.equal(store.get(t2.storageKey()), undefined);
});

test("T2 drops a late response after auth state changes", async () => {
	const { station, sandbox } = harness();
	const t2 = t2Screen(station, sandbox);
	t2.show = () => {};
	let finish;
	let applied = false;
	station.rpc = () =>
		new Promise((resolve) => {
			finish = resolve;
		});
	sandbox.uuid4 = () => "key";
	const request = t2.request("tracecore.v1.wash.add_set", { raw: "S1" }, () => {
		applied = true;
	});
	station.sessionVersion++;
	finish({ ok: true, set_id: "S1" });
	await request;
	assert.equal(applied, false);
});

test("T2 recognises the HOAN-THANH-NAP control code before any server call", async () => {
	const { station, sandbox } = harness();
	const t2 = t2Screen(station, sandbox);
	station.isOffline = () => false;
	let completed = 0;
	t2.complete = () => {
		completed++;
	};
	await t2.scan("hoan-thanh-nap");
	assert.equal(completed, 1);
});

function dailyTestScreen(reducedMotion = false) {
	const { station, sandbox } = harness();
	for (const file of [
		"tracecore/public/js/station_t5.js",
		"tracecore/public/js/station_daily_test.js",
	])
		vm.runInContext(fs.readFileSync(path.resolve(__dirname, "../..", file), "utf8"), sandbox);
	const scrolls = [];
	const formRegion = { scrollIntoView: (options) => scrolls.push(options) };
	sandbox.window = { matchMedia: () => ({ matches: reducedMotion }) };
	Object.assign(station, {
		isOffline: () => false,
		setState: (state, html) => {
			station.result.innerHTML = html;
		},
	});
	station.result.querySelector = (selector) =>
		selector === '[data-region="dt-form"]' &&
		station.result.innerHTML.includes('data-region="dt-form"')
			? formRegion
			: null;
	const screen = vm.runInContext("Object.create(DailyTestScreen.prototype)", sandbox);
	Object.assign(screen, {
		station,
		back: {},
		result: station.result,
		input: { value: "", placeholder: "", setAttribute() {} },
		pending: null,
		busy: null,
		offline: false,
	});
	screen.reset();
	screen.list = [
		{
			name: "TB-0005",
			equipment_name: "Washer",
			required: ["washer_cleaning"],
			missing: [],
			status: "Ready",
		},
		{
			name: "TB-0009",
			equipment_name: "Steam",
			required: ["bowie_dick", "leak"],
			missing: [],
			status: "Ready",
		},
	];
	return { screen, scrolls };
}

test("daily test scrolls to the form of the scanned machine once", async () => {
	const { screen, scrolls } = dailyTestScreen();
	await screen.scan("TB-0005");
	assert.equal(scrolls.length, 1);
	assert.equal(scrolls[0].block, "start");
	assert.equal(scrolls[0].behavior, "smooth");
	screen.onAction("dt-result", { dataset: { value: "Pass" } });
	assert.equal(scrolls.length, 1);
});

test("daily test scrolls to the form when a machine is chosen in the list", () => {
	const { screen, scrolls } = dailyTestScreen();
	screen.onAction("dt-select", { dataset: { machine: "TB-0009" } });
	assert.equal(scrolls.length, 1);
});

test("daily test jumps to the form without motion when reduced motion is preferred", async () => {
	const { screen, scrolls } = dailyTestScreen(true);
	await screen.scan("TB-0005");
	assert.equal(scrolls[0].behavior, "auto");
});
