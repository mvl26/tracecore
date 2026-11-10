"""Lệnh cách ly và phòng cách ly (FEAT-068; FR-M14-06, FR-M14-06.1, FR-M14-07, .1; BRU-MDR-003, BRU-HAI-005; UC-52;
A-146)."""

import json
from pathlib import Path

import frappe
from frappe.utils import add_days, add_to_date, now_datetime, today

from tracecore.core.errors import BlockedError
from tracecore.microbiology import indicators, isolation
from tracecore.microbiology.tests import factories as mf
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase, bru

R01, R08, R11, R12 = "TC R01", "TC R08", "TC R11", "TC R12"


def make_clinical(name, clinical=1):
	department = mf.make_department(name)
	frappe.db.set_value("Department", department, {"tc_clinical": clinical, "disabled": 0, "is_group": 0})
	return department


def make_dept_user(email, role, department):
	user = make_user(email, [role])
	if not frappe.db.exists(
		"User Permission", {"user": user, "allow": "Department", "for_value": department}
	):
		frappe.get_doc(
			{"doctype": "User Permission", "user": user, "allow": "Department", "for_value": department}
		).insert(ignore_permissions=True)
	return user


def make_room(department, code="PCL-T-01", beds=1, meets=1, checked_on=None, **values):
	doc = frappe.get_doc(
		{
			"doctype": isolation.ROOM_DOCTYPE,
			"room_code": code,
			"department": department,
			"room_type": "Single Room",
			"beds": beds,
			"meets_standard": meets,
			"checked_on": checked_on if checked_on is not None else (today() if meets else None),
			**values,
		}
	)
	return doc.insert(ignore_permissions=True)


class IsolationCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.ward = make_clinical("CL Khoa Hồi sức")
		self.other = make_clinical("CL Khoa Nội")
		for department in (self.ward, self.other):
			frappe.db.delete(isolation.DOCTYPE, {"department": department})
			frappe.db.delete(isolation.ROOM_DOCTYPE, {"department": department})

	def values(self, **extra):
		return {
			"department": self.ward,
			"patient_code": "BN0004821",
			"precaution_type": "Contact",
			"reason": isolation.REASON_COMMUNICABLE,
			**extra,
		}


class TestIsolationRoom(IsolationCase):
	def test_room_meeting_standard_needs_check_date(self):
		with self.assertRaises(frappe.ValidationError):
			make_room(self.ward, meets=1, checked_on="")

	def test_checked_room_not_meeting_standard_needs_note(self):
		with self.assertRaises(frappe.ValidationError):
			make_room(self.ward, meets=0, checked_on=today())
		room = make_room(self.ward, meets=0, checked_on=today(), standard_note="Thiếu bồn rửa tay")
		self.assertEqual(room.standard_note, "Thiếu bồn rửa tay")

	def test_room_not_checked_yet_is_allowed_without_note(self):
		room = make_room(self.ward, meets=0, checked_on="")
		self.assertFalse(room.meets_standard)

	def test_beds_at_least_one_and_code_unique(self):
		with self.assertRaises(frappe.ValidationError):
			make_room(self.ward, beds=0)
		make_room(self.ward, code="PCL-T-09")
		with self.assertRaises(frappe.ValidationError):
			make_room(self.other, code="pcl-t-09")

	def test_occupancy_from_open_orders(self):
		room = make_room(self.ward, beds=2)
		isolation.create_order(self.values(isolation_room=room.name))
		rows = {row["name"]: row for row in isolation.rooms([self.ward])}
		self.assertEqual(rows[room.name]["occupied"], 1)
		self.assertEqual(rows[room.name]["state"], isolation.ROOM_IN_USE)
		self.assertEqual(rows[room.name]["free"], 1)


