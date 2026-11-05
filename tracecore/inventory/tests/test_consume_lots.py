"""Trừ kho đúng lô đã chọn trên dòng vật tư và đúng lô chỉ thị đã quét (A-112; FR-M6-03.6, FR-M6-03.7, BRU-INV-004)."""

import frappe
from frappe.utils import flt

from tracecore.core import run_consumables
from tracecore.equipment import daily_test
from tracecore.inventory import consume
from tracecore.patches.v0_1 import link_consumable_lots_a112
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, bru

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

ENZYME, CI, BI = "CL-ENZ", "CI5-STEAM", "CL-BI"


def issued_lots(source_doctype, source_name):
	"""``{(vật tư, lô): số lượng}`` của phiếu xuất đã ghi sổ của nguồn."""
	entry = frappe.db.get_value(
		"Stock Entry", {"tc_source_doctype": source_doctype, "tc_source_name": source_name, "docstatus": 1}
	)
	out = {}
	for row in frappe.get_doc("Stock Entry", entry).items if entry else []:
		key = (row.item_code, row.batch_no)
		out[key] = out.get(key, 0) + flt(row.qty)
	return out


def indicator_lot(item_code, group, batch_id, **item_fields):
	"""Lô chỉ thị còn tồn 10: Item đúng nhóm chỉ thị tạo trước để `make_chemical_batch` không đổi nhóm."""
	factories.make_item(item_code, group, has_batch_no=1, apply_rules=True, **item_fields)
	return factories.make_chemical_batch(item_code, batch_id, expiry_days=90, qty=10).name


class LotsCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		factories.ensure_stock_masters()
		factories.use_stock_company(self)
		self.near = factories.make_chemical_batch(ENZYME, "CL-ENZ-NEAR", expiry_days=10, qty=20).name
		self.far = factories.make_chemical_batch(ENZYME, "CL-ENZ-FAR", expiry_days=90, qty=20).name
		self.ci_lot = indicator_lot(CI, "Chemical Indicator", "CL-CI-1", method="Steam", ci_class="5")
		self.bi_lot = indicator_lot(BI, "Biological Indicator", "CL-BI-1")
		self.employee = factories.make_employee()


class TestChosenLot(LotsCase):
	@bru("BRU-INV-004")
	def test_wash_issues_the_lot_chosen_on_the_row_not_fefo(self):
		washer = factories.make_wash_machine()
		program = factories.make_wash_program(
			washer.name, consumables=[{"item": ENZYME, "role": "Other", "qty_per_load": 3}]
		)
		rows = run_consumables.rows(
			program.name, 1, [{"item": ENZYME, "batch": self.far}], True, self.employee.name
		)
		batch = factories.make_wash_batch(
			washer, program, [factories.make_wash_ready_set()], consumables=rows
		)
		consume.on_wash_complete(
			{"batch": batch.name, "program": program.name, "sets": [], "chemicals": [], "result": "Pass"}
		)
		self.assertEqual(issued_lots("Wash Batch", batch.name), {(ENZYME, self.far): 3})

	def test_chosen_lot_short_of_stock_issues_what_it_has(self):
		washer = factories.make_wash_machine()
		program = factories.make_wash_program(
			washer.name, consumables=[{"item": ENZYME, "role": "Other", "qty_per_load": 25}]
		)
		rows = run_consumables.rows(
			program.name, 1, [{"item": ENZYME, "batch": self.far}], True, self.employee.name
		)
		batch = factories.make_wash_batch(
			washer, program, [factories.make_wash_ready_set()], consumables=rows
		)
		consume.on_wash_complete(
			{"batch": batch.name, "program": program.name, "sets": [], "chemicals": [], "result": "Pass"}
		)
		self.assertEqual(issued_lots("Wash Batch", batch.name), {(ENZYME, self.far): 20})


