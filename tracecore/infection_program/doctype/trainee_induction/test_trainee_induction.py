"""Trainee Induction — sinh viên thực tập (FEAT-059 AC-5, AC-10; FR-M11-11, FR-M11-11.1; UC-42 bước 4, E1; A-135 c)."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from tracecore.infection_program import training
from tracecore.infection_program.tests import training_fixtures as tf
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, assert_permission_matrix

DOCTYPE = "Trainee Induction"


class TestTraineeInduction(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.local.lang = "en"
		self.dept = factories.make_department("KSNK SV Ngoại")

	def test_meta(self):
		meta = frappe.get_meta(DOCTYPE)
		self.assertEqual(meta.module, "Infection Program")
		self.assertEqual(meta.autoname, "SV-.YYYY.-.#####")
		self.assertFalse(meta.is_submittable)
		self.assertEqual(meta.get_field("status").options.split("\n"), list(training.TRAINEE_STATUSES))
		self.assertTrue(meta.get_field("status").read_only)
		self.assertEqual(meta.get_field("result").options.split("\n"), ["", "Passed", "Failed"])

	def test_name_series(self):
		doc = tf.trainee(self.dept, trained_on=today())
		self.assertTrue(doc.name.startswith(f"SV-{today()[:4]}-"), doc.name)

	def test_trained_before_start_is_valid(self):
		doc = tf.trainee(self.dept, period_from=today(), trained_on=add_days(today(), -3))
		self.assertEqual(doc.status, "Valid")
		self.assertEqual(tf.trainee(self.dept, period_from=today(), trained_on=today()).status, "Valid")

	def test_not_trained(self):
		self.assertEqual(tf.trainee(self.dept, trained_on=None, result="").status, "Not Trained")

	def test_trained_late_is_saved_with_warning(self):
		frappe.clear_messages()
		doc = tf.trainee(self.dept, period_from=today(), trained_on=add_days(today(), 2))
		self.assertEqual(doc.status, "Trained After Start")
		self.assertTrue(frappe.db.exists(DOCTYPE, doc.name))
		messages = " ".join(str(row.get("message")) for row in frappe.get_message_log())
		self.assertIn("later than the internship start date", messages)
		frappe.clear_messages()

	def test_status_follows_edits(self):
		doc = tf.trainee(self.dept, period_from=today(), trained_on=add_days(today(), 2))
		doc.trained_on = add_days(today(), -1)
		doc.save(ignore_permissions=True)
		self.assertEqual(doc.status, "Valid")

	def test_period_to_before_period_from_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			tf.trainee(self.dept, period_from=today(), period_to=add_days(today(), -1))

	def test_rate_counts_valid_and_passed_in_period(self):
		tf.trainee(self.dept, trained_on=add_days(today(), -1))  # đạt
		tf.trainee(self.dept, trained_on=add_days(today(), -1), result="Failed")
		tf.trainee(self.dept, trained_on=add_days(today(), 1))  # muộn
		tf.trainee(self.dept, trained_on=None, result="")
		self.assertEqual(training.trainee_rate(today()[:7], self.dept), (1, 4, 4))

	def test_audit_log_written(self):
		doc = tf.trainee(self.dept, trained_on=today())
		self.assertTrue(frappe.db.exists("Audit Log", {"ref_doctype": DOCTYPE, "ref_name": doc.name}))

	def test_r12_reads_only_own_department(self):
		other = factories.make_department("KSNK SV Sản")
		user = factories.make_user("ksnk-sv-r12@example.com", ["TC R12"])
		frappe.get_doc(
			{"doctype": "User Permission", "user": user, "allow": "Department", "for_value": self.dept}
		).insert(ignore_permissions=True)
		mine = tf.trainee(self.dept, trained_on=today())
		theirs = tf.trainee(other, trained_on=today())
		frappe.set_user(user)
		names = set(frappe.get_list(DOCTYPE, pluck="name"))
		self.assertIn(mine.name, names)
		self.assertNotIn(theirs.name, names)


class TestTraineeInductionPermissions(FrappeTestCase):
	def test_permission_matrix(self):
		assert_permission_matrix(self, DOCTYPE)
