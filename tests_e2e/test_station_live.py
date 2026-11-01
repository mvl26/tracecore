"""Live Frappe/MariaDB browser checks; only the physical printer agent is outside this scope.

Prepare the dev site with scripts/e2e_prepare.sh and export its private env file.
No station RPC is routed or mocked in this module. Idle advances the controller's
last-human-activity timestamp; server absolute/idle expiry has integration coverage.
"""

from datetime import datetime, timezone

from conftest import desk_login, require_env
from playwright.sync_api import expect


def heartbeat(page, token):
	return page.request.post(
		"/api/method/tracecore.v1.station.heartbeat",
		data={"token": token, "client_ts": datetime.now(timezone.utc).isoformat()},
		headers={"X-Frappe-CSRF-Token": page.evaluate("frappe.csrf_token")},
	)


def test_live_card_identity_t4_indicator_and_logout(t4_page, t4_demo):
	page = t4_page
	expect(page.locator(".tc-session-person")).to_have_text("TraceCore Demo")
	expect(page.locator(".tc-station-code")).to_have_text(require_env("TC_E2E_T4_STATION"))
	expect(page.locator(".tc-session-roles")).not_to_be_empty()
	token = page.evaluate("frappe.tc_station.session.token")
	assert heartbeat(page, token).json()["message"]["ok"]
	field = page.locator("#tc-scan-input")
	field.fill(t4_demo["set_plasma"])
	field.press("Enter")
	expect(page.locator(".tc-t4[data-view='ctx'] .tc-code").first).to_have_text(t4_demo["set_plasma"])
	indicator = page.locator("#tc-ci-input")
	indicator.fill(t4_demo["ci_plasma"])
	indicator.press("Enter")
	expect(page.locator("[data-region='ci'] .tc-t4-ok")).to_contain_text(t4_demo["ci_plasma"])
	page.locator("[data-action='logout']").click()
	expect(page.locator("#tc-card-input")).to_be_visible()
	expect(page.locator(".tc-work")).to_be_hidden()
	assert page.evaluate("frappe.tc_station.storedToken()") is None
	response = heartbeat(page, token)
	assert response.status == 401
	assert response.json()["message"]["error"]["code"] == "SESSION_INVALID"


def test_live_second_station_replaces_first_and_idle_revokes(t4_page, browser, browser_context_args):
	page = t4_page
	old_token = page.evaluate("frappe.tc_station.session.token")
	with browser.new_context(**browser_context_args) as context:
		second = context.new_page()
		desk_login(second, "TC_E2E_T4")
		station = require_env("TC_E2E_T4_SECOND_STATION")
		second.goto(f"/app/station?station={station}")
		second.locator("#tc-card-input").fill(require_env("TC_E2E_T4_CARD_ID"))
		second.locator("#tc-card-input").press("Enter")
		expect(second.locator(".tc-session-station")).to_have_text(station)
		assert heartbeat(page, old_token).json()["message"]["error"]["code"] == "SESSION_INVALID"
		page.evaluate("frappe.tc_station.heartbeat()")
		expect(page.locator("#tc-card-input")).to_be_visible()
		expect(page.locator(".tc-work")).to_be_hidden()
		new_token = second.evaluate("frappe.tc_station.session.token")
		assert heartbeat(second, new_token).json()["message"]["ok"]
		second.evaluate(
			"async () => { frappe.tc_station.lastActivity = Date.now() - 600001; await frappe.tc_station.checkSession(); }"
		)
		expect(second.locator("#tc-card-input")).to_be_visible()
		assert second.evaluate("frappe.tc_station.storedToken()") is None
		assert heartbeat(second, new_token).json()["message"]["error"]["code"] == "SESSION_INVALID"
