"""E2E smoke cho kiosk /app/station (Playwright for Python, ADR-012).

Chuẩn bị site trước bằng ``scripts/e2e_prepare.sh <site>``; biến môi trường:
TC_BASE_URL, TC_E2E_USER, TC_E2E_PASSWORD, TC_E2E_SET_ID, TC_E2E_STATION (smoke FEAT-001, trạm không phải T4)
và TC_E2E_T4_* (test_station_t4.py; xem scripts/e2e_prepare.sh).
"""

import os

import pytest

BASE_URL = os.environ.get("TC_BASE_URL", "http://127.0.0.1:8000")
KIOSK_VIEWPORT = {"width": 1366, "height": 768}


def require_env(name):
	value = os.environ.get(name)
	if not value:
		pytest.skip(f"{name} is not set - run scripts/e2e_prepare.sh first")
	return value


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
	return {**browser_context_args, "viewport": KIOSK_VIEWPORT, "base_url": BASE_URL}


@pytest.fixture
def logged_in_page(page):
	response = page.request.post(
		"/api/method/login",
		form={"usr": require_env("TC_E2E_USER"), "pwd": require_env("TC_E2E_PASSWORD")},
	)
	assert response.ok, response.text()
	return page


@pytest.fixture
def station_page(logged_in_page):
	station = os.environ.get("TC_E2E_STATION", "TR-003")
	card = require_env("TC_E2E_CARD_ID")
	logged_in_page.goto(f"/app/station?station={station}")
	logged_in_page.locator("#tc-card-input").fill(card)
	logged_in_page.locator("#tc-card-input").press("Enter")
	logged_in_page.locator(".tc-result[data-state='empty']").wait_for(timeout=30000)
	return logged_in_page


@pytest.fixture
def set_id():
	return require_env("TC_E2E_SET_ID")


# --- T4 (SCR-08 đóng gói): user trạm TR-004 và dữ liệu demo `devdata.ensure_t4_demo` ---


@pytest.fixture
def t4_demo():
	"""Mã demo T4 từ scripts/e2e_prepare.sh (TC_E2E_T4_SET_STEAM, ...)."""
	keys = (
		"set_steam",
		"set_maint",
		"set_plasma",
		"set_gate_fail",
		"ci_steam",
		"ci_plasma",
		"roll_steam",
		"roll_plasma",
	)
	return {key: require_env(f"TC_E2E_T4_{key.upper()}") for key in keys}


@pytest.fixture
def t4_page(page):
	card = require_env("TC_E2E_T4_CARD_ID")
	response = page.request.post(
		"/api/method/login",
		form={"usr": require_env("TC_E2E_T4_USER"), "pwd": require_env("TC_E2E_T4_PASSWORD")},
	)
	assert response.ok, response.text()
	station = os.environ.get("TC_E2E_T4_STATION", "TR-004")
	page.goto(f"/app/station?station={station}")
	page.locator("#tc-card-input").fill(card)
	page.locator("#tc-card-input").press("Enter")
	page.locator(".tc-result[data-state='empty']").wait_for(timeout=30000)
	return page


# --- Desk cấu hình (SCR-33, FEAT-002): user TC R10, viewport WEB 1366x768 ---


@pytest.fixture
def r10_page(page):
	response = page.request.post(
		"/api/method/login",
		form={"usr": require_env("TC_E2E_R10_USER"), "pwd": require_env("TC_E2E_R10_PASSWORD")},
	)
	assert response.ok, response.text()
	return page
