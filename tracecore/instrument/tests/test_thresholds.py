"""Ngưỡng bảo dưỡng hiệu lực theo dụng cụ/nhóm, cảnh báo khi đổi ngưỡng, khởi tạo và tăng bộ đếm.

FEAT-014 Task 4; FR-M1-09 (.1, .2), BRU-REP-014; A-06 I5, I6, I16; Review Focus 4.
"""

import frappe
from frappe.utils import add_days, get_datetime, getdate, now_datetime, today

from tracecore.core import extension
from tracecore.core.errors import BlockedError
from tracecore.instrument import maintenance, thresholds
from tracecore.instrument.tests.test_maintenance import _ctx, _deferred
from tracecore.tests.factories import (
	make_bom,
	make_instrument,
	make_instrument_group,
	make_maintenance,
	make_set_type,
	make_set_unit,
)
from tracecore.tests.utils import IsolatedTestCase, bru

# Set Unit, Instrument Maintenance liên kết Item, Batch, Department, User, Employee của ERPNext/HRMS;
# site CI mới chưa chạy Setup Wizard nên bỏ phụ thuộc này (dữ liệu tạo qua tracecore/tests/factories.py).
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def _scene(type_code, lines, counters=None):
	"""Loại bộ + một bộ + BOM `lines` [(mã, qty)]; `counters` {mã: (chu trình, số lần hoãn)}; trả (bộ, loại bộ)."""
	set_type = make_set_type(type_code)
	set_unit = make_set_unit(set_type.name)
	make_bom(set_type, lines)
	for code, (cycles, deferred) in (counters or {}).items():
		make_maintenance(set_unit, code, cycles_since=cycles, deferred_count=deferred)
	return set_unit, set_type


def _counter(set_unit, instrument):
	return frappe.db.get_value(
		"Instrument Maintenance",
		{"set_unit": getattr(set_unit, "name", set_unit), "instrument": instrument},
		["cycles_since_maint", "deferred_count"],
	)


def _orange_messages():
	messages = [frappe.parse_json(m) if isinstance(m, str) else m for m in frappe.get_message_log()]
	return [m for m in messages if isinstance(m, dict) and m.get("indicator") == "orange"]


def _pairs(rows):
	return {(row["set_unit"], row["instrument"]): row["state"] for row in rows}


