"""RPC chỉ đọc tracecore.v1.costing.rate_at (FEAT-045, FR-M7-03.1, API-M7-01; A-48 D6)."""

import frappe

from tracecore.tests.factories import make_cost_rate_version, make_item, make_user, norm_line, rate_line
from tracecore.tests.utils import IsolatedTestCase, bru
from tracecore.v1 import costing as api
from tracecore.v1._common import BadRequestError

test_ignore = ["Item", "User"]


@bru("BRU-CST-002")
class TestRateAt(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		pouch = make_item("VT-F45-TUI", "Pouch").name
		self.version = make_cost_rate_version(
			effective_from="2031-01-01",
			rates=[rate_line(3000, "Electricity")],
			pack_norms=[norm_line(pouch, pouch, 1)],
			submit=True,
		)
		self.addCleanup(frappe.set_user, "Administrator")

	def test_rate_at_returns_version_payload(self):
		frappe.set_user(make_user("crv-r09@example.com", ["TC R09"]))
		result = api.rate_at("2031-05-01")
		self.assertTrue(result["ok"])
		self.assertEqual(result["version"], self.version.name)
		self.assertEqual(str(result["effective_from"]), "2031-01-01")
		self.assertIsNone(result["effective_to"])
		self.assertEqual(
			result["rates"], [{"rate_type": "Electricity", "item": None, "uom": "kWh", "rate": 3000}]
		)
		self.assertEqual(
			result["pack_norms"], [{"pack_type": "VT-F45-TUI", "item": "VT-F45-TUI", "qty_per_pack": 1}]
		)

	def test_rate_at_without_version(self):
		result = api.rate_at("2030-01-01")
		self.assertEqual((result["ok"], result["version"], result["rates"]), (True, None, []))

	def test_rate_at_rejects_bad_date(self):
		for value in (None, "", "31/02/2031", "not-a-date"):
			with self.assertRaises(BadRequestError, msg=value):
				api.rate_at(value)

	def test_rate_at_requires_role(self):
		frappe.set_user(make_user("crv-r03@example.com", ["TC R03"]))
		with self.assertRaises(frappe.PermissionError):
			api.rate_at("2031-05-01")
