"""Cảnh báo tồn dưới tối thiểu, lô sắp hết hạn, thiếu cấu hình và đề nghị mua một chạm (FEAT-043; FR-M6-06, .1-.3;
UC-26 bước 6, E3; A-52 C7-C12)."""

from unittest.mock import patch

import frappe

from tracecore.core.errors import BlockedError
from tracecore.inventory import alerts
from tracecore.inventory.tests.test_consume import ITEM, ConsumeCase
from tracecore.tests import factories

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
]


class AlertCase(ConsumeCase):
	"""ITEM có 15 đơn vị ở kho test: lô gần hạn 5 (hạn 10 ngày) và lô xa hạn 10 (hạn 90 ngày)."""

	def setUp(self):
		super().setUp()
		self.other_warehouse = factories.make_warehouse("Kho cảnh báo khác")

	def set_minimum(self, level, warehouse=None, reorder_qty=0, item=ITEM):
		doc = frappe.get_doc("Item", item)
		doc.set("reorder_levels", [])
		if level is not None:
			doc.append(
				"reorder_levels",
				{
					"warehouse": warehouse or self.warehouse,
					"warehouse_reorder_level": level,
					# ERPNext bắt buộc số lượng đặt lại khi lưu Item; 0 (dữ liệu cũ) được đặt thẳng vào DB bên dưới
					"warehouse_reorder_qty": reorder_qty or 1,
					"material_request_type": "Purchase",
				},
			)
		doc.save()
		if level is not None and not reorder_qty:
			frappe.db.set_value("Item Reorder", {"parent": item}, "warehouse_reorder_qty", 0)
		return doc

	def below(self):
		return {(row["item"], row["warehouse"]): row for row in alerts.below_minimum()}


class TestBelowMinimum(AlertCase):
	def test_stock_under_the_minimum_of_a_warehouse_is_listed(self):  # FR-M6-06
		self.set_minimum(20, reorder_qty=30)
		row = self.below()[(ITEM, self.warehouse)]
		self.assertEqual((row["qty"], row["minimum"], row["shortfall"], row["reorder_qty"]), (15, 20, 5, 30))

	def test_stock_equal_to_the_minimum_is_not_an_alert(self):
		self.set_minimum(15)
		self.assertNotIn((ITEM, self.warehouse), self.below())

	def test_an_empty_warehouse_with_a_minimum_is_an_alert(self):
		self.set_minimum(4, warehouse=self.other_warehouse)
		self.assertEqual(self.below()[(ITEM, self.other_warehouse)]["qty"], 0)

	def test_item_without_a_minimum_is_never_listed(self):  # FR-M6-06.3
		self.set_minimum(None)
		self.assertFalse([key for key in self.below() if key[0] == ITEM])

	def test_a_zero_minimum_means_not_configured(self):
		self.set_minimum(0)
		self.assertFalse([key for key in self.below() if key[0] == ITEM])

	def test_a_disabled_item_is_not_listed(self):
		self.set_minimum(20)
		frappe.db.set_value("Item", ITEM, "disabled", 1)
		self.assertFalse([key for key in self.below() if key[0] == ITEM])

	def test_the_reorder_quantity_defaults_to_the_shortfall(self):
		self.set_minimum(20)
		self.assertEqual(self.below()[(ITEM, self.warehouse)]["reorder_qty"], 5)


class TestExpiringBatches(AlertCase):
	def test_lot_expiring_within_30_days_is_listed(self):  # FR-M6-06.1
		rows = {row["batch"]: row for row in alerts.expiring_batches()}
		self.assertIn(self.near, rows)
		self.assertNotIn(self.far, rows)
		self.assertEqual((rows[self.near]["qty"], rows[self.near]["days_left"]), (5, 10))

	def test_the_window_can_be_widened(self):
		self.assertEqual({row["batch"] for row in alerts.expiring_batches(days=120)}, {self.near, self.far})

	def test_an_expired_lot_with_stock_is_listed_with_negative_days(self):
		frappe.db.set_value(
			"Batch", self.near, "expiry_date", frappe.utils.add_days(frappe.utils.today(), -2)
		)
		rows = {row["batch"]: row for row in alerts.expiring_batches()}
		self.assertEqual(rows[self.near]["days_left"], -2)

	def test_a_lot_without_stock_is_not_listed(self):
		factories.make_chemical_batch(ITEM, "F43-EMPTY", expiry_days=5, qty=0)
		self.assertNotIn("F43-EMPTY", {row["batch"] for row in alerts.expiring_batches()})


class TestUnconfigured(AlertCase):
	def test_cssd_item_without_a_minimum_is_in_the_missing_configuration_list(self):  # FR-M6-06.3, UC-26 E3
		self.set_minimum(None)
		self.assertIn(ITEM, {row["item"] for row in alerts.unconfigured_items()})

	def test_configured_disabled_and_non_cssd_items_are_not_listed(self):
		self.set_minimum(10)
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": "F43-PLAIN",
				"item_name": "F43-PLAIN",
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
				"is_stock_item": 1,
			}
		).insert(ignore_permissions=True)
		names = {row["item"] for row in alerts.unconfigured_items()}
		self.assertNotIn(ITEM, names)
		self.assertNotIn("F43-PLAIN", names)
		self.set_minimum(None)
		frappe.db.set_value("Item", ITEM, "disabled", 1)
		self.assertNotIn(ITEM, {row["item"] for row in alerts.unconfigured_items()})


