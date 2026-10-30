"""Sự cố / NC / CAPA (FEAT-030, UC-15, FR-M2-21, FR-M2-22): Incident CAPA, vòng đời WF-06, NC tự tạo, nhắc quá hạn."""

import frappe
from frappe.utils import add_days, today

from tracecore.core.errors import BlockedError
from tracecore.reprocessing import incidents
from tracecore.tests import factories
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def blocked(case, code, fn, *args, **kwargs):
	with case.assertRaises(BlockedError) as caught:
		fn(*args, **kwargs)
	case.assertEqual(caught.exception.block.code, code)
	return caught.exception.block


class IncidentCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.r01 = make_user("nc-r01@example.com", ["TC R01"])
		self.r02 = make_user("nc-r02@example.com", ["TC R02"])
		self.r04 = make_user("nc-r04@example.com", ["TC R04"])
		self.responsible = make_user("nc-owner@example.com", ["TC R04"])
		self.equipment = factories.make_equipment(
			name="Máy hấp NC", serial="NC-" + frappe.generate_hash(length=8)
		).name
		self.addCleanup(frappe.set_user, "Administrator")

	def as_user(self, user):
		frappe.set_user(user)

	def new(self, **values):
		values = {
			"incident_type": "Equipment Fault",
			"severity": "Medium",
			"description": "Máy báo lỗi áp suất",
			"equipment": self.equipment,
			**values,
		}
		return incidents.create(values)

	def notices(self, user):
		return frappe.get_all(
			"Notification Log",
			filters={"for_user": user, "document_type": "Incident CAPA"},
			pluck="document_name",
		)

	def planned(self, doc):
		incidents.start_analysis(doc.name)
		return incidents.plan_capa(
			doc.name,
			root_cause="Gioăng cửa mòn",
			actions=[
				{
					"action_type": "Corrective",
					"description": "Thay gioăng cửa",
					"responsible": self.responsible,
					"due_date": add_days(today(), 3),
				}
			],
		)


class TestCreate(IncidentCase):
	def test_new_incident_is_draft_named_nc_and_needs_a_linked_object(self):
		# FR-M2-21, FR-M2-21.2 (UC-15 E1): thiếu liên kết đối tượng → không lưu
		self.as_user(self.r04)
		blocked(self, "INCIDENT_LINK_REQUIRED", self.new, equipment=None)
		doc = self.new()
		self.assertTrue(doc.name.startswith("NC-"))
		self.assertEqual((doc.status, doc.docstatus, doc.reported_by), ("New", 0, self.r04))
		self.assertTrue(doc.occurred_at)

	def test_incident_cannot_be_deleted(self):
		# FR-M2-21.4
		doc = self.new()
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Incident CAPA", doc.name, ignore_permissions=True)

	def test_new_incident_notifies_r02_and_high_severity_also_r01(self):
		# FR-M2-21 (thông báo R02), FR-M2-21.3 (mức Cao thông báo R01)
		medium = self.new()
		self.assertIn(medium.name, self.notices(self.r02))
		self.assertNotIn(medium.name, self.notices(self.r01))
		high = self.new(severity="High")
		self.assertIn(high.name, self.notices(self.r01))
		self.assertIn(high.name, self.notices(self.r02))