class TestEffectiveRules(IsolatedTestCase):
	@bru("BRU-REP-014")
	def test_effective_rule_instrument_over_group(self):
		make_instrument_group("TH-G30", interval=30, maint_type="Blade Check")
		make_instrument("TH-OWN", interval=50, maint_type="Lubrication", group="TH-G30")
		make_instrument("TH-INH", group="TH-G30")

		rules = thresholds.effective_rules(["TH-OWN", "TH-INH", "TH-OWN"])

		self.assertEqual(
			rules,
			{
				"TH-OWN": {"interval": 50, "maint_type": "Lubrication", "source": "Instrument"},
				"TH-INH": {"interval": 30, "maint_type": "Blade Check", "source": "Group"},
			},
		)

	@bru("BRU-REP-014")
	def test_blank_threshold_everywhere_no_reminder(self):
		make_instrument_group("TH-G0")
		make_instrument("TH-NONE", group="TH-G0")
		make_instrument("TH-NOGRP")
		self.assertEqual(thresholds.effective_rules(["TH-NONE", "TH-NOGRP", "TH-MISSING"]), {})
		self.assertEqual(thresholds.effective_rules([]), {})

		set_unit, set_type = _scene(
			"THN", [("TH-NONE", 1), ("TH-NOGRP", 1)], {"TH-NONE": (500, 0), "TH-NOGRP": (500, 3)}
		)
		ctx = _ctx(set_unit, set_type)
		self.assertEqual(maintenance.pack_context(ctx), {"maintenance": []})
		self.assertIsNone(maintenance.check_pack(ctx))

	@bru("BRU-REP-014")
	def test_t4_reminder_uses_group_threshold(self):
		make_instrument_group("TH-G10", interval=10, maint_type="Screw Tightening")
		for code in ("TH-GA", "TH-GB", "TH-GC", "TH-GD", "TH-GE"):
			make_instrument(code, group="TH-G10")
		set_unit, set_type = _scene(
			"THG",
			[("TH-GA", 1), ("TH-GB", 1), ("TH-GC", 2), ("TH-GD", 1), ("TH-GE", 1)],
			{
				"TH-GA": (10, 0),  # đúng ngưỡng nhóm: đến hạn
				"TH-GB": (13, 0),  # vượt 20 %: quá hạn
				"TH-GC": (12, 0),  # đúng 120 %: vẫn chỉ đến hạn
				"TH-GD": (9, 0),  # chưa đến hạn
				"TH-GE": (10, 3),  # hoãn đủ 3 lần: quá hạn
			},
		)
		ctx = _ctx(set_unit, set_type)

		reminders = maintenance.pack_context(ctx)["maintenance"]

		self.assertEqual(
			{item["instrument"]: item["state"] for item in reminders},
			{"TH-GA": "due", "TH-GB": "overdue", "TH-GC": "due", "TH-GE": "overdue"},
		)
		self.assertEqual({item["interval"] for item in reminders}, {10})
		self.assertEqual({item["maint_type"] for item in reminders}, {"Screw Tightening"})

		deferred = _ctx(
			set_unit, set_type, [_deferred(code) for code in ("TH-GA", "TH-GB", "TH-GC", "TH-GE")]
		)
		block = maintenance.check_pack(deferred)
		self.assertEqual(block.code, "MAINT_OVERDUE")
		self.assertEqual([item["instrument"] for item in block.items], ["TH-GB", "TH-GE"])


