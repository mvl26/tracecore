"""Cost Sheet mẻ/lô và giá thành gói (FEAT-046 Task 2; FR-M7-05, .1, .2, FR-M7-06, .2; UC-29; A-53 b-g)."""

from unittest.mock import patch

import frappe
from frappe.utils import getdate, now_datetime

from tracecore.costing import sheet
from tracecore.tests import factories
from tracecore.tests.factories import make_cost_rate_version, norm_line, rate_line
from tracecore.tests.utils import IsolatedTestCase

test_ignore = ["Item", "Batch", "Department", "User", "Employee", "Supplier"]

ELECTRICITY, WATER, LABOR = 3000, 10, 60000  # đ/kWh, đ/L, đ/giờ


def lines(name):
	return {row.component: row for row in frappe.get_doc("Cost Sheet", name).lines}


class SheetCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.machine = factories.make_equipment(serial="SN-" + frappe.generate_hash(length=6))  # 20.000 đ/mẻ
		self.program = factories.make_sterilize_program(self.machine)  # 3,5 kWh, 20 L, 4 phút
		self.packs = [factories.make_load_ready_pack() for _ in range(3)]
		notify = patch.object(sheet, "emit")
		self.emit = notify.start()
		self.addCleanup(notify.stop)

	def priced(self, extra=(), pack_norms=None):
		return make_cost_rate_version(
			submit=True,
			rates=[
				rate_line(ELECTRICITY, "Electricity"),
				rate_line(WATER, "Tap Water"),
				rate_line(LABOR, "Labor"),
				*extra,
			],
			pack_norms=pack_norms or [],
		)

	def load(self, status="Released", packs=None):
		doc = factories.make_load(self.machine, self.program, packs if packs is not None else self.packs)
		frappe.db.set_value(
			"Sterilization Load",
			doc.name,
			{"status": status, "released_at": now_datetime(), "ended_at": now_datetime()},
		)
		return doc.name


