"""Hồ sơ nhân sự và chứng chỉ (FEAT-036, FR-M4-01, FR-M4-02, UC-19): Certificate, nhắc hạn 60/30/7, mã NV-."""

import frappe
from frappe.utils import add_days, today

from tracecore.hr import certificates, employees, reminders
from tracecore.patches.v0_1 import rename_certificate_types
from tracecore.tests.factories import make_employee, make_user
from tracecore.tests.utils import IsolatedTestCase, bru
from tracecore.v1 import staff as staff_api

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]
USERS = ["cert-r02@example.com", "cert-r10@example.com", "cert-r04@example.com", "cert-r03@example.com"]


def make_certificate(employee, days=None, **fields):
	"""Certificate của `employee`; `days` = số ngày tới hạn tính từ hôm nay (None = vĩnh viễn)."""
	values = {
		"doctype": "Certificate",
		"employee": employee,
		"certificate_type": "Sterilization",
		"certificate_no": "CC-" + frappe.generate_hash(length=8),
		"issuer": "Sở Y tế",
		"issued_on": add_days(today(), -400),
		"no_expiry": 1 if days is None else 0,
		"expires_on": None if days is None else add_days(today(), days),
		**fields,
	}
	return frappe.get_doc(values).insert(ignore_permissions=True)


def deliveries(event, **filters):
	return frappe.get_all(
		"Notification Delivery",
		filters={"event_code": event, "channel": "In App", "recipient": ["in", USERS], **filters},
		fields=["recipient", "subject"],
	)


