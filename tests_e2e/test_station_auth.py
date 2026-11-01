"""Browser integration of real station scripts; deterministic RPC boundary, no demo credentials/site writes."""

import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def auth_shell():
	active = {}
	requests = []
	serial = 0

	def open_shell(page, station="TR-004", bootstrap=None):
		nonlocal serial
		template = (ROOT / "tracecore/ui/page/station/station.html").read_text()
		template = re.sub(r'\{%= __\("([^"]*)"\) %\}', lambda match: match[1], template)

		def rpc(route):
			nonlocal serial
			method = route.request.url.rsplit("/", 1)[-1]
			args = route.request.post_data_json
			requests.append((method, args, route.request.headers))
			status = 200
			if method == "tracecore.v1.ping":
				body = {
					"station": {
						"name": station,
						"label": "Packing",
						"zone_type": "Clean",
						"functions": ["PACK"],
						"screens": [{"key": "pack", "label": "Packing"}],
					}
				}
			elif method.endswith("station.login"):
				serial += 1
				token = f"browser-private-{serial}"
				active["token"] = token
				body = {
					"ok": True,
					"session": {
						"token": token,
						"employee": "EMP-1",
						"employee_name": "Operator " + args["card_id"],
						"roles": ["TC R04"],
						"station": station,
						"expires_at": "2099-10-21 17:00:00",
					},
				}
			elif args.get("token") != active.get("token"):
				status = 401
				body = {
					"ok": False,
					"error": {
						"code": "SESSION_INVALID",
						"title": "Session ended",
						"reason": "Another station replaced this session.",
						"action": "Scan your employee card again.",
					},
				}
			elif method.endswith("station.logout"):
				active.clear()
				body = {"ok": True}
			elif method.endswith("station.heartbeat"):
				body = {
					"ok": True,
					"employee": "EMP-1",
					"employee_name": "Restored operator",
					"roles": ["TC R04"],
					"station": station,
					"expires_at": "2099-10-21 17:00:00",
				}
			elif method.endswith("pack.resolve_ci"):
				body = {
					"ok": True,
					"kind": "ci",
					"ci": {"batch": args["raw"], "ci_class": "5", "expiry_date": "2099-12-31"},
				}
			else:
				body = {
					"ok": False,
					"error": {
						"code": "SCAN_INVALID",
						"title": "Invalid code",
						"reason": "Use the indicator lot field.",
						"action": "Scan a Set ID.",
					},
				}
			route.fulfill(status=status, content_type="application/json", body=json.dumps({"message": body}))

		page.route("**/api/method/**", rpc)
		page.route("**/app/station?*", lambda route: route.fulfill(body="<div id='wrapper'></div>"))
		page.goto(f"http://station.test/app/station?station={station}")
		page.evaluate(
			r"""template => {
			window.__ = (s, args) => {
				const translated = s === 'TC R04' ? 'Translated packing role' : s;
				return args ? translated.replace(/\{(\d+)\}/g, (_, n) => args[n]) : translated;
			};
			window.frappe = {pages:{station:{}},csrf_token:'test',
				utils:{escape_html: value => String(value).replace(/[&<>\"']/g,
					c => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]))},
				render_template: () => template};
			window.$ = node => ({html: html => node.innerHTML = html, on: () => {}});
			// station_errors.js (A-71) không nạp trong shell này
			window.tcErrorTitle = error => error.title;
			window.tcGuideButton = () => '';
			window.tcWarningsHtml = () => '';
			window.tcBindScanLabel = () => {};
		} """,
			template,
		)
		for path in ("tracecore/ui/page/station/station.js", "tracecore/public/js/station_t4.js"):
			page.add_script_tag(path=str(ROOT / path))
		for path in ("tracecore/public/css/tokens.css", "tracecore/ui/page/station/station.css"):
			page.add_style_tag(path=str(ROOT / path))
		if bootstrap:
			page.evaluate(bootstrap)
		page.evaluate(
			"frappe.pages.station.on_page_load(document.querySelector('#wrapper')); frappe.pages.station.on_page_show()"
		)
		return page

	open_shell.requests = requests
	open_shell.active = active
	return open_shell


