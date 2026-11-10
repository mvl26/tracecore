"""NC Outbreak Control từ ổ dịch M14 (FEAT-069; FR-M14-09; A-150 Q3) — hook ``tracecore_outbreak_nc``."""

import frappe
from frappe.utils import add_days, today

from tracecore.core.errors import BlockedError
from tracecore.reprocessing import incidents
from tracecore.tests.factories import make_department, make_user
from tracecore.tests.utils import IsolatedTestCase


class TestOutbreakNc(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.department = make_department("NC Ổ dịch HSTC")
		self.user = make_user("nc-od-r11@example.com", ["TC R11"])
		self.od = self.outbreak()

	def outbreak(self):
		"""Ổ dịch tạo thẳng (cờ dịch vụ M14) — test M2 không import module M14."""
		doc = frappe.get_doc(
			{
				"doctype": "Outbreak Investigation",
				"title": "Ổ dịch test NC",
				"organism_or_disease": "CRE",
				"department": self.department,
				"start_date": today(),
			}
		)
		doc.flags.tc_outbreak = True
		return doc.insert(ignore_permissions=True).name

	def ctx(self, outbreak=None, text="Cách ly tiếp xúc"):
		return {
			"outbreak": outbreak or self.od,
			"department": self.department,
			"description": "Kiểm soát ổ dịch",
			"action": {"description": text, "responsible": self.user, "due_date": add_days(today(), 2)},
		}

	def test_one_nc_per_outbreak_with_actions(self):
		first = incidents.on_outbreak_nc(self.ctx())
		second = incidents.on_outbreak_nc(self.ctx(text="Sàng lọc người bệnh cùng phòng"))
		self.assertEqual(first, second)
		doc = frappe.get_doc(incidents.DOCTYPE, first)
		self.assertEqual(
			(doc.incident_type, doc.incident_category, doc.severity), ("Outbreak Control", "Outbreak", "High")
		)
		self.assertEqual((doc.source_doctype, doc.source_name), ("Outbreak Investigation", self.od))
		self.assertEqual(
			[row.description for row in doc.actions], ["Cách ly tiếp xúc", "Sàng lọc người bệnh cùng phòng"]
		)
		self.assertEqual({row.status for row in doc.actions}, {"Open"})

	def test_without_action_only_creates_nc(self):
		ctx = self.ctx(outbreak=self.outbreak())
		ctx.pop("action")
		name = incidents.on_outbreak_nc(ctx)
		self.assertEqual(len(frappe.get_doc(incidents.DOCTYPE, name).actions), 0)

	def test_closed_nc_refuses_new_action(self):
		name = incidents.on_outbreak_nc(self.ctx())
		frappe.db.set_value(incidents.DOCTYPE, name, {"docstatus": 1, "status": "Closed"})
		with self.assertRaises(BlockedError):
			incidents.on_outbreak_nc(self.ctx())
