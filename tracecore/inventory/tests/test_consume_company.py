"""Tiêu hao trên site nhiều bệnh viện và xử lý lại tiêu hao lỗi (A-78, #1816; FR-M6-03.3, FR-M6-03.4, FR-M6-04.5)."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from tracecore.core import notification
from tracecore.core.errors import BlockedError
from tracecore.inventory import consume, manual
from tracecore.inventory.tests.test_consume import ITEM, ConsumeCase, stock_of
from tracecore.tests import factories
from tracecore.tests.utils import bru

test_ignore = [
	"Item",
	"Batch",
	"Stock Entry",
	"Warehouse",
	"Company",
	"Supplier",
	"Stock Entry Type",
	"Fiscal Year",
]

COMPANY_B = "TraceCore Test Benh Vien B"
ABBR_B = "TCB"


def ensure_company_b():
	if not frappe.db.exists("Company", COMPANY_B):
		frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": COMPANY_B,
				"abbr": ABBR_B,
				"default_currency": "VND",
				"country": "Vietnam",
				"enable_perpetual_inventory": 0,
			}
		).insert(ignore_permissions=True)
	return f"Stores - {ABBR_B}"


def receive_in_b(item, batch_id, qty, expiry_days=5):
	"""Nhập `qty` của `item` vào kho Bệnh viện B, lô `batch_id`, hạn gần hơn lô của Company thử."""
	warehouse = ensure_company_b()
	line = {
		"item_code": item,
		"batch_id": batch_id,
		"expiry_date": add_days(today(), expiry_days),
		"qty": qty,
		"rate": 1000,
	}
	with patch("erpnext.get_default_company", return_value=COMPANY_B):
		entry = factories.build_receipt(
			[line], factories.make_supplier(), "DOC-" + frappe.generate_hash(length=8), warehouse
		)
		entry.company = COMPANY_B
		entry.insert(ignore_permissions=True)
		entry.submit()
	return warehouse


def asset_in(company):
	"""Asset tối thiểu chỉ để đọc `company` (không chạy luồng khấu hao của ERPNext)."""
	name = "AST-" + frappe.generate_hash(length=8)
	asset = frappe.new_doc("Asset")
	asset.update({"name": name, "asset_name": name, "company": company})
	asset.db_insert()
	return name


class MultiCompanyCase(ConsumeCase):
	def setUp(self):
		super().setUp()
		self.company_a = self.masters["company"]
		self.warehouse_b = receive_in_b(ITEM, "F42-B-NEAR", 4)

	def wash_batch_on(self, company=None, operator=None):
		"""Wash Batch tối thiểu: chỉ `equipment` và `operator` được đọc để xác định Company."""
		machine = factories.make_wash_machine()
		if company:
			frappe.db.set_value("Equipment", machine.name, "asset", asset_in(company), update_modified=False)
		name = "LR-" + frappe.generate_hash(length=8)
		doc = frappe.new_doc("Wash Batch")
		doc.update({"name": name, "equipment": machine.name, "operator": operator})
		doc.db_insert()
		return name

	def companies_of(self, entry):
		doc = frappe.get_doc("Stock Entry", entry)
		return doc.company, {
			frappe.db.get_value("Warehouse", row.s_warehouse, "company") for row in doc.items
		}


@bru("BRU-INV-001")
class TestPickByCompany(MultiCompanyCase):
	def test_pick_lots_can_be_limited_to_one_company(self):
		lots, short = consume.pick_lots(ITEM, 3, company=COMPANY_B)
		self.assertEqual([(lot.batch, lot.qty) for lot in lots], [("F42-B-NEAR", 3)])
		self.assertEqual(short, 0)
		lots, short = consume.pick_lots(ITEM, 10, company=COMPANY_B)
		self.assertEqual(sum(lot.qty for lot in lots), 4)  # không lấy sang bệnh viện kia
		self.assertEqual(short, 6)
		lots, _short = consume.pick_lots(ITEM, 2, company=self.company_a)
		self.assertEqual({lot.batch for lot in lots}, {self.near})

	def test_stock_companies_lists_only_companies_holding_stock(self):
		self.assertEqual(consume.stock_companies([ITEM]), {self.company_a, COMPANY_B})
		self.assertEqual(consume.stock_companies(["HC-KHONG-CO"]), set())


@bru("BRU-INV-002")
class TestAutomaticConsumptionOneCompany(MultiCompanyCase):
	def test_machine_asset_decides_the_company_and_fefo_never_crosses_it(self):
		batch = self.wash_batch_on(self.company_a)
		# lô gần hạn nhất đang ở bệnh viện B nhưng máy thuộc bệnh viện A
		result = consume.consume_for("Wash Batch", batch, [{"item": ITEM, "qty": 6}], reason="Auto")
		self.assertEqual(self.companies_of(result["entry"]), (self.company_a, {self.company_a}))
		self.assertEqual(stock_of(ITEM, self.warehouse_b), 4)

	def test_machine_of_a_hospital_without_stock_reports_short_instead_of_borrowing(self):
		other = self.wash_batch_on(COMPANY_B)
		result = consume.consume_for("Wash Batch", other, [{"item": ITEM, "qty": 6}], reason="Auto")
		self.assertEqual(self.companies_of(result["entry"]), (COMPANY_B, {COMPANY_B}))
		self.assertEqual(result["short"], [{"item": ITEM, "qty": 2}])

	def test_only_company_with_stock_is_used_when_the_machine_has_no_asset(self):
		factories.make_chemical_batch("HC-F42-ONE", "F42-ONE", expiry_days=30, qty=3)
		batch = self.wash_batch_on()
		result = consume.consume_for("Wash Batch", batch, [{"item": "HC-F42-ONE", "qty": 1}], reason="Auto")
		self.assertEqual(self.companies_of(result["entry"])[0], self.company_a)

	def test_pinned_lot_decides_when_the_machine_has_no_asset(self):
		batch = self.wash_batch_on()
		result = consume.consume_for(
			"Wash Batch", batch, [{"item": ITEM, "qty": 1, "batch": "F42-B-NEAR"}], reason="Auto"
		)
		self.assertEqual(self.companies_of(result["entry"]), (COMPANY_B, {COMPANY_B}))

	def test_operator_company_breaks_the_tie_only_if_it_holds_stock(self):
		operator = factories.make_employee(first_name="Bên B", company=COMPANY_B).name
		batch = self.wash_batch_on(operator=operator)
		result = consume.consume_for("Wash Batch", batch, [{"item": ITEM, "qty": 1}], reason="Auto")
		self.assertEqual(self.companies_of(result["entry"]), (COMPANY_B, {COMPANY_B}))

	def test_undeterminable_company_is_a_clear_error_and_nothing_is_issued(self):
		batch = self.wash_batch_on()
		before = stock_of(ITEM)
		with self.assertRaises(consume.CompanyUndetermined) as caught:
			consume.consume_for("Wash Batch", batch, [{"item": ITEM, "qty": 1}], reason="Auto")
		self.assertIn(COMPANY_B, str(caught.exception))
		self.assertEqual(stock_of(ITEM), before)

	def test_hook_turns_the_undeterminable_company_into_a_notification(self):
		batch = self.wash_batch_on()
		before = stock_of(ITEM)
		ctx = {
			"batch": batch,
			"result": "Pass",
			"program": None,
			"sets": [],
			"chemicals": [{"item": ITEM, "qty": 1}],
		}
		with patch("tracecore.inventory.consume.notification.emit") as emit:
			consume.on_wash_complete(ctx)
		self.assertEqual(emit.call_args.args[0], "CONSUMPTION_FAILED")
		self.assertIn(COMPANY_B, emit.call_args.kwargs["message"])
		self.assertEqual(stock_of(ITEM), before)

	def test_submit_issue_refuses_rows_of_two_companies(self):
		rows = [
			consume.issue_row(ITEM, 1, self.near, self.warehouse),
			consume.issue_row(ITEM, 1, "F42-B-NEAR", self.warehouse_b),
		]
		with self.assertRaises(consume.CompanyUndetermined):
			consume.submit_issue(rows, "Wash Batch", "WB-MIX", "Auto")


class TestManualIssueOneCompany(MultiCompanyCase):
	def block_code(self, fn, *args, **kwargs):
		try:
			fn(*args, **kwargs)
		except BlockedError as error:
			return error.block.code
		return None

	def test_two_companies_without_a_user_default_are_refused(self):
		with patch("frappe.defaults.get_user_default", return_value=None):
			self.assertEqual(self.block_code(manual.issue, ITEM, 1, "Xuất bù"), "ISSUE_COMPANY_AMBIGUOUS")
			self.assertEqual(self.block_code(manual.suggest, ITEM, 1), "ISSUE_COMPANY_AMBIGUOUS")

	def test_user_default_company_chooses_the_lots(self):
		with patch("frappe.defaults.get_user_default", return_value=COMPANY_B):
			result = manual.issue(ITEM, 2, "Xuất bù")
		self.assertEqual(self.companies_of(result["entry"]), (COMPANY_B, {COMPANY_B}))

	def test_chosen_lots_of_two_companies_are_refused(self):
		lots = [{"batch": self.near, "qty": 1}, {"batch": "F42-B-NEAR", "qty": 1}]
		self.assertEqual(
			self.block_code(manual.issue, ITEM, 2, "Xuất bù", lots=lots), "ISSUE_COMPANY_AMBIGUOUS"
		)

	def test_chosen_lots_of_one_company_are_issued(self):
		result = manual.issue(ITEM, 1, "Xuất bù", lots=[{"batch": "F42-B-NEAR", "qty": 1}])
		self.assertEqual(self.companies_of(result["entry"]), (COMPANY_B, {COMPANY_B}))


@bru("BRU-INV-002")
class TestDraftEntries(ConsumeCase):
	def leftover_draft(self, source="WB-F42-DRAFT"):
		doc = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": consume.ISSUE,
				"purpose": consume.ISSUE,
				"company": self.masters["company"],
				"tc_source_doctype": "Wash Batch",
				"tc_source_name": source,
				"tc_reason": "Auto",
				"items": [consume.issue_row(ITEM, 1, self.far, self.warehouse)],
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
		return doc.name

	def test_draft_is_submitted_with_fresh_rows_instead_of_counting_as_issued(self):
		draft = self.leftover_draft()
		result = consume.consume_for("Wash Batch", "WB-F42-DRAFT", [{"item": ITEM, "qty": 8}], reason="Auto")
		self.assertEqual(result["entry"], draft)
		self.assertTrue(result["created"])
		doc = frappe.get_doc("Stock Entry", draft)
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual({(row.batch_no, row.qty) for row in doc.items}, {(self.near, 5), (self.far, 3)})
		self.assertEqual(stock_of(ITEM), 7)
		self.assertEqual(
			frappe.db.count(
				"Stock Entry", {"tc_source_doctype": "Wash Batch", "tc_source_name": "WB-F42-DRAFT"}
			),
			1,
		)

	def test_second_run_after_the_draft_was_submitted_deducts_nothing_more(self):
		self.leftover_draft("WB-F42-DRAFT2")
		consume.consume_for("Wash Batch", "WB-F42-DRAFT2", [{"item": ITEM, "qty": 2}], reason="Auto")
		again = consume.consume_for("Wash Batch", "WB-F42-DRAFT2", [{"item": ITEM, "qty": 2}], reason="Auto")
		self.assertFalse(again["created"])
		self.assertEqual(stock_of(ITEM), 13)

	def test_draft_stays_a_draft_when_there_is_nothing_in_stock_to_issue(self):
		draft = self.leftover_draft("WB-F42-DRAFT3")
		result = consume.consume_for(
			"Wash Batch", "WB-F42-DRAFT3", [{"item": "HC-F42-NONE", "qty": 2}], "Auto"
		)
		self.assertIsNone(result["entry"])
		self.assertEqual(frappe.db.get_value("Stock Entry", draft, "docstatus"), 0)


class RetryCase(ConsumeCase):
	def setUp(self):
		super().setUp()
		notification.ensure_default_rules()
		self.machine = factories.make_equipment(
			equipment_type="Laundry Washer", serial="LW-" + frappe.generate_hash(length=8), zone_out=None
		)
		self.program = factories.make_program(
			self.machine.name,
			code="MG-" + frappe.generate_hash(length=6).upper(),
			consumables=[{"item": ITEM, "qty_per_load": 1, "qty_per_pack": 1, "qty_per_kg": 0.5}],
		)

	def failed_notice(self, doctype, name, users):
		frappe.db.delete("Notification Delivery", {"ref_doctype": doctype, "ref_name": name})
		notification.emit(
			"CONSUMPTION_FAILED", frappe._dict(doctype=doctype, name=name), "Lỗi tiêu hao", users=users
		)
		return frappe.get_all(
			"Notification Delivery",
			filters={"event_code": "CONSUMPTION_FAILED", "ref_doctype": doctype, "ref_name": name},
			pluck="name",
		)

	def statuses(self, names):
		return {frappe.db.get_value("Notification Delivery", name, "status") for name in names}

	def load_doc(self, name, status="Released", packs=2):
		doc = frappe.new_doc("Sterilization Load")
		doc.update(
			{
				"name": name,
				"equipment": self.machine.name,
				"program": self.program.name,
				"status": status,
				"docstatus": 1,
			}
		)
		doc.db_insert()
		for index in range(packs):
			row = frappe.new_doc("Load Pack")
			row.update(
				{
					"name": f"{name}-{index}",
					"parent": name,
					"parenttype": "Sterilization Load",
					"parentfield": "packs",
					"idx": index + 1,
					"pack": f"CY-{name}-{index}",
				}
			)
			row.db_insert()
		return name

	def laundry_doc(self, name, status="Passed", batch_type="In-house", weight=10):
		doc = frappe.new_doc("Laundry Batch")
		doc.update(
			{
				"name": name,
				"equipment": self.machine.name,
				"program": self.program.name,
				"status": status,
				"batch_type": batch_type,
				"weight_kg": weight,
				"docstatus": 1,
			}
		)
		doc.db_insert()
		return name


@bru("BRU-INV-002")
class TestRetrySources(RetryCase):
	def test_released_load_is_consumed_by_norm_times_packs(self):
		load = self.load_doc("ME-A78-01")
		before = stock_of(ITEM)
		result = consume.retry("Sterilization Load", load)
		self.assertTrue(result["created"])
		self.assertEqual(before - stock_of(ITEM), 3)  # 1 mẻ + 1 x 2 gói
		self.assertFalse(consume.retry("Sterilization Load", load)["created"])
		self.assertEqual(before - stock_of(ITEM), 3)

	def test_load_not_released_cannot_be_retried(self):
		load = self.load_doc("ME-A78-02", status="Quarantine")
		with self.assertRaises(frappe.ValidationError):
			consume.retry("Sterilization Load", load)

	def test_laundry_batch_is_consumed_by_norm_per_kg(self):
		batch = self.laundry_doc("LG-A78-01")
		before = stock_of(ITEM)
		self.assertTrue(consume.retry("Laundry Batch", batch)["created"])
		self.assertEqual(before - stock_of(ITEM), 6)  # 1 mẻ + 0,5 x 10 kg

	def test_outsourced_or_running_laundry_cannot_be_retried(self):
		for batch in (
			self.laundry_doc("LG-A78-02", batch_type="Outsourced"),
			self.laundry_doc("LG-A78-03", status="Running"),
		):
			with self.assertRaises(frappe.ValidationError):
				consume.retry("Laundry Batch", batch)

	def test_other_doctypes_are_refused(self):
		with self.assertRaises(frappe.ValidationError):
			consume.retry("Pack", "CY-1")


class TestRetryClosesTheAlert(RetryCase):
	def setUp(self):
		super().setUp()
		self.users = [
			factories.make_user("a78-r09@test.local", roles=("TC R09",)),
			factories.make_user("a78-r02@test.local", roles=("TC R02",)),
		]

	def test_successful_retry_marks_every_recipient_read(self):
		load = self.load_doc("ME-A78-10")
		rows = self.failed_notice("Sterilization Load", load, self.users)
		self.assertGreaterEqual(len(rows), 2)
		consume.retry("Sterilization Load", load)
		self.assertEqual(self.statuses(rows), {"Read"})

	def test_existing_entry_also_closes_the_alert(self):
		load = self.load_doc("ME-A78-11")
		consume.retry("Sterilization Load", load)
		rows = self.failed_notice("Sterilization Load", load, self.users)
		self.assertFalse(consume.retry("Sterilization Load", load)["created"])
		self.assertEqual(self.statuses(rows), {"Read"})

	def test_failed_retry_keeps_the_alert(self):
		load = self.load_doc("ME-A78-12")
		rows = self.failed_notice("Sterilization Load", load, self.users)
		with (
			patch("tracecore.inventory.consume.consume_for", side_effect=RuntimeError("boom")),
			self.assertRaises(frappe.ValidationError),
		):
			consume.retry("Sterilization Load", load)
		self.assertEqual(self.statuses(rows), {"Sent"})

	def test_retry_without_any_stock_keeps_the_alert(self):
		batch = self.laundry_doc("LG-A78-10", weight=10)
		rows = self.failed_notice("Laundry Batch", batch, self.users)
		frappe.db.set_value("Program Consumable", {"parent": self.program.name}, "item", "HC-F42-NONE")
		factories.make_item("HC-F42-NONE", "Chemical", has_batch_no=1, apply_rules=True)
		self.assertIsNone(consume.retry("Laundry Batch", batch)["entry"])
		self.assertEqual(self.statuses(rows), {"Sent"})

	def test_resolve_leaves_other_sources_and_events_alone(self):
		batch = self.laundry_doc("LG-A78-20")
		other = self.laundry_doc("LG-A78-21")
		rows = self.failed_notice("Laundry Batch", batch, self.users)
		kept = self.failed_notice("Laundry Batch", other, self.users)
		self.assertEqual(notification.resolve("CONSUMPTION_SHORT", "Laundry Batch", batch), 0)
		self.assertEqual(self.statuses(rows), {"Sent"})
		self.assertEqual(notification.resolve("CONSUMPTION_FAILED", "Laundry Batch", batch), len(rows))
		self.assertEqual(self.statuses(rows), {"Read"})
		self.assertEqual(self.statuses(kept), {"Sent"})
