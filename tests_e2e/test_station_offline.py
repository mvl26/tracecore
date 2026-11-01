"""E2E trạm T4 mất mạng (FEAT-009, FR-M2-07.11, NFR-AVAIL-02; kiosk 1366x768).

Chuẩn bị: ``scripts/e2e_prepare.sh <site>`` ngay trước khi chạy; dùng hai bộ hấp riêng ``set_offline_1/2`` của
``devdata.ensure_t4_demo`` (bị tiêu thụ khi đóng gói), không đụng bộ của ``test_station_t4.py``. Mạng tắt bằng
``context.set_offline(True)``.
"""

import re

from playwright.sync_api import expect
from test_station_t4 import SCAN_INPUT, mock_agent, scan, scan_indicator, scan_set_and_wait_context

OFFLINE_CYCLE = re.compile(r"^CY-\d{6}-T\d{3}-\d{4}$")


def wait_offline_data(page):
	"""Snapshot T4 (bộ sẵn sàng, lô chỉ thị, dải mã) đã tải vào trang sau đăng nhập thẻ."""
	page.wait_for_function(
		"() => frappe.tc_station && frappe.tc_station.offlineData"
		" && frappe.tc_station.offlineData.function === 'PACK'"
		" && (frappe.tc_station.offlineData.ranges || []).length > 0",
		timeout=30000,
	)


def test_t4_offline_pack_then_sync(t4_page, t4_demo):
	page = t4_page
	sent = mock_agent(page)
	wait_offline_data(page)

	page.context.set_offline(True)
	expect(page.locator(".tc-offline-banner")).to_be_visible()

	# quét bộ khi mất mạng: ngữ cảnh lấy từ snapshot, đóng gói không cần mạng
	scan_set_and_wait_context(page, t4_demo["set_offline_1"])
	expect(page.locator(".tc-missing")).not_to_contain_text("kết nối mạng")
	confirm_all = page.locator("[data-action='confirm-all']")
	expect(confirm_all).to_be_enabled(timeout=20000)  # ảnh không tải được khi offline vẫn tính là xong
	confirm_all.click()
	scan_indicator(page, t4_demo["ci_steam"])
	expect(page.locator("[data-region='ci'] .tc-t4-ok")).to_contain_text(t4_demo["ci_steam"])
	page.locator("[data-action='confirm-pack']").click()

	cycle = page.locator(".tc-cycle")
	expect(cycle).to_have_text(OFFLINE_CYCLE, timeout=15000)
	code = cycle.inner_text()
	expect(page.locator(".tc-t4-done")).to_contain_text("Nhãn in khi có mạng")
	expect(page.locator("[data-action='reprint']")).to_have_count(0)  # gói chưa lên server
	sync_bar = page.locator(".tc-sync-bar")
	expect(sync_bar).to_contain_text("1 giao dịch chờ")
	assert sent == []  # chưa in khi chưa có mạng

	# quét lại đúng bộ đó khi vẫn offline: không cho đóng gói lần hai
	scan(page, t4_demo["set_offline_1"])
	expect(page.locator(".tc-alert-error")).to_contain_text("đã đóng gói khi ngoại tuyến")

	# có mạng: tự phát lại theo client_ts, server nhận đúng mã offline và tạo nhãn
	page.context.set_offline(False)
	page.evaluate("window.dispatchEvent(new Event('online'))")
	expect(sync_bar).to_contain_text("In 1 nhãn chờ", timeout=30000)  # A-107: đồng bộ xong có nút in nhãn chờ
	# tra gói trên server qua RPC của trạm (phiên thẻ + CSRF như kiosk)
	body = page.evaluate(
		"""(code) => frappe.tc_station.rpc(
			"tracecore.v1.pack.scan",
			{raw: code, station: frappe.tc_station.station, client_ts: clientTs()},
			uuid4()
		)""",
		code,
	)
	assert body["kind"] == "pack" and body["pack"]["cycle_id"] == code, body
	assert body["pack"]["set_id"] == t4_demo["set_offline_1"], body  # gói của đúng bộ vừa đóng offline
	# A-107: nhãn chỉ ra khi bấm nút, không tự gửi sang Station Agent
	page.wait_for_timeout(1000)
	assert sent == [], sent
	expect(page.locator(".tc-sync-bar")).not_to_contain_text("xung đột")


def test_t4_offline_entry_survives_proxy_error(t4_page, t4_demo):
	"""Mã 4xx không do TraceCore trả (proxy 408, captive portal) không được làm mất giao dịch chờ (review C1)."""
	page = t4_page
	mock_agent(page)
	wait_offline_data(page)
	page.context.set_offline(True)
	scan_set_and_wait_context(page, t4_demo["set_offline_2"])
	confirm_all = page.locator("[data-action='confirm-all']")
	expect(confirm_all).to_be_enabled(timeout=20000)
	confirm_all.click()
	scan_indicator(page, t4_demo["ci_steam"])
	page.locator("[data-action='confirm-pack']").click()
	expect(page.locator(".tc-cycle")).to_have_text(OFFLINE_CYCLE, timeout=15000)
	sync_bar = page.locator(".tc-sync-bar")
	expect(sync_bar).to_contain_text("1 giao dịch chờ")

	timeouts = []

	def proxy_timeout(route):
		timeouts.append(route.request.url)
		route.fulfill(status=408, content_type="text/html", body="<html>Request Timeout</html>")

	page.route("**/api/method/tracecore.v1.pack.generate_cycle_id", proxy_timeout)
	page.context.set_offline(False)
	page.evaluate("window.dispatchEvent(new Event('online'))")
	page.wait_for_function("() => tcSync.running === null && tcSync.state.error", timeout=15000)
	assert timeouts, "phát lại chưa chạy"
	expect(sync_bar).to_contain_text("1 giao dịch chờ")  # mục vẫn còn

	page.unroute("**/api/method/tracecore.v1.pack.generate_cycle_id")
	page.evaluate("tcSync.replay()")
	expect(sync_bar).to_contain_text("In 1 nhãn chờ", timeout=30000)