class TestLoadSheet(SheetCase):
	def test_load_components_from_norms_and_rates(self):
		self.priced()
		name = sheet.build("Sterilization Load", self.load())
		parts = lines(name)
		self.assertEqual(parts["Equipment Depreciation"].amount, 20000)
		self.assertEqual(parts["Electricity"].amount, 3.5 * ELECTRICITY)
		self.assertEqual(parts["Tap Water"].amount, 20 * WATER)
		self.assertEqual(parts["Labor"].amount, 4 * LABOR / 60)
		doc = frappe.get_doc("Cost Sheet", name)
		self.assertEqual(doc.status, "Priced")
		self.assertEqual(doc.total_cost, 20000 + 10500 + 200 + 4000)
		self.assertEqual(doc.pack_count, 3)
		self.assertTrue(doc.rate_version)

	def test_split_by_pack_count_sums_exactly(self):
		self.priced()
		name = sheet.build("Sterilization Load", self.load())
		doc = frappe.get_doc("Cost Sheet", name)
		shares = [row.load_share for row in doc.packs]
		self.assertEqual(sum(shares), doc.total_cost)  # 34.700 / 3: gói cuối nhận phần dư
		self.assertEqual(shares, [11566, 11566, 11568])
		for row in doc.packs:
			self.assertEqual(frappe.db.get_value("Pack", row.pack, "cost_total"), row.total)

	def test_build_is_idempotent(self):
		self.priced()
		load = self.load()
		first = sheet.build("Sterilization Load", load)
		self.assertEqual(sheet.build("Sterilization Load", load), first)
		self.assertEqual(frappe.db.count("Cost Sheet", {"source_name": load, "is_recalculation": 0}), 1)

	def test_missing_rate_marks_unpriced_and_notifies_r09(self):
		make_cost_rate_version(submit=True, rates=[rate_line(ELECTRICITY, "Electricity")])
		name = sheet.build("Sterilization Load", self.load())
		doc = frappe.get_doc("Cost Sheet", name)
		self.assertEqual(doc.status, "Unpriced")
		self.assertIn("Tap Water", doc.missing_rates)
		self.assertEqual(lines(name)["Tap Water"].amount, 0)
		self.assertEqual(self.emit.call_args.args[0], "COST_SHEET_UNPRICED")

	def test_failed_load_is_quality_cost_without_pack_split(self):
		self.priced()
		name = sheet.build("Sterilization Load", self.load(status="Failed"))
		doc = frappe.get_doc("Cost Sheet", name)
		self.assertEqual((doc.is_quality_cost, len(doc.packs)), (1, 0))
		self.assertGreater(doc.total_cost, 0)

	def test_chemicals_from_consumption_entries(self):
		chemical = "CS-HC-" + frappe.generate_hash(length=4)
		factories.make_item(chemical, "Chemical")
		self.priced(extra=[rate_line(500, "Item", chemical)])
		with patch.object(sheet, "_consumed", return_value={chemical: 2.0}):
			name = sheet.build("Sterilization Load", self.load())
		row = lines(name)["Chemical"]
		self.assertEqual((row.item, row.quantity, row.amount), (chemical, 2.0, 1000))

	def test_maintenance_allocated_by_planned_loads_per_day(self):
		"""Mẫu số cố định theo số mẻ kế hoạch/ngày: job chạy ngay sau mỗi mẻ không làm tổng phân bổ vượt 100 % (review #1)."""
		self.priced()
		frappe.db.set_value("Equipment", self.machine.name, "planned_loads_year", 1095)  # 3 mẻ/ngày
		with patch.object(sheet, "_maintenance_today", return_value=9000) as daily:
			names = [sheet.build("Sterilization Load", self.load(packs=[pack])) for pack in self.packs]
		self.assertEqual([lines(name)["Maintenance"].amount for name in names], [3000, 3000, 3000])
		started = frappe.db.get_value(
			"Sterilization Load", frappe.db.get_value("Cost Sheet", names[0], "source_name"), "started_at"
		)
		self.assertEqual(
			daily.call_args.args[1], getdate(started)
		)  # ngày bắt đầu mẻ, không phải ngày giải phóng

	def test_build_takes_a_lock_on_the_source(self):
		"""Hai job song song cho cùng mẻ: khóa dòng nguồn trước khi kiểm bản chính (review #6)."""
		self.priced()
		load = self.load()
		with patch.object(sheet.frappe.db, "get_value", wraps=sheet.frappe.db.get_value) as get_value:
			sheet.build("Sterilization Load", load)
		self.assertTrue(
			any(
				c.kwargs.get("for_update") and c.args[:2] == ("Sterilization Load", load)
				for c in get_value.call_args_list
			)
		)

	def test_zero_rate_is_priced_not_missing(self):
		"""Đơn giá 0 đ là giá đã định, khác với thiếu giá (review FEAT-046 #4)."""
		make_cost_rate_version(
			submit=True,
			rates=[
				rate_line(ELECTRICITY, "Electricity"),
				rate_line(0, "Tap Water"),
				rate_line(LABOR, "Labor"),
			],
		)
		name = sheet.build("Sterilization Load", self.load())
		water = lines(name)["Tap Water"]
		self.assertEqual((water.amount, water.priced), (0, 1))
		self.assertEqual(frappe.db.get_value("Cost Sheet", name, "status"), "Priced")

	def test_notification_failure_keeps_the_sheet(self):
		make_cost_rate_version(submit=True, rates=[rate_line(ELECTRICITY, "Electricity")])
		self.emit.side_effect = RuntimeError("mail down")
		name = sheet.build("Sterilization Load", self.load())
		self.assertEqual(frappe.db.get_value("Cost Sheet", name, "status"), "Unpriced")

	def test_set_value_without_bom_version_uses_current_version_only(self):
		"""Gói thiếu phiên bản BOM: dùng phiên bản hiện hành, không cộng mọi phiên bản (review #4)."""
		set_type = frappe.db.get_value("Pack", self.packs[0].name, "set_type")
		frappe.db.set_value("Instrument Set Type", set_type, "current_bom_version", 2)
		code = "CS-DC-" + frappe.generate_hash(length=5).upper()
		factories.make_instrument(code)
		frappe.db.set_value("Instrument", code, "value", 100000)
		for version in (1, 2):  # mỗi phiên bản giữ đủ dòng BOM của nó
			frappe.get_doc(
				{
					"doctype": "Set BOM Item",
					"set_type": set_type,
					"bom_version": version,
					"instrument": code,
					"qty": 3,
				}
			).db_insert()
		# phiên bản 2 chỉ có dòng vừa tạo: 3 x 100.000; cộng mọi phiên bản sẽ ra từ 600.000 trở lên
		self.assertEqual(sheet._set_value(set_type, None), 300000)
		self.assertEqual(sheet._set_value(set_type, 2), 300000)