def login(page):
	page.locator("#tc-card-input").fill("SYNTHETIC-CARD")
	page.locator("#tc-card-input").press("Enter")
	expect(page.locator(".tc-work")).to_be_visible()


@pytest.mark.parametrize("viewport", [{"width": 1366, "height": 768}, {"width": 412, "height": 915}])
def test_card_login_identity_body_token_and_logout(page, auth_shell, viewport):
	page.set_viewport_size(viewport)
	auth_shell(page)
	expect(page.locator("#tc-card-input")).to_be_focused()
	expect(page.locator(".tc-work")).to_be_hidden()
	login(page)
	expect(page.locator(".tc-session")).to_contain_text("Operator")
	expect(page.locator(".tc-station-code")).to_have_text("TR-004")
	expect(page.locator(".tc-session")).to_contain_text("2099")
	page.locator("#tc-scan-input").fill("SET-TEST")
	page.locator("#tc-scan-input").press("Enter")
	expect(page.locator(".tc-alert-reason")).to_contain_text("indicator lot")
	method, args, headers = next(row for row in auth_shell.requests if row[0].endswith("pack.scan"))
	assert args["token"].startswith("browser-private-")
	assert args["client_ts"] and headers["x-idempotency-key"]
	assert "browser-private-" not in json.dumps(headers)
	assert "browser-private-" not in page.content()
	assert page.evaluate("localStorage.length") == 0
	assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
	if page.locator(".tc-menu-btn").is_visible():  # A-92: PDA để dòng phiên trong menu
		page.locator(".tc-menu-btn").click()
	page.locator("[data-action='logout']").click()
	expect(page.locator(".tc-work")).to_be_hidden()
	expect(page.locator("#tc-card-input")).to_be_focused()
	assert page.evaluate("sessionStorage.length") == 0


def test_second_station_login_locks_old_kiosk_on_heartbeat(page, browser, auth_shell):
	auth_shell(page)
	login(page)
	other_context = browser.new_context()
	try:
		other = other_context.new_page()
		auth_shell(other, "TR-005")
		login(other)
		page.evaluate("frappe.tc_station.heartbeat()")
		expect(page.locator(".tc-work")).to_be_hidden()
		expect(page.locator(".tc-auth-result")).to_contain_text("Another station replaced")
		expect(page.locator("#tc-card-input")).to_be_focused()
		assert page.evaluate("sessionStorage.length") == 0
		expect(other.locator(".tc-work")).to_be_visible()
	finally:
		other_context.close()


@pytest.mark.parametrize("end", ["idle", "remove", "rescan", "expiry"])
def test_session_end_clears_sensitive_work_and_pending_dialog(page, auth_shell, end):
	auth_shell(page)
	login(page)
	page.evaluate("""() => {
		const s = frappe.tc_station;
		s.screen.ctx = {set:{set_id:'PRIVATE-SET'}};
		s.screen.pending = {raw:'PRIVATE-SET'};
		s.screen.dialog = document.createElement('div');
		s.screen.dialog.className = 'tc-modal-overlay';
		s.root.append(s.screen.dialog);
		s.result.innerHTML = 'PRIVATE-SET';
	}""")
	if end == "idle":
		page.evaluate("frappe.tc_station.lastActivity = Date.now()-600001; frappe.tc_station.checkSession()")
	elif end == "remove":
		page.evaluate("window.dispatchEvent(new Event('tc-card-removed'))")
	elif end == "rescan":
		page.locator("[data-action='rescan-card']").click()
	else:
		auth_shell.active.clear()
		page.evaluate("frappe.tc_station.heartbeat()")
	expect(page.locator(".tc-work")).to_be_hidden()
	expect(page.locator(".tc-modal-overlay")).to_have_count(0)
	assert "PRIVATE-SET" not in page.content()
	assert page.evaluate("frappe.tc_station.screen.pending === null && frappe.tc_station.screen.ctx === null")
	assert page.evaluate("sessionStorage.length") == 0


