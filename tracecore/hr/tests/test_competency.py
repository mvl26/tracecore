"""Ma trận năng lực theo trạm (FEAT-037, FR-M4-03, UC-20, BRU-HR-001): gán/thu hồi, chứng chỉ bắt buộc, quyền tạm 24 giờ."""

import frappe
from frappe.utils import add_days, add_to_date, get_datetime, now_datetime, today

from tracecore.core import station_auth
from tracecore.core.errors import BlockedError
from tracecore.hr import certificates, competency, reminders
from tracecore.tests.factories import make_employee, make_user
from tracecore.tests.utils import IsolatedTestCase, bru
from tracecore.v1.tests.station_fixtures import make_station_employee

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]
STATION = "TR-004"  # T4, khu Sạch
KNOWN_TYPES = ["Practice License", "Infection Control", "Sterilization", "Pressure Equipment Operation"]
USERS = ["comp-r02@example.com", "comp-r10@example.com", "comp-r04@example.com", "comp-r05@example.com"]


def make_certificate(employee, certificate_type, days):
	return frappe.get_doc(
		{
			"doctype": "Certificate",
			"employee": employee,
			"certificate_type": certificate_type,
			"certificate_no": "CC-" + frappe.generate_hash(length=8),
			"issued_on": add_days(today(), -400),
			"no_expiry": 1 if days is None else 0,
			"expires_on": None if days is None else add_days(today(), days),
		}
	).insert(ignore_permissions=True)


def grant(employee, station=STATION, **kwargs):
	return competency.grant(
		employee, station, valid_until=kwargs.pop("valid_until", add_days(now_datetime(), 30)), **kwargs
	)


class CompetencyCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.r02 = make_user(USERS[0], ["TC R02"])
		self.r10 = make_user(USERS[1], ["TC R10"])
		self.r04 = make_user(USERS[2], ["TC R04"])
		self.worker_user = make_user(USERS[3], ["TC R04"])
		self.employee = make_station_employee(self.worker_user)
		holder = make_employee(first_name="Người giữ chứng chỉ").name
		for certificate_type in KNOWN_TYPES:
			make_certificate(holder, certificate_type, None)
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(self.r02)

	def reject_code(self, call, *args, **kwargs):
		with self.assertRaises(BlockedError) as caught:
			call(*args, **kwargs)
		return caught.exception.block.code

	def last_reject(self):
		rows = frappe.get_all(
			"Audit Log",
			filters={"action": "Reject", "ref_name": self.employee.name},
			fields=["new_value"],
			order_by="creation desc",
			limit=1,
		)
		return rows[0] if rows else None