class TestCertificate(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.r02 = make_user(USERS[0], ["TC R02"])
		self.r10 = make_user(USERS[1], ["TC R10"])
		self.r04 = make_user(USERS[2], ["TC R04"])
		self.staff = make_employee(first_name="Chứng chỉ", user_id=self.r04).name
		self.addCleanup(frappe.set_user, "Administrator")

	# --- FR-M4-02: bản ghi chứng chỉ ---
	def test_valid_certificate_gets_status_and_employee_name(self):
		cert = make_certificate(self.staff, 200)
		self.assertEqual(cert.status, "Valid")
		self.assertEqual(cert.employee_name, frappe.db.get_value("Employee", self.staff, "employee_name"))

	@bru("BRU-HR-002")
	def test_certificate_past_its_date_is_expired_from_the_start(self):
		self.assertEqual(make_certificate(self.staff, -1).status, "Expired")

	@bru("BRU-HR-002")
	def test_permanent_certificate_has_no_expiry_and_never_expires(self):
		cert = make_certificate(self.staff, None, expires_on=add_days(today(), -5))
		self.assertEqual((cert.status, cert.expires_on), ("Valid", None))
		reminders.run_daily()
		self.assertEqual(frappe.db.get_value("Certificate", cert.name, "status"), "Valid")
		self.assertEqual(deliveries("CERTIFICATE_EXPIRING", subject=["like", f"%{cert.certificate_no}%"]), [])

	def test_expiry_date_is_required_unless_permanent(self):
		with self.assertRaises(frappe.ValidationError):
			make_certificate(self.staff, 10, expires_on=None)

	def test_expiry_cannot_be_before_issue_date(self):
		with self.assertRaises(frappe.ValidationError):
			make_certificate(self.staff, 10, issued_on=add_days(today(), 20))

	def test_scan_over_10_mb_is_refused(self):
		saved = frappe.get_doc(
			{"doctype": "File", "file_name": "tc-cert-scan.txt", "content": b"scan", "is_private": 1}
		).insert(ignore_permissions=True)
		frappe.db.set_value("File", saved.name, "file_size", 10 * 1024 * 1024 + 1)
		with self.assertRaises(frappe.ValidationError):
			make_certificate(self.staff, 30, scan=saved.file_url)
		frappe.db.set_value("File", saved.name, "file_size", 10 * 1024 * 1024)
		self.assertEqual(make_certificate(self.staff, 30, scan=saved.file_url).scan, saved.file_url)

	# --- FR-M4-02.3: gia hạn giữ lịch sử ---
	def test_renewal_creates_a_new_record_and_keeps_the_old_one(self):
		old = make_certificate(self.staff, 5)
		new = make_certificate(self.staff, 400, renews=old.name)
		self.assertEqual(frappe.db.get_value("Certificate", old.name, "status"), "Superseded")
		self.assertEqual(new.status, "Valid")
		self.assertEqual(new.renews, old.name)

	def test_renewal_must_be_for_the_same_employee_and_type(self):
		old = make_certificate(self.staff, 5)
		other = make_employee(first_name="Người khác").name
		with self.assertRaises(frappe.ValidationError):
			make_certificate(other, 400, renews=old.name)
		with self.assertRaises(frappe.ValidationError):
			make_certificate(self.staff, 400, renews=old.name, certificate_type="Infection Control")

	def test_certificates_cannot_be_deleted(self):
		cert = make_certificate(self.staff, 30)
		with self.assertRaises(frappe.PermissionError):
			frappe.delete_doc("Certificate", cert.name, force=True)

	# --- quyền ---
	def test_permissions_r02_and_r10_write_r04_has_no_access(self):
		cert = make_certificate(self.staff, 30)
		frappe.set_user(self.r04)
		self.assertFalse(frappe.has_permission("Certificate", "read", doc=cert.name))
		frappe.set_user(self.r02)
		self.assertTrue(frappe.has_permission("Certificate", "write", doc=cert.name))
		frappe.set_user(self.r10)
		self.assertTrue(frappe.has_permission("Certificate", "create"))

	# --- FR-M4-02.1/.2: nhắc hạn và hết hạn ---
	def test_valid_types_for_competency_checks(self):
		make_certificate(self.staff, 30, certificate_type="Sterilization")
		make_certificate(self.staff, -3, certificate_type="Infection Control")
		make_certificate(self.staff, None, certificate_type="Practice License")
		self.assertEqual(
			certificates.valid_certificate_types(self.staff), {"Sterilization", "Practice License"}
		)
		self.assertEqual(
			certificates.valid_certificate_types(self.staff, add_days(today(), 31)), {"Practice License"}
		)

	@bru("BRU-HR-002")
	def test_reminders_go_to_employee_and_r02_once_per_threshold(self):
		cert = make_certificate(self.staff, 60)
		reminders.run_daily()
		sent = deliveries("CERTIFICATE_EXPIRING", subject=["like", f"%{cert.certificate_no}%"])
		self.assertEqual({row.recipient for row in sent}, {self.r04, self.r02})
		reminders.run_daily()  # cùng ngưỡng: không nhắc lại
		self.assertEqual(
			len(deliveries("CERTIFICATE_EXPIRING", subject=["like", f"%{cert.certificate_no}%"])), len(sent)
		)
		for days, level in ((30, 30), (7, 7)):
			frappe.db.set_value("Certificate", cert.name, "expires_on", add_days(today(), days))
			reminders.run_daily()
			self.assertEqual(frappe.db.get_value("Certificate", cert.name, "reminded_level"), level)
		self.assertEqual(
			len(deliveries("CERTIFICATE_EXPIRING", subject=["like", f"%{cert.certificate_no}%"])),
			len(sent) * 3,
		)

	def test_far_future_certificate_is_not_reminded(self):
		cert = make_certificate(self.staff, 61)
		reminders.run_daily()
		self.assertEqual(deliveries("CERTIFICATE_EXPIRING", subject=["like", f"%{cert.certificate_no}%"]), [])

	@bru("BRU-HR-002")
	def test_expired_certificate_is_marked_and_announced_once(self):
		cert = make_certificate(self.staff, 3)
		frappe.db.set_value("Certificate", cert.name, "expires_on", add_days(today(), -1))
		reminders.run_daily()
		self.assertEqual(frappe.db.get_value("Certificate", cert.name, "status"), "Expired")
		sent = deliveries("CERTIFICATE_EXPIRED", subject=["like", f"%{cert.certificate_no}%"])
		self.assertEqual({row.recipient for row in sent}, {self.r04, self.r02})
		reminders.run_daily()
		self.assertEqual(
			len(deliveries("CERTIFICATE_EXPIRED", subject=["like", f"%{cert.certificate_no}%"])), len(sent)
		)

	def test_superseded_certificate_is_not_reminded(self):
		old = make_certificate(self.staff, 7)
		make_certificate(self.staff, 400, renews=old.name)
		reminders.run_daily()
		self.assertEqual(deliveries("CERTIFICATE_EXPIRING", subject=["like", f"%{old.certificate_no}%"]), [])

	# --- FR-M4-01.4: khám sức khỏe, tiêm chủng ---
	def test_health_and_vaccination_expiry_reminders(self):
		frappe.db.set_value(
			"Employee",
			self.staff,
			{"tc_health_check_expiry": add_days(today(), 30), "tc_vaccination_expiry": add_days(today(), -2)},
		)
		reminders.run_daily()
		rows = deliveries("HEALTH_RECORD_EXPIRING")
		self.assertEqual({row.recipient for row in rows}, {self.r04, self.r02})
		self.assertEqual(len(rows), 4)  # hai loại hồ sơ, mỗi loại gửi cho nhân viên và R02
		reminders.run_daily()
		self.assertEqual(len(deliveries("HEALTH_RECORD_EXPIRING")), 4)

	def test_changing_the_expiry_date_resets_the_reminder_level(self):
		frappe.db.set_value(
			"Employee",
			self.staff,
			{"tc_health_check_expiry": add_days(today(), 7), "tc_health_remind_level": 7},
		)
		employee = frappe.get_doc("Employee", self.staff)
		employee.tc_health_check_expiry = add_days(today(), 365)
		employee.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Employee", self.staff, "tc_health_remind_level"), 0)


class TestEmployeeCode(IsolatedTestCase):
	def new_employee(self, **fields):
		return frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": "Mã NV",
				"gender": "Female",
				"date_of_birth": "1992-02-02",
				"date_of_joining": today(),
				"company": "_Test Company",
				"status": "Active",
				**fields,
			}
		).insert(ignore_permissions=True, ignore_mandatory=True, ignore_links=True)

	@bru("BRU-ID-006")
	def test_new_employee_gets_a_system_generated_nv_code_in_the_registry(self):
		first, second = self.new_employee(), self.new_employee()
		self.assertRegex(first.name, r"^NV-\d{5}$")
		self.assertNotEqual(first.name, second.name)
		registry = frappe.db.get_value(
			"Code Registry", first.name, ["prefix", "ref_doctype", "ref_name", "status"], as_dict=True
		)
		self.assertEqual(
			(registry.prefix, registry.ref_doctype, registry.ref_name, registry.status),
			("NV", "Employee", first.name, "Active"),
		)

	def test_card_defaults_to_the_nv_code(self):
		employee = self.new_employee()
		self.assertEqual(frappe.db.get_value("Employee", employee.name, "tc_card_id"), employee.name)

	def test_hospital_card_entered_by_hand_is_kept(self):
		employee = self.new_employee(tc_card_id="BV-THE-0042", tc_card_enabled=1)
		self.assertEqual(frappe.db.get_value("Employee", employee.name, "tc_card_id"), "BV-THE-0042")
		self.assertEqual(frappe.db.get_value("Employee", employee.name, "tc_card_enabled"), 1)

	def test_existing_nv_code_is_not_issued_twice(self):
		employee = self.new_employee()
		employees.register_code(employee)  # gọi lại không lỗi và không nhân đôi
		self.assertEqual(frappe.db.count("Code Registry", {"code": employee.name}), 1)


