"""Kiểm cơ số tại T4 (FEAT-032, A-18 Q1-Q3): cảnh báo sớm, cấp bộ + cấp dụng cụ, chặn và Hết vòng đời."""

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import step_gate
from tracecore.par import check
from tracecore.tests.factories import (
	make_cycle,
	make_instrument,
	make_par_level,
	make_set_type,
	make_set_unit,
)
from tracecore.tests.utils import bru

# Set Unit / Instrument liên kết Department, Item; CI chưa có Setup Wizard
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

SET_FIELDS = [
	"name",
	"set_type",
	"status",
	"cycles_used",
	"max_cycles",
	"active_cycle_id",
	"current_cycle_no",
]


def _code(prefix):
	return prefix + frappe.generate_hash(length=5).upper()


def make_par_scene(used=0, max_cycles=300, caps=None, set_par=None):
	"""Bộ (chu trình 1, T1..T3 Đạt) của loại bộ mới có BOM ``caps`` ``{hậu tố: cơ số}``; đặt ``cycles_used``.

	``set_par``: ``{warn_percent, warn_count}`` → Par Level riêng của loại bộ. Trả ``(set_unit, {hậu tố: mã})``.
	"""
	caps = caps if caps is not None else {"A": None}
	codes = {key: _code(f"PC{key}") for key in caps}
	for key, cap in caps.items():
		make_instrument(codes[key], max_cycles=cap, methods=("Steam 134", "Plasma"))
	set_type = make_set_type(_code("PC"), bom=[(codes[key], 1) for key in caps])
	if set_par:
		make_par_level("Instrument Set Type", set_type.name, max_cycles=max_cycles, **set_par)
	unit = make_set_unit(set_type.name, max_cycles=max_cycles).name
	make_cycle(unit)
	frappe.db.set_value("Set Unit", unit, "cycles_used", used)  # bộ đếm thật là FEAT-023
	return unit, codes


def hook_ctx(unit):
	"""``ctx`` như ``packing._open`` đưa cho hook (D9)."""
	row = frappe.db.get_value("Set Unit", unit, SET_FIELDS, as_dict=True)
	return {
		"set_unit": dict(row),
		"set_type": {"name": row.set_type},
		"station": "TR-004",
		"maint_actions": [],
	}


class TestWarnRule(FrappeTestCase):
	@bru("BRU-PAR-003")
	def test_warn_at_is_ten_percent_or_five_cycles_whichever_is_larger(self):
		cases = [(300, 30), (100, 10), (51, 6), (20, 5), (3, 5), (0, 0)]
		for limit, expected in cases:
			self.assertEqual(check.warn_at(limit), expected, msg=limit)
		self.assertEqual(check.warn_at(300, 20, 2), 60)
		self.assertEqual(check.warn_at(10, 0, 0), 0)