@pytest.mark.parametrize("viewport", [{"width": 1366, "height": 768}, {"width": 412, "height": 915}])
def test_indicator_lot_has_dedicated_form_and_restores_main_scan_focus(page, auth_shell, viewport):
	page.set_viewport_size(viewport)
	auth_shell(page)
	login(page)
	page.evaluate("""() => {
		const t = frappe.tc_station.screen;
		t.ctx = {set:{set_id:'SET',set_name:'Synthetic set',method:'Steam',status:'Processing',
			cycles_used:0,max_cycles:100},bom:[],maintenance:[],pack_types:[],
			ci:{classes:['5','6'],method:'Steam'}};
		t.show();
	}""")
	lot = page.locator("#tc-ci-input")
	expect(lot).to_be_visible()
	lot.fill("SYNTHETIC-LOT")
	lot.press("Enter")
	expect(page.locator("[data-region='ci'] .tc-t4-ok")).to_contain_text("SYNTHETIC-LOT")
	assert any(method.endswith("pack.resolve_ci") for method, _, _ in auth_shell.requests)
	assert not any(method.endswith("pack.scan") for method, _, _ in auth_shell.requests)
	expect(page.locator("#tc-scan-input")).to_be_focused()
	assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
	assert page.locator(".tc-ci-form button").bounding_box()["height"] >= 48


def test_tab_restore_validates_token_before_exposing_work(page, auth_shell):
	auth_shell(page)
	login(page)
	auth_shell(page)
	expect(page.locator(".tc-work")).to_be_visible()
	expect(page.locator(".tc-session")).to_contain_text("Restored operator")
	assert any(method.endswith("station.heartbeat") for method, _, _ in auth_shell.requests)
	auth_shell.active.clear()
	auth_shell(page)
	expect(page.locator(".tc-work")).to_be_hidden()
	expect(page.locator(".tc-auth-result")).to_contain_text("Session ended")


def test_card_rejection_displays_title_reason_action_inline(page, auth_shell):
	auth_shell(page)
	page.route(
		"**/api/method/tracecore.v1.station.login",
		lambda route: route.fulfill(
			status=403,
			content_type="application/json",
			body=json.dumps(
				{
					"message": {
						"ok": False,
						"error": {
							"code": "COMPETENCY_REQUIRED",
							"title": "Card rejected",
							"reason": "Competency expired",
							"action": "Ask R02 to review competency",
						},
					}
				}
			),
		),
	)
	page.locator("#tc-card-input").fill("SYNTHETIC-CARD")
	page.locator("#tc-card-input").press("Enter")
	alert = page.locator(".tc-auth-result .tc-alert-error")
	expect(alert).to_contain_text("Card rejected")
	expect(alert).to_contain_text("Competency expired")
	expect(alert).to_contain_text("Ask R02")
	expect(page.locator(".tc-work")).to_be_hidden()


def test_offline_card_login_stays_locked_and_can_login_after_reconnect(page, context, auth_shell):
	auth_shell(page)
	context.set_offline(True)
	expect(page.locator(".tc-offline-banner")).to_be_visible()
	expect(page.locator(".tc-auth-result")).to_contain_text("Card login needs the server")
	page.locator("#tc-card-input").fill("SYNTHETIC-CARD")
	page.locator("#tc-card-input").press("Enter")
	expect(page.locator(".tc-work")).to_be_hidden()
	context.set_offline(False)
	expect(page.locator(".tc-offline-banner")).to_be_hidden()
	login(page)
	context.set_offline(True)
	expect(page.locator(".tc-result")).to_have_attribute("data-state", "offline")
	expect(page.locator(".tc-result")).to_contain_text("Station offline")
	context.set_offline(False)
	expect(page.locator(".tc-result")).to_have_attribute("data-state", "empty")


