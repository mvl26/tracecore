"""Home độc lập: session/OTP thật, quyền server và shell desktop/PDA.

Chạy scripts/e2e_prepare.sh tracecore-dev.local trước; xem README.md.
TC_E2E_HOME_MANAGER_USER/PASSWORD/OTP_SECRET là fixture tùy chọn cho
System Manager hoặc Administrator; không tự tạo hay nâng quyền tài khoản.
"""

import re
import time
from urllib.parse import urlsplit

import pytest
from conftest import PDA_VIEWPORT, desk_login, require_env
from playwright.sync_api import expect

HOME_API = "/api/method/tracecore.v1.home.context"
LOGIN_BUTTON = re.compile(r"^(Log in|Login|Đăng nhập)$", re.IGNORECASE)


def home_context(page):
	response = page.request.get(HOME_API)
	assert response.ok, f"Home context returned HTTP {response.status}"
	return response.json()["message"]


def assert_home_shell(page):
	expect(page.get_by_role("main")).to_be_visible()
	expect(page.get_by_role("heading", level=1)).to_contain_text("Xin chào,")
	expect(page.get_by_role("heading", name="Cần chú ý", exact=True)).to_be_visible()
	# Frappe's own stable shell markers must not be mounted on the website route.
	expect(page.locator(".desk-sidebar, .layout-side-section, .navbar, #navbar-breadcrumbs")).to_have_count(0)
	assert page.evaluate("typeof window.frappe") == "undefined"


@pytest.fixture
def operator_home(logged_in_page):
	page = logged_in_page
	page.goto("/tracecore")
	assert_home_shell(page)
	return page


def test_interactive_login_redirects_to_tracecore_home(page):
	user = require_env("TC_E2E_USER")
	password = require_env("TC_E2E_PASSWORD")
	page.goto("/login")  # No redirect-to: prove the server's default landing route.
	page.get_by_role("textbox", name=re.compile(r"Email|E-mail|Tên đăng nhập", re.IGNORECASE)).fill(user)
	page.get_by_label(re.compile(r"^(Password|Mật khẩu)$", re.IGNORECASE)).fill(password)
	with page.expect_response(lambda response: urlsplit(response.url).path == "/login" and response.request.method == "POST") as pending:
		page.get_by_role("button", name=LOGIN_BUTTON).click()
	response = pending.value
	assert response.ok, f"Interactive login returned HTTP {response.status}"
	verify = page.get_by_role("button", name=re.compile(r"^(Verify|Xác minh|Xác thực)$", re.IGNORECASE))
	verify.or_(page.get_by_role("heading", level=1, name=re.compile("Xin chào,"))).wait_for(timeout=30000)
	if verify.is_visible():
		import pyotp

		totp = pyotp.TOTP(require_env("TC_E2E_OTP_SECRET"))
		# Avoid submitting a code whose native 30-second verification window is about to end.
		remaining = totp.interval - time.time() % totp.interval
		if remaining < 5:
			time.sleep(remaining + 0.1)
		# Native Frappe's OTP input has no label; it is the only visible textbox at this step.
		page.get_by_role("textbox").fill(totp.now())
		with page.expect_response(lambda response: urlsplit(response.url).path == "/login" and response.request.method == "POST") as pending:
			page.get_by_role("button", name=re.compile(r"^(Verify|Xác minh|Xác thực)$", re.IGNORECASE)).click()
		assert pending.value.ok, f"OTP verification returned HTTP {pending.value.status}"
	expect(page).to_have_url(re.compile(r"/tracecore/?$"), timeout=30000)
	assert_home_shell(page)
	assert home_context(page)["user"]["name"] == user


def test_operational_user_opens_authorized_shortcut(page):
	# The prepared TC R02 account has real Set Unit read permission.
	desk_login(page, "TC_E2E_INSTR")
	payload = home_context(page)
	assert "TC R02" in payload["user"]["roles"]
	assert "set-units" in payload["capabilities"]
	shortcut = next(item for item in payload["navigation"] if item["route_key"] == "set-units")
	page.goto("/tracecore")
	assert_home_shell(page)
	page.get_by_role("navigation", name="Điều hướng chính").get_by_role("link", name=shortcut["label"], exact=True).click()
	expect(page).to_have_url(re.compile(r"/app/set-unit(?:[/?#].*)?$"), timeout=30000)
	expect(page.get_by_role("heading", name="Bộ dụng cụ", exact=True)).to_be_visible(timeout=30000)


def test_non_manager_cannot_see_frappe_admin(operator_home):
	payload = home_context(operator_home)
	assert payload["user"]["name"] != "Administrator"
	assert "System Manager" not in payload["user"]["roles"]
	assert "frappe-admin" not in payload["capabilities"]
	expect(operator_home.get_by_role("link", name=re.compile("Frappe Admin"))).to_have_count(0)


def test_manager_can_see_and_open_frappe_admin(page):
	desk_login(page, "TC_E2E_HOME_MANAGER")
	payload = home_context(page)
	assert payload["user"]["name"] == "Administrator" or "System Manager" in payload["user"]["roles"]
	assert "frappe-admin" in payload["capabilities"]
	page.goto("/tracecore")
	assert_home_shell(page)
	page.get_by_role("navigation", name="Điều hướng chính").get_by_role("link", name="Frappe Admin", exact=True).click()
	expect(page).to_have_url(re.compile(r"/app(?:[/?#].*)?$"), timeout=30000)
	expect(page.locator(".navbar")).to_be_visible(timeout=30000)


def test_home_is_responsive_with_explicit_pda_menu(operator_home):
	page = operator_home
	page.set_viewport_size(PDA_VIEWPORT)
	navigation = page.get_by_role("navigation", name="Điều hướng chính")
	expect(navigation).to_be_hidden()
	menu = page.get_by_role("button", name="Mở menu", exact=True)
	expect(menu).to_be_visible()
	expect(menu).to_have_attribute("aria-expanded", "false")
	menu.click()
	expect(navigation).to_be_visible()
	expect(page.get_by_role("button", name="Đóng menu", exact=True)).to_have_attribute("aria-expanded", "true")
	page.keyboard.press("Escape")
	expect(navigation).to_be_hidden()
	expect(menu).to_be_focused()
	assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
	assert_home_shell(page)


@pytest.mark.parametrize("route", ["/tracecore", "/tracecore/home", "/tracecore/search"])
def test_direct_route_refresh_keeps_application_shell(logged_in_page, route):
	page = logged_in_page
	page.goto(route)
	assert_home_shell(page)
	page.reload()
	expect(page).to_have_url(re.compile(re.escape(route) + r"/?$"))
	assert_home_shell(page)


def test_logout_reaches_login_and_removes_business_actions(operator_home):
	page = operator_home
	shortcut_labels = [item["label"] for item in home_context(page)["navigation"]]
	page.get_by_role("button", name="Đăng xuất", exact=True).click()
	expect(page).to_have_url(re.compile(r"/login(?:[?#].*)?$"), timeout=30000)
	expect(page.get_by_role("button", name=LOGIN_BUTTON)).to_be_visible()
	for label in shortcut_labels:
		expect(page.get_by_role("link", name=label, exact=True)).to_have_count(0)
	assert page.request.get(HOME_API).status in (401, 403)
	page.goto("/tracecore")
	expect(page).to_have_url(re.compile(r"/login\?redirect-to=.*tracecore(?:#.*)?$"))
	expect(page.get_by_role("navigation", name="Điều hướng chính")).to_have_count(0)
