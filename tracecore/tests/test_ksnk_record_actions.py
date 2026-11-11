"""TcKsnk.recordActions — hàng thao tác dùng chung của khối bản ghi KSNK (A-131): luôn đủ thao tác theo
trạng thái và quyền, không bao giờ chỉ còn chữ."""

from frappe.tests.utils import FrappeTestCase

from tracecore.tests.js_harness import run_js
from tracecore.tests.test_ksnk_page import SHELL


class TestRecordActions(FrappeTestCase):
	def actions(self, opts):
		script = f"emit({{html: TcKsnk.recordActions({opts})}});"
		out = run_js(self, [SHELL], [["TcKsnk"]], script)
		return out["html"]

	def test_draft_writer_opens_and_prints(self):
		html = self.actions(
			'{doctype: "IC Committee", name: "HD-1", docstatus: 0, can_write: true, can_create: true, create_label: "New"}'
		)
		self.assertIn('href="/app/ic-committee/HD-1"', html)
		self.assertIn(">Open form<", html)
		self.assertIn("/app/ic-committee/new", html)
		self.assertIn("printview", html)

	def test_submitted_writer_can_cancel_or_amend_and_create(self):
		html = self.actions(
			'{doctype: "IC Committee", name: "HD-1", docstatus: 1, can_write: true, can_create: true}'
		)
		self.assertIn("Open form to cancel or amend", html)
		self.assertIn("/app/ic-committee/new", html)

	def test_cancelled_offers_amend_without_print(self):
		html = self.actions('{doctype: "IC Committee", name: "HD-1", docstatus: 2, can_write: true}')
		self.assertIn("Open form to amend", html)
		self.assertNotIn("printview", html)

	def test_read_only_sees_view_and_print_only(self):
		html = self.actions(
			'{doctype: "IC Committee", name: "HD-1", docstatus: 1, can_write: false, can_create: false}'
		)
		self.assertIn(">View form<", html)
		self.assertIn("printview", html)
		self.assertNotIn("/new", html)
		self.assertNotIn("cancel or amend", html)

	def test_no_record_only_create(self):
		html = self.actions(
			'{doctype: "IC Committee", name: null, can_write: true, can_create: true, create_label: "Create committee"}'
		)
		self.assertIn("Create committee", html)
		self.assertNotIn("printview", html)
		self.assertNotIn("Open form", html)


class TestButtonBorders(FrappeTestCase):
	def test_css_gives_default_buttons_a_token_border(self):
		import os
		import re

		import frappe

		path = os.path.join(frappe.get_app_path("tracecore"), "ui/page/tc_ksnk/tc_ksnk.css")
		css = re.sub(r"/\*.*?\*/", "", open(path, encoding="utf8").read(), flags=re.DOTALL)
		rule = re.search(r"\.tc-ksnk .btn.btn-default[^{]*\{([^}]*)\}", css)
		self.assertIsNotNone(rule)
		body = rule.group(1)
		self.assertIn("border: var(--tc-bw-hair) solid var(--tc-border-input)", body)
		self.assertIn("background: var(--tc-card)", body)

	def test_scr47_actions_render_as_buttons(self):
		import os

		import frappe

		path = os.path.join(frappe.get_app_path("tracecore"), "public/js/ksnk/scr_47_co_cau.js")
		src = open(path, encoding="utf8").read()
		for href in ("/app/ic-committee/new", "/app/ic-network-member/new"):
			for line in src.splitlines():
				if f'<a href="{href}"' in line:
					self.fail(f"link chữ không viền: {line.strip()}")