class TestThresholdChanges(IsolatedTestCase):
	def test_threshold_edit_keeps_counters_and_warns(self):
		make_instrument("TH-EDIT", interval=50, maint_type="Blade Check")
		overdue, due, fine = make_set_unit(), make_set_unit(), make_set_unit()
		make_maintenance(overdue, "TH-EDIT", cycles_since=25, deferred_count=1)
		make_maintenance(due, "TH-EDIT", cycles_since=21)
		make_maintenance(fine, "TH-EDIT", cycles_since=10)
		frappe.clear_messages()

		doc = frappe.get_doc("Instrument", "TH-EDIT")
		doc.maint_interval_cycles = 20
		doc.save()

		# không reset bộ đếm (Review Focus 4)
		self.assertEqual(_counter(overdue, "TH-EDIT"), (25, 1))
		self.assertEqual(_counter(due, "TH-EDIT"), (21, 0))
		self.assertEqual(_counter(fine, "TH-EDIT"), (10, 0))
		expected = {(overdue.name, "TH-EDIT"): "overdue", (due.name, "TH-EDIT"): "due"}
		self.assertEqual(_pairs(doc.flags.tc_affected_counters), expected)
		self.assertEqual(_pairs(thresholds.affected_counters(instrument="TH-EDIT")), expected)
		messages = _orange_messages()
		self.assertEqual(len(messages), 1)
		self.assertIn(overdue.name, messages[0]["message"])
		self.assertIn(due.name, messages[0]["message"])
		self.assertNotIn(fine.name, messages[0]["message"])

		# tăng ngưỡng: không bộ nào chuyển sang đến hạn, không cảnh báo
		frappe.clear_messages()
		doc = frappe.get_doc("Instrument", "TH-EDIT")
		doc.maint_interval_cycles = 100
		doc.save()
		self.assertEqual(doc.flags.tc_affected_counters, [])
		self.assertEqual(_orange_messages(), [])
		self.assertEqual(_counter(overdue, "TH-EDIT"), (25, 1))

		# sửa trường khác: không tính lại
		frappe.clear_messages()
		doc = frappe.get_doc("Instrument", "TH-EDIT")
		doc.manufacturer = "Aesculap"
		doc.save()
		self.assertIsNone(doc.flags.tc_affected_counters)

	def test_group_change_warns_affected_sets(self):
		make_instrument_group("TH-GRA", interval=50, maint_type="Blade Check")
		make_instrument_group("TH-GRB", interval=20, maint_type="Lubrication")
		make_instrument("TH-MOVE", group="TH-GRA")
		make_instrument("TH-STAY", group="TH-GRA")
		make_instrument("TH-OWNR", interval=50, group="TH-GRA")
		set_unit = make_set_unit()
		make_maintenance(set_unit, "TH-MOVE", cycles_since=25)
		make_maintenance(set_unit, "TH-STAY", cycles_since=22)
		make_maintenance(set_unit, "TH-OWNR", cycles_since=25)
		frappe.clear_messages()

		# dụng cụ đổi nhóm: theo ngưỡng nhóm mới
		doc = frappe.get_doc("Instrument", "TH-MOVE")
		doc.instrument_group = "TH-GRB"
		doc.save()
		self.assertEqual(_pairs(doc.flags.tc_affected_counters), {(set_unit.name, "TH-MOVE"): "overdue"})
		self.assertEqual(len(_orange_messages()), 1)
		self.assertEqual(_counter(set_unit, "TH-MOVE"), (25, 0))

		# nhóm giảm ngưỡng: chỉ dụng cụ thừa hưởng ngưỡng nhóm (TH-OWNR có ngưỡng riêng)
		frappe.clear_messages()
		group = frappe.get_doc("Instrument Group", "TH-GRA")
		group.maint_interval_cycles = 20
		group.save()
		self.assertEqual(_pairs(group.flags.tc_affected_counters), {(set_unit.name, "TH-STAY"): "due"})
		messages = _orange_messages()
		self.assertEqual(len(messages), 1)
		self.assertIn("TH-STAY", messages[0]["message"])
		self.assertNotIn("TH-OWNR", messages[0]["message"])
		self.assertEqual(_counter(set_unit, "TH-STAY"), (22, 0))

		# quy tắc giả định: nhóm 10 → TH-STAY vượt 20 %
		self.assertEqual(
			_pairs(thresholds.affected_counters(group="TH-GRA", new_rule={"interval": 10})),
			{(set_unit.name, "TH-STAY"): "overdue"},
		)
		self.assertEqual(thresholds.affected_counters(group="TH-GRA", new_rule={"interval": 0}), [])
		self.assertEqual(thresholds.affected_counters(), [])