class TestCreateOrder(IsolationCase):
	def test_order_is_posted_open_with_masked_code(self):
		order = isolation.create_order(self.values())
		self.assertEqual(order.docstatus, 1)
		self.assertEqual(order.status, isolation.OPEN)
		self.assertEqual(order.patient_code_masked, "***4821")
		self.assertTrue(order.patient_code_hash)
		self.assertTrue(order.start_at)
		self.assertTrue(order.name.startswith("CL-"))

	def test_precaution_and_reason_required(self):
		for field in ("precaution_type", "reason"):
			with self.subTest(field=field), self.assertRaises(BlockedError) as raised:
				isolation.create_order(self.values(**{field: ""}))
			self.assertEqual(
				raised.exception.block.code,
				{
					"precaution_type": "ISOLATION_PRECAUTION_REQUIRED",
					"reason": "ISOLATION_REASON_REQUIRED",
				}[field],
			)

	def test_patient_code_required(self):
		with self.assertRaises(BlockedError) as raised:
			isolation.create_order(self.values(patient_code=""))
		self.assertEqual(raised.exception.block.code, "ISOLATION_PATIENT_REQUIRED")

	def test_room_of_other_department_blocked(self):
		room = make_room(self.other, code="PCL-T-OT")
		with self.assertRaises(BlockedError) as raised:
			isolation.create_order(self.values(isolation_room=room.name))
		self.assertEqual(raised.exception.block.code, "ISOLATION_ROOM_INVALID")

	def test_no_room_or_full_room_is_bedside_with_warning(self):
		order = isolation.create_order(self.values())
		self.assertTrue(order.bedside_isolation)
		room = make_room(self.ward, beds=1)
		first = isolation.create_order(self.values(isolation_room=room.name))
		self.assertFalse(first.bedside_isolation)
		second = isolation.create_order(self.values(patient_code="BN0009999", isolation_room=room.name))
		self.assertTrue(second.bedside_isolation)
		self.assertFalse(second.isolation_room)
		self.assertTrue(second.flags.tc_warnings)

	def test_future_start_blocked(self):
		with self.assertRaises(BlockedError) as raised:
			isolation.create_order(self.values(start_at=add_to_date(now_datetime(), hours=2)))
		self.assertEqual(raised.exception.block.code, "ISOLATION_TIME_INVALID")

	def test_reason_mdro_marks_order_mdro(self):
		order = isolation.create_order(self.values(reason=isolation.REASON_MDRO))
		self.assertTrue(order.is_mdro)

	def test_desk_insert_without_service_is_blocked(self):
		doc = frappe.get_doc({"doctype": isolation.DOCTYPE, **self.values()})
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_open_list_by_department(self):
		isolation.create_order(self.values())
		isolation.create_order(self.values(department=self.other, patient_code="BN0001111"))
		rows = isolation.open_orders([self.ward])
		self.assertEqual({row["department"] for row in rows}, {self.ward})
		self.assertNotIn("patient_code", rows[0])
		self.assertEqual(rows[0]["patient_code_masked"], "***4821")
		self.assertEqual(rows[0]["days"], 1)


class TestFromIsolate(IsolationCase):
	def setUp(self):
		super().setUp()
		frappe.db.delete("Microbiology Isolate", {"lab_sample_id": ["like", "CL-L-%"]})
		mf.make_organism()
		if not frappe.db.exists("MDRO Rule", {"rule_code": "T-CRE", "docstatus": 1}):
			mf.make_rule()
		self.isolate = mf.new_isolate(lab="CL-L-001", department=self.ward, patient="BN0007730")

	def test_prefill_from_isolate(self):
		prefill = isolation.prefill(self.isolate.name)
		self.assertEqual(prefill["department"], self.ward)
		self.assertEqual(prefill["reason"], isolation.REASON_MDRO)
		self.assertEqual(prefill["precaution_type"], "Contact")
		self.assertEqual(prefill["patient_code_masked"], "***7730")
		self.assertNotIn("patient_code", prefill)

	def test_order_from_isolate_copies_code_and_resolves_alert(self):
		frappe.get_doc(
			{
				"doctype": "Notification Delivery",
				"recipient": "Administrator",
				"channel": "In App",
				"status": "Sent",
				"event_code": "MDRO_DETECTED",
				"ref_doctype": "Microbiology Isolate",
				"ref_name": self.isolate.name,
				"subject": "x",
			}
		).insert(ignore_permissions=True)
		order = isolation.create_order(
			{"isolate": self.isolate.name, "precaution_type": "Contact", "reason": isolation.REASON_MDRO}
		)
		self.assertEqual(order.department, self.ward)
		self.assertEqual(order.patient_code_hash, self.isolate.patient_code_hash)
		self.assertEqual(order.patient_code_masked, "***7730")
		self.assertTrue(order.is_mdro)
		self.assertFalse(
			frappe.db.exists(
				"Notification Delivery",
				{"event_code": "MDRO_DETECTED", "ref_name": self.isolate.name, "status": "Sent"},
			)
		)

	def test_mdro_alert_links_to_isolation_portal(self):
		from tracecore.microbiology import isolates

		links = []
		original = isolates.notification.emit
		isolates.notification.emit = lambda code, **kw: links.append(kw.get("link")) or []
		self.addCleanup(setattr, isolates.notification, "emit", original)
		isolate = mf.new_isolate(lab="CL-L-002", department=self.ward, patient="BN0007731")
		self.assertEqual(links, [isolation.alert_link(isolate.name)])
		self.assertEqual(isolation.alert_link(isolate.name), f"/ksnk-khoa/cach-ly?isolate={isolate.name}")


