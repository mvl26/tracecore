"""Thanh lý bộ (FEAT-004, A-37 (a), FR-M1-05.2, FR-M1-06): R02 đề nghị kèm lý do, R01 duyệt bằng PIN, Set ID vô hiệu."""

import frappe

from tracecore.core import code_registry, station_auth, step_gate
from tracecore.core.errors import BlockedError
from tracecore.instrument import disposal
from tracecore.tests import factories
from tracecore.tests.factories import make_employee, make_user
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]
PIN = "135790"


def blocked(case, code, fn, *args, **kwargs):
	with case.assertRaises(BlockedError) as caught:
		fn(*args, **kwargs)
	case.assertEqual(caught.exception.block.code, code)


class DisposalCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.r01 = make_user("tl-r01@example.com", ["TC R01"])
		self.r02 = make_user("tl-r02@example.com", ["TC R02"])
		self.r04 = make_user("tl-r04@example.com", ["TC R04"])
		employee = make_employee(first_name="Trưởng khoa", user_id=self.r01).name
		station_auth.set_pin(employee, PIN)
		station_auth.clear_pin_rate_limit(employee)
		self.addCleanup(frappe.set_user, "Administrator")

	def end_of_life(self):
		unit = factories.make_set_unit()
		factories.make_cycle(unit.name, passed=("T1", "T2", "T3"))
		step_gate.end_of_life(unit.name, "Hết cơ số")
		return unit.name

	def branch_disposal(self):
		unit = factories.make_set_unit()
		factories.make_cycle(unit.name, passed=("T1", "T2"))
		factories.make_assembly_record(unit.name, result="Fail", branch="Disposal", branch_reason="Khay nứt")
		self.assertEqual(frappe.db.get_value("Set Unit", unit.name, "status"), "Reprocess")
		return unit.name

	def notices(self, user, name):
		return frappe.get_all(
			"Notification Log", filters={"for_user": user, "document_name": name}, pluck="name"
		)


class TestRequest(DisposalCase):
	def test_r02_requests_for_end_of_life_or_t3_disposal_branch(self):
		for set_unit in (self.end_of_life(), self.branch_disposal()):
			frappe.set_user(self.r02)
			disposal.request(set_unit, "Hết cơ số, dụng cụ mòn")
			row = frappe.db.get_value(
				"Set Unit",
				set_unit,
				["disposal_status", "disposal_reason", "disposal_requested_by"],
				as_dict=True,
			)
			self.assertEqual(
				(row.disposal_status, row.disposal_reason, row.disposal_requested_by),
				("Requested", "Hết cơ số, dụng cụ mòn", self.r02),
			)
			self.assertTrue(self.notices(self.r01, set_unit))

	def test_request_rules(self):
		frappe.set_user("Administrator")
		in_use = factories.make_set_unit().name
		eol = self.end_of_life()
		frappe.set_user(self.r04)
		blocked(self, "DISPOSAL_NOT_ALLOWED", disposal.request, eol, "x")
		frappe.set_user(self.r02)
		blocked(self, "REASON_REQUIRED", disposal.request, eol, "  ")
		blocked(self, "DISPOSAL_NOT_ELIGIBLE", disposal.request, in_use, "Chưa hết cơ số")
		disposal.request(eol, "Mòn")
		blocked(self, "DISPOSAL_PENDING", disposal.request, eol, "Lần 2")


class TestDecision(DisposalCase):
	def requested(self):
		set_unit = self.end_of_life()
		frappe.set_user(self.r02)
		disposal.request(set_unit, "Mòn")
		return set_unit

	@bru("BRU-ID-001")
	def test_r01_approves_with_pin_and_set_id_is_disabled_for_ever(self):
		set_unit = self.requested()
		frappe.set_user(self.r01)
		disposal.approve(set_unit, "Đồng ý thanh lý", PIN)
		row = frappe.db.get_value(
			"Set Unit", set_unit, ["status", "disposal_status", "disposal_decided_by"], as_dict=True
		)
		self.assertEqual(
			(row.status, row.disposal_status, row.disposal_decided_by), ("Disposed", "Approved", self.r01)
		)
		self.assertEqual(frappe.db.get_value("Code Registry", set_unit, "status"), "Disabled")
		self.assertTrue(self.notices(self.r02, set_unit))
		# không quay lại được: không hết vòng đời lại, không chuyển tay, Set ID vẫn trong sổ nên không cấp lại
		with self.assertRaises(frappe.ValidationError):
			step_gate.end_of_life(set_unit)
		with self.assertRaises(frappe.ValidationError):
			step_gate.force_status(set_unit, "Processing", "thử")
		self.assertTrue(code_registry.is_issued(set_unit))

	def test_reject_keeps_the_set_and_needs_a_note(self):
		set_unit = self.requested()
		frappe.set_user(self.r01)
		blocked(self, "REASON_REQUIRED", disposal.reject, set_unit, " ", PIN)
		disposal.reject(set_unit, "Còn dùng được sau sửa chữa", PIN)
		row = frappe.db.get_value("Set Unit", set_unit, ["status", "disposal_status"], as_dict=True)
		self.assertEqual((row.status, row.disposal_status), ("End of Life", "Rejected"))
		self.assertEqual(frappe.db.get_value("Code Registry", set_unit, "status"), "Active")

	def test_only_r01_decides_with_a_valid_pin(self):
		set_unit = self.requested()
		frappe.set_user(self.r02)
		blocked(self, "DISPOSAL_NOT_ALLOWED", disposal.approve, set_unit, "ok", PIN)
		frappe.set_user(self.r01)
		blocked(self, "PIN_INVALID", disposal.approve, set_unit, "ok", "000000")
		self.assertEqual(frappe.db.get_value("Set Unit", set_unit, "status"), "End of Life")
		disposal.approve(set_unit, "ok", PIN)
		blocked(self, "DISPOSAL_NOT_PENDING", disposal.approve, set_unit, "ok", PIN)
