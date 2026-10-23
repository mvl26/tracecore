from unittest.mock import patch

import frappe
from frappe.utils import get_datetime

from tracecore.core import extension
from tracecore.core.errors import BlockedError
from tracecore.instrument import maintenance
from tracecore.tests.factories import (
	make_batch,
	make_bom,
	make_instrument,
	make_item,
	make_maintenance,
	make_set_type,
	make_set_unit,
	make_user,
)
from tracecore.tests.utils import IsolatedTestCase, bru

# Set Unit, Instrument Maintenance liên kết Item, Batch, Department, User, Employee của ERPNext/HRMS;
# site CI mới chưa chạy Setup Wizard nên bỏ phụ thuộc này (dữ liệu tạo qua tracecore/tests/factories.py).
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

OIL = "DAU-MNT-001"


STAMP = "2026-10-21 08:30:00"


def _scene(*rows, type_code="MNT", bom_version=1):
	"""Loại bộ + bộ + BOM (theo thứ tự `rows`) + dòng bảo dưỡng; trả `(set_unit, ctx)`.

	rows: ``(mã dụng cụ, ngưỡng, số chu trình kể từ lần bảo dưỡng, số lần hoãn, loại bảo dưỡng)``.
	`cycles` là None thì không tạo dòng Instrument Maintenance (coi như 0).
	"""
	set_type = make_set_type(type_code)
	set_unit = make_set_unit(set_type.name)
	for code, interval, _cycles, _deferred, maint_type in rows:
		make_instrument(code, interval=interval, maint_type=maint_type)
	make_bom(set_type, [(row[0], 1) for row in rows], version=bom_version)
	for code, _interval, cycles, deferred, _maint_type in rows:
		if cycles is not None:
			make_maintenance(set_unit, code, cycles_since=cycles, deferred_count=deferred)
	return set_unit, _ctx(set_unit, set_type)


def _ctx(set_unit, set_type, actions=()):
	return {
		"set_unit": {
			"name": set_unit.name,
			"set_type": set_type.name,
			"status": "Clean",
			"cycles_used": 0,
			"max_cycles": 300,
			"active_cycle_id": None,
			"current_cycle_no": 1,
			"is_loaner": 0,
		},
		"set_type": {
			"name": set_type.name,
			"set_type_name": set_type.set_type_name,
			"method": set_type.method,
			"gtin": set_type.gtin,
			"department": None,
			"default_pack_type": None,
			"shelf_life_days": 0,
			"tray_image": None,
			"current_bom_version": set_type.current_bom_version,
		},
		"station": "T4",
		"maint_actions": list(actions),
	}


def _done(instrument, oil_batch=None):
	return {"instrument": instrument, "action": "Done", "oil_batch": oil_batch}


def _deferred(instrument, reason="Urgent surgery"):
	return {"instrument": instrument, "action": "Deferred", "reason": reason}


def _oil_lot(batch_id=OIL):
	make_item("VT-DAU-MNT", "Lubricant", has_batch_no=1)
	return make_batch("VT-DAU-MNT", batch_id).name


def _states(ctx):
	return {item["instrument"]: item["state"] for item in maintenance.pack_context(ctx)["maintenance"]}


def _row(set_unit, instrument):
	return frappe.get_doc("Instrument Maintenance", f"{set_unit.name}-{instrument}")


