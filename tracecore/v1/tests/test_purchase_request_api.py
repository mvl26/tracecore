"""RPC tracecore.v1.stock.alerts / create_purchase_request — cảnh báo tồn và đề nghị mua một chạm (FEAT-043, FR-M6-06, .2)."""

import uuid
from datetime import datetime, timezone

import frappe

from tracecore.inventory.tests.test_alerts import AlertCase
from tracecore.inventory.tests.test_consume import ITEM
from tracecore.tests.factories import make_user
from tracecore.tests.utils import request_headers
from tracecore.v1 import stock as api

test_ignore = [
	"Item",
	"Batch",
	"Stock Entry",
	"Material Request",
	"Warehouse",
	"Company",
	"Supplier",
	"Stock Entry Type",
	"Fiscal Year",
	"User",
]


class TestStockAlertsApi(AlertCase):
	def setUp(self):
		super().setUp()
		self.users = {
			role: make_user(f"alerts-api-{role.lower().replace(' ', '-')}@example.com", [role])
			for role in ("TC R09", "TC R02", "TC R01", "TC R06", "TC R04")
		}
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)

	def request(self, key="p-1", **kwargs):
		values = {
			"item": ITEM,
			"warehouse": self.warehouse,
			"client_ts": datetime.now(timezone.utc).isoformat(),
			**kwargs,
		}
		with request_headers({"X-Idempotency-Key": str(uuid.uuid5(uuid.NAMESPACE_URL, key))}):
			return api.create_purchase_request(**values)

	def test_alerts_list_the_three_kinds(self):
		self.set_minimum(20, reorder_qty=30)
		frappe.set_user(self.users["TC R09"])
		result = api.alerts()
		self.assertTrue(result["ok"])
		self.assertIn(ITEM, [row["item"] for row in result["below_minimum"]])
		self.assertIn(self.near, [row["batch"] for row in result["expiring"]])
		self.assertEqual(sorted(result), ["below_minimum", "expiring", "ok", "unconfigured"])

	def test_who_may_read_the_alerts(self):
		for role in ("TC R09", "TC R02", "TC R01", "TC R06"):
			frappe.set_user(self.users[role])
			self.assertTrue(api.alerts()["ok"], role)
		frappe.set_user(self.users["TC R04"])
		with self.assertRaises(frappe.PermissionError):
			api.alerts()

	def test_one_tap_creates_a_draft_purchase_request(self):  # FR-M6-06.2
		self.set_minimum(20, reorder_qty=30)
		frappe.set_user(self.users["TC R09"])
		result = self.request()
		self.assertTrue(result["ok"], msg=result)
		doc = frappe.get_doc("Material Request", result["request"]["name"])
		self.assertEqual((doc.docstatus, doc.items[0].item_code, doc.items[0].qty), (0, ITEM, 30))
		self.assertEqual((result["request"]["item"], result["request"]["qty"]), (ITEM, 30))

	def test_the_same_key_and_a_new_tap_both_return_the_open_request(self):
		self.set_minimum(20, reorder_qty=30)
		frappe.set_user(self.users["TC R09"])
		sent_at = datetime.now(timezone.utc).isoformat()
		first = self.request(key="p-same", client_ts=sent_at)
		replay = self.request(key="p-same", client_ts=sent_at)
		another = self.request(key="p-other")
		self.assertEqual(first["request"]["name"], replay["request"]["name"])
		self.assertEqual(first["request"]["name"], another["request"]["name"])
		self.assertEqual(frappe.db.count("Material Request", {"docstatus": 0}), 1)

	def test_a_row_that_is_not_an_alert_is_a_conflict_body(self):
		self.set_minimum(10)
		frappe.set_user(self.users["TC R09"])
		result = self.request(key="p-fine")
		self.assertEqual((result["ok"], result["error"]["code"]), (False, "PURCHASE_NOT_NEEDED"))
		self.assertEqual(frappe.local.response.get("http_status_code"), 409)

	def test_an_unknown_item_is_a_422_body(self):
		frappe.set_user(self.users["TC R09"])
		result = self.request(key="p-bad", item="KHONG-CO")
		self.assertEqual(result["error"]["code"], "PURCHASE_ITEM_INVALID")
		self.assertEqual(frappe.local.response.get("http_status_code"), 422)

	def test_only_r09_and_r02_can_create_the_request(self):
		self.set_minimum(20, reorder_qty=30)
		for role in ("TC R06", "TC R01", "TC R04"):
			frappe.set_user(self.users[role])
			with self.assertRaises(frappe.PermissionError):
				self.request(key=f"p-{role}")
		frappe.set_user(self.users["TC R02"])
		self.assertTrue(self.request(key="p-r02")["ok"])