class TestRunDaily(AlertCase):
	def run_with_spy(self):
		with patch("tracecore.inventory.alerts.notification.emit") as emit:
			summary = alerts.run_daily()
		return summary, [
			(call.args[0], call.args[1].get("doctype"), call.args[1].get("name"))
			for call in emit.call_args_list
		]

	def test_one_notification_per_alert_and_none_for_missing_configuration(self):  # FR-M6-06, .1, .3
		self.set_minimum(20)
		summary, sent = self.run_with_spy()
		self.assertIn(("STOCK_BELOW_MIN", "Item", ITEM), sent)
		self.assertIn(("BATCH_EXPIRING", "Batch", self.near), sent)
		self.assertNotIn(("BATCH_EXPIRING", "Batch", self.far), sent)
		self.assertEqual(summary["below_minimum"], len([s for s in sent if s[0] == "STOCK_BELOW_MIN"]))
		self.assertEqual(summary["expiring"], len([s for s in sent if s[0] == "BATCH_EXPIRING"]))

	def test_an_item_without_a_minimum_sends_no_stock_alert(self):
		self.set_minimum(None)
		_summary, sent = self.run_with_spy()
		self.assertNotIn(("STOCK_BELOW_MIN", "Item", ITEM), sent)

	def test_a_failing_notification_never_stops_the_job(self):
		self.set_minimum(20)
		with patch("tracecore.inventory.alerts.notification.emit", side_effect=RuntimeError("boom")):
			summary = alerts.run_daily()
		self.assertEqual(summary["failed"], summary["below_minimum"] + summary["expiring"])

	def test_the_job_is_scheduled_every_morning_and_events_exist(self):
		self.assertIn(
			"tracecore.inventory.alerts.run_daily", frappe.get_hooks("scheduler_events")["cron"]["0 6 * * *"]
		)
		from tracecore.core import notification

		for event in ("STOCK_BELOW_MIN", "BATCH_EXPIRING"):
			self.assertIn(event, notification.EVENTS)
			self.assertIn("TC R09", notification.EVENTS[event][4])


class TestPurchaseRequest(AlertCase):
	def make(self, **kwargs):
		return alerts.create_purchase_request(
			kwargs.pop("item", ITEM), kwargs.pop("warehouse", self.warehouse)
		)

	def test_creates_a_draft_purchase_request_for_the_reorder_quantity(self):  # FR-M6-06.2
		self.set_minimum(20, reorder_qty=30)
		doc = self.make()
		self.assertEqual((doc.docstatus, doc.material_request_type), (0, "Purchase"))
		self.assertEqual(
			[(row.item_code, row.qty, row.warehouse) for row in doc.items], [(ITEM, 30, self.warehouse)]
		)

	def test_the_quantity_defaults_to_the_shortfall(self):
		self.set_minimum(20)
		self.assertEqual(self.make().items[0].qty, 5)

	def test_a_second_tap_returns_the_open_request_instead_of_a_new_one(self):
		self.set_minimum(20, reorder_qty=30)
		first = self.make()
		again = self.make()
		self.assertEqual(first.name, again.name)
		self.assertEqual(frappe.db.count("Material Request", {"docstatus": 0}), 1)

	def test_unknown_item_or_warehouse_is_refused(self):
		for kwargs in ({"item": "KHONG-CO"}, {"warehouse": "Kho không có"}, {"item": None}):
			with self.assertRaises(BlockedError) as caught:
				self.make(**kwargs)
			self.assertEqual(caught.exception.block.code, "PURCHASE_ITEM_INVALID", msg=kwargs)

	def test_no_request_when_the_stock_is_not_below_the_minimum(self):
		self.set_minimum(10)
		with self.assertRaises(BlockedError) as caught:
			self.make()
		self.assertEqual(caught.exception.block.code, "PURCHASE_NOT_NEEDED")
		self.set_minimum(None)
		with self.assertRaises(BlockedError):
			self.make()


class TestPurchaseRequestLifecycle(AlertCase):
	def setUp(self):
		super().setUp()
		self.set_minimum(20, reorder_qty=30)

	def test_a_posted_request_still_being_ordered_blocks_a_duplicate(self):
		first = alerts.create_purchase_request(ITEM, self.warehouse)
		first.submit()
		again = alerts.create_purchase_request(ITEM, self.warehouse)
		self.assertEqual(again.name, first.name)

	def test_a_fully_ordered_request_no_longer_blocks_a_new_one(self):
		first = alerts.create_purchase_request(ITEM, self.warehouse)
		first.submit()
		frappe.db.set_value("Material Request", first.name, {"per_ordered": 100, "status": "Ordered"})
		again = alerts.create_purchase_request(ITEM, self.warehouse)
		self.assertNotEqual(again.name, first.name)

	def test_a_cancelled_request_does_not_block(self):
		first = alerts.create_purchase_request(ITEM, self.warehouse)
		first.submit()
		first.cancel()
		self.assertNotEqual(alerts.create_purchase_request(ITEM, self.warehouse).name, first.name)

	def test_only_a_draft_request_can_be_deleted(self):
		from tracecore.inventory import count

		draft = alerts.create_purchase_request(ITEM, self.warehouse)
		self.assertTrue(frappe.has_permission("Material Request", "delete", doc=draft, user=self.r09()))
		count.only_draft_deletable(draft)  # không ném
		draft.submit()
		with self.assertRaises(frappe.ValidationError):
			count.only_draft_deletable(draft)
		self.assertFalse(
			frappe.has_permission("Material Request", "delete", doc=draft, user=self.user_without_delete())
		)

	def r09(self):
		return factories.make_user("pr-life-r09@example.com", roles=("TC R09",))

	def user_without_delete(self):
		return factories.make_user("pr-life-r02@example.com", roles=("TC R02",))
