"""Isolated browser checks using actual launcher assets and a mocked read-only RPC.

These checks complement, but do not replace, an installed-site integration check.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
JQUERY_RELATIVE = "apps/frappe/node_modules/jquery/dist/jquery.min.js"


def find_jquery():
	"""jQuery của Frappe trong bench: TC_JQUERY (đường dẫn file), BENCH_DIR, bench CI (~/frappe-bench) hoặc bench dev."""
	candidates = [Path(os.environ["TC_JQUERY"])] if os.environ.get("TC_JQUERY") else []
	benches = [os.environ.get("BENCH_DIR"), Path.home() / "frappe-bench", Path.home() / "tracecore-dev"]
	candidates += [Path(bench) / JQUERY_RELATIVE for bench in benches if bench]
	return next((path for path in candidates if path.is_file()), candidates[0])


JQUERY = find_jquery()
ASSETS = ROOT / "tracecore/ui/page/tracecore"


def mount(page, fail=False):
	page.route("http://launcher.test/", lambda route: route.fulfill(body="<html><body></body></html>"))
	page.goto("http://launcher.test/")
	page.set_content("<html><body><main id='launcher'></main></body></html>")
	page.add_style_tag(content=(ROOT / "tracecore/public/css/tokens.css").read_text())
	page.add_style_tag(content=(ASSETS / "tracecore.css").read_text())
	page.add_script_tag(content=JQUERY.read_text())
	page.evaluate(
		"""(fail) => {
		window.__ = text => text;
		window.frappe = {
			pages: {tracecore: {}}, get_route: () => ['tracecore'],
			ui: {make_app_page: () => ({main: document.querySelector('#launcher')})},
			call: async () => {
				if (fail) throw new Error('offline test');
				return {message: {
					management: [{doctype: 'Pack', route: '/app/pack'}], department: true,
					stations: [
						{name: 'TR-123', label: 'T2 Washing', step: 'T2', implemented: true},
						{name: 'TR-999', label: 'T1 Receiving', step: 'T1', implemented: false}
					]
				}};
			}
		};
	} """,
		fail,
	)
	page.add_script_tag(content=(ASSETS / "tracecore.js").read_text())
	page.evaluate("""() => {
		const wrapper = document.querySelector('#launcher');
		frappe.pages.tracecore.on_page_load(wrapper);
		frappe.pages.tracecore.on_page_show(wrapper);
	}""")


@pytest.mark.parametrize("viewport", [{"width": 1366, "height": 768}, {"width": 412, "height": 915}])
def test_launcher_cards_and_station_link(page, viewport):
	page.set_viewport_size(viewport)
	mount(page)
	expect(page.locator(".tc-launcher-card")).to_have_count(3)
	expect(page.locator("option[value='TR-999']")).to_be_disabled()
	expect(page.get_by_role("link", name="Pack", exact=True)).to_have_attribute("href", "/app/pack")
	assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
	preview = ROOT / ".pytest_cache" / "launcher-preview"
	preview.mkdir(parents=True, exist_ok=True)
	page.screenshot(path=str(preview / f"launcher-{viewport['width']}.png"), full_page=True)
	page.route("**/app/station?station=TR-123", lambda route: route.fulfill(body="Station destination"))
	page.get_by_role("button", name="Enter station").click()
	expect(page).to_have_url("http://launcher.test/app/station?station=TR-123")


def test_launcher_error_retry_and_offline(page):
	mount(page, fail=True)
	expect(page.get_by_role("alert")).to_contain_text("Cannot load workspaces")
	page.evaluate("frappe.call = async () => ({message: {management: [], stations: [], department: false}})")
	page.get_by_role("button", name="Try again").click()
	expect(page.get_by_role("button", name="Enter station")).to_be_disabled()
	page.context.set_offline(True)
	expect(page.get_by_role("status")).to_contain_text("Offline")
	page.context.set_offline(False)
	expect(page.locator(".tc-launcher-card")).to_have_count(3)


def test_home_and_sidebar_links_are_idempotent(page):
	page.set_content("""<div class='page-container'>
		<aside class='standard-sidebar-section' data-title='Public'><div item-name='Home'>Home</div></aside>
		<div class='layout-main-section'>Home workspace</div></div>""")
	page.add_script_tag(content=JQUERY.read_text())
	page.evaluate("""() => {
		window.__ = text => text;
		window.frappe = {
			user_roles: ['TC R03'], get_route: () => ['Workspaces', 'Home'],
			after_ajax: fn => fn(), router: {on: (event, fn) => window.onRoute = fn}
		};
	}""")
	page.add_script_tag(content=(ROOT / "tracecore/public/js/tc_launcher.js").read_text())
	expect(page.locator(".tc-home-launcher")).to_have_attribute("href", "/app/tracecore")
	expect(page.locator(".tc-sidebar-launcher a")).to_have_attribute("href", "/app/tracecore")
	page.evaluate("onRoute(); onRoute()")
	expect(page.locator(".tc-home-launcher")).to_have_count(1)
	expect(page.locator(".tc-sidebar-launcher")).to_have_count(1)
