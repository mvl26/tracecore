"""Đơn vị thuê ngoài: nhắc giấy phép 60/30/7 ngày, hết hạn chỉ cảnh báo (FEAT-066 AC-7..AC-9; FR-M12-13, FR-M12-13.1;
BRU-AUD-006; UC-46 bước 5-7, E2)."""

import frappe
from frappe.utils import add_days, getdate, today

from tracecore.compliance_audit import vendors
from tracecore.compliance_audit.tests import chemical_factories as cf
from tracecore.compliance_audit.tests import factories as af
from tracecore.core import notification
from tracecore.tests.factories import make_department
from tracecore.tests.utils import IsolatedTestCase, bru


def _deliveries(event, supplier):
	return frappe.db.count("Notification Delivery", {"event_code": event, "ref_name": supplier})


class TestVendors(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		notification.ensure_default_rules()
		af.factories.make_user("ksnk-r01-vendor@test.local", ["TC R01"])
		self.day = getdate("2026-09-01")

	def post_session(self, supplier, code, audit_date=None):
		"""Phiếu giám sát "Đơn vị thuê ngoài" đã ghi sổ gắn ``supplier``."""
		department = make_department("KSNK Test Khoa thuê ngoài")
		template = af.make_template(code, audit_type="Outsourced Service", effective_from="2026-01-01")
		doc = frappe.get_doc(
			{
				"doctype": "Audit Session",
				"audit_template": template.name,
				"department": department,
				"supplier": supplier,
				"observer": af.make_observer(first_name="Vendor Observer"),
				"audit_date": audit_date or today(),
				"answers": af.answers(**{item.item_code: "Pass" for item in template.items}),
			}
		).insert(ignore_permissions=True)
		doc.submit()
		return doc

	def test_reminds_at_60_30_7_days_once(self):
		supplier = cf.make_vendor("KSNK Test Vệ sinh A", license_expiry=add_days(self.day, 30))
		vendors.run_daily(self.day)
		vendors.run_daily(self.day)
		self.assertEqual(_deliveries(vendors.EXPIRING_EVENT, supplier) > 0, True)
		count = _deliveries(vendors.EXPIRING_EVENT, supplier)
		vendors.run_daily(add_days(self.day, 1))  # còn 29 ngày: không nhắc
		self.assertEqual(_deliveries(vendors.EXPIRING_EVENT, supplier), count)
		self.assertEqual(vendors.notice_days(add_days(self.day, 60), self.day), 60)
		self.assertIsNone(vendors.notice_days(add_days(self.day, 59), self.day))

	@bru("BRU-AUD-006")
	def test_expired_license_warns_and_logs_once_without_blocking(self):
		supplier = cf.make_vendor(
			"KSNK Test Giặt là B", service="Laundry", license_expiry=add_days(self.day, -1)
		)
		vendors.run_daily(self.day)
		vendors.run_daily(add_days(self.day, 1))
		self.assertEqual(
			frappe.db.count(
				"Audit Log", {"ref_doctype": "Supplier", "ref_name": supplier, "action": "Update"}
			),
			1,
		)
		self.assertGreater(_deliveries(vendors.EXPIRED_EVENT, supplier), 0)
		# không chặn: phiếu giám sát đơn vị thuê ngoài vẫn ghi sổ được
		session = self.post_session(supplier, "T-TN66")
		self.assertEqual(session.docstatus, 1)
		self.assertEqual(vendors.status(supplier, getdate(today()))["state"], vendors.EXPIRED)

	def test_status_labels(self):
		self.assertEqual(vendors.state_of(add_days(self.day, 39), self.day), (vendors.EXPIRING, 39))
		self.assertEqual(vendors.state_of(add_days(self.day, 61), self.day), (vendors.VALID, 61))
		self.assertEqual(vendors.state_of(add_days(self.day, -3), self.day), (vendors.EXPIRED, -3))
		self.assertEqual(vendors.state_of(None, self.day), (vendors.UNKNOWN, None))

	def test_unaudited_vendors_in_quarter_and_reminder_on_last_month(self):
		audited = cf.make_vendor("KSNK Test Suất ăn D", service="Catering", license_expiry="2027-06-30")
		missing = cf.make_vendor(
			"KSNK Test Tiệt khuẩn E", service="Sterilization", contract=("2026-01-01", "2026-12-31")
		)
		ended = cf.make_vendor("KSNK Test Hết HĐ F", contract=("2025-01-01", "2025-12-31"))
		session = self.post_session(audited, "T-TN66B", "2026-08-10")
		names = vendors.unaudited(2026, 3)
		self.assertIn(missing, names)
		self.assertNotIn(audited, names)
		self.assertNotIn(ended, names)
		last = vendors.last_session(audited)
		self.assertEqual(last["name"], session.name)
		vendors.run_daily(getdate("2026-09-01"))  # ngày 1 tháng cuối quý III
		self.assertTrue(frappe.db.exists("Notification Delivery", {"event_code": vendors.UNAUDITED_EVENT}))

	def test_r09_edits_supplier_and_warehouse_without_delete(self):
		"""A-142 Q4: R09 sửa hồ sơ thuê ngoài và gán khoa cho kho; quyền chuẩn ERPNext giữ nguyên, không ai xóa."""
		from tracecore.compliance_audit import permissions

		permissions.ensure_permissions()
		permissions.ensure_permissions()  # idempotent
		for doctype, role in (("Supplier", "TC R09"), ("Warehouse", "TC R09"), ("Warehouse", "TC R10")):
			row = frappe.db.get_value(
				"Custom DocPerm",
				{"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0},
				["read", "write", "create", "delete"],
				as_dict=True,
			)
			self.assertEqual(
				(row.read, row.write, row.create, row.delete), (1, 1, 1, 0), msg=f"{doctype} {role}"
			)
		self.assertEqual(
			frappe.db.get_value("Custom DocPerm", {"parent": "Supplier", "role": "TC R13"}, "write"), 0
		)
		self.assertTrue(
			frappe.db.exists("Custom DocPerm", {"parent": "Supplier", "role": "Purchase Manager"})
		)
