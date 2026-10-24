"""Authenticated website entry points for the independent React Home."""

from importlib import import_module
from pathlib import Path
from unittest.mock import patch

import frappe
from bs4 import BeautifulSoup
from frappe.tests.utils import FrappeTestCase
from frappe.utils import set_request
from frappe.website.path_resolver import resolve_path
from frappe.website.serve import get_response


class TestHomePage(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, frappe.session.user)
		frappe.set_user("Administrator")

	def response(self, path="/tracecore"):
		set_request(method="GET", path=path)
		return get_response()

	def test_tracecore_home_is_served_without_desk_shell(self):
		response = self.response()
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.mimetype, "text/html")
		body = response.get_data(as_text=True)
		self.assertIn('<div id="tracecore-root"></div>', body)
		self.assertTrue(body.lstrip().lower().startswith("<!doctype html>"))
		shell = BeautifulSoup(body, "html.parser")
		self.assertEqual(len(shell.select("#tracecore-root")), 1)
		self.assertEqual(len(shell.find_all("html")), 1)
		self.assertEqual(len(shell.find_all("head")), 1)
		self.assertEqual(len(shell.find_all("body")), 1)
		self.assertFalse(shell.select("nav, footer, .navbar, .page-content-wrapper, .layout-main"))
		for marker in ("desk.bundle", "frappe-web.bundle", "frappe.boot", 'id="body"', "/app/"):
			self.assertNotIn(marker, body)

	def test_tracecore_deep_route_uses_same_shell(self):
		root = self.response().get_data(as_text=True)
		for path in ("/tracecore/home", "/tracecore/search", "/tracecore/station/T4"):
			with self.subTest(path=path):
				self.assertEqual(resolve_path(path.strip("/")), "tracecore")
				response = self.response(path)
				self.assertEqual(response.status_code, 200)
				self.assertEqual(response.get_data(as_text=True), root)

	def test_guest_is_redirected_to_login_with_tracecore_return_route(self):
		frappe.set_user("Guest")
		for path in ("/tracecore", "/tracecore/station/T4"):
			with self.subTest(path=path):
				response = self.response(path)
				self.assertEqual(response.status_code, 302)
				self.assertEqual(response.headers["Location"], "/login?redirect-to=/tracecore")
				self.assertNotIn("tracecore-root", response.get_data(as_text=True))

	def test_home_shell_references_built_assets(self):
		shell = BeautifulSoup(self.response().get_data(as_text=True), "html.parser")
		self.assertEqual(
			[(tag.get("src"), tag.get("type")) for tag in shell.find_all("script")],
			[("/assets/tracecore/home/home.js", "module")],
		)
		self.assertEqual(
			[tag["href"] for tag in shell.select('link[rel="stylesheet"]')],
			["/assets/tracecore/home/home.css"],
		)
		for asset in ("home.js", "home.css"):
			self.assertTrue(Path(frappe.get_app_path("tracecore", "public", "home", asset)).is_file())
		# Vite already incorporates the generated design tokens into the Home stylesheet.
		css = Path(frappe.get_app_path("tracecore", "public", "home", "home.css")).read_text()
		self.assertIn("--tc-primary:", css)

	def test_route_rules_do_not_capture_api_or_assets(self):
		self.assertEqual(
			frappe.get_hooks("website_route_rules", app_name="tracecore"),
			[
				{"from_route": "/tracecore", "to_route": "tracecore"},
				{"from_route": "/tracecore/<path:app_path>", "to_route": "tracecore"},
			],
		)
		for path in (
			"api/method/tracecore.v1.home.context",
			"assets/tracecore/home/home.js",
			"tracecore-other",
		):
			with self.subTest(path=path):
				self.assertEqual(resolve_path(path), path)
		# Desk already owns its own catch-all route in Frappe.
		self.assertEqual(resolve_path("app/station"), "app")

	def test_controller_only_bootstraps_language_and_csrf(self):
		controller = import_module("tracecore.www.tracecore")
		self.assertEqual(controller.no_cache, 1)
		with patch("frappe.sessions.get", side_effect=AssertionError("Desk boot must not be loaded")):
			context = frappe._dict()
			controller.get_context(context)
		self.assertEqual(set(context), {"lang", "csrf_token"})
		self.assertEqual(context.lang, frappe.local.lang)
		self.assertTrue(context.csrf_token)
		self.assertEqual(context.csrf_token, frappe.sessions.get_csrf_token())

	def test_shell_exposes_nonempty_session_csrf_token(self):
		shell = BeautifulSoup(self.response().get_data(as_text=True), "html.parser")
		tokens = shell.select('meta[name="csrf-token"]')
		self.assertEqual(len(tokens), 1)
		self.assertTrue(tokens[0]["content"])
		self.assertEqual(tokens[0]["content"], frappe.sessions.get_csrf_token())
		self.assertEqual(shell.html["lang"], frappe.local.lang)

	def test_boot_values_are_escaped_in_html_attributes(self):
		context = {"lang": 'vi" onload="unexpected', "csrf_token": '"><script>unexpected</script>'}
		body = frappe.render_template("www/tracecore.html", context)
		shell = BeautifulSoup(body, "html.parser")
		self.assertEqual(shell.html["lang"], context["lang"])
		self.assertNotIn("onload", shell.html.attrs)
		self.assertEqual(shell.select_one('meta[name="csrf-token"]')["content"], context["csrf_token"])
		self.assertEqual(len(shell.find_all("script")), 1)
