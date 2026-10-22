import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.par import config
from tracecore.tests.factories import (
	make_bom_set_type,
	make_department,
	make_instrument,
	make_par_level,
	make_set_type,
	make_set_unit,
	make_user,
)
from tracecore.tests.utils import assert_permission_matrix, bru

# Par Level liên kết Instrument/Instrument Set Type (→ Department, Item); CI chưa có Setup Wizard
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def _history(par):
	return [(row.field_name, row.old_value, row.new_value) for row in par.reload().history]


class TestParLevel(FrappeTestCase):
	def test_create_reprocessing_par_for_instrument(self):
		make_instrument("PL-INS1")
		par = make_par_level("Instrument", "PL-INS1", max_cycles=500, source="IFU")
		self.assertEqual((par.max_cycles, par.source, par.warn_percent, par.warn_count), (500, "IFU", 10, 5))
		self.assertTrue(par.name.startswith("PAR-"))

	def test_blank_cap_is_undefined_not_blocked(self):
		make_instrument("PL-INS2")
		par = make_par_level("Instrument", "PL-INS2", max_cycles=0)
		self.assertEqual(par.max_cycles, 0)
		self.assertEqual(frappe.db.get_value("Instrument", "PL-INS2", "max_cycles_status"), "Undefined")

	def test_target_must_exist_and_be_supported(self):
		with self.assertRaises(frappe.ValidationError):
			make_par_level("Instrument", "PL-NOPE", max_cycles=10)
		with self.assertRaises(frappe.ValidationError):
			make_par_level("Item", "Any item", max_cycles=10)

	def test_unique_kind_target_department(self):
		make_instrument("PL-INS3")
		make_par_level("Instrument", "PL-INS3", max_cycles=100)
		with self.assertRaises(frappe.ValidationError):
			make_par_level("Instrument", "PL-INS3", max_cycles=200)
		make_set_type("PLU")
		dept = make_department()
		make_par_level(
			"Instrument Set Type", "PLU", par_kind="Department Stock", department=dept, min_qty=1, max_qty=3
		)
		with self.assertRaises(frappe.ValidationError):
			make_par_level(
				"Instrument Set Type",
				"PLU",
				par_kind="Department Stock",
				department=dept,
				min_qty=1,
				max_qty=4,
			)

	def test_department_required_for_stock_par(self):
		make_set_type("PLD")
		with self.assertRaises(frappe.ValidationError):
			make_par_level("Instrument Set Type", "PLD", par_kind="Department Stock", min_qty=1, max_qty=3)

	def test_stock_par_only_for_set_types(self):
		make_instrument("PL-INS4")
		with self.assertRaises(frappe.ValidationError):
			make_par_level("Instrument", "PL-INS4", par_kind="Department Stock", department=make_department())

	@bru("BRU-PAR-005")
	def test_min_greater_than_max_blocked(self):
		make_set_type("PLM")
		dept = make_department()
		with self.assertRaises(frappe.ValidationError):
			make_par_level(
				"Instrument Set Type",
				"PLM",
				par_kind="Department Stock",
				department=dept,
				min_qty=5,
				max_qty=4,
			)
		ok = make_par_level(
			"Instrument Set Type", "PLM", par_kind="Department Stock", department=dept, min_qty=4, max_qty=4
		)
		self.assertEqual((ok.min_qty, ok.max_qty), (4, 4))

	@bru("BRU-PAR-005")
	def test_over_percent_only_for_emergency_dept_max_20(self):
		make_set_type("PLE")
		dept = make_department()
		stock = {"par_kind": "Department Stock", "department": dept, "min_qty": 1, "max_qty": 5}
		with self.assertRaises(frappe.ValidationError):
			make_par_level("Instrument Set Type", "PLE", over_percent=10, **stock)
		with self.assertRaises(frappe.ValidationError):
			make_par_level("Instrument Set Type", "PLE", over_percent=21, is_emergency_dept=1, **stock)
		par = make_par_level("Instrument Set Type", "PLE", over_percent=20, is_emergency_dept=1, **stock)
		self.assertEqual(par.over_percent, 20)

	def test_history_one_row_per_changed_field(self):
		make_instrument("PL-INS5")
		par = make_par_level("Instrument", "PL-INS5", max_cycles=500, source="Estimate")
		par.max_cycles, par.source, par.warn_count = 400, "IFU", 8
		par.reason = "Updated IFU"
		par.save()
		rows = {row.field_name: row for row in par.reload().history if row.old_value not in ("", None)}
		self.assertEqual(set(rows), {"max_cycles", "source", "warn_count"})
		self.assertEqual((rows["max_cycles"].old_value, rows["max_cycles"].new_value), ("500", "400"))
		self.assertEqual(rows["max_cycles"].changed_by, frappe.session.user)
		self.assertEqual({row.reason for row in rows.values()}, {"Updated IFU"})

	def test_reason_required_when_changing_cap(self):
		make_instrument("PL-INS6")
		par = make_par_level("Instrument", "PL-INS6", max_cycles=500)
		par.max_cycles = 450
		with self.assertRaises(frappe.ValidationError):
			par.save()

	def test_history_immutable_even_for_system_manager(self):
		make_instrument("PL-INS7")
		par = make_par_level("Instrument", "PL-INS7", max_cycles=500)
		par.reload()
		par.history[0].new_value = "tampered"
		with self.assertRaises(frappe.ValidationError):
			par.save()
		par.reload()
		par.remove(par.history[0])
		with self.assertRaises(frappe.ValidationError):
			par.save()

	def test_no_delete_for_anyone(self):
		make_instrument("PL-INS8")
		par = make_par_level("Instrument", "PL-INS8", max_cycles=500)
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Par Level", par.name, force=True)

	def test_par_changes_are_audited(self):
		make_instrument("PL-INS9")
		par = make_par_level("Instrument", "PL-INS9", max_cycles=500)
		par.max_cycles, par.reason = 450, "IFU v2"
		par.save()
		rows = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "Par Level", "ref_name": par.name, "action": "Update"},
			fields=["old_value", "new_value"],
		)
		self.assertTrue(any(frappe.parse_json(r.new_value).get("max_cycles") == 450 for r in rows), rows)

	def test_permissions_match_matrix_and_r04_reads_only(self):
		assert_permission_matrix(self, "Par Level")
		make_instrument("PL-INS10")
		par = make_par_level("Instrument", "PL-INS10", max_cycles=500)
		user = make_user("par.r04@example.com", ["TC R04"])
		frappe.set_user(user)
		self.addCleanup(frappe.set_user, "Administrator")
		self.assertTrue(frappe.has_permission("Par Level", "read", doc=par))
		self.assertFalse(frappe.has_permission("Par Level", "write", doc=par))
		self.assertFalse(frappe.has_permission("Par Level", "delete", doc=par))


