"""Dịch vụ quét sử dụng T8 (FEAT-027; FR-M2-17 .1-.4, FR-M2-18 .1-.3; UC-13; BRU-ID-003, BRU-REP-010, BRU-FLOW-003)."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, add_to_date, now_datetime, today

from tracecore.core import step_gate
from tracecore.core.errors import BlockedError
from tracecore.reprocessing import pick_list, storage, usage
from tracecore.tests.factories import make_department, make_employee, make_stocked_pack
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

STATION = "TR-008"
T7 = "TR-007"


def issue(pack, department):
	"""Cấp phát gói cho khoa như T7: phiếu ghi sổ, Pack Issued, bộ Tại khoa."""
	note = frappe.get_doc(
		{
			"doctype": "Issue Note",
			"department": department,
			"station": T7,
			"issued_by_user": frappe.session.user,
			"packs": [{"pack": pack.name, "set_unit": pack.set_unit}],
		}
	)
	note.flags.tc_issuing = True
	note.insert(ignore_permissions=True)
	note.submit()
	locked = storage._lock_pack(pack.name)
	locked.update({"status": "Issued", "location": None})
	storage._save(locked)
	step_gate.issue_to_department(pack.set_unit, T7)
	return frappe.get_doc("Pack", pack.name)


def blocked(case, fn, *args, **kwargs):
	with case.assertRaises(BlockedError) as raised:
		fn(*args, **kwargs)
	return raised.exception.block


class UsageCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.dept = make_department("Khoa phẫu thuật T8")
		self.nurse = make_employee(first_name="Điều dưỡng T8", department=self.dept).name
		self.pack = issue(make_stocked_pack(), self.dept)

	def new_pack(self, department=None):
		return issue(make_stocked_pack(), department or self.dept)

	def confirm(self, pack=None, **kwargs):
		values = {
			"patient_code": "BN12345678",
			"surgery_code": "CA-001",
			"surgeon": "BS Nguyễn",
			"room": "P1",
			**kwargs,
		}
		return usage.confirm((pack or self.pack).name, STATION, self.nurse, **values)


class TestDepartmentOverview(UsageCase):
	def test_packs_at_department_with_expiry_and_used_waiting_return(self):
		used = self.new_pack()
		self.confirm(used)
		other = issue(make_stocked_pack(), make_department("Khoa khác T8"))
		data = usage.department_overview(self.dept)
		held = {row["cycle_id"]: row for row in data["at_department"]}
		self.assertIn(self.pack.name, held)
		self.assertNotIn(used.name, held)
		self.assertNotIn(other.name, held)
		self.assertIn("expiry", held[self.pack.name])
		self.assertEqual([row["cycle_id"] for row in data["waiting_return"]], [used.name])

	def test_pack_expiring_soon_is_flagged(self):
		frappe.db.set_value("Pack", self.pack.name, "expiry", add_days(today(), 3))
		row = next(
			row
			for row in usage.department_overview(self.dept)["at_department"]
			if row["cycle_id"] == self.pack.name
		)
		self.assertEqual(row["days_left"], 3)
		self.assertTrue(row["expiring"])

	def test_no_department_returns_empty_lists(self):
		data = usage.department_overview(None)
		self.assertEqual((data["at_department"], data["waiting_return"]), ([], []))

	def test_pick_list_of_t8_only_shows_packs_of_the_department(self):
		other = issue(make_stocked_pack(), make_department("Khoa khác T8"))
		ids = [row["id"] for row in pick_list.suggest("T8", department=self.dept, page_length=100)["items"]]
		self.assertIn(self.pack.name, ids)
		self.assertNotIn(other.name, ids)


class TestScan(UsageCase):
	def test_scan_returns_card_for_issued_pack(self):
		card = usage.scan(self.pack.name, STATION, self.nurse)
		self.assertEqual(card["cycle_id"], self.pack.name)
		self.assertEqual(card["set_id"], self.pack.set_unit)
		self.assertEqual((card["pack_department"], card["scanner_department"]), (self.dept, self.dept))
		self.assertFalse(card["department_mismatch"])

	def test_scan_wrong_station_and_bad_codes(self):
		self.assertEqual(blocked(self, usage.scan, self.pack.name, T7, self.nurse).code, "STATION_WRONG_STEP")
		self.assertEqual(blocked(self, usage.scan, "xyz", STATION, self.nurse).code, "SCAN_INVALID")
		self.assertEqual(
			blocked(self, usage.scan, "CY-990101-0001", STATION, self.nurse).code, "PACK_NOT_FOUND"
		)

	@bru("BRU-ID-003")
	def test_scan_blocks_every_unusable_state_with_reason_and_date(self):
		cases = {
			"PACK_USED": lambda p: self.set_status(p, "Used"),
			"PACK_RECALLED": lambda p: self.set_status(p, "Recalled"),
			"PACK_VOID": lambda p: self.set_status(p, "Void", void_reason="Torn"),
			"PACK_NOT_ISSUED": lambda p: self.set_status(p, "In Sterile Stock"),
			"PACK_EXPIRED": lambda p: frappe.db.set_value("Pack", p.name, "expiry", add_days(today(), -1)),
		}
		for code, prepare in cases.items():
			with self.subTest(code=code):
				pack = self.new_pack()
				prepare(pack)
				block = blocked(self, usage.scan, pack.name, STATION, self.nurse)
				self.assertEqual(block.code, code)
				self.assertTrue(block.reason and block.action)
		# bộ vượt cơ số (FR-M2-18.1)
		pack = self.new_pack()
		frappe.db.set_value("Set Unit", pack.set_unit, "status", "End of Life")
		self.assertEqual(blocked(self, usage.scan, pack.name, STATION, self.nurse).code, "SET_END_OF_LIFE")

	def set_status(self, pack, status, **fields):
		locked = storage._lock_pack(pack.name)
		locked.update({"status": status, **fields})
		storage._save(locked)


class TestConfirm(UsageCase):
	@bru("BRU-FLOW-003", "BRU-REP-010")
	def test_confirm_records_usage_and_moves_pack_and_set(self):
		result = self.confirm()
		record = frappe.get_doc("Usage Record", result["usage"])
		self.assertEqual((record.docstatus, record.pack, record.department), (1, self.pack.name, self.dept))
		self.assertEqual(record.station, STATION)
		self.assertEqual(record.patient_code_masked, "BN1****678")
		self.assertEqual(frappe.db.get_value("Pack", self.pack.name, "status"), "Used")
		unit = frappe.db.get_value(
			"Set Unit", self.pack.set_unit, ["status", "active_cycle_id"], as_dict=True
		)
		self.assertEqual((unit.status, unit.active_cycle_id), ("Awaiting Receipt", None))
		self.assertNotIn("BN12345678", frappe.as_json(result))

	@bru("BRU-ID-003")
	def test_second_confirm_of_same_pack_is_blocked_and_never_reactivates(self):
		self.confirm()
		self.assertEqual(blocked(self, self.confirm).code, "PACK_USED")
		self.assertEqual(frappe.db.count("Usage Record", {"pack": self.pack.name}), 1)

	@bru("BRU-REP-010")
	def test_patient_and_surgery_code_are_required(self):
		self.assertEqual(blocked(self, self.confirm, patient_code="  ").code, "PATIENT_CODE_REQUIRED")
		self.assertEqual(blocked(self, self.confirm, surgery_code="").code, "DATA_INCOMPLETE")
		self.assertEqual(blocked(self, self.confirm, patient_code="x" * 51).code, "PATIENT_CODE_REQUIRED")
		self.assertEqual(frappe.db.get_value("Pack", self.pack.name, "status"), "Issued")

	def test_several_packs_share_one_surgery_code(self):
		other = self.new_pack()
		first, second = self.confirm(), self.confirm(other)
		records = frappe.get_all("Usage Record", filters={"surgery_code": "CA-001"}, pluck="name")
		self.assertCountEqual(records, [first["usage"], second["usage"]])
		self.assertEqual(len(second["surgery_packs"]), 2)

	def test_other_department_needs_a_reason(self):
		other_dept = make_department("Khoa khác T8")
		pack = self.new_pack(other_dept)
		card = usage.scan(pack.name, STATION, self.nurse)
		self.assertTrue(card["department_mismatch"])
		self.assertEqual(blocked(self, self.confirm, pack).code, "DEPARTMENT_REASON_REQUIRED")
		result = self.confirm(pack, department_reason="Mượn bộ do khoa kia hết bộ")
		record = frappe.get_doc("Usage Record", result["usage"])
		self.assertEqual((record.department, record.pack_department), (self.dept, other_dept))
		self.assertIn("Mượn bộ", record.department_reason)


class TestEmergency(UsageCase):
	@bru("BRU-REP-010")
	def test_emergency_allows_patient_code_within_24_hours(self):
		result = self.confirm(patient_code="", emergency=1)
		record = frappe.get_doc("Usage Record", result["usage"])
		self.assertEqual((record.emergency, record.patient_code_masked), (1, ""))
		self.assertGreater(record.patient_code_due, now_datetime())
		usage.set_patient_code(record.name, "BN99887766", self.nurse)
		self.assertEqual(frappe.get_doc("Usage Record", record.name).patient_code_masked, "BN9****766")
		self.assertEqual(
			blocked(self, usage.set_patient_code, record.name, "OTHER", self.nurse).code,
			"PATIENT_CODE_ALREADY_SET",
		)

	def test_patient_code_after_deadline_is_blocked(self):
		record = frappe.get_doc("Usage Record", self.confirm(patient_code="", emergency=1)["usage"])
		later = add_to_date(now_datetime(), hours=25)
		with patch("tracecore.reprocessing.usage.now_datetime", return_value=later):
			self.assertEqual(
				blocked(self, usage.set_patient_code, record.name, "BN1", self.nurse).code,
				"PATIENT_CODE_DEADLINE",
			)

	def test_set_patient_code_unknown_usage(self):
		self.assertEqual(
			blocked(self, usage.set_patient_code, "US-2026-99999", "BN1", self.nurse).code, "USAGE_NOT_FOUND"
		)


class TestReveal(UsageCase):
	@bru("BRU-REP-010")
	def test_reveal_returns_code_and_audits_without_the_code(self):
		record = self.confirm()["usage"]
		self.assertEqual(blocked(self, usage.reveal_patient_code, record, "  ").code, "REASON_REQUIRED")
		self.assertEqual(usage.reveal_patient_code(record, "Đối chiếu hồ sơ ca mổ"), "BN12345678")
		rows = frappe.get_all(
			"Audit Log",
			filters={"action": "View Patient Code", "ref_doctype": "Usage Record", "ref_name": record},
			fields=["reason", "old_value", "new_value"],
		)
		self.assertEqual(len(rows), 1)
		self.assertIn("Đối chiếu", rows[0].reason)
		self.assertNotIn("BN12345678", frappe.as_json(rows))

	def test_reveal_unknown_usage(self):
		self.assertEqual(
			blocked(self, usage.reveal_patient_code, "US-2026-99999", "x").code, "USAGE_NOT_FOUND"
		)