class TestUnfinishedSource(SheetCase):
	"""Job xếp sau commit vẫn chạy khi nghiệp vụ hoàn tác về savepoint (Frappe v15 không xóa after_commit khi rollback
	savepoint): mẻ chưa Giải phóng/Không đạt thì không lập Cost Sheet (review FEAT-046 #1)."""

	def test_quarantined_load_gets_no_sheet(self):
		self.priced()
		load = self.load(status="Quarantine")
		self.assertIsNone(sheet.build("Sterilization Load", load))
		self.assertFalse(frappe.db.exists("Cost Sheet", {"source_name": load}))
		self.assertFalse(frappe.db.get_value("Pack", self.packs[0].name, "cost_total"))

	def test_job_for_a_load_rolled_back_to_quarantine_writes_nothing(self):
		self.priced()
		load = self.load(status="Quarantine")
		sheet.run_job("Sterilization Load", load)
		self.assertFalse(frappe.db.exists("Cost Sheet", {"source_name": load}))
		# mẻ sau đó Không đạt thật: bản chính là chi phí chất lượng, không bị bản sai chặn trước
		frappe.db.set_value("Sterilization Load", load, "status", "Failed")
		name = sheet.build("Sterilization Load", load)
		self.assertEqual(frappe.db.get_value("Cost Sheet", name, "is_quality_cost"), 1)


class TestPackCost(SheetCase):
	def test_pack_adds_assembly_packaging_and_instrument_depreciation(self):
		label = "CS-NHAN-" + frappe.generate_hash(length=4)
		factories.make_item(label, "Chemical")
		pack = frappe.get_doc("Pack", self.packs[0].name)
		frappe.db.set_value("Instrument Set Type", pack.set_type, "assembly_minutes", 6)
		self.priced(extra=[rate_line(200, "Item", label)], pack_norms=[norm_line(pack.pack_type, label, 2)])
		with patch.object(sheet, "_set_value", return_value=300000):
			frappe.db.set_value("Set Unit", pack.set_unit, "max_cycles", 300)
			name = sheet.build("Sterilization Load", self.load())
		row = next(r for r in frappe.get_doc("Cost Sheet", name).packs if r.pack == pack.name)
		self.assertEqual(row.assembly_cost, 6 * LABOR / 60)
		self.assertEqual(row.packaging_cost, 400)
		self.assertEqual(row.instrument_depreciation, 1000)
		self.assertEqual(row.total, row.load_share + row.wash_share + 6000 + 400 + 1000)

	def test_loaner_set_has_no_instrument_depreciation(self):
		pack = frappe.get_doc("Pack", self.packs[0].name)
		frappe.db.set_value("Set Unit", pack.set_unit, "is_loaner", 1)
		self.priced()
		with patch.object(sheet, "_set_value", return_value=300000):
			name = sheet.build("Sterilization Load", self.load())
		row = next(r for r in frappe.get_doc("Cost Sheet", name).packs if r.pack == pack.name)
		self.assertEqual(row.instrument_depreciation, 0)

	def test_wash_share_from_latest_wash_batch_of_the_set(self):
		self.priced()
		pack = frappe.get_doc("Pack", self.packs[0].name)
		with patch.object(
			sheet,
			"_wash_share",
			side_effect=lambda set_unit, before, pricer=None: 700 if set_unit == pack.set_unit else 0,
		):
			name = sheet.build("Sterilization Load", self.load())
		rows = {r.pack: r for r in frappe.get_doc("Cost Sheet", name).packs}
		self.assertEqual(rows[pack.name].wash_share, 700)
		self.assertEqual(rows[self.packs[1].name].wash_share, 0)