class TestCloseOrder(IsolationCase):
	def setUp(self):
		super().setUp()
		self.r08 = make_dept_user("cl-r08@example.com", R08, self.ward)
		self.r12 = make_dept_user("cl-r12@example.com", R12, self.ward)
		self.r11 = make_user("cl-r11@example.com", [R11])

	@bru("BRU-MDR-003")
	def test_close_requires_end_reason(self):
		order = isolation.create_order(self.values())
		with self.assertRaises(BlockedError) as raised:
			isolation.close_order(order.name, end_reason=" ")
		self.assertEqual(raised.exception.block.code, "ISOLATION_END_REASON_REQUIRED")

	@bru("BRU-MDR-003")
	def test_department_staff_cannot_close_mdro_order(self):
		order = isolation.create_order(self.values(reason=isolation.REASON_MDRO))
		for user in (self.r08, self.r12):
			frappe.set_user(user)
			with self.subTest(user=user), self.assertRaises(BlockedError) as raised:
				isolation.close_order(order.name, end_reason="Âm tính 2 lần")
			self.assertEqual(raised.exception.block.code, "ISOLATION_MDRO_CLOSE_DENIED")
		frappe.set_user(self.r11)
		closed = isolation.close_order(order.name, end_reason="Âm tính 2 lần")
		self.assertEqual(closed.status, isolation.CLOSED)
		self.assertEqual(closed.closed_by, self.r11)

	def test_department_staff_close_non_mdro_order(self):
		order = isolation.create_order(self.values())
		frappe.set_user(self.r08)
		closed = isolation.close_order(order.name, end_reason="Hết thời gian lây")
		self.assertEqual(closed.status, isolation.CLOSED)
		self.assertTrue(closed.end_at)
		self.assertEqual(isolation.open_orders([self.ward]), [])

	def test_end_before_start_or_in_future_blocked(self):
		order = isolation.create_order(self.values(start_at=add_days(now_datetime(), -2)))
		for end_at in (add_days(now_datetime(), -3), add_to_date(now_datetime(), hours=2)):
			with self.subTest(end_at=end_at), self.assertRaises(BlockedError) as raised:
				isolation.close_order(order.name, end_reason="x", end_at=end_at)
			self.assertEqual(raised.exception.block.code, "ISOLATION_TIME_INVALID")

	def test_closed_order_cannot_close_again(self):
		order = isolation.create_order(self.values())
		isolation.close_order(order.name, end_reason="Xuất viện")
		with self.assertRaises(BlockedError) as raised:
			isolation.close_order(order.name, end_reason="Xuất viện")
		self.assertEqual(raised.exception.block.code, "ISOLATION_ALREADY_CLOSED")

	def test_other_department_blocked(self):
		order = isolation.create_order(self.values(department=self.other))
		frappe.set_user(self.r08)
		with self.assertRaises(BlockedError) as raised:
			isolation.close_order(order.name, end_reason="x")
		self.assertEqual(raised.exception.block.code, "ISOLATION_NOT_ALLOWED")

	def test_cancel_only_r01_r11(self):
		order = isolation.create_order(self.values())
		frappe.set_user(self.r08)
		with self.assertRaises(frappe.PermissionError):
			isolation.cancel_order(order.name, reason="Nhập nhầm")
		frappe.set_user(self.r11)
		cancelled = isolation.cancel_order(order.name, reason="Nhập nhầm")
		self.assertEqual(cancelled.docstatus, 2)
		self.assertEqual(cancelled.status, isolation.CANCELLED)