class TestMaintenanceContext(IsolatedTestCase):
	@bru("BRU-REP-014")
	def test_context_lists_due_instruments_only(self):
		_unit, ctx = _scene(
			("MN-A", 10, 9, 0, "Blade Check"),  # chưa đến hạn
			("MN-B", 10, 10, 0, "Lubrication"),  # đến hạn đúng ngưỡng
			("MN-C", 10, 13, 1, "Screw Tightening"),  # vượt 20 %
			("MN-D", 0, 500, 0, None),  # không khai báo ngưỡng: không bao giờ nhắc (FR-M1-09.1)
			("MN-E", 10, None, 0, "Blade Check"),  # chưa có dòng Instrument Maintenance = 0 chu trình
		)
		frappe.db.set_value(
			"Instrument", "MN-B", {"instrument_name": "Mayo scissors", "image": "/files/mn-b.png"}
		)

		result = maintenance.pack_context(ctx)

		self.assertEqual(set(result), {"maintenance"})
		self.assertEqual([item["instrument"] for item in result["maintenance"]], ["MN-B", "MN-C"])
		first, second = result["maintenance"]
		self.assertEqual(
			first,
			{
				"instrument": "MN-B",
				"instrument_name": "Mayo scissors",
				"image": "/files/mn-b.png",
				"thumbnail": None,
				"maint_type": "Lubrication",
				"interval": 10,
				"cycles_since": 10,
				"deferred_count": 0,
				"state": "due",
				"can_defer": True,
			},
		)
		self.assertEqual(
			(second["state"], second["can_defer"], second["cycles_since"], second["deferred_count"]),
			("overdue", False, 13, 1),
		)

	def test_context_follows_bom_order_and_current_version_only(self):
		set_type = make_set_type("MNV")
		set_unit = make_set_unit(set_type.name)
		for code in ("MV-1", "MV-2", "MV-3"):
			make_instrument(code, interval=5)
			make_maintenance(set_unit, code, cycles_since=5)
		make_bom(set_type, [("MV-3", 1), ("MV-1", 1)], version=1)
		make_bom(set_type, [("MV-2", 1), ("MV-3", 1)], version=2)
		# phiên bản hiện hành chỉ dịch vụ BOM ghi (FEAT-015): giả lập bằng ghi thẳng DB như các test khác
		frappe.db.set_value("Instrument Set Type", set_type.name, "current_bom_version", 2)
		set_type.reload()

		ctx = _ctx(set_unit, set_type)
		self.assertEqual(
			[item["instrument"] for item in maintenance.pack_context(ctx)["maintenance"]], ["MV-2", "MV-3"]
		)

	def test_context_counts_only_the_rows_of_this_set_unit(self):
		set_type = make_set_type("MNU")
		mine, other = make_set_unit(set_type.name), make_set_unit(set_type.name)
		make_instrument("MU-1", interval=5)
		make_bom(set_type, [("MU-1", 1)])
		make_maintenance(mine, "MU-1", cycles_since=2)
		make_maintenance(other, "MU-1", cycles_since=40, deferred_count=3)

		self.assertEqual(maintenance.pack_context(_ctx(mine, set_type))["maintenance"], [])
		self.assertEqual(_states(_ctx(other, set_type)), {"MU-1": "overdue"})

	@bru("BRU-REP-014")
	def test_overdue_threshold_integer_boundary(self):
		# so sánh bằng số nguyên cycles * 10 > interval * 12: 12/10 = 1,2 chưa vượt, 13/10 vượt
		_unit, ctx = _scene(
			("MB-10-11", 10, 11, 0, None),
			("MB-10-12", 10, 12, 0, None),
			("MB-10-13", 10, 13, 0, None),
			("MB-7-8", 7, 8, 0, None),
			("MB-7-9", 7, 9, 0, None),
			("MB-5-6", 5, 6, 0, None),
			("MB-5-7", 5, 7, 0, None),
		)
		self.assertEqual(
			_states(ctx),
			{
				"MB-10-11": "due",
				"MB-10-12": "due",
				"MB-10-13": "overdue",
				"MB-7-8": "due",
				"MB-7-9": "overdue",
				"MB-5-6": "due",
				"MB-5-7": "overdue",
			},
		)

	@bru("BRU-REP-014")
	def test_three_postponements_make_it_overdue_and_not_deferrable(self):
		_unit, ctx = _scene(("MD-2", 10, 10, 2, None), ("MD-3", 10, 10, 3, None), ("MD-4", 10, 10, 4, None))
		items = {i["instrument"]: i for i in maintenance.pack_context(ctx)["maintenance"]}
		self.assertEqual((items["MD-2"]["state"], items["MD-2"]["can_defer"]), ("due", True))
		self.assertEqual((items["MD-3"]["state"], items["MD-3"]["can_defer"]), ("overdue", False))
		self.assertEqual((items["MD-4"]["state"], items["MD-4"]["can_defer"]), ("overdue", False))

	def test_context_without_reminders_returns_empty_list(self):
		_unit, ctx = _scene(("MZ-1", 10, 3, 0, None), ("MZ-2", 0, 99, 0, None))
		self.assertEqual(maintenance.pack_context(ctx), {"maintenance": []})

	def test_context_for_set_type_without_bom_is_empty(self):
		set_type = make_set_type("MNE")
		ctx = _ctx(make_set_unit(set_type.name), set_type)
		self.assertEqual(maintenance.pack_context(ctx), {"maintenance": []})
		self.assertIsNone(maintenance.check_pack(ctx))