class TestGrantAndRevoke(CompetencyCase):
	@bru("BRU-HR-001")
	def test_r02_grants_with_evaluator_date_and_required_certificates(self):
		doc = grant(
			self.employee.name, required_certificates=["Pressure Equipment Operation", "Sterilization"]
		)
		self.assertEqual((doc.is_active, doc.is_temporary), (1, 0))
		self.assertEqual(doc.evaluator, self.r02)
		self.assertEqual(str(doc.evaluated_on), today())
		self.assertEqual(
			sorted(row.certificate_type for row in doc.required_certificates),
			["Pressure Equipment Operation", "Sterilization"],
		)
		self.assertTrue(
			frappe.db.exists("Audit Log", {"ref_doctype": "Station Competency", "ref_name": doc.name})
		)

	def test_only_r02_r10_and_system_manager_can_grant(self):
		frappe.set_user(self.r04)
		self.assertEqual(self.reject_code(grant, self.employee.name), "COMPETENCY_NOT_ALLOWED")
		frappe.set_user(self.r10)
		self.assertEqual(grant(self.employee.name).is_active, 1)

	def test_second_active_competency_for_the_same_station_is_refused(self):
		grant(self.employee.name)
		self.assertEqual(self.reject_code(grant, self.employee.name), "COMPETENCY_EXISTS")

	def test_period_station_and_certificate_type_are_validated(self):
		self.assertEqual(
			self.reject_code(
				grant,
				self.employee.name,
				valid_from=add_days(now_datetime(), 5),
				valid_until=add_days(now_datetime(), 2),
			),
			"COMPETENCY_INVALID",
		)
		self.assertEqual(self.reject_code(grant, self.employee.name, station="ZONE-CLEAN"), "STATION_INVALID")
		self.assertEqual(
			self.reject_code(grant, self.employee.name, required_certificates=["Magic"]),
			"CERTIFICATE_TYPE_INVALID",
		)
		self.assertEqual(self.reject_code(grant, "NV-NOBODY"), "EMPLOYEE_INVALID")

	def test_required_types_follow_the_types_already_used(self):
		doc = grant(self.employee.name, required_certificates=[" sterilization ", "Sterilization"])
		self.assertEqual([row.certificate_type for row in doc.required_certificates], ["Sterilization"])
		self.assertEqual(
			self.reject_code(
				grant, self.employee.name, station="TR-005", required_certificates=["Lái xe nâng"]
			),
			"CERTIFICATE_TYPE_INVALID",
		)
		make_certificate(self.employee.name, "Lái xe nâng", 30)
		self.assertEqual(
			competency.required_types(
				grant(self.employee.name, station="TR-005", required_certificates=["Lái xe nâng"]).name
			),
			["Lái xe nâng"],
		)

	def test_matrix_offers_the_types_already_used(self):
		self.assertLessEqual(set(KNOWN_TYPES), set(competency.matrix()["certificate_types"]))

	@bru("BRU-HR-001")
	def test_temporary_access_needs_a_reason_and_is_limited_to_24_hours(self):
		soon = add_to_date(now_datetime(), hours=23)
		self.assertEqual(
			self.reject_code(grant, self.employee.name, valid_until=soon, is_temporary=1), "REASON_REQUIRED"
		)
		self.assertEqual(
			self.reject_code(
				grant,
				self.employee.name,
				valid_until=add_to_date(now_datetime(), hours=25),
				is_temporary=1,
				reason="Thiếu người ca đêm",
			),
			"TEMP_TOO_LONG",
		)
		doc = grant(self.employee.name, valid_until=soon, is_temporary=1, reason="Thiếu người ca đêm")
		self.assertEqual(
			(doc.is_temporary, doc.approved_by, doc.temporary_reason), (1, self.r02, "Thiếu người ca đêm")
		)

	def test_revoke_deactivates_keeps_the_record_and_needs_a_reason(self):
		doc = grant(self.employee.name)
		self.assertEqual(self.reject_code(competency.revoke, doc.name, ""), "REASON_REQUIRED")
		competency.revoke(doc.name, "Chuyển khu")
		self.assertEqual(frappe.db.get_value("Station Competency", doc.name, "is_active"), 0)
		self.assertEqual(self.reject_code(competency.revoke, doc.name, "Lần hai"), "COMPETENCY_NOT_ACTIVE")
		frappe.set_user(self.r04)
		other = frappe.db.get_value("Station Competency", doc.name, "name")
		self.assertEqual(self.reject_code(competency.revoke, other, "x"), "COMPETENCY_NOT_ALLOWED")

	def test_regrant_after_revoke_is_allowed(self):
		first = grant(self.employee.name)
		competency.revoke(first.name, "Sai trạm")
		self.assertNotEqual(grant(self.employee.name).name, first.name)


