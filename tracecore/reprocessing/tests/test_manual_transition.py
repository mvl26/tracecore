"""R02 chuyển trạng thái bộ/gói thủ công khi sự cố hệ thống (FEAT-004, A-37 (b), FR-M2-00.3): lý do + ticket, audit, NC."""

import frappe

from tracecore.core.errors import BlockedError
from tracecore.reprocessing import manual_transition
from tracecore.tests import factories
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def blocked(case, code, fn, *args, **kwargs):
	with case.assertRaises(BlockedError) as caught:
		fn(*args, **kwargs)
	case.assertEqual(caught.exception.block.code, code)


class TestManualTransition(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.r02 = make_user("mt-r02@example.com", ["TC R02"])
		self.r04 = make_user("mt-r04@example.com", ["TC R04"])
		self.unit = factories.make_set_unit()
		factories.make_cycle(self.unit.name, passed=("T1", "T2"))
		self.addCleanup(frappe.set_user, "Administrator")

	@bru("BRU-FLOW-002")
	def test_r02_moves_a_set_with_reason_and_ticket_audit_and_nc(self):
		frappe.set_user(self.r02)
		result = manual_transition.force_set_status(
			self.unit.name, "Awaiting Receipt", "Máy chủ treo khi ghi sổ T3", "SC-2026-015"
		)
		self.assertEqual(frappe.db.get_value("Set Unit", self.unit.name, "status"), "Awaiting Receipt")
		audit = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "Set Unit", "ref_name": self.unit.name, "action": "Override"},
			fields=["reason", "user"],
		)
		self.assertTrue(any("SC-2026-015" in (row.reason or "") and row.user == self.r02 for row in audit))
		incident = frappe.get_doc("Incident CAPA", result["incident"])
		self.assertEqual(incident.set_unit, self.unit.name)
		self.assertIn("SC-2026-015", incident.description)

	def test_rules_role_reason_ticket_and_target(self):
		frappe.set_user(self.r04)
		blocked(
			self,
			"TRANSITION_NOT_ALLOWED",
			manual_transition.force_set_status,
			self.unit.name,
			"Sterile",
			"x",
			"SC-1",
		)
		frappe.set_user(self.r02)
		blocked(
			self,
			"REASON_REQUIRED",
			manual_transition.force_set_status,
			self.unit.name,
			"Sterile",
			" ",
			"SC-1",
		)
		blocked(
			self, "TICKET_REQUIRED", manual_transition.force_set_status, self.unit.name, "Sterile", "x", " "
		)
		for target in ("Disposed", "New", "In Circulation", "Bất kỳ"):
			blocked(
				self,
				"STATUS_INVALID",
				manual_transition.force_set_status,
				self.unit.name,
				target,
				"x",
				"SC-1",
			)
		current = frappe.db.get_value("Set Unit", self.unit.name, "status")
		blocked(
			self, "STATUS_INVALID", manual_transition.force_set_status, self.unit.name, current, "x", "SC-1"
		)

	def test_r02_moves_a_pack(self):
		pack = factories.make_stocked_pack()
		frappe.set_user(self.r02)
		blocked(
			self, "VOID_REASON_REQUIRED", manual_transition.force_pack_status, pack.name, "Void", "x", "SC-1"
		)
		result = manual_transition.force_pack_status(
			pack.name, "Void", "Nhãn hỏng, không quét được", "SC-2026-016", void_reason="Label Damaged"
		)
		row = frappe.db.get_value("Pack", pack.name, ["status", "void_reason"], as_dict=True)
		self.assertEqual((row.status, row.void_reason), ("Void", "Label Damaged"))
		self.assertEqual(frappe.db.get_value("Code Registry", pack.name, "status"), "Disabled")
		self.assertEqual(frappe.db.get_value("Set Unit", pack.set_unit, "status"), "Awaiting Receipt")
		self.assertEqual(frappe.get_doc("Incident CAPA", result["incident"]).pack, pack.name)
		blocked(self, "STATUS_INVALID", manual_transition.force_pack_status, pack.name, "Packed", "x", "SC-1")
		blocked(self, "STATUS_INVALID", manual_transition.force_pack_status, pack.name, "Used", "x", "SC-1")
