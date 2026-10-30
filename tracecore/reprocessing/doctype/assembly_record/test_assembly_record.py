import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import step_gate
from tracecore.tests.factories import (
	make_assembly_record,
	make_cycle,
	make_set_type,
	make_set_unit,
	make_user,
)
from tracecore.tests.utils import bru

# Set Unit → Instrument Set Type → Department (ERPNext) đã được test của các DocType đó bỏ qua;
# Assembly Record chỉ liên kết trực tiếp tới Set Unit nên không cần khai báo thêm.

BOM = [("AS-KEO", 2), ("AS-KEP", 1), ("AS-DAO", 3)]


def _t3(set_unit):
	return step_gate.gates(set_unit)[2]


def _bom_set(code="ASM1"):
	"""Bộ có BOM ba dòng, đã mở chu trình (ghim BOM v1)."""
	su = make_set_unit(make_set_type(code, bom=BOM).name).name
	step_gate.start_cycle(su)
	return su


def _lines(**overrides):
	"""Dòng kiểm đếm đủ theo BOM; `overrides`: {mã dụng cụ: {trường: giá trị}}."""
	rows = []
	for code, qty in BOM:
		row = {"instrument": code, "counted": 1, "actual_qty": qty}
		row.update(overrides.get(code, {}))
		rows.append(row)
	return rows


def _draft(su, lines=None, **fields):
	return frappe.get_doc(
		{"doctype": "Assembly Record", "set_unit": su, "result": "Pass", "lines": lines, **fields}
	).insert()