class TestMaintenanceCheck(IsolatedTestCase):
	def _block(self, ctx):
		block = maintenance.check_pack(ctx)
		self.assertIsNotNone(block, msg="expected a Block")
		return block

	@bru("BRU-REP-014")
	def test_due_requires_action(self):
		_unit, ctx = _scene(
			("MA-1", 10, 10, 0, "Blade Check"),
			("MA-2", 10, 11, 0, "Screw Tightening"),
			("MA-3", 10, 3, 0, "Blade Check"),  # chưa đến hạn: không đòi action
		)
		block = self._block(ctx)
		self.assertEqual(block.code, "MAINT_ACTION_REQUIRED")
		self.assertEqual(block.http_status, 422)
		self.assertTrue(block.title and block.reason and block.action)
		self.assertEqual([item["instrument"] for item in block.items], ["MA-1", "MA-2"])
		self.assertEqual(
			set(block.items[0]), {"instrument", "instrument_name", "maint_type", "state"}, msg=block.items[0]
		)

		# chỉ nêu những dụng cụ còn thiếu action
		ctx["maint_actions"] = [_done("MA-1")]
		block = self._block(ctx)
		self.assertEqual(block.code, "MAINT_ACTION_REQUIRED")
		self.assertEqual([item["instrument"] for item in block.items], ["MA-2"])

		ctx["maint_actions"] = [_done("MA-1"), _deferred("MA-2")]
		self.assertIsNone(maintenance.check_pack(ctx))

	def test_unknown_or_blank_action_counts_as_missing(self):
		_unit, ctx = _scene(("MU-1", 10, 10, 0, None), ("MU-2", 10, 10, 0, None))
		ctx["maint_actions"] = [{"instrument": "MU-1", "action": "Skip"}, {"instrument": "MU-2"}]
		block = self._block(ctx)
		self.assertEqual(block.code, "MAINT_ACTION_REQUIRED")
		self.assertEqual([item["instrument"] for item in block.items], ["MU-1", "MU-2"])

	def test_no_reminders_means_no_block(self):
		_unit, ctx = _scene(("MN-1", 10, 4, 0, None), ("MN-2", 0, 400, 0, None))
		self.assertIsNone(maintenance.check_pack(ctx))
		# action cho dụng cụ chưa đến hạn bị bỏ qua, kể cả khi không hợp lệ
		ctx["maint_actions"] = [_deferred("MN-1", reason=""), _done("MN-2")]
		self.assertIsNone(maintenance.check_pack(ctx))

	@bru("BRU-REP-014")
	def test_overdue_blocks_unless_done(self):
		_unit, ctx = _scene(("MO-1", 10, 13, 0, "Blade Check"))
		ctx["maint_actions"] = [_deferred("MO-1")]
		block = self._block(ctx)
		self.assertEqual(block.code, "MAINT_OVERDUE")
		self.assertEqual(block.http_status, 409)
		self.assertTrue(block.title and block.reason and block.action)
		self.assertEqual([item["instrument"] for item in block.items], ["MO-1"])

		ctx["maint_actions"] = [_done("MO-1")]
		self.assertIsNone(maintenance.check_pack(ctx))

		# Lubrication quá hạn: Done phải kèm lô dầu hợp lệ
		_unit, ctx = _scene(("MO-2", 10, 13, 0, "Lubrication"), type_code="MNL")
		ctx["maint_actions"] = [_done("MO-2", _oil_lot())]
		self.assertIsNone(maintenance.check_pack(ctx))

	@bru("BRU-REP-014")
	def test_three_postponements_block_further_deferral(self):
		_unit, ctx = _scene(("MT-1", 10, 10, 3, "Blade Check"))
		item = maintenance.pack_context(ctx)["maintenance"][0]
		self.assertEqual((item["state"], item["can_defer"]), ("overdue", False))

		ctx["maint_actions"] = [_deferred("MT-1")]
		self.assertEqual(self._block(ctx).code, "MAINT_OVERDUE")
		ctx["maint_actions"] = [_done("MT-1")]
		self.assertIsNone(maintenance.check_pack(ctx))

		# mới hoãn 2 lần: còn được hoãn tiếp (có lý do)
		_unit, ctx = _scene(("MT-2", 10, 10, 2, "Blade Check"), type_code="MNT2")
		item = maintenance.pack_context(ctx)["maintenance"][0]
		self.assertEqual((item["state"], item["can_defer"]), ("due", True))
		ctx["maint_actions"] = [_deferred("MT-2")]
		self.assertIsNone(maintenance.check_pack(ctx))

	def test_deferral_needs_reason(self):
		_unit, ctx = _scene(("MR-1", 10, 10, 0, "Blade Check"))
		for reason in (None, "", "   \n"):
			ctx["maint_actions"] = [{"instrument": "MR-1", "action": "Deferred", "reason": reason}]
			block = self._block(ctx)
			self.assertEqual((block.code, block.http_status), ("REASON_REQUIRED", 422), msg=repr(reason))
			self.assertEqual([item["instrument"] for item in block.items], ["MR-1"])
		ctx["maint_actions"] = [{"instrument": "MR-1", "action": "Deferred"}]
		self.assertEqual(self._block(ctx).code, "REASON_REQUIRED")
		ctx["maint_actions"] = [_deferred("MR-1", reason="  Urgent surgery ")]
		self.assertIsNone(maintenance.check_pack(ctx))

	def test_lubrication_needs_oil_lot(self):
		good = _oil_lot()
		make_item("VT-GOI-MNT", "Packaging", has_batch_no=1)
		wrong_group = make_batch("VT-GOI-MNT", "GOI-MNT-001").name
		_unit, ctx = _scene(("ML-1", 10, 10, 0, "Lubrication"))

		reasons = set()
		for oil_batch in (None, "", "  ", "NO-SUCH-LOT", wrong_group):
			ctx["maint_actions"] = [_done("ML-1", oil_batch)]
			block = self._block(ctx)
			self.assertEqual((block.code, block.http_status), ("MAINT_OIL_LOT_REQUIRED", 422), msg=oil_batch)
			self.assertTrue(block.title and block.reason and block.action)
			self.assertEqual([item["instrument"] for item in block.items], ["ML-1"])
			reasons.add(block.reason)
		# lý do nêu cụ thể: chưa nhập / không tồn tại / không phải dầu bôi trơn
		self.assertEqual(len(reasons), 3, msg=reasons)
		ctx["maint_actions"] = [_done("ML-1", "NO-SUCH-LOT")]
		self.assertIn("NO-SUCH-LOT", self._block(ctx).reason)
		ctx["maint_actions"] = [_done("ML-1", wrong_group)]
		self.assertIn(wrong_group, self._block(ctx).reason)

		ctx["maint_actions"] = [_done("ML-1", good)]
		self.assertIsNone(maintenance.check_pack(ctx))
		# mã quét có nhiễu và khác hoa/thường vẫn nhận ra lô
		ctx["maint_actions"] = [_done("ML-1", f"\r\n {good.lower()} \r\n")]
		self.assertIsNone(maintenance.check_pack(ctx))

	def test_oil_lot_only_required_for_lubrication(self):
		_unit, ctx = _scene(("MF-1", 10, 10, 0, "Blade Check"), ("MF-2", 10, 10, 0, None))
		ctx["maint_actions"] = [_done("MF-1"), _done("MF-2", "NO-SUCH-LOT")]
		self.assertIsNone(maintenance.check_pack(ctx))

	def test_check_reports_first_problem_in_documented_order(self):
		_unit, ctx = _scene(
			("MQ-1", 10, 10, 0, "Blade Check"),  # sẽ thiếu action
			("MQ-2", 10, 13, 0, "Blade Check"),  # quá hạn, bị hoãn
			("MQ-3", 10, 10, 0, "Blade Check"),  # hoãn thiếu lý do
			("MQ-4", 10, 10, 0, "Lubrication"),  # Done thiếu lô dầu
		)
		ctx["maint_actions"] = [
			_deferred("MQ-2"),
			_deferred("MQ-3", reason=""),
			_done("MQ-4"),
		]
		self.assertEqual(self._block(ctx).code, "MAINT_ACTION_REQUIRED")
		ctx["maint_actions"].append(_done("MQ-1"))
		self.assertEqual(self._block(ctx).code, "MAINT_OVERDUE")
		ctx["maint_actions"][0] = _done("MQ-2")
		self.assertEqual(self._block(ctx).code, "REASON_REQUIRED")
		ctx["maint_actions"][1] = _deferred("MQ-3")
		self.assertEqual(self._block(ctx).code, "MAINT_OIL_LOT_REQUIRED")
		ctx["maint_actions"][2] = _done("MQ-4", _oil_lot())
		self.assertIsNone(maintenance.check_pack(ctx))

	def test_check_uses_maintenance_already_in_ctx(self):
		_unit, ctx = _scene(("MC-1", 10, 10, 0, "Blade Check"))
		ctx.update(maintenance.pack_context(ctx))
		self.assertEqual(self._block(ctx).code, "MAINT_ACTION_REQUIRED")
		# ngữ cảnh đã gộp là bản chụp người dùng thấy: danh sách rỗng nghĩa là không có gì đến hạn
		ctx["maintenance"] = []
		self.assertIsNone(maintenance.check_pack(ctx))