class TestWashSheet(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		notify = patch.object(sheet, "emit")
		notify.start()
		self.addCleanup(notify.stop)

	def batch(self, ended=True):
		machine = factories.make_wash_machine()
		program = factories.make_wash_program(machine)
		batch = factories.make_wash_batch(
			machine, program, [factories.make_wash_ready_set() for _ in range(2)]
		)
		if ended:
			frappe.db.set_value("Wash Batch", batch.name, "ended_at", now_datetime())
		sets = frappe.get_all(
			"Wash Batch Set Unit", filters={"parent": batch.name}, pluck="set_unit", order_by="idx"
		)
		return batch.name, sets

	def rates(self):
		make_cost_rate_version(
			submit=True,
			rates=[
				rate_line(ELECTRICITY, "Electricity"),
				rate_line(WATER, "Tap Water"),
				rate_line(LABOR, "Labor"),
			],
		)

	def test_running_wash_batch_gets_no_sheet(self):
		self.rates()
		name, _sets = self.batch(ended=False)
		self.assertIsNone(sheet.build("Wash Batch", name))
		self.assertFalse(frappe.db.exists("Cost Sheet", {"source_name": name}))

	def test_wash_shares_sum_exactly_to_the_batch_cost(self):
		"""Phần lô rửa của các bộ cộng lại đúng tới đồng; bộ cuối lô nhận phần dư (review FEAT-046 #3)."""
		self.rates()
		name, sets = self.batch()
		cost_sheet = sheet.build("Wash Batch", name)
		frappe.db.set_value("Cost Sheet", cost_sheet, "total_cost", 10001)
		shares = [sheet._wash_share(set_unit, now_datetime()) for set_unit in sets]
		self.assertEqual(shares, [5000, 5001])

	def test_wash_batch_without_cost_sheet_marks_the_pack_unpriced(self):
		"""Lô rửa của bộ chưa có Cost Sheet (job lỗi/chưa chạy): không im lặng tính 0 đ (review FEAT-046 #3)."""
		name, sets = self.batch()
		pricer = sheet.Pricer(None)
		self.assertEqual(sheet._wash_share(sets[0], now_datetime(), pricer), 0)
		self.assertTrue(any(name in missing for missing in pricer.missing))

	def test_wash_batch_sheet_writes_batch_cost_and_share(self):
		make_cost_rate_version(
			submit=True,
			rates=[
				rate_line(ELECTRICITY, "Electricity"),
				rate_line(WATER, "Tap Water"),
				rate_line(LABOR, "Labor"),
			],
		)
		machine = factories.make_wash_machine()
		program = factories.make_wash_program(machine)
		sets = [factories.make_wash_ready_set() for _ in range(2)]
		batch = factories.make_wash_batch(machine, program, sets)
		frappe.db.set_value("Wash Batch", batch.name, "ended_at", now_datetime())
		with patch.object(sheet, "_norm_consumption", wraps=sheet._norm_consumption) as norms:
			name = sheet.build("Wash Batch", batch.name)
		# không có phiếu xuất: định mức mỗi bộ nhân số bộ của lô (như FEAT-042), không phải số gói (review #2)
		self.assertEqual(norms.call_args.args[1], 2)
		doc = frappe.get_doc("Cost Sheet", name)
		self.assertEqual(frappe.db.get_value("Wash Batch", batch.name, "cost_total"), doc.total_cost)
		set_unit = frappe.get_all("Wash Batch Set Unit", filters={"parent": batch.name}, pluck="set_unit")[0]
		self.assertEqual(sheet._wash_share(set_unit, now_datetime()), doc.total_cost // 2)