def test_t4_transport_retry_preserves_timestamp_key_and_body_token(page, auth_shell):
	auth_shell(page)
	login(page)
	attempts = []

	def fail_once(route):
		attempts.append((route.request.post_data_json, route.request.headers))
		if len(attempts) == 1:
			route.abort()
		else:
			route.fallback()

	page.route("**/api/method/tracecore.v1.pack.scan", fail_once)
	page.locator("#tc-scan-input").fill("SET-TEST")
	page.locator("#tc-scan-input").press("Enter")
	expect(page.locator(".tc-result")).to_contain_text("No answer from the server")
	page.locator("[data-action='retry']").click()
	expect(page.locator(".tc-result")).to_contain_text("Invalid code")
	assert len(attempts) == 2
	assert attempts[0][0] == attempts[1][0]
	assert attempts[0][1]["x-idempotency-key"] == attempts[1][1]["x-idempotency-key"]


@pytest.mark.parametrize("active", [False, True])
def test_reader_card_scan_event_logs_in_and_replaces_current_session(page, auth_shell, active):
	auth_shell(page)
	if active:
		login(page)
	page.evaluate(
		"window.dispatchEvent(new CustomEvent('tc-card-scanned', {detail:{card_id:'SYNTHETIC-NEXT-CARD'}}))"
	)
	if active:
		page.wait_for_function(
			"frappe.tc_station.sessionVersion > 0 && frappe.tc_station.session && !frappe.tc_station.authBusy",
			timeout=5000,
		)
	expect(page.locator(".tc-work")).to_be_visible()
	logins = [args for method, args, _ in auth_shell.requests if method.endswith("station.login")]
	assert logins[-1]["card_id"] == "SYNTHETIC-NEXT-CARD"
	if active:
		logout_index = next(
			i for i, row in enumerate(auth_shell.requests) if row[0].endswith("station.logout")
		)
		login_index = next(
			i
			for i, row in enumerate(auth_shell.requests)
			if row[0].endswith("station.login") and row[1]["card_id"] == "SYNTHETIC-NEXT-CARD"
		)
		assert logout_index < login_index


def reader_scan(page, card):
	page.evaluate(
		"card => window.dispatchEvent(new CustomEvent('tc-card-scanned', {detail:{card_id:card}}))", card
	)


def test_reader_latest_scan_wins_while_first_login_is_pending(page, auth_shell):
	auth_shell(page)
	page.evaluate("""() => {
		const real = window.fetch;
		let first = true;
		window.fetch = (...args) => {
			if (String(args[0]).endsWith('station.login') && first) {
				first = false;
				return new Promise(resolve => window.releaseFirstLogin = () => resolve(real(...args)));
			}
			return real(...args);
		};
	}""")
	reader_scan(page, "CARD-A")
	page.wait_for_function("typeof releaseFirstLogin === 'function'")
	reader_scan(page, "CARD-B")
	page.evaluate("releaseFirstLogin()")
	expect(page.locator(".tc-session")).to_contain_text("Operator CARD-B")
	logins = [args["card_id"] for method, args, _ in auth_shell.requests if method.endswith("station.login")]
	assert logins == ["CARD-A", "CARD-B"]
	assert any(method.endswith("station.logout") for method, _, _ in auth_shell.requests)


DELAY_RESTORE = """() => {
	const real = window.fetch;
	window.fetch = (...args) => {
		if (String(args[0]).endsWith('station.heartbeat'))
			return new Promise(resolve => window.releaseRestore = reply => resolve(new Response(
				JSON.stringify({message:reply.body}), {status:reply.status, headers:{'Content-Type':'application/json'}})));
		return real(...args);
	};
}"""


