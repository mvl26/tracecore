"""Native Vue UI smoke tests against the real dev site and Frappe login/OTP."""

from conftest import desk_login
from playwright.sync_api import expect


def test_guest_sees_tracecore_login(page):
	page.goto("/tracecore")
	expect(page.get_by_role("heading", name="Đăng nhập", exact=True)).to_be_visible()
	expect(page.locator(".wordmark")).to_have_text("TRACECORE")
	expect(page.locator(".navbar")).to_have_count(0)


def test_role_navigation_and_instrument_form(page):
	desk_login(page, "TC_E2E_INSTR")
	page.goto("/tracecore")
	expect(page.get_by_role("heading", name="Không gian làm việc TraceCore")).to_be_visible()
	page.locator(".role-card").filter(has_text="Giám sát CSSD").click()
	expect(page.get_by_role("heading", name="Tổng quan · Giám sát CSSD")).to_be_visible()
	page.locator("nav .screen-button").filter(has_text="Danh mục dụng cụ").click()
	expect(page.get_by_role("heading", name="Danh mục dụng cụ", exact=True)).to_be_visible()
	expect(page.get_by_role("button", name="Thêm mới", exact=True)).to_be_visible()
	page.get_by_role("button", name="Thêm mới", exact=True).click()
	expect(page.get_by_role("dialog")).to_be_visible()
	expect(page.get_by_role("heading", name="Thêm dụng cụ", exact=True)).to_be_visible()
	expect(page.get_by_text("Phương pháp tương thích", exact=True)).to_be_visible()
	page.screenshot(path="/tmp/tracecore-admin-instrument.png", full_page=True)


def test_deep_link_and_unknown_role_are_denied(page):
	desk_login(page, "TC_E2E_INSTR")
	page.goto("/tracecore/R02/instruments")
	expect(page.get_by_role("heading", name="Danh mục dụng cụ", exact=True)).to_be_visible()
	page.reload()
	expect(page.get_by_role("heading", name="Danh mục dụng cụ", exact=True)).to_be_visible()
	page.goto("/tracecore/R01/overrides")
	expect(page.get_by_role("alert")).to_contain_text("Không có quyền mở không gian này")


def test_logout_clears_role_ui(page):
	desk_login(page, "TC_E2E_INSTR")
	page.goto("/tracecore")
	page.get_by_role("button", name="Đăng xuất", exact=True).click()
	expect(page.get_by_role("heading", name="Đăng nhập", exact=True)).to_be_visible()
	expect(page.locator("aside")).to_have_count(0)


def test_native_login_form_completes_frappe_otp(page):
	import pyotp
	from conftest import require_env

	page.goto("/tracecore")
	page.locator("#user").fill(require_env("TC_E2E_INSTR_USER"))
	page.locator("#password").fill(require_env("TC_E2E_INSTR_PASSWORD"))
	page.get_by_role("button", name="Tiếp tục", exact=True).click()
	expect(page.locator("#otp, .role-card").first).to_be_visible(timeout=15000)
	if page.locator("#otp").is_visible():
		expect(page.locator("#otp")).to_be_visible()
		page.locator("#otp").fill(pyotp.TOTP(require_env("TC_E2E_INSTR_OTP_SECRET")).now())
		page.get_by_role("button", name="Tiếp tục", exact=True).click()
	expect(page.get_by_role("heading", name="Không gian làm việc TraceCore")).to_be_visible(timeout=15000)


def test_home_does_not_stay_loading_after_leaving_pending_role(page):
	desk_login(page, "TC_E2E_INSTR")
	page.goto("/tracecore")
	expect(page.locator(".role-card")).to_be_visible()
	pending = []
	page.route("**/api/method/tracecore.v1.admin_ui.dashboard?*", lambda route: pending.append(route))
	page.locator(".role-card").filter(has_text="Giám sát CSSD").click()
	expect(page.get_by_text("Đang tải dữ liệu…", exact=True)).to_be_visible()
	page.get_by_role("button", name="Về trang tổng", exact=True).click()
	expect(page.locator(".role-card")).to_be_visible()
	for route in pending:
		route.fulfill(json={"message": {"counts": [], "attention": []}})
