"""RPC tracecore.v1.help.get (FEAT-013, FR-M9-15, A-55 D6): hướng dẫn của trạm, xem được cả trước khi quét thẻ."""

import frappe

from tracecore.tests.utils import IsolatedTestCase
from tracecore.ui import station_help
from tracecore.v1 import help as api


def _article(key, title):
	return frappe.get_doc(
		{
			"doctype": "Help Article",
			"title": title,
			"category": station_help.ensure_category(),
			"content": '<ol><li>One <img src="/files/one.png"></li><li>Two</li><li>Three</li></ol>',
			"published": 1,
			"tc_station_key": key,
		}
	).insert(ignore_permissions=True)


class TestHelpGet(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.delete("Help Article", {"tc_station_key": ["is", "set"]})
		self.addCleanup(frappe.set_user, "Administrator")

	def test_guest_reads_guide_of_station_step(self):
		_article("T4", "API guide T4")
		frappe.set_user("Guest")
		result = api.get("TR-004")
		self.assertTrue(result["ok"])
		self.assertEqual(result["key"], "T4")
		self.assertEqual(result["article"]["title"], "API guide T4")
		self.assertEqual(
			result["article"]["steps"][0], {"text": "One", "image": "/files/one.png"}
		)
		self.assertNotIn("content", result["article"])

	def test_no_guide_returns_empty_article(self):
		result = api.get("TR-004")
		self.assertEqual((result["ok"], result["key"], result["article"]), (True, "T4", None))

	def test_unknown_station_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			api.get("TR-DOES-NOT-EXIST")

	def test_get_only(self):
		self.assertIn("GET", frappe.allowed_http_methods_for_whitelisted_func[api.get])
		self.assertNotIn("POST", frappe.allowed_http_methods_for_whitelisted_func[api.get])
		self.assertIn(api.get, frappe.guest_methods)