def test_restore_candidate_is_not_active_before_server_validation(page, auth_shell):
	auth_shell(page)
	login(page)
	auth_shell(page, bootstrap=DELAY_RESTORE)
	page.wait_for_function("typeof releaseRestore === 'function'")
	assert page.evaluate("frappe.tc_station.session === null")
	expect(page.locator(".tc-work")).to_be_hidden()


@pytest.mark.parametrize("status", [200, 401])
def test_late_restore_cannot_overwrite_or_clear_new_card_session(page, auth_shell, status):
	auth_shell(page)
	login(page)
	auth_shell(page, bootstrap=DELAY_RESTORE)
	page.wait_for_function("typeof releaseRestore === 'function'")
	reader_scan(page, "CARD-B")
	expect(page.locator(".tc-session")).to_contain_text("Operator CARD-B")
	new_token = page.evaluate("frappe.tc_station.session.token")
	body = (
		{
			"ok": True,
			"employee": "OLD-EMP",
			"employee_name": "Old operator",
			"station": "TR-004",
			"expires_at": "2099-10-21 17:00:00",
			"roles": ["TC R04"],
		}
		if status == 200
		else {
			"ok": False,
			"error": {
				"code": "SESSION_INVALID",
				"title": "Old restore rejected",
				"reason": "Old token",
				"action": "Scan card",
			},
		}
	)
	page.evaluate("reply => releaseRestore(reply)", {"status": status, "body": body})
	page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
	expect(page.locator(".tc-work")).to_be_visible()
	expect(page.locator(".tc-session")).to_contain_text("Operator CARD-B")
	assert page.evaluate("frappe.tc_station.session.token") == new_token
	assert page.evaluate("sessionStorage.getItem(frappe.tc_station.storageKey())") == new_token


def test_hidden_page_ignores_reader_events(page, auth_shell):
	auth_shell(page)
	login(page)
	page.evaluate("frappe.pages.station.on_page_hide()")
	before = sum(method.endswith("station.login") for method, _, _ in auth_shell.requests)
	reader_scan(page, "HIDDEN-CARD")
	page.wait_for_function("!frappe.tc_station.authBusy")
	page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
	after = sum(method.endswith("station.login") for method, _, _ in auth_shell.requests)
	assert after == before
	assert page.evaluate("frappe.tc_station.session === null && frappe.tc_station.sessionTimer === null")


def test_replaced_page_disposes_old_reader_listeners_and_timer(page, auth_shell):
	auth_shell(page)
	page.evaluate("""() => {
		window.oldStation = frappe.tc_station;
		frappe.pages.station.on_page_load(document.querySelector('#wrapper'));
		frappe.pages.station.on_page_show();
	}""")
	reader_scan(page, "NEW-MOUNT-CARD")
	expect(page.locator(".tc-session")).to_contain_text("Operator NEW-MOUNT-CARD")
	logins = [args["card_id"] for method, args, _ in auth_shell.requests if method.endswith("station.login")]
	assert logins == ["NEW-MOUNT-CARD"]
	assert page.evaluate("oldStation.disposed && !oldStation.visible && oldStation.sessionTimer === null")


def test_roles_are_translated_on_login_restore_and_cleared_at_logout(page, auth_shell):
	auth_shell(page)
	login(page)
	expect(page.locator(".tc-session-roles")).to_have_text("Role: Translated packing role")
	auth_shell(page)
	expect(page.locator(".tc-session-roles")).to_have_text("Role: Translated packing role")
	page.locator("[data-action='logout']").click()
	expect(page.locator(".tc-session-roles")).to_have_text("")


