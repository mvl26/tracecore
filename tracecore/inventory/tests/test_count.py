"""Phiếu kiểm kê (ERPNext Stock Reconciliation): chênh lệch theo lô, phê duyệt, lý do, khóa kho (FEAT-043; FR-M6-05, .1, .2;
UC-26, E1, E2; A-52 C1-C6).

ERPNext bỏ các dòng không đổi và từ chối phiếu không còn dòng nào, nên mọi phiếu thử đều có ít nhất một dòng chênh lệch; các
test chặn so khớp thông điệp để không "pass" nhầm vì lỗi phiếu rỗng.
"""

import frappe

from tracecore.inventory import consume, permissions
from tracecore.inventory.tests.test_consume import ITEM, ConsumeCase
from tracecore.tests import factories

test_ignore = [
	"Item",
	"Batch",
	"Stock Entry",
	"Stock Reconciliation",
	"Warehouse",
	"Company",
	"Supplier",
	"Stock Entry Type",
	"Fiscal Year",
]


class CountCase(ConsumeCase):
	def setUp(self):
		super().setUp()
		permissions.ensure_permissions()
		self.other_warehouse = factories.make_warehouse("Kho kiểm kê khác")

	def row(self, batch, qty, reason=None, warehouse=None):
		row = {
			"item_code": ITEM,
			"warehouse": warehouse or self.warehouse,
			"batch_no": batch,
			"qty": qty,
			"valuation_rate": 100,
			"use_serial_batch_fields": 1,
		}
		if reason:
			row["tc_variance_reason"] = reason
		return row

	def count(self, rows=None, **kwargs):
		"""Phiếu kiểm kê Nháp; mặc định đếm lô xa hạn thiếu 1 (10 -> 9, đúng 10 % nên chưa cần lý do)."""
		doc = frappe.get_doc(
			{
				"doctype": "Stock Reconciliation",
				"purpose": "Stock Reconciliation",
				"company": factories.STOCK_COMPANY,
				"items": rows if rows is not None else [self.row(self.far, 9)],
				**kwargs,
			}
		)
		return doc.insert()

	def user(self, role):
		return factories.make_user(f"count-{role.lower().replace(' ', '-')}@example.com", roles=(role,))

	def manual_entry(self, warehouse=None, source=None):
		entry = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Issue",
				"purpose": "Material Issue",
				"company": factories.STOCK_COMPANY,
				"tc_source_doctype": source,
				"tc_source_name": "X-1" if source else None,
				"items": [
					{
						"item_code": ITEM,
						"qty": 1,
						"s_warehouse": warehouse or self.warehouse,
						"batch_no": self.far,
						"use_serial_batch_fields": 1,
					}
				],
			}
		)
		return entry.insert()

	def assert_refused(self, call, text):
		with self.assertRaises(frappe.ValidationError) as caught:
			call()
		self.assertIn(text, str(caught.exception))


class TestCountSheet(CountCase):
	def test_every_lot_row_shows_the_system_quantity_and_the_difference(self):  # FR-M6-05
		doc = self.count([self.row(self.near, 4, reason="Hỏng"), self.row(self.far, 12, reason="Thừa")])
		rows = {row.batch_no: row for row in doc.items}
		self.assertEqual((rows[self.near].current_qty, rows[self.near].quantity_difference), (5, -1))
		self.assertEqual((rows[self.far].current_qty, rows[self.far].quantity_difference), (10, 2))

	def test_a_partial_count_lists_only_the_counted_lots(self):  # UC-26 A1
		doc = self.count([self.row(self.far, 9)])
		self.assertEqual([row.batch_no for row in doc.items], [self.far])

	def test_unknown_lot_is_refused(self):  # UC-26 E2
		self.assert_refused(lambda: self.count([self.row("KHONG-CO-LO", 3)]), "KHONG-CO-LO")

	def test_a_lot_of_another_item_is_refused(self):
		factories.make_chemical_batch("HC-F43-OTHER", "F43-OTHER-1", expiry_days=30, qty=5)
		self.assert_refused(lambda: self.count([self.row("F43-OTHER-1", 3)]), "does not belong")


class TestVarianceReason(CountCase):
	MESSAGE = "differs from the system quantity by more than 10 %"

	def test_difference_over_ten_percent_needs_a_reason(self):  # UC-26 E1
		self.assert_refused(lambda: self.count([self.row(self.far, 8)]), self.MESSAGE)  # 10 -> 8: lệch 20 %
		doc = self.count([self.row(self.far, 8, reason="Hao hụt khi pha")])
		self.assertEqual(doc.items[0].tc_variance_reason, "Hao hụt khi pha")

	def test_difference_of_exactly_ten_percent_needs_no_reason(self):
		self.assertEqual(self.count([self.row(self.far, 9)]).docstatus, 0)

	def test_a_surplus_over_ten_percent_needs_a_reason_too(self):
		self.assert_refused(lambda: self.count([self.row(self.far, 12)]), self.MESSAGE)

	def test_a_blank_reason_does_not_count(self):
		self.assert_refused(lambda: self.count([self.row(self.far, 8, reason="   ")]), self.MESSAGE)

	def test_a_lot_with_no_system_stock_needs_no_reason(self):
		doc = self.count([self.row(self.far, 3, warehouse=self.other_warehouse)])
		self.assertEqual(doc.items[0].current_qty, 0)