class TestLoginCertificates(CompetencyCase):
	def login(self):
		return station_auth.login(self.employee.tc_card_id, STATION)

	def test_no_required_certificates_keeps_the_existing_login_behaviour(self):
		grant(self.employee.name)
		self.assertEqual(self.login()["station"], STATION)

	@bru("BRU-HR-001")
	def test_missing_required_certificate_blocks_login_and_audits_the_reason(self):
		grant(self.employee.name, required_certificates=["Pressure Equipment Operation"])
		with self.assertRaises(BlockedError) as caught:
			self.login()
		# A-71 (g): thẻ hợp lệ thấy NS-001 kèm loại chứng chỉ
		self.assertEqual(caught.exception.block.as_dict()["error_code"], "NS-001")
		self.assertEqual(caught.exception.block.items, ["Pressure Equipment Operation"])
		reject = self.last_reject()
		self.assertIn("CERTIFICATE_REQUIRED", reject.new_value)
		self.assertIn("Pressure Equipment Operation", reject.new_value)

	@bru("BRU-HR-001")
	def test_valid_certificate_lets_the_employee_in_and_expiry_blocks_again(self):
		cert = make_certificate(self.employee.name, "Pressure Equipment Operation", 30)
		grant(self.employee.name, required_certificates=["Pressure Equipment Operation"])
		self.assertEqual(self.login()["employee"], self.employee.name)
		frappe.db.set_value("Certificate", cert.name, "expires_on", add_days(today(), -1))
		with self.assertRaises(BlockedError):
			self.login()
		self.assertIn("CERTIFICATE_REQUIRED", self.last_reject().new_value)

	@bru("BRU-HR-002")
	def test_expired_certificate_temporary_access_until_expiry(self):
		"""Nghiệm thu A-71: hết hạn thì không vào, thấy NS-001; duyệt tạm thì vào, có log người duyệt; hết hạn duyệt thì lại không vào."""
		from unittest.mock import patch

		from tracecore.core import error_codes
		from tracecore.setup.error_codes import ensure_error_codes
		from tracecore.v1.station import _session_response

		ensure_error_codes()
		grant(self.employee.name, required_certificates=["Pressure Equipment Operation"])
		body = _session_response(self.login, STATION)
		self.assertEqual(body["error"]["error_code"], "NS-001")
		log = frappe.get_all(
			"TraceCore Error Log",
			filters={"error_code": "NS-001", "object_name": self.employee.name, "status": "Open"},
			pluck="name",
		)[0]
		with patch.object(error_codes.frappe, "get_roles", return_value=["TC R02"]):
			error_codes.grant_permit(log, 2, "ca mổ cấp cứu")
		row = frappe.get_doc("TraceCore Error Log", log)
		self.assertEqual(row.status, "Temporarily Allowed")
		self.assertEqual(row.approved_by, frappe.session.user)
		session = self.login()
		expires = frappe.db.get_value("Station Session", session["session"], "absolute_expires_at")
		self.assertEqual(get_datetime(expires), get_datetime(row.valid_until))
		frappe.db.set_value("TraceCore Error Log", log, "valid_until", add_to_date(now_datetime(), hours=-1))
		with self.assertRaises(BlockedError):
			self.login()

	def test_renewal_restores_the_login(self):
		old = make_certificate(self.employee.name, "Sterilization", -1)
		grant(self.employee.name, required_certificates=["Sterilization"])
		with self.assertRaises(BlockedError):
			self.login()
		frappe.get_doc(
			{
				"doctype": "Certificate",
				"employee": self.employee.name,
				"certificate_type": "Sterilization",
				"certificate_no": "CC-NEW-" + frappe.generate_hash(length=6),
				"issued_on": today(),
				"expires_on": add_days(today(), 365),
				"renews": old.name,
			}
		).insert(ignore_permissions=True)
		self.assertEqual(self.login()["employee"], self.employee.name)

	def test_permanent_certificate_never_blocks(self):
		make_certificate(self.employee.name, "Practice License", None)
		grant(self.employee.name, required_certificates=["Practice License"])
		self.assertEqual(self.login()["employee"], self.employee.name)

	def test_temporary_access_still_needs_the_required_certificates(self):
		grant(
			self.employee.name,
			valid_until=add_to_date(now_datetime(), hours=2),
			is_temporary=1,
			reason="Thiếu người",
			required_certificates=["Sterilization"],
		)
		with self.assertRaises(BlockedError):
			self.login()

	def test_without_competency_the_reject_code_stays_competency_required(self):
		with self.assertRaises(BlockedError):
			self.login()
		self.assertIn("COMPETENCY_REQUIRED", self.last_reject().new_value)

	def test_revoked_competency_blocks_login(self):
		doc = grant(self.employee.name)
		competency.revoke(doc.name, "Nghỉ phép dài")
		with self.assertRaises(BlockedError):
			self.login()