@pytest.mark.parametrize("action", ["logout", "rescan-card"])
def test_keyboard_tab_can_reach_and_activate_session_controls(page, auth_shell, action):
	auth_shell(page)
	login(page)
	page.locator("#tc-scan-input").focus()
	page.keyboard.press("Shift+Tab")
	page.wait_for_timeout(200)  # exceed the previous 150ms forced-refocus timer
	expect(page.locator("[data-action='logout']")).to_be_focused()
	if action == "rescan-card":
		page.keyboard.press("Shift+Tab")
		page.wait_for_timeout(200)
		expect(page.locator("[data-action='rescan-card']")).to_be_focused()
	page.keyboard.press("Enter")
	expect(page.locator(".tc-work")).to_be_hidden()
	expect(page.locator("#tc-card-input")).to_be_focused()


def test_repeated_replacements_keep_the_original_pending_login_barrier(page, auth_shell):
	auth_shell(page)
	page.evaluate("""() => {
		const real = window.fetch;
		let first = true;
		window.fetch = (...args) => {
			if (String(args[0]).endsWith('station.login') && first) {
				first = false;
				return new Promise(resolve => window.releaseOriginalLogin = () => resolve(real(...args)));
			}
			return real(...args);
		};
	}""")
	reader_scan(page, "CARD-A")
	page.wait_for_function("typeof releaseOriginalLogin === 'function'")
	page.evaluate("""() => {
		window.retiredStations = [];
		for (let i = 0; i < 2; i++) {
			retiredStations.push(frappe.tc_station);
			frappe.pages.station.on_page_load(document.querySelector('#wrapper'));
			frappe.pages.station.on_page_show();
		}
	}""")
	reader_scan(page, "CARD-C")
	page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
	assert not any(method.endswith("station.login") for method, _, _ in auth_shell.requests)
	page.evaluate("releaseOriginalLogin()")
	expect(page.locator(".tc-session")).to_contain_text("Operator CARD-C")
	logins = [args["card_id"] for method, args, _ in auth_shell.requests if method.endswith("station.login")]
	assert logins == ["CARD-A", "CARD-C"]
	assert page.evaluate(
		"retiredStations.every(s => s.disposed && s.listeners.length === 0 && s.globalListeners.length === 0 && s.sessionTimer === null)"
	)
	page.evaluate("frappe.tc_station.heartbeat()")
	expect(page.locator(".tc-work")).to_be_visible()


def test_hiding_pending_restore_preserves_candidate_storage_and_ignores_its_late_denial(page, auth_shell):
	auth_shell(page)
	login(page)
	token = page.evaluate("frappe.tc_station.session.token")
	auth_shell(page, bootstrap=DELAY_RESTORE)
	page.wait_for_function("typeof releaseRestore === 'function'")
	page.evaluate("window.releaseOldRestore = releaseRestore; frappe.pages.station.on_page_hide()")
	assert page.evaluate("sessionStorage.getItem(frappe.tc_station.storageKey())") == token
	page.evaluate("frappe.pages.station.on_page_show()")
	page.wait_for_function("releaseRestore !== releaseOldRestore")
	page.evaluate(
		"releaseOldRestore({status:401,body:{ok:false,error:{code:'SESSION_INVALID',title:'Old response'}}})"
	)
	page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
	assert page.evaluate("sessionStorage.getItem(frappe.tc_station.storageKey())") == token
	assert page.evaluate("frappe.tc_station.session === null && frappe.tc_station.restoreCandidate !== null")
	page.evaluate(
		"releaseRestore({status:200,body:{ok:true,employee:'EMP-1',employee_name:'Restored operator',station:'TR-004',roles:['TC R04']}})"
	)
	expect(page.locator(".tc-session")).to_contain_text("Restored operator")