class TestParConfig(FrappeTestCase):
	def test_save_syncs_instrument_max_cycles(self):
		make_instrument("PC-INS1", max_cycles=100)
		par = make_par_level("Instrument", "PC-INS1", max_cycles=500)
		self.assertEqual(
			frappe.db.get_value("Instrument", "PC-INS1", ["max_cycles", "max_cycles_status"], as_dict=True),
			{"max_cycles": 500, "max_cycles_status": "Defined"},
		)
		par.max_cycles, par.reason = 300, "Re-estimated"
		par.save()
		self.assertEqual(frappe.db.get_value("Instrument", "PC-INS1", "max_cycles"), 300)
		par.max_cycles, par.reason = 0, "Unknown again"
		par.save()
		self.assertEqual(
			frappe.db.get_value("Instrument", "PC-INS1", ["max_cycles", "max_cycles_status"], as_dict=True),
			{"max_cycles": 0, "max_cycles_status": "Undefined"},
		)

	def test_sync_is_audited_on_instrument(self):
		make_instrument("PC-INS2")
		par = make_par_level("Instrument", "PC-INS2", max_cycles=250)
		row = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "Instrument", "ref_name": "PC-INS2", "action": "Update"},
			fields=["new_value", "reason"],
		)
		self.assertTrue(any(par.name in (r.reason or "") for r in row), row)

	def test_inactive_par_does_not_touch_instrument(self):
		make_instrument("PC-INS3", max_cycles=100)
		make_par_level("Instrument", "PC-INS3", max_cycles=500, is_active=0)
		self.assertEqual(frappe.db.get_value("Instrument", "PC-INS3", "max_cycles"), 100)

	def test_set_type_par_does_not_touch_set_unit(self):
		st = make_set_type("PCS1")
		unit = make_set_unit(st.name, max_cycles=300)
		make_par_level("Instrument Set Type", st.name, max_cycles=200)
		self.assertEqual(frappe.db.get_value("Set Unit", unit.name, "max_cycles"), 300)

	def test_effective_set_type_cap_own_par_wins(self):
		st = make_bom_set_type("PCS2", [("PC-A", 1), ("PC-B", 1)], caps={"PC-A": 500, "PC-B": 300})
		make_par_level("Instrument Set Type", st.name, max_cycles=250)
		self.assertEqual(
			config.effective_set_type_cap(st.name), {"value": 250, "source": "Par Level", "undefined": []}
		)

	@bru("BRU-PAR-001")
	def test_effective_set_type_cap_derived_min_of_bom(self):
		st = make_bom_set_type(
			"PCS3", [("PC-C", 1), ("PC-D", 1), ("PC-E", 1)], caps={"PC-C": 500, "PC-D": 300}
		)
		self.assertEqual(
			config.effective_set_type_cap(st.name), {"value": 300, "source": "Derived", "undefined": ["PC-E"]}
		)

	def test_effective_set_type_cap_undefined_when_nothing_set(self):
		st = make_bom_set_type("PCS4", [("PC-F", 1)], caps={})
		self.assertEqual(
			config.effective_set_type_cap(st.name),
			{"value": None, "source": "Undefined", "undefined": ["PC-F"]},
		)

	def test_cap_not_above_used_blocks_unless_confirmed(self):
		st = make_set_type("PCS5")
		unit = make_set_unit(st.name, max_cycles=300)
		frappe.db.set_value("Set Unit", unit.name, "cycles_used", 40)
		with self.assertRaises(frappe.ValidationError):
			make_par_level("Instrument Set Type", st.name, max_cycles=40)
		with self.assertRaises(frappe.ValidationError):
			make_par_level("Instrument Set Type", st.name, max_cycles=10)
		ok = make_par_level("Instrument Set Type", st.name, max_cycles=41)
		self.assertEqual(ok.max_cycles, 41)
		ok.max_cycles, ok.reason = 30, "Retire early"
		with self.assertRaises(frappe.ValidationError):
			ok.save()
		ok.reload()
		ok.max_cycles, ok.reason, ok.confirm_below_used = 30, "Retire early", 1
		ok.save()
		self.assertEqual(ok.reload().max_cycles, 30)
		self.assertEqual(ok.confirm_below_used, 0)

	def test_used_cycles_unknown_for_instrument(self):
		make_instrument("PC-INS4")
		par = make_par_level("Instrument", "PC-INS4", max_cycles=1)
		self.assertIsNone(config.used_cycles(par))