class TestWorkflow(IncidentCase):
	def test_full_flow_new_analysis_capa_verification_closed(self):
		# FR-M2-22, UC-15 bước 3 đến 6
		doc = self.new()
		self.as_user(self.r02)
		doc = self.planned(doc)
		self.assertEqual(doc.status, "CAPA")
		blocked(self, "CAPA_ACTIONS_OPEN", incidents.submit_verification, doc.name)
		self.as_user(self.responsible)
		incidents.complete_action(doc.name, doc.actions[0].name, "Đã thay gioăng, chạy thử Đạt")
		self.as_user(self.r02)
		doc = incidents.submit_verification(doc.name)
		self.assertEqual(doc.status, "Verification")
		blocked(self, "VERIFICATION_REQUIRED", incidents.close, doc.name, "")
		doc = incidents.close(doc.name, "Ba mẻ liên tiếp Đạt, không tái diễn")
		self.assertEqual((doc.status, doc.docstatus, doc.closed_by), ("Closed", 1, self.r02))

	def test_plan_capa_needs_root_cause_and_complete_actions(self):
		doc = self.new()
		self.as_user(self.r02)
		incidents.start_analysis(doc.name)
		blocked(self, "ROOT_CAUSE_REQUIRED", incidents.plan_capa, doc.name, root_cause=" ", actions=[])
		blocked(self, "CAPA_ACTION_REQUIRED", incidents.plan_capa, doc.name, root_cause="Mòn", actions=[])
		incomplete = [
			{"action_type": "Corrective", "description": "Thay", "responsible": None, "due_date": None}
		]
		blocked(
			self,
			"CAPA_ACTION_INCOMPLETE",
			incidents.plan_capa,
			doc.name,
			root_cause="Mòn",
			actions=incomplete,
		)

	def test_steps_must_follow_order(self):
		doc = self.new()
		self.as_user(self.r02)
		blocked(self, "INCIDENT_STATUS_INVALID", incidents.submit_verification, doc.name)
		blocked(self, "INCIDENT_STATUS_INVALID", incidents.close, doc.name, "ok")

	def test_only_r01_or_r02_move_close_or_cancel(self):
		# FR-M2-22.2: vai trò khác không được đóng
		doc = self.new()
		self.as_user(self.r04)
		blocked(self, "INCIDENT_NOT_ALLOWED", incidents.start_analysis, doc.name)
		blocked(self, "INCIDENT_NOT_ALLOWED", incidents.cancel, doc.name, "Trùng")
		self.as_user(self.r01)
		doc = self.planned(doc)
		incidents.complete_action(doc.name, doc.actions[0].name, "Xong")
		incidents.submit_verification(doc.name)
		self.as_user(self.r04)
		blocked(self, "INCIDENT_NOT_ALLOWED", incidents.close, doc.name, "Đạt")
		self.as_user(self.r01)
		self.assertEqual(incidents.close(doc.name, "Đạt").status, "Closed")

	def test_cancel_needs_reason_and_closes_the_record(self):
		# FR-M2-21.4: hủy phải có lý do
		doc = self.new()
		self.as_user(self.r02)
		blocked(self, "REASON_REQUIRED", incidents.cancel, doc.name, "  ")
		doc = incidents.cancel(doc.name, "Ghi trùng NC-khác")
		self.assertEqual(
			(doc.status, doc.docstatus, doc.cancel_reason), ("Cancelled", 1, "Ghi trùng NC-khác")
		)
		blocked(self, "INCIDENT_STATUS_INVALID", incidents.cancel, doc.name, "lại")

	def test_only_responsible_or_supervisor_completes_an_action(self):
		doc = self.new()
		self.as_user(self.r02)
		doc = self.planned(doc)
		self.as_user(self.r04)
		blocked(self, "INCIDENT_NOT_ALLOWED", incidents.complete_action, doc.name, doc.actions[0].name, "x")
		self.as_user(self.responsible)
		blocked(self, "RESULT_REQUIRED", incidents.complete_action, doc.name, doc.actions[0].name, " ")

	def test_status_cannot_be_edited_by_hand(self):
		doc = self.new()
		doc = frappe.get_doc("Incident CAPA", doc.name)
		doc.status = "Closed"
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)


