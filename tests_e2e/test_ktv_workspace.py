"""Live role workspace navigation and real read API; no simulated lifecycle completion."""

import re

from conftest import desk_login, require_env
from playwright.sync_api import expect


def test_ktv_station_navigation_and_real_reads(page):
	desk_login(page, "TC_E2E_T4")
	errors = []
	page.on("pageerror", lambda error: errors.append(str(error)))
	page.goto("/tracecore/R04/assembly")
	expect(page.get_by_role("heading", name="T3 · Kiểm tra \u2013 lắp ráp")).to_be_visible()
	expect(page.get_by_role("textbox", name="Set ID")).to_be_visible()
	page.get_by_role("textbox", name="Set ID").fill(require_env("TC_E2E_T4_SET_STEAM"))
	page.get_by_role("button", name="Quét bộ", exact=True).click()
	expect(page.get_by_role("heading", name="Ảnh bộ & danh sách dụng cụ")).to_be_visible()
	# ghi nhận T3 chạy ở kiosk thật: không có nút hoàn tất giả, có link sang trạm T3
	expect(page.get_by_role("button", name="Hoàn tất T3", exact=True)).to_have_count(0)
	kiosk = page.get_by_role("link", name="Mở trạm T3", exact=False).first
	expect(kiosk).to_have_attribute("href", re.compile(r"^/app/station\?station="))
	page.get_by_role("link", name="Mở bộ này tại T4").click()
	expect(page.get_by_role("heading", name="T4 · Đóng gói")).to_be_visible()
	expect(page.get_by_role("textbox", name="Set ID")).to_have_value(require_env("TC_E2E_T4_SET_STEAM"))
	expect(page.get_by_role("heading", name="Ảnh bộ & danh sách dụng cụ")).to_be_visible()
	page.screenshot(path="/tmp/tracecore-ktv-live-t4.png", full_page=True)
	page.get_by_role("navigation", name="Chức năng KTV").get_by_role("link", name="Tra cứu dụng cụ").click()
	expect(page.get_by_role("heading", name="Tra cứu dụng cụ")).to_be_visible()
	expect(page.get_by_role("button", name="Thêm mới", exact=True)).to_have_count(0)
	page.get_by_role("link", name="Đề nghị của tôi", exact=True).click()
	expect(page.get_by_text("Chỉ hiển thị đề nghị do tài khoản", exact=False)).to_be_visible()
	expect(page.get_by_role("alert")).to_have_count(0)
	assert errors == []


def test_ktv_mobile_has_no_page_overflow(page):
	desk_login(page, "TC_E2E_T4")
	page.set_viewport_size({"width": 412, "height": 915})
	page.goto("/tracecore/R04/assembly")
	expect(page.get_by_role("textbox", name="Set ID")).to_be_visible()
	assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
	page.screenshot(path="/tmp/tracecore-ktv-live-mobile.png", full_page=True)


def mock_station_workspace(page):
	"""UI contract fixture only: never substitutes for live lifecycle integration tests."""
	workspace = {
		"waiting": 0,
		"queue": [],
		"issues": [],
		"completed": 0,
		"card_ready": True,
		"assembly_ready": False,
		"stations": [{"name": "TR-004", "zone_station_name": "T4 Contract"}],
	}
	page.route(
		"**/api/method/tracecore.v1.ktv.workspace?*", lambda route: route.fulfill(json={"message": workspace})
	)
	context = {
		"set": {
			"name": "SET-CONTRACT",
			"set_type": "TYPE",
			"current_cycle_no": 2,
			"cycles_used": 1,
			"max_cycles": 10,
		},
		"bom": {"lines": [{"instrument": "I1", "instrument_name": "Kẹp", "qty": 1}], "bom_version": 1},
		"gates": [],
		"par": {"state": "ok"},
	}
	page.route(
		"**/api/method/tracecore.v1.ktv.context?*", lambda route: route.fulfill(json={"message": context})
	)
	return context


