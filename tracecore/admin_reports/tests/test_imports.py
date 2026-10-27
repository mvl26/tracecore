"""Import Khoa và Nhân viên từ Excel (FEAT-011 Task 3; FR-M9-11, UC-39; A-41 Q1, Q3, D3)."""

import uuid

import frappe

from tracecore.core import importer
from tracecore.core.tests.test_importer import workbook
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase

test_ignore = ["Department", "Employee", "Company"]


def run(key, header, rows):
	return frappe.get_doc("Import Batch", importer.run(key, workbook(header, rows), "f.xlsx"))


class TestDepartmentImport(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")

	def test_departments_created_as_wards_with_parent(self):
		parent = factories.make_department("Khoa Ngoại nhập")
		name = "Khoa Phẫu thuật " + uuid.uuid4().hex[:6]
		batch = run("department", ["Department Name", "Parent Department", "Ward"], [[name, parent, "x"]])
		self.assertEqual(batch.created, 1, batch.rows)
		doc = frappe.get_doc("Department", batch.rows[0].ref_name)
		self.assertEqual((doc.department_name, doc.parent_department, doc.tc_is_ward), (name, parent, 1))

	def test_existing_department_skipped(self):
		name = factories.make_department("Khoa Đã có " + uuid.uuid4().hex[:6])
		label = frappe.db.get_value("Department", name, "department_name")
		self.assertEqual(run("department", ["Department Name"], [[label]]).skipped, 1)

	def test_unknown_parent_is_row_error(self):
		result = importer.check(
			"department", workbook(["Department Name", "Parent Department"], [["K1", "Không có"]])
		)
		self.assertEqual([(i["row"], i["code"]) for i in result["issues"]], [(2, "PARENT_NOT_FOUND")])


class TestEmployeeImport(IsolatedTestCase):
	HEADER = (
		"First Name",
		"Gender",
		"Date of Birth",
		"Date of Joining",
		"Department",
		"Card ID",
		"User Email",
	)

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.department = factories.make_department("Khoa nhân viên import")

	def row(self, card=None, email=None, **over):
		values = {
			"First Name": "Nguyễn Văn A",
			"Gender": "Male",
			"Date of Birth": "01/02/1990",
			"Date of Joining": "01/10/2026",
			"Department": self.department,
			"Card ID": card,
			"User Email": email,
			**over,
		}
		return [values[name] for name in self.HEADER]

	def test_employee_created_with_card(self):
		card = "IMP-" + uuid.uuid4().hex[:8].upper()
		batch = run("employee", self.HEADER, [self.row(card=card)])
		self.assertEqual(batch.created, 1, batch.rows)
		doc = frappe.get_doc("Employee", batch.rows[0].ref_name)
		self.assertEqual((doc.tc_card_id, doc.tc_card_enabled, doc.department), (card, 1, self.department))

	def test_same_card_on_reimport_is_existing(self):
		card = "IMP-" + uuid.uuid4().hex[:8].upper()
		run("employee", self.HEADER, [self.row(card=card)])
		self.assertEqual(run("employee", self.HEADER, [self.row(card=card)]).skipped, 1)

	def test_card_or_email_required(self):
		result = importer.check("employee", workbook(self.HEADER, [self.row()]))
		self.assertEqual([i["code"] for i in result["issues"]], ["IDENTITY_REQUIRED"])

	def test_unknown_department_is_row_error(self):
		result = importer.check(
			"employee", workbook(self.HEADER, [self.row(card="IMP-X1", Department="Khoa không có")])
		)
		self.assertEqual([i["code"] for i in result["issues"]], ["DEPARTMENT_NOT_FOUND"])

	def test_employee_code_column_rejected(self):
		with self.assertRaises(importer.ImportFileError):
			importer.parse(importer.get_kind("employee"), workbook([*self.HEADER, "Employee Code"], []))
