import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import step_gate
from tracecore.tests.factories import make_assembly_record, make_set_unit, make_user
from tracecore.tests.utils import bru

# Set Unit → Instrument Set Type → Department (ERPNext) đã được test của các DocType đó bỏ qua;
# Assembly Record chỉ liên kết trực tiếp tới Set Unit nên không cần khai báo thêm.


def _t3(set_unit):
	return step_gate.gates(set_unit)[2]


class TestAssemblyRecord(FrappeTestCase):
	def test_name_series_and_cycle_taken_from_set_unit(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		step_gate.start_cycle(su)
		doc = make_assembly_record(su, "Pass", submit=False)
		self.assertRegex(doc.name, r"^AS-\d{4}-\d{5}$")
		self.assertEqual(doc.cycle_no, 2)
		self.assertEqual(doc.docstatus, 0)

	def test_cycle_no_cannot_be_forced_by_the_caller(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		doc = frappe.get_doc(
			{"doctype": "Assembly Record", "set_unit": su, "result": "Pass", "cycle_no": 7}
		).insert()
		self.assertEqual(doc.cycle_no, 1)

	def test_draft_does_not_record_the_gate(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		make_assembly_record(su, "Pass", submit=False)
		self.assertEqual(_t3(su), {"step": "T3", "result": "Pending", "redo_count": 0})

	@bru("BRU-FLOW-004")
	def test_submit_pass_records_t3_pass_and_links_the_record(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		doc = make_assembly_record(su, "Pass")
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(_t3(su), {"step": "T3", "result": "Pass", "redo_count": 0})
		row = frappe.get_doc("Step Gate Result", f"{su}-C1-T3")
		self.assertEqual((row.ref_doctype, row.ref_name), ("Assembly Record", doc.name))

	@bru("BRU-FLOW-004")
	def test_submit_fail_sends_the_set_back_to_reprocess(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		make_assembly_record(su, "Fail")
		self.assertEqual(_t3(su), {"step": "T3", "result": "Fail", "redo_count": 1})
		self.assertEqual(frappe.db.get_value("Set Unit", su, "status"), "Reprocess")

	def test_cannot_be_created_before_a_cycle_starts(self):
		su = make_set_unit().name
		with self.assertRaises(frappe.ValidationError):
			make_assembly_record(su, "Pass", submit=False)

	def test_missing_or_unknown_set_unit_is_reported_by_standard_validation(self):
		with self.assertRaises(frappe.MandatoryError):
			frappe.get_doc({"doctype": "Assembly Record", "result": "Pass"}).insert()
		with self.assertRaises(frappe.LinkValidationError):
			frappe.get_doc(
				{"doctype": "Assembly Record", "set_unit": "NO-SUCH-SET", "result": "Pass"}
			).insert()

	def test_result_is_mandatory(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		with self.assertRaises(frappe.MandatoryError):
			frappe.get_doc({"doctype": "Assembly Record", "set_unit": su}).insert()

	def test_stale_draft_cannot_be_submitted_into_a_newer_cycle(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		draft = make_assembly_record(su, "Pass", submit=False)
		step_gate.start_cycle(su)
		with self.assertRaises(frappe.ValidationError):
			draft.submit()
		self.assertEqual(_t3(su), {"step": "T3", "result": "Pending", "redo_count": 0})

	def test_cannot_be_deleted_or_cancelled(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		doc = make_assembly_record(su, "Pass")
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Assembly Record", doc.name, ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			doc.cancel()
		# hủy bị chặn nên cổng T3 vẫn giữ nguyên
		self.assertEqual(_t3(su), {"step": "T3", "result": "Pass", "redo_count": 0})
		perms = frappe.get_all(
			"DocPerm", filters={"parent": "Assembly Record"}, fields=["role", "delete", "cancel", "amend"]
		)
		self.assertTrue(perms)
		for perm in perms:
			for ptype in ("delete", "cancel", "amend"):
				self.assertFalse(perm[ptype], msg=f"{perm.role} has {ptype}")

	def test_station_role_r04_can_create_and_submit(self):
		user = make_user("assembly-r04@example.com", roles=["TC R04"])
		for ptype in ("create", "read", "write", "submit"):
			self.assertTrue(frappe.has_permission("Assembly Record", ptype, user=user), ptype)
