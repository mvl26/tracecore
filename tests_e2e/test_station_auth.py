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

	def open_shell(page, station="TR-004"):
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
				body = {"station": {"name": station, "label": "Packing", "step": "T4", "zone_type": "Clean"}}
			elif method.endswith("station.login"):
				serial += 1
				token = f"browser-private-{serial}"
				active["token"] = token
				body = {
					"ok": True,
					"session": {
						"token": token,
						"employee": "EMP-1",
						"employee_name": "Operator",
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
			window.__ = (s, args) => args ? s.replace(/\{(\d+)\}/g, (_, n) => args[n]) : s;
			window.frappe = {pages:{station:{}},csrf_token:'test',
				utils:{escape_html: value => String(value).replace(/[&<>\"']/g,
					c => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]))},
				render_template: () => template};
			window.$ = node => ({html: html => node.innerHTML = html});
		} """,
			template,
		)
		for path in ("tracecore/ui/page/station/station.js", "tracecore/public/js/station_t4.js"):
			page.add_script_tag(path=str(ROOT / path))
		for path in ("tracecore/public/css/tokens.css", "tracecore/ui/page/station/station.css"):
			page.add_style_tag(path=str(ROOT / path))
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
	expect(page.locator(".tc-session")).to_contain_text("TR-004")
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
		s.t4.ctx = {set:{set_id:'PRIVATE-SET'}};
		s.t4.pending = {raw:'PRIVATE-SET'};
		s.t4.dialog = document.createElement('div');
		s.t4.dialog.className = 'tc-modal-overlay';
		s.root.append(s.t4.dialog);
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
	assert page.evaluate("frappe.tc_station.t4.pending === null && frappe.tc_station.t4.ctx === null")
	assert page.evaluate("sessionStorage.length") == 0


@pytest.mark.parametrize("viewport", [{"width": 1366, "height": 768}, {"width": 412, "height": 915}])
def test_indicator_lot_has_dedicated_form_and_restores_main_scan_focus(page, auth_shell, viewport):
	page.set_viewport_size(viewport)
	auth_shell(page)
	login(page)
	page.evaluate("""() => {
		const t = frappe.tc_station.t4;
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
	expect(page.locator(".tc-session")).to_contain_text("EMP-1")
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
	expect(page.locator(".tc-result")).to_contain_text("Packing needs a network connection")
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