class TestInitCounter(IsolatedTestCase):
	def _setup(self, code="TH-INIT", type_code="THI"):
		make_instrument(code, interval=40, maint_type="Blade Check")
		set_unit, set_type = _scene(type_code, [(code, 1)])
		return set_unit, set_type

	def _code(self, call):
		with self.assertRaises(BlockedError) as raised:
			call()
		return raised.exception.block.code

	@bru("BRU-REP-014")
	def test_init_counter_from_last_maintenance(self):
		set_unit, set_type = self._setup()

		name = maintenance.init_counter(
			set_unit.name, "TH-INIT", 37, getdate("2026-09-01"), "  Sổ bảo dưỡng giấy  "
		)

		row = frappe.get_doc("Instrument Maintenance", name)
		self.assertEqual((row.set_unit, row.instrument), (set_unit.name, "TH-INIT"))
		self.assertEqual((row.cycles_since_maint, row.deferred_count), (37, 0))
		self.assertEqual(get_datetime(row.last_maint_on), get_datetime("2026-09-01 00:00:00"))
		self.assertFalse(row.last_maint_by)
		audit = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "Instrument Maintenance", "ref_name": name, "action": "Create"},
			fields=["reason", "new_value"],
		)
		self.assertEqual(len(audit), 1)
		self.assertEqual(audit[0].reason, "Sổ bảo dưỡng giấy")
		self.assertEqual(frappe.parse_json(audit[0].new_value)["cycles_since_maint"], 37)

		# nhắc T4 tính từ 37: 3 lần giải phóng nữa thì đến hạn (ngưỡng 40)
		ctx = _ctx(set_unit, set_type)
		self.assertEqual(maintenance.pack_context(ctx)["maintenance"], [])
		release = {"set_unit": set_unit.name, "set_type": set_type.name, "bom_version": 1}
		for _i in range(3):
			maintenance.on_set_released(release)
		reminders = maintenance.pack_context(ctx)["maintenance"]
		self.assertEqual([(item["cycles_since"], item["state"]) for item in reminders], [(40, "due")])

		# chưa có lịch sử T4: khởi tạo lại được (sửa nhập sai), Audit Log Update có lý do
		maintenance.init_counter(set_unit.name, "TH-INIT", 12, None, "Nhập sai")
		self.assertEqual(_counter(set_unit, "TH-INIT"), (12, 0))
		update = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "Instrument Maintenance", "ref_name": name, "action": "Update"},
			fields=["reason"],
			order_by="name desc",
			limit=1,
		)
		self.assertEqual(update[0].reason, "Nhập sai")

	def test_init_counter_rejected_after_t4_history_or_out_of_bom(self):
		set_unit, _set_type = self._setup("TH-HIST", "THH")
		now = now_datetime()
		histories = (
			{"last_defer_on": now},
			{"deferred_count": 1},
			{"last_maint_on": now, "last_maint_by": "Administrator"},
		)
		for index, history in enumerate(histories):
			unit = make_set_unit(_set_type.name)
			row = make_maintenance(unit, "TH-HIST", cycles_since=3)
			row.update(history)
			row.flags.tc_maintenance = True
			row.save()
			code = self._code(lambda unit=unit: maintenance.init_counter(unit.name, "TH-HIST", 5, None, "x"))
			self.assertEqual(code, "COUNTER_INIT_INVALID", index)
			self.assertEqual(_counter(unit, "TH-HIST")[0], 3)

		# bộ không chứa dụng cụ trong BOM hiện hành (bộ khác loại, hoặc chỉ ở phiên bản BOM cũ)
		other_unit, _other = _scene("THX", [("TH-OTHER", 1)])
		self.assertEqual(
			self._code(lambda: maintenance.init_counter(other_unit.name, "TH-HIST", 5, None, "x")),
			"COUNTER_INIT_INVALID",
		)
		# phiên bản hiệu lực tính từ dòng BOM (FEAT-015 S1) nên không bật/tắt current_bom_version được nữa: dùng một loại
		# bộ riêng có v2 (hiệu lực hôm nay) bỏ TH-HIST; bộ chưa ghim phiên bản dùng v2
		old_unit, old_type = _scene("THV", [("TH-HIST", 1)])
		make_bom(old_type, [("TH-OTHER", 1)], version=2)
		self.assertEqual(
			self._code(lambda: maintenance.init_counter(old_unit.name, "TH-HIST", 5, None, "x")),
			"COUNTER_INIT_INVALID",
		)

		for value in (-1, 10000, "abc", 3.5, True, None):
			self.assertEqual(
				self._code(
					lambda value=value: maintenance.init_counter(set_unit.name, "TH-HIST", value, None, "x")
				),
				"COUNTER_INIT_INVALID",
				repr(value),
			)
		self.assertEqual(
			self._code(
				lambda: maintenance.init_counter(
					set_unit.name, "TH-HIST", 5, getdate(add_days(today(), 1)), "x"
				)
			),
			"COUNTER_INIT_INVALID",
		)
		self.assertEqual(
			self._code(lambda: maintenance.init_counter(set_unit.name, "TH-HIST", 5, "not a date", "x")),
			"COUNTER_INIT_INVALID",
		)
		for blank in ("", "   ", None):
			self.assertEqual(
				self._code(
					lambda blank=blank: maintenance.init_counter(set_unit.name, "TH-HIST", 5, None, blank)
				),
				"REASON_REQUIRED",
			)
		self.assertEqual(
			self._code(lambda: maintenance.init_counter("SU-NONE", "TH-HIST", 5, None, "x")), "SET_NOT_FOUND"
		)
		self.assertEqual(
			self._code(lambda: maintenance.init_counter(set_unit.name, "TH-NOPE", 5, None, "x")),
			"INSTRUMENT_NOT_FOUND",
		)
		self.assertIsNone(_counter(set_unit, "TH-HIST"))

		# biên hợp lệ
		maintenance.init_counter(set_unit.name, "TH-HIST", 0, None, "x")
		maintenance.init_counter(set_unit.name, "TH-HIST", "9999", today(), "x")
		self.assertEqual(_counter(set_unit, "TH-HIST"), (9999, 0))

	def test_init_counter_rejects_odd_numbers_without_crashing(self):
		# '²', '①' qua được str.isdigit() nhưng int() lỗi; chuỗi > 4300 chữ số làm int() lỗi → phải là 422, không 500
		set_unit, _set_type = self._setup("TH-ODD", "THO")
		for value in (
			"²",
			"①",
			"٣",
			"1" * 5000,
			10**5000,
			-1,
			"-1",
			" -5 ",
			True,
			False,
			chr(0xFF11) + chr(0xFF12),  # chữ số toàn độ rộng: isdecimal() nhưng không ASCII
			"0000001",
		):
			self.assertEqual(
				self._code(
					lambda value=value: maintenance.init_counter(set_unit.name, "TH-ODD", value, None, "x")
				),
				"COUNTER_INIT_INVALID",
				type(value).__name__ if isinstance(value, int) else value[:40],
			)
		self.assertIsNone(_counter(set_unit, "TH-ODD"))
		maintenance.init_counter(set_unit.name, "TH-ODD", " 0042 ", None, "x")
		self.assertEqual(_counter(set_unit, "TH-ODD"), (42, 0))

	def test_init_counter_concurrent_first_insert(self):
		# request song song vừa tạo dòng (chưa có lịch sử T4) giữa lúc kiểm và lúc insert → không DuplicateEntryError
		from unittest.mock import patch

		set_unit, _set_type = self._setup("TH-RACE", "THQ")
		real = maintenance._counter_name
		calls = []

		def racing(unit, instrument, for_update=False):
			if not calls:
				calls.append(1)
				make_maintenance(set_unit, "TH-RACE", cycles_since=3)
				return None
			return real(unit, instrument, for_update=for_update)

		with patch.object(maintenance, "_counter_name", side_effect=racing):
			name = maintenance.init_counter(set_unit.name, "TH-RACE", 7, None, "x")
		self.assertEqual(name, f"{set_unit.name}-TH-RACE")
		self.assertEqual(_counter(set_unit, "TH-RACE"), (7, 0))

		# dòng song song đã có lịch sử T4 → vẫn bị chặn như bình thường
		other = make_set_unit(_set_type.name)
		calls.clear()

		def racing_history(unit, instrument, for_update=False):
			if not calls:
				calls.append(1)
				make_maintenance(other, "TH-RACE", cycles_since=3, deferred_count=1)
				return None
			return real(unit, instrument, for_update=for_update)

		with patch.object(maintenance, "_counter_name", side_effect=racing_history):
			code = self._code(lambda: maintenance.init_counter(other.name, "TH-RACE", 7, None, "x"))
		self.assertEqual(code, "COUNTER_INIT_INVALID")
		self.assertEqual(_counter(other, "TH-RACE"), (3, 1))

	@bru("BRU-REP-014")
	def test_init_counter_rejected_after_counted_release(self):
		# lần giải phóng đã đếm (last_release_cycle) là lịch sử: khởi tạo không được ghi đè số đã đếm (I6)
		set_unit, set_type = self._setup("TH-REL", "THL")
		# trước mọi lần giải phóng: khởi tạo được (luồng I6 không đổi)
		maintenance.init_counter(set_unit.name, "TH-REL", 10, None, "Sổ giấy")
		release = {
			"set_unit": set_unit.name,
			"set_type": set_type.name,
			"bom_version": 1,
			"cycle_id": "CY-REL-1",
		}
		maintenance.on_set_released(release)
		self.assertEqual(_counter(set_unit, "TH-REL"), (11, 0))
		self.assertEqual(
			self._code(lambda: maintenance.init_counter(set_unit.name, "TH-REL", 2, None, "x")),
			"COUNTER_INIT_INVALID",
		)
		self.assertEqual(_counter(set_unit, "TH-REL"), (11, 0))
		# dòng do lần giải phóng tạo (chưa khởi tạo) cũng vậy; form không mời khởi tạo
		other = make_set_unit(set_type.name)
		maintenance.on_set_released({**release, "set_unit": other.name, "cycle_id": "CY-REL-2"})
		self.assertEqual(
			self._code(lambda: maintenance.init_counter(other.name, "TH-REL", 0, None, "x")),
			"COUNTER_INIT_INVALID",
		)
		rule = thresholds.effective_rules(["TH-REL"]).get("TH-REL")
		can_init = {
			row["set_unit"]: row["can_init"] for row in maintenance.instrument_counters("TH-REL", rule)
		}
		self.assertEqual(can_init, {set_unit.name: False, other.name: False})

	def test_init_counter_allowed_on_retired_instrument(self):
		# quyết định: dụng cụ Ngừng sử dụng vẫn khởi tạo được (bộ còn chứa nó trong BOM hiện hành, nhập bù sổ giấy)
		from tracecore.instrument import catalog

		set_unit, _set_type = self._setup("TH-RET", "THT")
		catalog.retire("TH-RET", "Hỏng", confirm=1)
		maintenance.init_counter(set_unit.name, "TH-RET", 6, None, "Sổ cũ")
		self.assertEqual(_counter(set_unit, "TH-RET"), (6, 0))