class TestMaintenanceApply(IsolatedTestCase):
	@bru("BRU-REP-014")
	def test_apply_done_resets_counter(self):
		unit, ctx = _scene(
			("MP-1", 10, 12, 2, "Lubrication"),
			("MP-2", 10, 5, 1, "Blade Check"),  # chưa đến hạn: giữ nguyên
		)
		# thời điểm cố định: không so với đồng hồ thật (đồng hồ WSL có thể lùi khi đồng bộ, test từng fail ngẫu nhiên)
		stamp = get_datetime(STAMP)
		ctx["maint_actions"] = [_done("MP-1", _oil_lot())]

		with patch.object(maintenance, "now_datetime", return_value=stamp):
			self.assertIsNone(maintenance.apply_pack(None, ctx))

		row = _row(unit, "MP-1")
		self.assertEqual((row.cycles_since_maint, row.deferred_count), (0, 0))
		self.assertEqual(row.last_maint_by, frappe.session.user)
		self.assertEqual(row.last_oil_batch, OIL)
		self.assertEqual(get_datetime(row.last_maint_on), stamp)
		self.assertFalse(row.last_defer_on)
		untouched = _row(unit, "MP-2")
		self.assertEqual((untouched.cycles_since_maint, untouched.deferred_count), (5, 1))
		# sau Đã bảo dưỡng thì không còn nhắc
		self.assertEqual(maintenance.pack_context(ctx)["maintenance"], [])
		# thay đổi có Audit Log
		self.assertTrue(
			frappe.db.exists(
				"Audit Log",
				{"ref_doctype": "Instrument Maintenance", "ref_name": row.name, "action": "Update"},
			)
		)

	def test_apply_done_stores_canonical_oil_batch_only_for_lubrication(self):
		unit, ctx = _scene(("MK-1", 10, 10, 0, "Lubrication"), ("MK-2", 10, 10, 0, "Blade Check"))
		good = _oil_lot()
		ctx["maint_actions"] = [_done("MK-1", f" {good.lower()}\r\n"), _done("MK-2", good)]
		maintenance.apply_pack(None, ctx)
		self.assertEqual(_row(unit, "MK-1").last_oil_batch, good)
		self.assertFalse(_row(unit, "MK-2").last_oil_batch)

	@bru("BRU-REP-014")
	def test_apply_deferred_increments(self):
		unit, ctx = _scene(("MI-1", 10, 11, 1, "Blade Check"))
		stamp = get_datetime(STAMP)
		ctx["maint_actions"] = [_deferred("MI-1", reason="  Urgent surgery  ")]

		with patch.object(maintenance, "now_datetime", return_value=stamp):
			maintenance.apply_pack(None, ctx)

		row = _row(unit, "MI-1")
		self.assertEqual((row.cycles_since_maint, row.deferred_count), (11, 2))
		self.assertEqual(row.last_defer_reason, "Urgent surgery")
		self.assertEqual(get_datetime(row.last_defer_on), stamp)
		self.assertFalse(row.last_maint_on)
		# hoãn lần 3 rồi thì chặn hoãn tiếp
		ctx["maint_actions"] = [_deferred("MI-1")]
		maintenance.apply_pack(None, ctx)
		self.assertEqual(_row(unit, "MI-1").deferred_count, 3)
		self.assertEqual(maintenance.check_pack(ctx).code, "MAINT_OVERDUE")

	def test_apply_ignores_actions_for_instruments_not_due(self):
		unit, ctx = _scene(("MJ-1", 10, 4, 1, "Blade Check"), ("MJ-2", 0, 99, 0, None))
		ctx["maint_actions"] = [_done("MJ-1"), _deferred("MJ-2"), _done("MJ-NOT-IN-BOM")]
		maintenance.apply_pack(None, ctx)
		self.assertEqual((_row(unit, "MJ-1").cycles_since_maint, _row(unit, "MJ-1").deferred_count), (4, 1))
		self.assertEqual(_row(unit, "MJ-2").deferred_count, 0)
		self.assertFalse(frappe.db.exists("Instrument Maintenance", f"{unit.name}-MJ-NOT-IN-BOM"))

	def test_apply_without_actions_changes_nothing(self):
		unit, ctx = _scene(("MG-1", 10, 10, 1, "Blade Check"))
		maintenance.apply_pack(None, ctx)
		row = _row(unit, "MG-1")
		self.assertEqual((row.cycles_since_maint, row.deferred_count), (10, 1))
		self.assertFalse(
			frappe.db.exists("Audit Log", {"ref_name": row.name, "action": "Update"}),
			msg="no change, no audit row",
		)

	def test_apply_skips_due_instrument_without_valid_action(self):
		unit, ctx = _scene(("MS-1", 10, 10, 0, "Blade Check"))
		ctx["maint_actions"] = [{"instrument": "MS-1", "action": "Skip"}]
		maintenance.apply_pack(None, ctx)
		row = _row(unit, "MS-1")
		self.assertEqual((row.cycles_since_maint, row.deferred_count), (10, 0))

	def test_apply_creates_missing_row_from_snapshot(self):
		set_type = make_set_type("MNC")
		unit = make_set_unit(set_type.name)
		make_instrument("MX-1", interval=10, maint_type="Blade Check")
		make_bom(set_type, [("MX-1", 1)])
		ctx = _ctx(unit, set_type, [_deferred("MX-1")])
		# bản chụp ngữ cảnh có nhắc cho dụng cụ chưa có dòng bảo dưỡng
		ctx["maintenance"] = [
			{
				"instrument": "MX-1",
				"instrument_name": "x",
				"image": None,
				"maint_type": "Blade Check",
				"interval": 10,
				"cycles_since": 10,
				"deferred_count": 0,
				"state": "due",
				"can_defer": True,
			}
		]
		self.assertFalse(frappe.db.exists("Instrument Maintenance", f"{unit.name}-MX-1"))

		maintenance.apply_pack(None, ctx)

		row = _row(unit, "MX-1")
		self.assertEqual((row.set_unit, row.instrument, row.deferred_count), (unit.name, "MX-1", 1))
		self.assertTrue(
			frappe.db.exists(
				"Audit Log",
				{"ref_doctype": "Instrument Maintenance", "ref_name": row.name, "action": "Create"},
			)
		)

	def test_apply_works_for_users_without_write_permission(self):
		unit, ctx = _scene(("MW-1", 10, 10, 0, "Blade Check"))
		ctx["maint_actions"] = [_done("MW-1")]
		packer = make_user("maint.packer@example.com", ["TC R04"])
		original = frappe.session.user
		try:
			frappe.set_user(packer)
			maintenance.apply_pack(None, ctx)
		finally:
			frappe.set_user(original)
		row = _row(unit, "MW-1")
		self.assertEqual((row.cycles_since_maint, row.last_maint_by), (0, packer))

	def test_apply_refuses_invalid_oil_lot(self):
		unit, ctx = _scene(("MY-1", 10, 10, 0, "Lubrication"))
		ctx["maint_actions"] = [_done("MY-1", "NO-SUCH-LOT")]
		with self.assertRaises(BlockedError) as raised:
			maintenance.apply_pack(None, ctx)
		self.assertEqual(raised.exception.block.code, "MAINT_OIL_LOT_REQUIRED")
		self.assertEqual(_row(unit, "MY-1").cycles_since_maint, 10)


