"""Sức khỏe người chế biến (FEAT-073; FR-M17-02, FR-M17-02.1; BRU-FS-001; UC-56 bước 2, E1, E3, A3)."""

import frappe
from frappe.utils import add_days, getdate, today

from tracecore.core.errors import BlockedError
from tracecore.food_safety import handlers
from tracecore.food_safety.tests import factories as ff
from tracecore.tests.utils import IsolatedTestCase, bru

ALLOWED_FIELDS = {
	"full_name",
	"employee",
	"supplier",
	"supplier_name",
	"department",
	"checked_on",
	"next_due",
	"fit_for_work",
	"evidence",
	"handler_key",
	"reminded_level",
	"amended_from",
}


class TestHealthCheck(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.delete(handlers.DOCTYPE)
		self.caterer = ff.make_caterer()

	@bru("BRU-FS-001")
	def test_only_conclusion_and_due_date_no_diagnosis_field(self):
		meta = frappe.get_meta(handlers.DOCTYPE)
		data_fields = {
			f.fieldname for f in meta.fields if f.fieldtype not in ("Section Break", "Column Break")
		}
		self.assertEqual(data_fields, ALLOWED_FIELDS)
		self.assertEqual(meta.get_field("fit_for_work").options.split("\n")[1:], ["Fit", "Unfit"])
		for word in ("diagnos", "result", "test", "disease"):
			self.assertFalse([name for name in data_fields if word in name], word)

	def test_needs_exactly_one_of_employee_or_vendor(self):
		with self.assertRaises(BlockedError) as ctx:
			frappe.get_doc(
				{
					"doctype": handlers.DOCTYPE,
					"full_name": "Không đơn vị",
					"checked_on": today(),
					"next_due": add_days(today(), 365),
					"fit_for_work": "Fit",
				}
			).insert(ignore_permissions=True)
		self.assertEqual(ctx.exception.block.code, "FOOD_HANDLER_UNIT_REQUIRED")
		employee = frappe.get_doc(
			"Employee", ff.factories.make_employee(department=ff.make_department()).name
		).name
		with self.assertRaises(BlockedError):
			ff.make_check(employee=employee, supplier=self.caterer, submit=False)

	def test_due_date_must_follow_check_date_and_check_not_in_future(self):
		with self.assertRaises(BlockedError) as ctx:
			ff.make_check(supplier=self.caterer, checked_on=today(), next_due=add_days(today(), -1))
		self.assertEqual(ctx.exception.block.code, "FOOD_HANDLER_DATE_INVALID")
		with self.assertRaises(BlockedError):
			ff.make_check(supplier=self.caterer, checked_on=add_days(today(), 1))

	def test_handler_key_for_vendor_staff_ignores_case_and_spaces(self):
		one = ff.make_check("Nguyễn  Văn A", supplier=self.caterer)
		two = ff.make_check("nguyễn văn a", supplier=self.caterer, checked_on=today())
		self.assertEqual(one.handler_key, two.handler_key)
		self.assertTrue(one.handler_key.startswith(f"S:{self.caterer}:"))

	def test_internal_staff_take_name_and_department_from_employee(self):
		ward = ff.make_department()
		employee = ff.factories.make_employee(department=ward, first_name="Bếp Nội Bộ")
		doc = ff.make_check("x", employee=employee.name)
		self.assertEqual(doc.handler_key, f"E:{employee.name}")
		self.assertEqual(doc.department, ward)
		self.assertEqual(doc.full_name, employee.employee_name)

	def test_latest_check_per_handler_decides_state(self):
		day = getdate(today())
		ff.make_check(
			"Bếp A", supplier=self.caterer, checked_on=add_days(day, -400), next_due=add_days(day, -35)
		)
		ff.make_check(
			"Bếp A", supplier=self.caterer, checked_on=add_days(day, -5), next_due=add_days(day, 360)
		)
		ff.make_check("Bếp B", supplier=self.caterer, next_due=add_days(day, 12))
		ff.make_check("Bếp C", supplier=self.caterer, next_due=add_days(day, -20))
		cancelled = ff.make_check("Bếp D", supplier=self.caterer, next_due=add_days(day, -3))
		cancelled.cancel()
		rows = {row["full_name"]: row for row in handlers.latest(day)}
		self.assertEqual(set(rows), {"Bếp A", "Bếp B", "Bếp C"})
		self.assertEqual(rows["Bếp A"]["state"], handlers.VALID)
		self.assertEqual((rows["Bếp B"]["state"], rows["Bếp B"]["days_left"]), (handlers.DUE_SOON, 12))
		self.assertEqual(rows["Bếp C"]["state"], handlers.OVERDUE)
		self.assertEqual(rows["Bếp C"]["unit"], "ATTP Công ty suất ăn D")

	def test_unfit_handler_is_listed_with_label_but_not_blocked(self):
		doc = ff.make_check("Bếp Không đủ", supplier=self.caterer, fit="Unfit")
		self.assertEqual(doc.docstatus, 1)
		row = next(row for row in handlers.latest() if row["name"] == doc.name)
		self.assertEqual(row["fit_for_work"], "Unfit")
		self.assertIn(doc.name, [r["name"] for r in handlers.not_eligible()])

	def test_overdue_listed_by_unit(self):
		day = getdate(today())
		other = ff.make_caterer("ATTP Công ty suất ăn E")
		ff.make_check("Bếp 1", supplier=self.caterer, next_due=add_days(day, -1))
		ff.make_check("Bếp 2", supplier=self.caterer, next_due=add_days(day, -10))
		ff.make_check("Bếp 3", supplier=other, next_due=add_days(day, -2))
		ff.make_check("Bếp 4", supplier=other, next_due=add_days(day, 100))
		groups = {
			group["unit"]: [r["full_name"] for r in group["handlers"]]
			for group in handlers.overdue_by_unit(day)
		}
		self.assertEqual(
			groups, {"ATTP Công ty suất ăn D": ["Bếp 2", "Bếp 1"], "ATTP Công ty suất ăn E": ["Bếp 3"]}
		)


class TestReminders(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.delete(handlers.DOCTYPE)
		self.r11 = ff.make_user("attp-r11@example.com", [ff.R11])
		self.caterer = ff.make_caterer()

	def _sent(self, event):
		return frappe.get_all(
			"Notification Delivery", filters={"event_code": event, "recipient": self.r11}, pluck="ref_name"
		)

	def test_reminds_r11_at_30_days_and_when_overdue_once_each(self):
		day = getdate(today())
		due = ff.make_check("Bếp 30", supplier=self.caterer, next_due=add_days(day, 30))
		late = ff.make_check("Bếp trễ", supplier=self.caterer, next_due=add_days(day, -1))
		fine = ff.make_check("Bếp xa", supplier=self.caterer, next_due=add_days(day, 31))
		handlers.run_daily(day)
		handlers.run_daily(day)
		self.assertEqual(self._sent(handlers.DUE_EVENT), [due.name])
		self.assertEqual(self._sent(handlers.OVERDUE_EVENT), [late.name])
		self.assertNotIn(fine.name, self._sent(handlers.DUE_EVENT))
		# hết 30 ngày: hồ sơ đã nhắc mốc 30 ngày được nhắc tiếp khi quá hạn
		handlers.run_daily(add_days(day, 31))
		self.assertIn(due.name, self._sent(handlers.OVERDUE_EVENT))

	def test_reminder_skips_handler_with_newer_check(self):
		day = getdate(today())
		ff.make_check(
			"Bếp mới", supplier=self.caterer, checked_on=add_days(day, -380), next_due=add_days(day, -15)
		)
		ff.make_check(
			"Bếp mới", supplier=self.caterer, checked_on=add_days(day, -2), next_due=add_days(day, 363)
		)
		handlers.run_daily(day)
		self.assertEqual(self._sent(handlers.OVERDUE_EVENT), [])