class TestMatrix(CompetencyCase):
	def cell(self, employee=None, station=STATION, zone=None):
		data = competency.matrix(zone)
		row = next(r for r in data["employees"] if r["employee"] == (employee or self.employee.name))
		return row["cells"].get(station)

	def test_cell_states_none_valid_temporary_and_suspended(self):
		self.assertEqual(self.cell()["state"], "none")
		doc = grant(self.employee.name)
		self.assertEqual(self.cell()["state"], "valid")
		competency.revoke(doc.name, "Đổi trạm")
		grant(
			self.employee.name,
			valid_until=add_to_date(now_datetime(), hours=3),
			is_temporary=1,
			reason="Thiếu người",
		)
		self.assertEqual(self.cell()["state"], "temporary")

	@bru("BRU-HR-001")
	def test_expired_certificate_suspends_the_cell_and_names_what_is_missing(self):
		grant(self.employee.name, required_certificates=["Pressure Equipment Operation"])
		cell = self.cell()
		self.assertEqual((cell["state"], cell["missing"]), ("suspended", ["Pressure Equipment Operation"]))
		make_certificate(self.employee.name, "Pressure Equipment Operation", 40)
		self.assertEqual(self.cell()["state"], "valid")

	def test_zone_filter_limits_the_stations(self):
		zone = frappe.db.get_value("Zone Station", STATION, "parent_zone")
		data = competency.matrix(zone)
		self.assertIn(STATION, [s["name"] for s in data["stations"]])
		self.assertTrue(all(s["zone"] == zone for s in data["stations"]))
		other = next(z for z in ("ZONE-DIRTY", "ZONE-STERILE") if z != zone)
		self.assertNotIn(STATION, [s["name"] for s in competency.matrix(other)["stations"]])

	def test_only_active_employees_are_listed(self):
		frappe.db.set_value("Employee", self.employee.name, "status", "Left")
		names = [row["employee"] for row in competency.matrix()["employees"]]
		self.assertNotIn(self.employee.name, names)

	def test_matrix_is_readable_by_r02_but_not_by_r04(self):
		self.assertTrue(competency.matrix()["stations"])
		frappe.set_user(self.r04)
		self.assertEqual(self.reject_code(competency.matrix), "COMPETENCY_NOT_ALLOWED")


class TestSuspensionNotice(CompetencyCase):
	def test_expiring_a_certificate_tells_r02_which_competencies_are_suspended(self):
		cert = make_certificate(self.employee.name, "Sterilization", 3)
		grant(self.employee.name, required_certificates=["Sterilization"])
		other_station = "TR-006"
		if frappe.db.exists("Zone Station", other_station):
			grant(self.employee.name, station=other_station)  # không yêu cầu chứng chỉ: không bị ảnh hưởng
		frappe.db.set_value("Certificate", cert.name, "expires_on", add_days(today(), -1))
		reminders.run_daily()
		rows = frappe.get_all(
			"Notification Delivery",
			filters={"event_code": "COMPETENCY_SUSPENDED", "recipient": ["in", USERS], "channel": "In App"},
			fields=["recipient", "subject"],
		)
		self.assertEqual({row.recipient for row in rows}, {self.r02, self.worker_user})
		self.assertTrue(all(STATION in row.subject for row in rows))
		self.assertFalse(any(other_station in row.subject for row in rows))
		reminders.run_daily()  # không báo lại
		self.assertEqual(
			frappe.db.count(
				"Notification Delivery",
				{"event_code": "COMPETENCY_SUSPENDED", "recipient": ["in", USERS], "channel": "In App"},
			),
			len(rows),
		)

	def test_certificate_helpers_agree_with_the_competency_check(self):
		make_certificate(self.employee.name, "Sterilization", 10)
		doc = grant(self.employee.name, required_certificates=["Sterilization", "Infection Control"])
		self.assertEqual(
			competency.missing_certificate_types(self.employee.name, doc.name), ["Infection Control"]
		)
		self.assertEqual(certificates.valid_certificate_types(self.employee.name), {"Sterilization"})