class TestApproval(CountCase):
	def can(self, role, ptype, doc):
		return frappe.has_permission("Stock Reconciliation", ptype, doc=doc, user=self.user(role))

	def test_r06_prepares_but_only_r02_and_r09_can_post(self):  # FR-M6-05.1
		doc = self.count()
		self.assertTrue(self.can("TC R06", "create", doc))
		self.assertTrue(self.can("TC R06", "write", doc))
		self.assertFalse(self.can("TC R06", "submit", doc))
		self.assertFalse(self.can("TC R06", "cancel", doc))
		self.assertTrue(self.can("TC R09", "submit", doc))
		self.assertTrue(self.can("TC R02", "submit", doc))

	def test_nobody_can_delete_a_count(self):
		doc = self.count()
		for role in ("TC R06", "TC R09", "TC R02", "TC R10"):
			self.assertFalse(self.can(role, "delete", doc), role)

	def test_only_r02_and_r09_post_whoever_may_edit(self):  # ma trận SEC DT-STOCKCOUNT (A-52 C2)
		doc = self.count()
		for role in ("TC R03", "TC R04", "TC R05", "TC R07", "TC R10", "TC R01"):
			self.assertFalse(self.can(role, "submit", doc), f"{role} submit")
		for role in ("TC R03", "TC R04", "TC R10", "TC R01"):
			self.assertFalse(self.can(role, "write", doc), f"{role} write")

	def test_posting_the_count_adjusts_the_stock(self):
		self.count([self.row(self.far, 9)]).submit()
		lots = {lot.batch: lot.qty for lot in consume._stock_by_lot(ITEM)}
		self.assertEqual(lots[self.far], 9)


class TestOneOpenCountPerWarehouse(CountCase):
	MESSAGE = "is already open"

	def test_a_second_open_count_of_the_same_warehouse_is_refused(self):  # UC-26 tiền điều kiện, C5
		self.count()
		self.assert_refused(lambda: self.count([self.row(self.far, 9)]), self.MESSAGE)

	def test_another_warehouse_may_have_its_own_count(self):
		self.count()
		doc = self.count([self.row(self.far, 3, warehouse=self.other_warehouse)])
		self.assertEqual(doc.items[0].warehouse, self.other_warehouse)

	def test_a_posted_count_frees_the_warehouse(self):
		self.count([self.row(self.far, 9)]).submit()
		self.assertTrue(self.count([self.row(self.far, 8, reason="Hao hụt")]))

	def test_saving_the_open_count_again_is_not_a_second_count(self):
		doc = self.count()
		doc.save()
		self.assertEqual(doc.docstatus, 0)


class TestWarehouseLock(CountCase):
	MESSAGE = "is being counted"

	def test_manual_stock_entry_is_blocked_while_the_count_is_open(self):  # FR-M6-05.2
		self.count()
		self.assert_refused(self.manual_entry, self.MESSAGE)
		self.assert_refused(lambda: self.manual_entry(source="Manual Issue"), self.MESSAGE)

	def test_automatic_consumption_is_not_blocked(self):  # C4: tiêu hao tự động chỉ chạy một lần
		self.count()
		self.assertTrue(self.manual_entry(source="Wash Batch"))

	def test_other_warehouses_are_not_locked(self):
		self.count()
		self.assertTrue(self.manual_entry(warehouse=self.other_warehouse))

	def test_the_lock_is_lifted_when_the_count_is_posted_or_cancelled(self):
		first = self.count([self.row(self.far, 9)])
		self.assert_refused(self.manual_entry, self.MESSAGE)
		first.submit()
		self.assertTrue(self.manual_entry())
		again = self.count([self.row(self.far, 8, reason="Hao hụt")])
		self.assert_refused(self.manual_entry, self.MESSAGE)
		again.submit()
		again.cancel()
		self.assertTrue(self.manual_entry())


class TestAbandonedCount(CountCase):
	"""Frappe không cho hủy bản Nháp và phiếu không bị xóa: phiếu bỏ dở phải thôi khóa kho bằng cờ Abandoned (review FEAT-043)."""

	def abandon(self, doc):
		doc.tc_abandoned = 1
		doc.save()
		return doc

	def test_an_abandoned_draft_no_longer_locks_the_warehouse(self):
		self.abandon(self.count())
		self.assertTrue(self.manual_entry())
		self.assertTrue(self.count([self.row(self.far, 8, reason="Hao hụt")]))

	def test_an_abandoned_count_cannot_be_posted(self):
		doc = self.abandon(self.count())
		self.assert_refused(doc.submit, "was abandoned")

	def test_unticking_abandoned_while_another_count_is_open_is_refused(self):
		first = self.abandon(self.count())
		self.count([self.row(self.far, 8, reason="Hao hụt")])
		first.tc_abandoned = 0
		self.assert_refused(first.save, "is already open")

	def test_the_count_stays_on_record(self):
		doc = self.abandon(self.count())
		self.assertEqual(frappe.db.get_value("Stock Reconciliation", doc.name, "tc_abandoned"), 1)