class TestPackHooks(IsolatedTestCase):
	def test_hooks_registered(self):
		expected = {
			"tracecore_pack_context": [
				"tracecore.instrument.bom.pack_context",
				"tracecore.instrument.maintenance.pack_context",
				"tracecore.par.check.pack_context",
			],
			"tracecore_pack_prechecks": ["tracecore.par.check.check_pack"],
			"tracecore_pack_checks": ["tracecore.instrument.maintenance.check_pack"],
			"tracecore_after_cycle_id": [
				"tracecore.instrument.maintenance.apply_pack",
				"tracecore.par.override.consume",
			],
		}
		for hook, paths in expected.items():
			registered = frappe.get_hooks(hook, app_name="tracecore")
			self.assertEqual(list(registered), paths, msg=hook)
			for path in paths:
				self.assertTrue(callable(frappe.get_attr(path)), msg=path)

	def test_hooks_run_through_extension(self):
		"""M2 chỉ biết tên hook (`core.extension.run`), không import M1/M8."""
		unit, ctx = _scene(
			("MH-1", 10, 10, 0, "Blade Check"),
			("MH-2", 10, 3, 0, "Blade Check"),
		)
		ctx["set_unit"]["cycles_used"] = 270
		ctx["set_type"]["tray_image"] = "/files/tray.png"
		real_get_hooks = frappe.get_hooks

		def own_hooks(hook, *args, **kwargs):
			# đọc thẳng hooks.py của app: không phụ thuộc cache hook còn từ trước khi sửa hooks.py
			return real_get_hooks(hook, app_name="tracecore")

		with patch("frappe.get_hooks", side_effect=own_hooks):
			merged = {}
			for part in extension.run("tracecore_pack_context", ctx):
				merged.update(part)
			self.assertEqual(
				set(merged),
				{"bom", "bom_version", "tray_image", "tray_images", "maintenance", "par"},
				msg=sorted(merged),
			)
			self.assertEqual(merged["par"]["state"], "warn")
			self.assertEqual([row["instrument"] for row in merged["bom"]], ["MH-1", "MH-2"])
			self.assertEqual([item["instrument"] for item in merged["maintenance"]], ["MH-1"])
			self.assertEqual(merged["tray_image"], "/files/tray.png")

			self.assertEqual(extension.run("tracecore_pack_prechecks", ctx), [])
			blocks = extension.run("tracecore_pack_checks", ctx)
			self.assertEqual([block.code for block in blocks], ["MAINT_ACTION_REQUIRED"])

			ctx["maint_actions"] = [_deferred("MH-1")]
			self.assertEqual(extension.run("tracecore_pack_checks", ctx), [])
			self.assertEqual(extension.run("tracecore_after_cycle_id", None, ctx), [])
		self.assertEqual(_row(unit, "MH-1").deferred_count, 1)