class TestEvaluate(FrappeTestCase):
	@bru("BRU-PAR-003")
	def test_set_level_states(self):
		unit, _codes = make_par_scene()
		for used, state, remaining in [
			(0, "ok", 300),
			(269, "ok", 31),
			(270, "warn", 30),
			(299, "warn", 1),
			(300, "blocked", 0),
			(305, "blocked", 0),
		]:
			frappe.db.set_value("Set Unit", unit, "cycles_used", used)
			par = check.evaluate(unit)
			self.assertEqual((par["state"], par["remaining"]), (state, remaining), msg=used)
			self.assertEqual((par["cycles_used"], par["max_cycles"], par["warn_at"]), (used, 300, 30))
			self.assertEqual(par["percent"], used * 100 // 300)
			self.assertEqual(par["instruments"], [])
			self.assertIsNone(par["override"])

	@bru("BRU-PAR-003")
	def test_set_type_par_level_thresholds(self):
		unit, _codes = make_par_scene(used=239, set_par={"warn_percent": 20, "warn_count": 2})
		self.assertEqual(check.evaluate(unit)["state"], "ok")
		frappe.db.set_value("Set Unit", unit, "cycles_used", 240)
		par = check.evaluate(unit)
		self.assertEqual((par["state"], par["warn_at"]), ("warn", 60))

	@bru("BRU-PAR-002")
	def test_instrument_cap_blocks_whole_set(self):
		unit, codes = make_par_scene(used=100, caps={"A": 100, "B": None, "C": 500})
		par = check.evaluate(unit)
		self.assertEqual(par["state"], "blocked")
		self.assertEqual(par["remaining"], 200)  # cấp bộ còn 200, nhưng dụng cụ A đã hết
		self.assertEqual(
			[
				(row["instrument"], row["max_cycles"], row["remaining"], row["state"])
				for row in par["instruments"]
			],
			[(codes["A"], 100, 0, "blocked")],
		)
		self.assertTrue(par["instruments"][0]["instrument_name"])

	@bru("BRU-PAR-003")
	def test_instrument_close_to_cap_warns(self):
		unit, codes = make_par_scene(used=89, caps={"A": 100})
		self.assertEqual(check.evaluate(unit)["state"], "ok")
		frappe.db.set_value("Set Unit", unit, "cycles_used", 90)
		par = check.evaluate(unit)
		self.assertEqual(par["state"], "warn")
		self.assertEqual(
			[(row["instrument"], row["remaining"], row["state"]) for row in par["instruments"]],
			[(codes["A"], 10, "warn")],
		)

	def test_instrument_par_level_thresholds(self):
		unit, codes = make_par_scene(used=50, caps={"A": 100})
		make_par_level("Instrument", codes["A"], max_cycles=100, warn_percent=50, warn_count=1)
		self.assertEqual(check.evaluate(unit)["instruments"][0]["state"], "warn")

	def test_uses_bom_version_pinned_for_the_cycle(self):
		unit, _codes = make_par_scene(used=100, caps={"A": 100})
		frappe.db.set_value("Set Unit", unit, "cycle_bom_version", 99)  # phiên bản không có dòng nào
		self.assertEqual(check.evaluate(unit)["state"], "ok")

	@bru("BRU-PAR-002")
	def test_undefined_limit_does_not_block(self):
		unit, _codes = make_par_scene(used=50)
		frappe.db.set_value("Set Unit", unit, "max_cycles", 0)  # dữ liệu cũ: cơ số Chưa xác định (UC-31 E3)
		par = check.evaluate(unit)
		self.assertEqual(
			(par["state"], par["max_cycles"], par["percent"], par["remaining"]), ("undefined", 0, 0, None)
		)
		self.assertIsNone(check.check_pack(hook_ctx(unit)))

	def test_accepts_hook_dict_values(self):
		# T4 đưa giá trị đã đọc (D9); evaluate tin các giá trị đó, chỉ đọc thêm phiên bản BOM ghim
		unit, _codes = make_par_scene(used=0)
		ctx = hook_ctx(unit)
		ctx["set_unit"]["cycles_used"] = 280
		self.assertEqual(check.evaluate(ctx["set_unit"])["state"], "warn")

	def test_pack_context_keeps_feat018_keys(self):
		unit, _codes = make_par_scene(used=270)
		par = check.pack_context(hook_ctx(unit))["par"]
		self.assertEqual(
			{key: par[key] for key in ("cycles_used", "max_cycles", "percent", "state")},
			{"cycles_used": 270, "max_cycles": 300, "percent": 90, "state": "warn"},
		)
		self.assertIs(type(par["percent"]), int)


class TestCheckPack(FrappeTestCase):
	def test_under_limit_passes_without_writes(self):
		unit, _codes = make_par_scene(used=299)
		self.assertIsNone(check.check_pack(hook_ctx(unit)))
		self.assertEqual(frappe.db.get_value("Set Unit", unit, "status"), "Processing")

	@bru("BRU-PAR-002")
	def test_set_limit_blocks_and_moves_set_to_end_of_life(self):
		unit, _codes = make_par_scene(used=300)
		block = check.check_pack(hook_ctx(unit))
		self.assertEqual((block.code, block.http_status), ("PAR_EXCEEDED", 409))
		self.assertIn(unit, block.reason)
		self.assertIn("300", block.reason)
		self.assertTrue(block.title and block.action)
		self.assertNotIn("FEAT-032", block.action)
		self.assertIsNone(block.items)
		self.assertEqual(frappe.db.get_value("Set Unit", unit, "status"), "End of Life")
		audit = frappe.get_all(
			"Audit Log",
			filters={
				"ref_doctype": "Set Unit",
				"ref_name": unit,
				"action": "Update",
				"reason": check.EOL_REASON,
			},
			pluck="name",
		)
		self.assertEqual(len(audit), 1)
		# đã Hết vòng đời: mọi trạm chặn trước khi tới kiểm cơ số (UC-31 E2)
		self.assertEqual(step_gate.check(unit, "T4").code, "SET_END_OF_LIFE")

	@bru("BRU-PAR-002")
	def test_instrument_limit_lists_exceeded_instruments(self):
		unit, codes = make_par_scene(used=120, caps={"A": 100, "B": 120, "C": 500})
		block = check.check_pack(hook_ctx(unit))
		self.assertEqual(block.code, "PAR_EXCEEDED")
		self.assertEqual([item["instrument"] for item in block.items], sorted([codes["A"], codes["B"]]))
		for item in block.items:
			self.assertEqual(item["state"], "blocked")
			self.assertTrue(item["instrument_name"])
		self.assertEqual(frappe.db.get_value("Set Unit", unit, "status"), "End of Life")
