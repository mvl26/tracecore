"""RPC tracecore.v1.stock.* — xuất kho thủ công FEFO (FEAT-042, FR-M6-04, API-M6-01)."""

import uuid
from datetime import datetime, timezone

import frappe

from tracecore.inventory.tests.test_consume import ITEM, ConsumeCase, stock_of
from tracecore.tests.factories import make_user
from tracecore.tests.utils import bru, request_headers
from tracecore.v1 import stock as api

test_ignore = [
	"Item",
	"Batch",
	"Stock Entry",
	"Warehouse",
	"Company",
	"Supplier",
	"Stock Entry Type",
	"Fiscal Year",
	"User",
]


@bru("BRU-INV-001")
class TestStockApi(ConsumeCase):
	def setUp(self):
		super().setUp()
		self.r09 = make_user("stock-api-r09@example.com", ["TC R09"])
		self.r04 = make_user("stock-api-r04@example.com", ["TC R04"])
		self.addCleanup(frappe.set_user, "Administrator")

	def issue(self, key="k-1", **kwargs):
		values = {
			"item": ITEM,
			"qty": 4,
			"reason": "Cấp khoa",
			"client_ts": datetime.now(timezone.utc).isoformat(),
			**kwargs,
		}
		with request_headers({"X-Idempotency-Key": str(uuid.uuid5(uuid.NAMESPACE_URL, key))}):
			return api.issue_manual(**values)

	def test_issue_returns_entry_lots_and_warnings(self):
		frappe.set_user(self.r09)
		result = self.issue()
		self.assertTrue(result["ok"])
		self.assertEqual(result["lots"], [{"batch": self.near, "qty": 4}])
		self.assertEqual(stock_of(ITEM), 11)

	def test_same_key_replays_without_a_second_issue(self):
		frappe.set_user(self.r09)
		sent_at = datetime.now(timezone.utc).isoformat()
		first = self.issue(key="k-same", client_ts=sent_at)
		second = self.issue(key="k-same", client_ts=sent_at)
		self.assertEqual(second["entry"], first["entry"])
		self.assertEqual(stock_of(ITEM), 11)

	def test_business_rejection_is_a_body_not_an_exception(self):
		frappe.set_user(self.r09)
		result = self.issue(key="k-no-reason", reason="")
		self.assertEqual((result["ok"], result["error"]["code"]), (False, "REASON_REQUIRED"))

	def test_lots_can_be_sent_as_json_text(self):
		frappe.set_user(self.r09)
		result = self.issue(key="k-json", lots=f'[{{"batch": "{self.far}", "qty": 4}}]')
		self.assertEqual([w["code"] for w in result["warnings"]], ["FEFO_NOT_FOLLOWED"])

	def test_malformed_lots_are_a_bad_request(self):
		frappe.set_user(self.r09)
		with self.assertRaises(api.BadRequestError):
			self.issue(key="k-bad", lots="not json")

	def test_role_without_permission_is_refused_before_any_change(self):
		frappe.set_user(self.r04)
		with self.assertRaises(frappe.PermissionError):
			self.issue(key="k-denied")
		with self.assertRaises(frappe.PermissionError):
			api.suggest_lots(ITEM, 3)
		frappe.set_user("Administrator")
		self.assertEqual(stock_of(ITEM), 15)

	def test_suggest_lots_returns_fefo_order(self):
		frappe.set_user(self.r09)
		result = api.suggest_lots(ITEM, 8)
		self.assertEqual([lot["batch"] for lot in result["lots"]], [self.near, self.far])

	def test_suggest_lots_needs_an_existing_item(self):
		frappe.set_user(self.r09)
		with self.assertRaises(api.BadRequestError):
			api.suggest_lots("KHONG-CO", 1)


@bru("BRU-INV-002")
class TestRetryConsumptionApi(ConsumeCase):
	def setUp(self):
		super().setUp()
		self.r09 = make_user("stock-retry-r09@example.com", ["TC R09"])
		self.r04 = make_user("stock-retry-r04@example.com", ["TC R04"])
		self.addCleanup(frappe.set_user, "Administrator")

	def test_role_without_permission_is_refused(self):
		frappe.set_user(self.r04)
		with self.assertRaises(frappe.PermissionError):
			api.retry_consumption("Wash Batch", "LR-000000-01")

	def test_accounting_calls_the_service_with_the_document(self):
		frappe.set_user(self.r09)
		from unittest.mock import patch

		with patch(
			"tracecore.v1.stock.consume.retry", return_value={"entry": "MAT-X", "created": True, "lots": [], "short": []}
		) as retry:
			result = api.retry_consumption("Wash Batch", "LR-000000-01")
		retry.assert_called_once_with("Wash Batch", "LR-000000-01")
		self.assertEqual((result["ok"], result["entry"], result["created"]), (True, "MAT-X", True))