class TestIndicatorLots(LotsCase):
	def setUp(self):
		super().setUp()
		self.machine = factories.make_sterilizer()
		# định mức cũ không vai trò có chỉ thị: không được trừ thêm theo chương trình
		self.program = factories.make_sterilize_program(
			self.machine.name,
			consumables=[{"item": CI, "qty_per_pack": 1}, {"item": ENZYME, "qty_per_load": 1}],
		)

	def indicator(self, load, kind, batch, **fields):
		row = frappe.get_doc(
			{
				"doctype": "Load Indicator Result",
				"load": load,
				"indicator": kind,
				"result": "Pass",
				"batch": batch,
				"lot": batch,
				**fields,
			}
		)
		row.flags.tc_releasing = True
		row.flags.ignore_links = True
		return row.insert(ignore_permissions=True)

	@bru("BRU-INV-004")
	def test_released_load_issues_the_scanned_ci_lot_per_pack_and_the_recorded_indicator_lots(self):
		packs = [factories.make_load_ready_pack(ci_batch=self.ci_lot) for _ in range(2)]
		load = factories.make_load(self.machine, self.program, packs)
		self.indicator(load.name, "biological", self.bi_lot)
		self.indicator(load.name, "chemical_class_5", None)  # lô chưa có trong kho: không trừ
		consume.on_load_release(
			{"load": load.name, "program": self.program.name, "packs": [pack.name for pack in packs]}
		)
		lots = issued_lots("Sterilization Load", load.name)
		self.assertEqual(lots[(CI, self.ci_lot)], 2)
		self.assertEqual(lots[(BI, self.bi_lot)], 1)
		self.assertEqual(sum(qty for (item, _lot), qty in lots.items() if item == CI), 2)
		self.assertIn((ENZYME, self.near), lots)

	def test_passed_wash_issues_its_indicator_lot_once(self):
		washer = factories.make_wash_machine()
		program = factories.make_wash_program(washer.name)
		batch = factories.make_wash_batch(washer, program, [factories.make_wash_ready_set()])
		self.indicator(None, "wash_indicator", self.ci_lot, wash_batch=batch.name)
		consume.on_wash_complete(
			{"batch": batch.name, "program": program.name, "sets": [], "chemicals": [], "result": "Pass"}
		)
		self.assertEqual(issued_lots("Wash Batch", batch.name).get((CI, self.ci_lot)), 1)


class TestDailyTestLot(LotsCase):
	"""Lô gói test ghi lúc có kết quả: trùng Batch thì liên kết và trừ đúng lô đó (A-112 (e), E5)."""

	def setUp(self):
		super().setUp()
		self.machine = factories.make_sterilizer()
		factories.make_program(
			self.machine.name,
			code="BD-" + frappe.generate_hash(length=6).upper(),
			water=20,
			program_kind="Test",
			daily_test_type="bowie_dick",
			consumables=[{"item": ENZYME, "role": "Test Pack", "is_required": 1, "qty_per_load": 1}],
		)

	def run_test(self, lot, lot_expiry=None):
		started = daily_test.start_run(
			self.machine.name,
			"bowie_dick",
			"TR-005",
			self.employee.name,
			consumables=[{"item": ENZYME, "qty": 1}],
			consumables_confirmed=True,
		)
		daily_test.end_run(self.machine.name, "bowie_dick")
		daily_test.record(
			self.machine.name,
			"bowie_dick",
			"Pass",
			"TR-005",
			lot=lot,
			lot_expiry=lot_expiry,
			photo="/private/files/bd.png",
			employee=self.employee.name,
		)
		return frappe.get_doc("Daily Test", started["daily_test"])

	def test_lot_in_stock_is_linked_dated_from_the_batch_and_issued(self):
		test = self.run_test(self.far)  # hạn không gõ: lấy theo Batch
		self.assertEqual(test.batch, self.far)
		self.assertEqual(str(test.lot_expiry), str(frappe.db.get_value("Batch", self.far, "expiry_date")))
		# dòng gợi ý FEFO là lô gần hạn, nhưng gói thật đã dùng là lô ghi lúc có kết quả
		self.assertEqual(issued_lots("Daily Test", test.name), {(ENZYME, self.far): 1})

	def test_patch_links_old_daily_tests_whose_lot_is_a_batch(self):
		test = self.run_test(self.far)
		frappe.db.set_value("Daily Test", test.name, "batch", None)
		link_consumable_lots_a112.execute()
		self.assertEqual(frappe.db.get_value("Daily Test", test.name, "batch"), self.far)

	@bru("BRU-INV-004")
	def test_no_lot_typed_takes_the_lot_of_the_test_pack_line(self):
		test = self.run_test(None)  # dòng Gói test đã có lô FEFO lúc Bắt đầu test (A-112 D5)
		self.assertEqual((test.lot, test.batch), (self.near, self.near))
		self.assertEqual(issued_lots("Daily Test", test.name), {(ENZYME, self.near): 1})

	def test_expiry_of_a_stock_lot_comes_from_the_batch(self):
		expired = factories.make_chemical_batch(ENZYME, "CL-ENZ-OLD", expiry_days=-2).name
		with self.assertRaises(frappe.ValidationError) as raised:
			self.run_test("(01)08931234567890(10)" + expired, frappe.utils.add_days(frappe.utils.today(), 30))
		# A-130: có vật tư Gói test thì lô hết hạn bị chặn ngay ở bước kiểm lô theo vật tư
		self.assertEqual(raised.exception.block.code, "CONSUMABLE_LOT_INVALID")

	def test_free_text_lot_is_blocked_when_the_program_has_a_test_pack(self):
		# A-130 thay A-112 (E5): chương trình có Gói test thì chỉ nhận lô có trong kho của đúng vật tư, không còn ghi chú tự do
		with self.assertRaises(frappe.ValidationError) as raised:
			self.run_test("LOT-ON-THE-BOX", frappe.utils.add_days(frappe.utils.today(), 30))
		self.assertEqual(raised.exception.block.code, "CONSUMABLE_LOT_INVALID")