class TestFreeTextCertificateType(IsolatedTestCase):
	"""Loại chứng chỉ tự điền, gợi ý từ các loại đã dùng (A-58, FR-M4-02)."""

	def setUp(self):
		super().setUp()
		self.staff = make_employee(first_name="Nhân viên chứng chỉ").name
		self.addCleanup(frappe.set_user, "Administrator")

	def test_new_type_is_accepted_and_suggested_afterwards(self):
		self.assertNotIn("Lái xe nâng", certificates.certificate_types())
		make_certificate(self.staff, 30, certificate_type="Lái xe nâng")
		self.assertIn("Lái xe nâng", certificates.certificate_types())

	def test_spaces_are_cleaned_and_casing_follows_the_type_already_used(self):
		make_certificate(self.staff, 30, certificate_type="Lái xe nâng")
		other = make_certificate(self.staff, 30, certificate_type="  lái   XE nâng ")
		self.assertEqual(other.certificate_type, "Lái xe nâng")
		self.assertEqual(certificates.certificate_types().count("Lái xe nâng"), 1)

	def test_blank_type_is_refused(self):
		with self.assertRaises(frappe.MandatoryError):
			make_certificate(self.staff, 30, certificate_type="   ")

	def test_renewal_typed_in_another_casing_is_the_same_type(self):
		old = make_certificate(self.staff, 5, certificate_type="Lái xe nâng")
		new = make_certificate(self.staff, 400, certificate_type="lái xe nâng", renews=old.name)
		self.assertEqual(new.renews, old.name)

	def test_suggestion_rpc_needs_read_permission(self):
		make_certificate(self.staff, 30, certificate_type="Lái xe nâng")
		reader = make_user("cert-r02-types@example.com", ["TC R02"])
		other = make_user("cert-r04-types@example.com", ["TC R04"])
		frappe.set_user(reader)
		self.assertIn("Lái xe nâng", staff_api.certificate_types())
		frappe.set_user(other)
		with self.assertRaises(frappe.PermissionError):
			staff_api.certificate_types()

	def test_patch_turns_the_old_english_values_into_vietnamese(self):
		cert = make_certificate(self.staff, 30)
		frappe.db.set_value("Certificate", cert.name, "certificate_type", "Practice License")
		rename_certificate_types.execute()
		self.assertEqual(
			frappe.db.get_value("Certificate", cert.name, "certificate_type"), "Chứng chỉ hành nghề (CCHN)"
		)