class TestNotifications(IsolationCase):
	def test_open_and_close_emit_events(self):
		calls = []
		original = isolation.notification.emit
		isolation.notification.emit = lambda code, **kw: calls.append((code, kw.get("doc").name)) or []
		self.addCleanup(setattr, isolation.notification, "emit", original)
		order = isolation.create_order(self.values())
		isolation.close_order(order.name, end_reason="Xuất viện")
		self.assertEqual(
			calls,
			[(isolation.OPENED_EVENT, order.name), (isolation.CLOSED_EVENT, order.name)],
		)


class TestDepartmentScope(IsolationCase):
	"""NFR-SEC-09, UC-52 E4: R12/R08 khoa A không thấy lệnh và phòng khoa B (Desk list, form)."""

	def test_department_user_lists_only_own_department(self):
		mine = isolation.create_order(self.values())
		theirs = isolation.create_order(self.values(department=self.other, patient_code="BN0003333"))
		make_room(self.ward, code="PCL-T-SC1")
		make_room(self.other, code="PCL-T-SC2")
		r12 = make_dept_user("cl-scope-r12@example.com", R12, self.ward)
		r11 = make_user("cl-scope-r11@example.com", [R11])
		frappe.set_user(r12)
		self.assertEqual(
			set(
				frappe.get_list(
					isolation.DOCTYPE, filters={"name": ["in", [mine.name, theirs.name]]}, pluck="name"
				)
			),
			{mine.name},
		)
		self.assertEqual(
			set(
				frappe.get_list(
					isolation.ROOM_DOCTYPE, filters={"room_code": ["like", "PCL-T-SC%"]}, pluck="room_code"
				)
			),
			{"PCL-T-SC1"},
		)
		self.assertFalse(frappe.has_permission(isolation.DOCTYPE, "read", theirs))
		self.assertTrue(frappe.has_permission(isolation.DOCTYPE, "read", mine))
		frappe.set_user(r11)
		self.assertEqual(
			len(frappe.get_list(isolation.DOCTYPE, filters={"name": ["in", [mine.name, theirs.name]]})), 2
		)

	def test_department_role_without_department_sees_nothing(self):
		from tracecore.microbiology import permissions

		lone = make_user("cl-scope-lone@example.com", [R08])
		frappe.db.delete("User Permission", {"user": lone, "allow": "Department"})
		self.assertEqual(permissions.order_query(lone), "1=0")
		self.assertEqual(permissions.room_query(make_user("cl-scope-r13@example.com", ["TC R13"])), "")


class TestCoverage(IsolationCase):
	def setUp(self):
		super().setUp()
		self.non_clinical = make_clinical("CL Khoa Dược", clinical=0)

	def test_rate_of_clinical_departments_with_a_room_meeting_standard(self):
		make_room(self.ward)
		make_room(self.other, code="PCL-T-NO", meets=0, checked_on=today(), standard_note="Thiếu khu đệm")
		make_room(self.non_clinical, code="PCL-T-DUOC")
		result = isolation.coverage()
		mine = {row["department"]: row for row in result["departments"]}
		self.assertTrue(mine[self.ward]["covered"])
		self.assertFalse(mine[self.other]["covered"])
		self.assertNotIn(self.non_clinical, mine)
		self.assertIn(self.other, [row["department"] for row in result["missing"]])
		num, den, n = indicators.isolation_room_coverage(today()[:7], self.ward)
		self.assertEqual((num, den, n), (1, 1, 1))
		num, den, _n = indicators.isolation_room_coverage(today()[:7], self.other)
		self.assertEqual((num, den), (0, 1))

	def test_room_checked_after_period_not_counted(self):
		make_room(self.ward, checked_on=today())
		last_year = str(int(today()[:4]) - 1) + "-01"
		self.assertEqual(indicators.isolation_room_coverage(last_year, self.ward)[0], 0)

	def test_registered_in_indicator_hook(self):
		from tracecore.core import indicators as core_indicators

		self.assertIn(indicators.COVERAGE_KEY, core_indicators.registry())


class TestPrivacy(IsolationCase):
	@bru("BRU-HAI-005")
	def test_no_patient_name_field_and_code_is_password(self):
		path = Path(frappe.get_app_path("tracecore", "microbiology", "doctype", "isolation_order"))
		meta = json.loads((path / "isolation_order.json").read_text())
		fields = {row["fieldname"]: row for row in meta["fields"]}
		self.assertEqual(fields["patient_code"]["fieldtype"], "Password")
		for name in fields:
			self.assertNotIn("patient_name", name)
			self.assertNotIn("full_name", name)