def test_card_removal_before_initial_restore_clears_and_revokes_saved_token(page, auth_shell):
	auth_shell(page)
	login(page)
	token = page.evaluate("frappe.tc_station.session.token")
	auth_shell(
		page,
		bootstrap="""() => {
		const real = window.fetch;
		let first = true;
		window.fetch = (...args) => {
			if (String(args[0]).endsWith('tracecore.v1.ping') && first) {
				first = false;
				return new Promise(resolve => window.releaseInitialPing = () => resolve(real(...args)));
			}
			return real(...args);
		};
	}""",
	)
	page.wait_for_function("typeof releaseInitialPing === 'function'")
	assert page.evaluate("frappe.tc_station.session === null && frappe.tc_station.restoreCandidate === null")
	page.evaluate("window.dispatchEvent(new Event('tc-card-removed'))")
	assert page.evaluate("sessionStorage.getItem(frappe.tc_station.storageKey())") is None
	page.evaluate("releaseInitialPing(); frappe.tc_station.handshake()")
	expect(page.locator(".tc-work")).to_be_hidden()
	assert any(
		method.endswith("station.logout") and args["token"] == token
		for method, args, _ in auth_shell.requests
	)
	assert "token" not in auth_shell.active


def test_card_removal_after_failed_restore_clears_and_revokes_preserved_token(page, auth_shell):
	auth_shell(page)
	login(page)
	token = page.evaluate("frappe.tc_station.session.token")
	auth_shell(
		page,
		bootstrap="""() => {
		const real = window.fetch;
		let first = true;
		window.fetch = (...args) => {
			if (String(args[0]).endsWith('station.heartbeat') && first) {
				first = false;
				return Promise.reject(new TypeError('Synthetic restore transport failure'));
			}
			return real(...args);
		};
	}""",
	)
	expect(page.locator(".tc-auth-result")).to_contain_text("Card login needs the server")
	assert page.evaluate("frappe.tc_station.session === null && frappe.tc_station.restoreCandidate === null")
	assert page.evaluate("sessionStorage.getItem(frappe.tc_station.storageKey())") == token
	page.evaluate("window.dispatchEvent(new Event('tc-card-removed'))")
	assert page.evaluate("sessionStorage.getItem(frappe.tc_station.storageKey())") is None
	page.evaluate("frappe.tc_station.handshake()")
	expect(page.locator(".tc-work")).to_be_hidden()
	assert any(
		method.endswith("station.logout") and args["token"] == token
		for method, args, _ in auth_shell.requests
	)
	assert "token" not in auth_shell.active


def test_offline_new_card_after_failed_restore_cannot_restore_previous_operator_on_reconnect(
	page, context, auth_shell
):
	auth_shell(page)
	login(page)
	token = page.evaluate("frappe.tc_station.session.token")
	auth_shell(
		page,
		bootstrap="""() => {
		const real = window.fetch;
		let first = true;
		window.fetch = (...args) => {
			if (String(args[0]).endsWith('station.heartbeat') && first) {
				first = false;
				return Promise.reject(new TypeError('Synthetic restore transport failure'));
			}
			return real(...args);
		};
	}""",
	)
	expect(page.locator(".tc-auth-result")).to_contain_text("Card login needs the server")
	assert page.evaluate("frappe.tc_station.session === null && frappe.tc_station.restoreCandidate === null")
	assert page.evaluate("sessionStorage.getItem(frappe.tc_station.storageKey())") == token
	context.set_offline(True)
	reader_scan(page, "OFFLINE-NEW-CARD")
	assert page.evaluate("sessionStorage.getItem(frappe.tc_station.storageKey())") is None
	page.wait_for_function("!frappe.tc_station.authBusy")
	expect(page.locator(".tc-work")).to_be_hidden()
	context.set_offline(False)
	page.evaluate("frappe.tc_station.handshake()")
	expect(page.locator(".tc-work")).to_be_hidden()
	assert page.evaluate("frappe.tc_station.session === null")
	assert page.evaluate("sessionStorage.getItem(frappe.tc_station.storageKey())") is None
	assert not any(
		method.endswith("station.login") and args["card_id"] == "OFFLINE-NEW-CARD"
		for method, args, _ in auth_shell.requests
	)
