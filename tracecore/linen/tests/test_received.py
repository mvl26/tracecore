"""Đồ vải đã nhận nhìn từ khoa (FEAT-101, A-161; FR-M9-32, FR-M3-06)."""

import frappe
from frappe.utils import get_first_day, get_last_day, getdate, today

from tracecore.linen import received
from tracecore.tests.factories import make_department
from tracecore.tests.utils import IsolatedTestCase

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def make_type(name, department=None, quota=None):
	if not frappe.db.exists("Linen Type", name):
		doc = frappe.new_doc("Linen Type")
		doc.update({"name": name, "type_name": name, "is_active": 1})
		doc.db_insert()
	if department and quota:
		row = frappe.new_doc("Linen Dept Quota")
		row.update(
			{
				"name": frappe.generate_hash(length=10),
				"parent": name,
				"parenttype": "Linen Type",
				"parentfield": "quotas",
				"idx": 1,
				"department": department,
				"min_qty": quota[0],
				"max_qty": quota[1],
			}
		)
		row.db_insert()
	return name


def post(doctype, child, department, at, lines, kind=None, docstatus=1):
	"""Phiếu đồ vải ghi thẳng ở trạng thái `docstatus` (không chạy dịch vụ trạm)."""
	doc = frappe.new_doc(doctype)
	stamp = "collected_at" if doctype == "Linen Collection" else "issued_at"
	doc.update(
		{
			"name": "LT-" + frappe.generate_hash(length=8),
			"docstatus": docstatus,
			"department": department,
			stamp: at,
		}
	)
	if kind:
		doc.kind = kind
	doc.db_insert()
	for idx, (linen_type, qty, kg) in enumerate(lines, 1):
		row = frappe.new_doc(child)
		row.update(
			{
				"name": frappe.generate_hash(length=10),
				"parent": doc.name,
				"parenttype": doctype,
				"parentfield": "lines",
				"idx": idx,
				"linen_type": linen_type,
				"qty": qty,
				"weight_kg": kg,
			}
		)
		row.db_insert()


class TestLinenReceived(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.dept = make_department("Khoa đồ vải A")
		self.other = make_department("Khoa đồ vải B")
		self.sheet = make_type("TCF Ga giường", self.dept, (10, 60))
		self.gown = make_type("TCF Áo phẫu thuật")
		self.first = get_first_day(today())
		self.day = f"{self.first} 08:00:00"

	def test_daily_rows_pair_collection_with_return_and_disposal(self):
		post(
			"Linen Collection",
			"Linen Collection Line",
			self.dept,
			self.day,
			[(self.sheet, 42, 27.3), (self.gown, 30, 12.0)],
		)
		post(
			"Linen Issue",
			"Linen Issue Line",
			self.dept,
			self.day,
			[(self.sheet, 42, 27.1), (self.gown, 28, 11.2)],
			kind="Return",
		)
		post("Linen Issue", "Linen Issue Line", self.dept, self.day, [(self.gown, 2, 0.8)], kind="Dispose")
		# phiếu nháp, phiếu khoa khác và phiếu cấp mới không tính
		post(
			"Linen Collection",
			"Linen Collection Line",
			self.dept,
			self.day,
			[(self.sheet, 99, 9)],
			docstatus=0,
		)
		post("Linen Collection", "Linen Collection Line", self.other, self.day, [(self.sheet, 7, 1)])
		post("Linen Issue", "Linen Issue Line", self.dept, self.day, [(self.sheet, 5, 1)], kind="New")
		rows = {
			row["linen_type"]: row for row in received.daily(self.dept, self.first, get_last_day(self.first))
		}
		sheet, gown = rows[self.sheet], rows[self.gown]
		self.assertEqual(getdate(sheet["date"]), getdate(self.first))
		self.assertEqual((sheet["collected"], sheet["collected_kg"]), (42, 27.3))
		self.assertEqual((sheet["returned"], sheet["returned_kg"], sheet["difference"]), (42, 27.1, 0))
		self.assertEqual(
			(gown["collected"], gown["returned"], gown["disposed"], gown["difference"]), (30, 28, 2, -2)
		)
		self.assertEqual(gown["type_name"], self.gown)

	def test_overview_gives_month_quota_stock_and_variance(self):
		post("Linen Collection", "Linen Collection Line", self.dept, self.day, [(self.sheet, 100, 60)])
		post("Linen Issue", "Linen Issue Line", self.dept, self.day, [(self.sheet, 90, 54)], kind="Return")
		out = received.overview(self.dept)
		self.assertEqual(out["month"], str(self.first)[:7])
		self.assertEqual(len(out["rows"]), 1)
		self.assertEqual(
			(out["variance_pct"], out["variance_limit_pct"], out["over_variance"]), (10.0, 5.0, True)
		)
		quota = next(row for row in out["quotas"] if row["linen_type"] == self.sheet)
		self.assertEqual((quota["min"], quota["max"], quota["stock"], quota["state"]), (10, 60, -10, "below"))
		# loại không đặt định mức cho khoa không nằm trong dòng định mức
		self.assertNotIn(self.gown, [row["linen_type"] for row in out["quotas"]])

	def test_other_month_and_bad_month_text(self):
		post("Linen Collection", "Linen Collection Line", self.dept, self.day, [(self.sheet, 3, 1)])
		self.assertEqual(received.overview(self.dept, "2020-01")["rows"], [])
		self.assertEqual(received.overview(self.dept, "2020-01")["month"], "2020-01")
		self.assertEqual(received.overview(self.dept, "garbage")["month"], str(self.first)[:7])