class TestSetReleased(IsolatedTestCase):
	@bru("BRU-REP-014")
	def test_on_set_released_increments_each_instrument_once(self):
		make_instrument_group("TH-RG", interval=10, maint_type="Blade Check")
		make_instrument("TH-R1", interval=5)
		make_instrument("TH-R2", group="TH-RG")
		make_instrument("TH-R3")  # không ngưỡng
		set_unit, set_type = _scene("THR", [("TH-R1", 2), ("TH-R3", 1), ("TH-R2", 1)], {"TH-R1": (4, 2)})
		release = {"set_unit": set_unit.name, "set_type": set_type.name, "bom_version": 1}

		maintenance.on_set_released(release)

		self.assertEqual(_counter(set_unit, "TH-R1"), (5, 2))  # qty 2 → +1 một lần, giữ số lần hoãn
		self.assertEqual(_counter(set_unit, "TH-R2"), (1, 0))  # chưa có dòng → tạo với 1
		self.assertIsNone(_counter(set_unit, "TH-R3"))
		maintenance.on_set_released(release)
		self.assertEqual(_counter(set_unit, "TH-R1"), (6, 2))
		self.assertEqual(_counter(set_unit, "TH-R2"), (2, 0))

		# BOM áp dụng của gói (bom_version trong ctx), không phải BOM hiện hành
		make_bom(set_type, [("TH-R3", 1)], version=2)
		frappe.db.set_value("Instrument Set Type", set_type.name, "current_bom_version", 2)
		maintenance.on_set_released(release)
		self.assertEqual(_counter(set_unit, "TH-R1"), (7, 2))
		updates = frappe.db.count(
			"Audit Log",
			{
				"ref_doctype": "Instrument Maintenance",
				"ref_name": f"{set_unit.name}-TH-R1",
				"action": "Update",
			},
		)
		self.assertEqual(updates, 3)

	def test_after_release_hook_registered(self):
		self.assertIn(
			"tracecore.instrument.maintenance.on_set_released", frappe.get_hooks("tracecore_after_release")
		)
		make_instrument("TH-HK", interval=3)
		set_unit, set_type = _scene("THK", [("TH-HK", 1)])
		extension.run(
			"tracecore_after_release",
			{"set_unit": set_unit.name, "set_type": set_type.name, "bom_version": 1},
		)
		self.assertEqual(_counter(set_unit, "TH-HK"), (1, 0))

	@bru("BRU-REP-014")
	def test_on_set_released_same_cycle_counts_once(self):
		# FEAT-023 gọi lại bước giải phóng cho cùng Cycle ID → mỗi dụng cụ chỉ +1 một lần
		make_instrument("TH-C1", interval=5)
		make_instrument("TH-C2", interval=8)
		set_unit, set_type = _scene("THC", [("TH-C1", 1), ("TH-C2", 1)], {"TH-C1": (2, 1)})
		release = {
			"set_unit": set_unit.name,
			"set_type": set_type.name,
			"bom_version": 1,
			"cycle_id": "CY-0001",
		}

		maintenance.on_set_released(release)
		maintenance.on_set_released(dict(release))

		self.assertEqual(_counter(set_unit, "TH-C1"), (3, 1))
		self.assertEqual(_counter(set_unit, "TH-C2"), (1, 0))  # dòng mới cũng ghi Cycle ID
		self.assertEqual(
			frappe.db.get_value(
				"Instrument Maintenance",
				{"set_unit": set_unit.name, "instrument": "TH-C2"},
				"last_release_cycle",
			),
			"CY-0001",
		)

		# Cycle ID khác → tăng tiếp, rồi gọi lại Cycle ID mới đó cũng chỉ đếm một lần
		maintenance.on_set_released({**release, "cycle_id": "CY-0002"})
		maintenance.on_set_released({**release, "cycle_id": "CY-0002"})
		self.assertEqual(_counter(set_unit, "TH-C1"), (4, 1))
		self.assertEqual(_counter(set_unit, "TH-C2"), (2, 0))

	def test_on_set_released_concurrent_same_cycle_counts_once(self):
		# request song song cùng Cycle ID vừa tạo dòng giữa lúc kiểm và lúc insert → không cộng lần hai
		from unittest.mock import patch

		make_instrument("TH-CR", interval=5)
		set_unit, set_type = _scene("THW", [("TH-CR", 1)])
		real = maintenance._counter_name
		calls = []

		def racing(unit, instrument, for_update=False):
			if not calls:
				calls.append(1)
				row = make_maintenance(set_unit, "TH-CR", cycles_since=1)
				row.last_release_cycle = "CY-0300"
				row.flags.tc_maintenance = True
				row.save()
				return None
			return real(unit, instrument, for_update=for_update)

		release = {
			"set_unit": set_unit.name,
			"set_type": set_type.name,
			"bom_version": 1,
			"cycle_id": "CY-0300",
		}
		with patch.object(maintenance, "_counter_name", side_effect=racing):
			maintenance.on_set_released(release)
		self.assertEqual(_counter(set_unit, "TH-CR"), (1, 0))

	def test_on_set_released_without_cycle_id_is_not_deduplicated(self):
		# hợp đồng: ctx phải có cycle_id; thiếu thì giữ hành vi cũ (+1 mỗi lần gọi) và không đổi last_release_cycle
		make_instrument("TH-N1", interval=5)
		set_unit, set_type = _scene("THN", [("TH-N1", 1)])
		release = {"set_unit": set_unit.name, "set_type": set_type.name, "bom_version": 1}
		maintenance.on_set_released({**release, "cycle_id": "CY-0100"})
		for missing in ({}, {"cycle_id": None}, {"cycle_id": "  "}):
			maintenance.on_set_released({**release, **missing})
		self.assertEqual(_counter(set_unit, "TH-N1"), (4, 0))
		self.assertEqual(
			frappe.db.get_value(
				"Instrument Maintenance",
				{"set_unit": set_unit.name, "instrument": "TH-N1"},
				"last_release_cycle",
			),
			"CY-0100",
		)
		self.assertIn("cycle_id", maintenance.on_set_released.__doc__)
