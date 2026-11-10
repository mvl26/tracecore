"""RPC tracecore.v1.ksnk_training.* — màn SCR-49 Đào tạo KSNK (FEAT-059 AC-6, AC-9; FR-M11-09..11; plan D7)."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from tracecore.infection_program import training
from tracecore.infection_program.tests import ic_fixtures as fx
from tracecore.infection_program.tests import training_fixtures as tf
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase
from tracecore.v1 import ksnk_training as api


class TestKsnkTrainingApi(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.local.lang = "en"
		fx.clear_required_departments()
		frappe.db.delete("IC Network Member")
		fx.settings(staff=())
		self.dept = factories.make_department("KSNK API Đào tạo")
		staff = [fx.employee(f"API DT {index}", self.dept) for index in range(2)]
		tf.trained(staff[:1], training.BASIC)
		fx.network_member(staff[1], self.dept, "Nurse")
		tf.trainee(self.dept, trained_on=add_days(today(), 2), full_name="SV muộn")
		self.users = {
			code: factories.make_user(f"ksnk-training-{code.lower()}@example.com", [f"TC {code}"])
			for code in ("R01", "R02", "R10", "R11", "R13")
		}

	def test_status_payload(self):
		frappe.set_user(self.users["R01"])
		data = api.status(department=self.dept)
		self.assertEqual(data["year"], int(today()[:4]))
		row = next(row for row in data["basic"]["departments"] if row["department"] == self.dept)
		self.assertEqual((row["employees"], row["trained"]), (2, 1))
		self.assertEqual(data["basic"]["total"]["employees"], 2)
		self.assertEqual(
			data["core"]["total"], {"passed": 0, "people": 1, "rate": 0.0, "rate_label": "0,0 %"}
		)
		self.assertEqual(data["trainees"]["late"], 1)
		self.assertEqual(data["trainees"]["rows"][0]["status"], "Trained After Start")
		self.assertTrue(data["can_remind"])

	def test_status_bad_year_rejected(self):
		frappe.set_user(self.users["R01"])
		with self.assertRaises(frappe.ValidationError):
			api.status(year="abc")

	def test_r13_reads_without_remind(self):
		frappe.set_user(self.users["R13"])
		self.assertFalse(api.status()["can_remind"])

	def test_role_without_screen_is_rejected(self):
		frappe.set_user(self.users["R02"])
		with self.assertRaises(frappe.PermissionError):
			api.status()

	def test_r02_and_r01_remind(self):
		for code in ("R01", "R02", "R10"):
			with self.subTest(role=code):
				frappe.set_user(self.users[code])
				with patch.object(training.notification, "emit", return_value=[]):
					result = api.remind(self.dept)
				self.assertTrue(result["ok"])
				self.assertEqual(result["untrained"], 1)

	def test_r11_and_r13_cannot_remind(self):
		for code in ("R11", "R13"):
			with self.subTest(role=code):
				frappe.set_user(self.users[code])
				with self.assertRaises(frappe.PermissionError):
					api.remind(self.dept)

	def test_remind_requires_department(self):
		frappe.set_user(self.users["R01"])
		result = api.remind("")
		self.assertFalse(result["ok"])
		self.assertTrue(result["error"]["reason"])