class TestAutoNc(IncidentCase):
	def test_wash_failed_creates_one_incident_per_batch(self):
		# FR-M2-21.1, FR-M2-04.4
		washer = factories.make_equipment(
			name="Máy rửa NC",
			equipment_type="Washer-Disinfector",
			serial="NCW-" + frappe.generate_hash(length=8),
			zone_in="ZONE-DIRTY",
			zone_out=None,
		).name
		batch = factories.make_wash_batch(
			washer, factories.make_wash_program(washer), [factories.make_set_unit()]
		).name
		ctx = {"batch": batch, "equipment": washer, "program": None, "sets": ["S1"], "result": "Fail"}
		first = incidents.on_wash_failed(ctx)
		again = incidents.on_wash_failed(ctx)
		self.assertEqual(first, again)
		doc = frappe.get_doc("Incident CAPA", first)
		self.assertEqual(
			(
				doc.incident_type,
				doc.severity,
				doc.is_auto,
				doc.source_doctype,
				doc.source_name,
				doc.equipment,
			),
			("Wash Failed", "Medium", 1, "Wash Batch", batch, washer),
		)

	def test_load_failed_creates_high_incident(self):
		# FR-M2-21.1, FR-M2-12.2: NC loại Mẻ không đạt
		program = factories.make_sterilize_program(self.equipment)
		load = factories.make_load(self.equipment, program, [factories.make_load_ready_pack()]).name
		ctx = {"load": load, "equipment": self.equipment, "program": None, "sets": [], "redo_from": "T4"}
		name = incidents.on_load_failed(ctx)
		doc = frappe.get_doc("Incident CAPA", name)
		self.assertEqual((doc.incident_type, doc.severity, doc.source_name), ("Load Failed", "High", load))
		self.assertIn(name, self.notices(self.r01))

	def test_assembly_shortage_and_foreign_instrument(self):
		# FR-M2-06.2 thiếu dụng cụ, FR-M1-02.4 dụng cụ lạ
		unit = factories.make_set_unit()
		factories.make_cycle(unit.name, passed=("T1", "T2"))
		assembly = factories.make_assembly_record(unit.name, submit=False).name
		shortage = incidents.on_assembly_nc(
			{"assembly": assembly, "set_unit": unit.name, "kind": "Shortage", "items": ["DC-1"]}
		)
		foreign = incidents.on_assembly_nc(
			{"assembly": assembly, "set_unit": unit.name, "kind": "Foreign Instrument", "items": ["DC-9"]}
		)
		self.assertNotEqual(shortage, foreign)
		self.assertEqual(
			frappe.db.get_value("Incident CAPA", shortage, "incident_type"), "Missing Instrument"
		)
		self.assertEqual(frappe.db.get_value("Incident CAPA", foreign, "incident_type"), "Foreign Instrument")
		self.assertIn("DC-1", frappe.db.get_value("Incident CAPA", shortage, "description"))

	def test_hooks_are_registered(self):
		self.assertIn(
			"tracecore.reprocessing.incidents.on_wash_failed", frappe.get_hooks("tracecore_after_wash_failed")
		)
		self.assertIn(
			"tracecore.reprocessing.incidents.on_load_failed", frappe.get_hooks("tracecore_after_load_failed")
		)
		self.assertIn(
			"tracecore.reprocessing.incidents.on_assembly_nc", frappe.get_hooks("tracecore_assembly_nc")
		)


class TestOverdue(IncidentCase):
	def test_overdue_action_reminds_owner_and_r02_once_a_day(self):
		# FR-M2-22.1, UC-15 E2
		doc = self.new()
		self.as_user(self.r02)
		doc = self.planned(doc)
		frappe.db.set_value("CAPA Action", doc.actions[0].name, "due_date", add_days(today(), -1))
		frappe.set_user("Administrator")
		self.assertEqual(incidents.remind_overdue(), 1)
		self.assertEqual(incidents.remind_overdue(), 0)
		self.assertIn(doc.name, self.notices(self.responsible))
		self.assertGreaterEqual(self.notices(self.r02).count(doc.name), 2)  # lúc tạo + nhắc quá hạn


class TestWasteNc(IncidentCase):
	@bru("BRU-WST-001")
	def test_waste_misclassification_creates_one_incident_per_container(self):
		"""M10 báo qua hook, M2 tạo NC (FEAT-047, FR-M10-02.4, A-60 W3)."""
		employee = factories.make_employee(first_name="Waste NC").name
		container = factories.make_waste_container()
		ctx = {
			"container": container,
			"waste_type": "Sharp",
			"department": None,
			"employee": employee,
			"station": None,
			"note": "Sharps outside the box",
		}
		name = incidents.on_waste_nc(ctx)
		self.assertEqual(incidents.on_waste_nc(ctx), name)
		doc = frappe.get_doc("Incident CAPA", name)
		self.assertEqual(doc.incident_type, "Waste Misclassification")
		self.assertEqual((doc.source_doctype, doc.source_name), ("Waste Container", ctx["container"]))
		self.assertEqual(doc.employee, employee)
		self.assertIn("Sharps outside the box", doc.description)

	def test_hook_is_registered(self):
		self.assertIn("tracecore.reprocessing.incidents.on_waste_nc", frappe.get_hooks("tracecore_waste_nc"))