def test_t4_contract_requires_and_sends_lubricant_lot(page):
	desk_login(page, "TC_E2E_T4")
	context = mock_station_workspace(page)
	user = page.request.get("/api/method/frappe.auth.get_logged_user").json()["message"]
	page.route(
		"**/api/method/tracecore.v1.station.login",
		lambda route: route.fulfill(
			json={
				"message": {
					"ok": True,
					"session": {"token": "test-only", "user": user, "employee_name": "Contract KTV"},
				}
			}
		),
	)
	packing = {
		"bom": context["bom"]["lines"],
		"maintenance": [{"instrument": "I1", "maint_type": "Lubrication"}],
		"pack_types": [{"item": "POUCH", "expected_expiry": "2026-12-31"}],
	}
	page.route(
		"**/api/method/tracecore.v1.pack.scan",
		lambda route: route.fulfill(json={"message": {"ok": True, "kind": "context", "context": packing}}),
	)
	page.route(
		"**/api/method/tracecore.v1.pack.resolve_ci",
		lambda route: route.fulfill(json={"message": {"ok": True, "ci": {"batch": "CI-TEST"}}}),
	)
	page.route(
		"**/api/method/tracecore.v1.pack.generate_cycle_id",
		lambda route: route.fulfill(
			json={"message": {"ok": True, "pack": {"cycle_id": "CY-CONTRACT"}, "print": {"status": "Queued"}}}
		),
	)
	page.route(
		"**/api/method/tracecore.v1.station.logout",
		lambda route: route.fulfill(json={"message": {"ok": True}}),
	)
	page.goto("/tracecore/R04/packs")
	page.get_by_label("Thẻ nhân viên").fill("test-card")
	page.get_by_role("button", name="Mở phiên trạm").click()
	expect(page.get_by_text("Đã xác thực: Contract KTV")).to_be_visible()
	page.get_by_label("Set ID", exact=True).fill("SET-CONTRACT")
	page.get_by_role("button", name="Quét bộ", exact=True).click()
	page.get_by_label("Đã kiểm I1", exact=True).check()
	page.get_by_label("Loại gói").select_option("POUCH")
	page.get_by_label("Lô chỉ thị", exact=True).fill("CI-TEST")
	page.get_by_role("button", name="Kiểm tra lô", exact=True).click()
	page.get_by_role("checkbox", name="Đã bảo dưỡng I1 theo hướng dẫn").check()
	complete = page.get_by_role("button", name="Hoàn tất đóng gói & tạo nhãn")
	expect(complete).to_be_disabled()
	page.get_by_label("Lô dầu I1", exact=True).fill("OIL-LOT-TEST")
	expect(complete).to_be_enabled()
	with page.expect_request("**/api/method/tracecore.v1.pack.generate_cycle_id") as submitted:
		complete.click()
	assert submitted.value.post_data_json["maint_actions"] == [
		{"instrument": "I1", "action": "Done", "oil_batch": "OIL-LOT-TEST"}
	]
	expect(page.get_by_text("CY-CONTRACT", exact=True)).to_be_visible()


def test_stale_station_login_is_discarded_after_switching_step(page):
	desk_login(page, "TC_E2E_T4")
	mock_station_workspace(page)
	pending = []
	page.route("**/api/method/tracecore.v1.station.login", lambda route: pending.append(route))
	page.route(
		"**/api/method/tracecore.v1.station.logout",
		lambda route: route.fulfill(json={"message": {"ok": True}}),
	)
	page.goto("/tracecore/R04/assembly")
	page.get_by_label("Thẻ nhân viên").fill("test-card")
	with page.expect_request("**/api/method/tracecore.v1.station.login"):
		page.get_by_role("button", name="Mở phiên trạm").click()
	page.get_by_role("navigation", name="Chức năng KTV").get_by_role("link", name="T4 · Đóng gói").click()
	expect(page.get_by_role("heading", name="T4 · Đóng gói")).to_be_visible()
	with page.expect_request("**/api/method/tracecore.v1.station.logout") as discarded:
		pending[0].fulfill(
			json={
				"message": {
					"ok": True,
					"session": {"token": "stale-test", "user": "old", "employee_name": "Old"},
				}
			}
		)
	assert discarded.value.post_data_json["token"] == "stale-test"
	expect(page.get_by_role("button", name="Mở phiên trạm")).to_be_visible()
	expect(page.get_by_text("Đã xác thực: Old")).to_have_count(0)


def test_offline_locks_station_and_explains_recovery(page, context):
	desk_login(page, "TC_E2E_T4")
	page.goto("/tracecore/R04/assembly")
	expect(page.get_by_role("textbox", name="Set ID")).to_be_visible()
	context.set_offline(True)
	expect(page.get_by_role("alert")).to_contain_text("Mất kết nối")
	expect(page.get_by_text("● Chế độ xem", exact=True)).to_be_visible()
	context.set_offline(False)
	expect(page.get_by_role("alert")).to_have_count(0)
