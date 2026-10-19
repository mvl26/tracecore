"""E2E smoke cho kiosk /app/station (Playwright for Python, ADR-012).

Chuẩn bị site trước bằng ``scripts/e2e_prepare.sh <site>``; biến môi trường:
TC_BASE_URL, TC_E2E_USER, TC_E2E_PASSWORD, TC_E2E_SET_ID, TC_E2E_STATION.
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
	station = os.environ.get("TC_E2E_STATION", "TR-004")
	logged_in_page.goto(f"/app/station?station={station}")
	logged_in_page.locator(".tc-result[data-state='empty']").wait_for(timeout=30000)
	return logged_in_page


@pytest.fixture
def set_id():
	return require_env("TC_E2E_SET_ID")