class TestAssemblyRecord(FrappeTestCase):
	# --- giữ nguyên hành vi của stub FEAT-018 (T1) ---

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

	def test_result_is_required_to_submit(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		doc = frappe.get_doc({"doctype": "Assembly Record", "set_unit": su}).insert()
		with self.assertRaises(frappe.MandatoryError):
			doc.submit()

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

	# --- kiểm đếm theo BOM (FEAT-020) ---

	@bru("BRU-REP-003")
	def test_line_status_enough_short_over(self):
		su = _bom_set()
		doc = _draft(
			su,
			_lines(**{"AS-KEO": {"actual_qty": 1}, "AS-DAO": {"actual_qty": 4}}),
		)
		status = {row.instrument: (row.line_status, row.missing_qty, row.bom_qty) for row in doc.lines}
		self.assertEqual(status["AS-KEO"], ("Short", 1, 2))
		self.assertEqual(status["AS-KEP"], ("Enough", 0, 1))
		self.assertEqual(status["AS-DAO"], ("Over", 0, 3))
		self.assertEqual(doc.has_shortage, 1)
		self.assertIn("AS-KEO", doc.shortage_summary)
		self.assertEqual(doc.bom_version, 1)
		self.assertEqual(doc.set_type, frappe.db.get_value("Set Unit", su, "set_type"))

	def test_uncounted_line_is_not_a_shortage(self):
		su = _bom_set("ASM2")
		doc = _draft(su, [{"instrument": code} for code, _qty in BOM])
		self.assertEqual(doc.has_shortage, 0)
		self.assertFalse(any(row.line_status for row in doc.lines))

	def test_replaced_cannot_exceed_damaged(self):
		su = _bom_set("ASM3")
		with self.assertRaises(frappe.ValidationError):
			_draft(su, _lines(**{"AS-KEO": {"damaged_qty": 1, "replaced_qty": 2, "disposition": "Repair"}}))

	def test_damaged_counted_line_needs_disposition(self):
		su = _bom_set("ASM4")
		with self.assertRaises(frappe.ValidationError):
			_draft(su, _lines(**{"AS-KEO": {"damaged_qty": 1, "replaced_qty": 1}}))
		doc = _draft(
			su,
			_lines(
				**{
					"AS-KEO": {
						"damaged_qty": 1,
						"replaced_qty": 1,
						"disposition": "Dispose",
						"replacement_instrument": "AS-KEP",
					}
				}
			),
		)
		keo = next(row for row in doc.lines if row.instrument == "AS-KEO")
		self.assertEqual((keo.line_status, keo.replacement_instrument), ("Enough", "AS-KEP"))

	def test_negative_quantities_are_rejected(self):
		su = _bom_set("ASM5")
		with self.assertRaises(frappe.ValidationError):
			_draft(su, _lines(**{"AS-KEO": {"actual_qty": -1}}))

	def test_lines_must_match_pinned_bom(self):
		su = _bom_set("ASM6")
		with self.assertRaises(frappe.ValidationError):  # thiếu một dòng BOM
			_draft(su, _lines()[:2])
		with self.assertRaises(frappe.ValidationError):  # dụng cụ ngoài BOM
			_draft(su, [*_lines(), {"instrument": "AS-LA", "counted": 1, "actual_qty": 1}])
		with self.assertRaises(frappe.ValidationError):  # trùng dòng
			_draft(su, [*_lines(), {"instrument": "AS-KEO", "counted": 1, "actual_qty": 1}])
		with self.assertRaises(frappe.ValidationError):  # bộ có BOM thì không được bỏ trống dòng
			_draft(su, None)

	def test_legacy_record_without_lines_allowed_when_bom_not_pinned(self):
		su = make_set_unit().name  # loại bộ không có BOM
		step_gate.start_cycle(su)
		doc = make_assembly_record(su, "Pass")
		self.assertEqual((doc.docstatus, doc.has_shortage, len(doc.lines)), (1, 0, 0))

	@bru("BRU-REP-003")
	def test_pass_blocked_with_unconfirmed_shortage(self):
		su = _bom_set("ASM7")
		doc = _draft(su, _lines(**{"AS-KEO": {"actual_qty": 0}}))
		with self.assertRaises(frappe.ValidationError):
			doc.submit()
		self.assertEqual(_t3(su), {"step": "T3", "result": "Pending", "redo_count": 0})

	def test_pass_blocked_with_uncounted_line(self):
		su = _bom_set("ASM8")
		lines = _lines()
		lines[0]["counted"] = 0
		doc = _draft(su, lines)
		with self.assertRaises(frappe.ValidationError):
			doc.submit()

	@bru("BRU-REP-003")
	def test_shortage_confirmation_cannot_be_set_by_hand(self):
		su = _bom_set("ASM9")
		doc = _draft(su, _lines(**{"AS-KEO": {"actual_qty": 0}}))
		doc.shortage_confirmed = 1
		doc.shortage_reason = "Gấp"
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		# qua dịch vụ (cờ tc_assembly) và có người xác nhận thì được
		doc.reload()
		doc.flags.tc_assembly = True
		doc.update(
			{
				"shortage_confirmed": 1,
				"shortage_reason": "Ca mổ gấp",
				"shortage_confirmed_by": "Administrator",
				"shortage_confirmed_at": frappe.utils.now_datetime(),
			}
		)
		doc.save()
		doc.submit()
		self.assertEqual(_t3(su)["result"], "Pass")

	def test_confirmation_is_dropped_when_the_shortage_changes(self):
		su = _bom_set("ASMA")
		doc = _draft(su, _lines(**{"AS-KEO": {"actual_qty": 0}}))
		doc.flags.tc_assembly = True
		doc.update(
			{
				"shortage_confirmed": 1,
				"shortage_reason": "Ca mổ gấp",
				"shortage_confirmed_by": "Administrator",
				"shortage_confirmed_at": frappe.utils.now_datetime(),
			}
		)
		doc.save()
		self.assertEqual(doc.shortage_confirmed, 1)
		doc.flags.tc_assembly = False
		keo = next(row for row in doc.lines if row.instrument == "AS-KEO")
		keo.actual_qty = 1  # thiếu ít hơn lúc R02 xác nhận
		doc.save()
		self.assertEqual((doc.shortage_confirmed, doc.shortage_confirmed_by), (0, None))
		doc.lines[0].actual_qty = 2
		doc.save()
		self.assertEqual(doc.has_shortage, 0)

	def test_branch_needs_fail_and_reason(self):
		su = _bom_set("ASMB")
		with self.assertRaises(frappe.ValidationError):
			_draft(su, _lines(), branch="Repair", branch_reason="Gãy mũi kéo").submit()
		doc = frappe.get_doc(
			{
				"doctype": "Assembly Record",
				"set_unit": su,
				"result": "Fail",
				"branch": "Disposal",
				"lines": _lines(**{"AS-KEO": {"damaged_qty": 2, "disposition": "Dispose", "actual_qty": 0}}),
			}
		).insert()
		with self.assertRaises(frappe.ValidationError):  # thiếu lý do rẽ nhánh
			doc.submit()
		doc.reload()
		doc.branch_reason = "Hỏng nặng, không sửa được"
		doc.save()
		doc.submit()
		self.assertEqual(_t3(su), {"step": "T3", "result": "Fail", "redo_count": 1})
		self.assertEqual(frappe.db.get_value("Set Unit", su, "status"), "Reprocess")

	@bru("BRU-FLOW-004")
	def test_submit_records_t3_with_station_and_client_ts(self):
		su = _bom_set("ASMC")
		stamp = frappe.utils.now_datetime()
		doc = _draft(su, _lines(), station="TR-003", client_ts=stamp)
		doc.submit()
		row = frappe.db.get_value("Step Gate Result", f"{su}-C1-T3", ["result", "station"], as_dict=True)
		self.assertEqual((row.result, row.station), ("Pass", "TR-003"))
		self.assertEqual(frappe.db.get_value("Set Unit", su, "status"), "Processing")

	def test_make_cycle_t3_passes_for_a_set_with_bom(self):
		su = make_set_unit(make_set_type("ASMD", bom=BOM).name).name
		make_cycle(su, passed=("T1", "T2", "T3"))
		self.assertEqual(_t3(su)["result"], "Pass")
		doc = frappe.get_all("Assembly Record", filters={"set_unit": su}, pluck="name")[0]
		self.assertEqual(frappe.db.count("Assembly Line", {"parent": doc}), 3)
