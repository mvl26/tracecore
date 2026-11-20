"""FEAT-004, A-37 (c)(d), A-164, A-165, A-166: xóa danh mục (FR-M9-16) và báo cáo Audit Trail (NFR-SEC-03)."""

import inspect

import frappe
from frappe.utils import now_datetime

from tracecore.core.audit import MASTER_DOCTYPES
from tracecore.setup.permissions import build_custom_docperms
from tracecore.tests import factories
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase
from tracecore.tracecore.report.audit_trail import audit_trail

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


class TestMasterDelete(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.r10 = make_user("md-r10@example.com", ["TC R10", "System Manager"])
		self.r02 = make_user("md-r02@example.com", ["TC R02", "System Manager"])
		self.addCleanup(frappe.set_user, "Administrator")

	def test_r10_hard_deletes_an_unused_master(self):
		location = factories.make_sterile_location("Kệ chưa dùng").name
		frappe.set_user(self.r10)
		frappe.delete_doc("Sterile Location", location, ignore_permissions=True)
		self.assertFalse(frappe.db.exists("Sterile Location", location))
		self.assertEqual(frappe.db.get_value("Code Registry", location, "status"), "Disabled")
		self.assertTrue(
			frappe.db.exists(
				"Audit Log",
				{
					"ref_doctype": "Sterile Location",
					"ref_name": location,
					"action": "Delete",
					"user": self.r10,
				},
			)
		)

	def test_master_with_transactions_or_other_roles_cannot_be_deleted(self):
		used = factories.make_stocked_pack()
		location = frappe.db.get_value("Pack", used.name, "location")
		frappe.set_user(self.r10)
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Sterile Location", location, ignore_permissions=True)
		frappe.set_user("Administrator")
		unused = factories.make_sterile_location("Kệ khác").name
		frappe.set_user(self.r02)
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Sterile Location", unused, ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Sterile Location", unused))


class TestEmployeeDelete(IsolatedTestCase):
	"""A-164: R10 và Administrator xóa cứng nhân viên chưa có giao dịch; đã có giao dịch thì chỉ cho nghỉ (Left)."""

	def setUp(self):
		super().setUp()
		self.r10 = make_user("ed-r10@example.com", ["TC R10"])
		self.r02 = make_user("ed-r02@example.com", ["TC R02", "System Manager"])
		self.sysman = make_user("ed-sm@example.com", ["System Manager"])
		self.addCleanup(frappe.set_user, "Administrator")

	def _assert_deleted(self, employee, user):
		self.assertFalse(frappe.db.exists("Employee", employee))
		self.assertTrue(
			frappe.db.exists(
				"Audit Log",
				{"ref_doctype": "Employee", "ref_name": employee, "action": "Delete", "user": user},
			)
		)
		codes = frappe.get_all(
			"Code Registry", filters={"ref_doctype": "Employee", "ref_name": employee}, pluck="status"
		)
		if employee.startswith("NV-"):
			self.assertTrue(codes)
		self.assertEqual(set(codes) - {"Disabled"}, set())

	def test_r10_hard_deletes_employee_without_transactions(self):
		employee = factories.make_employee(first_name="Xóa thử").name
		frappe.set_user(self.r10)
		frappe.delete_doc("Employee", employee, ignore_permissions=True)
		self._assert_deleted(employee, self.r10)

	def test_administrator_hard_deletes_employee_without_transactions(self):
		employee = factories.make_employee(first_name="Xóa thử Admin").name
		frappe.delete_doc("Employee", employee, ignore_permissions=True)
		self._assert_deleted(employee, "Administrator")

	def test_employee_with_certificate_cannot_be_deleted(self):
		employee = factories.make_employee(first_name="Có chứng chỉ").name
		frappe.get_doc(
			{
				"doctype": "Certificate",
				"employee": employee,
				"certificate_type": "Sterilization",
				"certificate_no": "CC-" + frappe.generate_hash(length=8),
				"issued_on": "2025-01-01",
				"no_expiry": 1,
			}
		).insert(ignore_permissions=True)
		frappe.set_user(self.r10)
		with self.assertRaises(frappe.LinkExistsError):
			frappe.delete_doc("Employee", employee, ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Employee", employee))

	def test_employee_with_station_session_cannot_be_deleted(self):
		employee = factories.make_employee(first_name="Có phiên trạm").name
		now = now_datetime()
		frappe.get_doc(
			{
				"doctype": "Station Session",
				"employee": employee,
				"user": "Administrator",
				"station": "TRAM-GIA",
				"token_hash": frappe.generate_hash(length=32),
				"started_at": now,
				"last_activity_at": now,
				"absolute_expires_at": now,
			}
		).insert(ignore_permissions=True, ignore_links=True)
		frappe.set_user(self.r10)
		with self.assertRaises(frappe.LinkExistsError):
			frappe.delete_doc("Employee", employee, ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Employee", employee))

	def test_employee_with_login_account_cannot_be_deleted(self):
		employee = factories.make_employee(first_name="Có tài khoản", user_id=self.r02).name
		frappe.set_user(self.r10)
		with self.assertRaises(frappe.LinkExistsError):
			frappe.delete_doc("Employee", employee, ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Employee", employee))

	def test_other_roles_cannot_delete_employee(self):
		employee = factories.make_employee(first_name="Không quyền").name
		for user in (self.r02, self.sysman):
			frappe.set_user(user)
			with self.assertRaises(frappe.ValidationError):
				frappe.delete_doc("Employee", employee, ignore_permissions=True)
			frappe.set_user("Administrator")
		self.assertTrue(frappe.db.exists("Employee", employee))


# A-165: danh mục TraceCore bổ sung vào phạm vi xóa của R10/Administrator (FR-M9-16)
A165_MASTERS = {
	"Audit Schedule",
	"Environment Zone",
	"Sampling Plan",
	"Wastewater Point",
	"IC Indicator",
	"IC Network Member",
	"IC Procedure Document",
	"Linen Type",
	"Cluster Alert Rule",
	"Communicable Disease",
	"Isolation Room",
	"Import Mapping Profile",
	"Report Export Profile",
	"Waste Container",
	"Waste Quota",
	"Waste Storage Location",
	"Waste Treatment Vendor",
	"Waste Type",
}


class TestEveryMasterHasDelete(IsolatedTestCase):
	"""A-165: mọi danh mục trong MASTER_DOCTYPES có nút Xóa cho R10 (và Administrator) và có chặn xóa khi đã dùng."""

	def test_a165_masters_are_deletable_masters(self):
		self.assertLessEqual(A165_MASTERS, MASTER_DOCTYPES)
		# kỳ báo cáo và sổ mã không bao giờ xóa
		self.assertFalse(
			{"IC Reporting Period", "Code Registry", "Code Range", "Set BOM Item"} & MASTER_DOCTYPES
		)

	def test_r10_has_delete_on_every_master(self):
		missing = []
		for doctype in sorted(MASTER_DOCTYPES):
			generated = [r for r in build_custom_docperms({doctype}) if r["parent"] == doctype]
			rows = generated or [
				{"role": p.role, "delete": p.delete}
				for p in frappe.get_meta(doctype).permissions
				if p.permlevel == 0
			]
			if not any(r["role"] == "TC R10" and r.get("delete") for r in rows):
				missing.append(doctype)
		self.assertEqual(missing, [])

	def test_every_master_runs_block_delete_on_trash(self):
		hooks = frappe.get_hooks("doc_events")
		missing = []
		for doctype in sorted(MASTER_DOCTYPES):
			handlers = hooks.get(doctype, {}).get("on_trash") or []
			handlers = handlers if isinstance(handlers, list) else [handlers]
			cls = frappe.get_doc({"doctype": doctype}).__class__
			own = inspect.getsource(cls.on_trash) if "on_trash" in cls.__dict__ else ""
			if "tracecore.core.audit.block_delete" not in handlers and "block_delete" not in own:
				missing.append(doctype)
		self.assertEqual(missing, [])


class TestA165MasterDelete(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.r10 = make_user("a165-r10@example.com", ["TC R10"])
		self.r02 = make_user("a165-r02@example.com", ["TC R02", "System Manager"])
		self.addCleanup(frappe.set_user, "Administrator")

	def test_r10_deletes_unused_linen_type_with_audit(self):
		name = factories.make_linen_type().name
		frappe.set_user(self.r10)
		frappe.delete_doc("Linen Type", name)
		self.assertFalse(frappe.db.exists("Linen Type", name))
		self.assertTrue(
			frappe.db.exists("Audit Log", {"ref_doctype": "Linen Type", "ref_name": name, "action": "Delete"})
		)

	def test_other_roles_cannot_delete_and_used_master_is_blocked(self):
		unused = factories.make_linen_type().name
		frappe.set_user(self.r02)
		with self.assertRaises(frappe.PermissionError):
			frappe.delete_doc("Linen Type", unused)
		frappe.set_user("Administrator")
		waste_type = factories.make_waste_type().name
		factories.make_waste_vendor([waste_type])
		frappe.set_user(self.r10)
		with self.assertRaises(frappe.LinkExistsError):
			frappe.delete_doc("Waste Type", waste_type)
		self.assertTrue(frappe.db.exists("Waste Type", waste_type))


class TestA166StockMasterDelete(IsolatedTestCase):
	"""A-166: Vật tư (Item), Kho (Warehouse), Nhà cung cấp (Supplier) có nút Xóa cho R10/Administrator."""

	def setUp(self):
		super().setUp()
		self.r10 = make_user("a166-r10@example.com", ["TC R10"])
		self.r09 = make_user("a166-r09@example.com", ["TC R09", "Stock Manager", "Item Manager"])
		self.addCleanup(frappe.set_user, "Administrator")

	def test_stock_masters_are_deletable_masters(self):
		self.assertLessEqual({"Item", "Warehouse", "Supplier"}, MASTER_DOCTYPES)

	def test_only_r10_has_delete_on_item(self):
		deleters = {p.role for p in frappe.get_meta("Item").permissions if p.delete}
		self.assertEqual(deleters, {"TC R10"})
		self.assertTrue(frappe.has_permission("Item", "delete", user=self.r10))
		self.assertFalse(frappe.has_permission("Item", "delete", user=self.r09))

	def test_r10_deletes_unused_item_supplier_warehouse_with_audit(self):
		item = factories.make_item("A166-UNUSED-" + frappe.generate_hash(length=6), "Chemical").name
		supplier = factories.make_supplier("A166 NCC " + frappe.generate_hash(length=6))
		warehouse = factories.make_warehouse("A166 Kho " + frappe.generate_hash(length=6))
		frappe.set_user(self.r10)
		for doctype, name in (("Item", item), ("Supplier", supplier), ("Warehouse", warehouse)):
			frappe.delete_doc(doctype, name)
			self.assertFalse(frappe.db.exists(doctype, name), doctype)
			self.assertTrue(
				frappe.db.exists("Audit Log", {"ref_doctype": doctype, "ref_name": name, "action": "Delete"}),
				doctype,
			)

	def test_used_item_cannot_be_deleted(self):
		item = factories.make_item(
			"A166-USED-" + frappe.generate_hash(length=6), "Chemical", has_batch_no=1
		).name
		factories.make_batch(item, "A166-LOT-" + frappe.generate_hash(length=6))
		frappe.set_user(self.r10)
		with self.assertRaises(frappe.LinkExistsError):
			frappe.delete_doc("Item", item)
		self.assertTrue(frappe.db.exists("Item", item))


class TestAuditTrail(IsolatedTestCase):
	def test_report_lists_audit_rows_with_filters(self):
		unit = factories.make_set_unit()
		columns, rows = audit_trail.execute({"ref_doctype": "Set Unit", "ref_name": unit.name})[:2]
		self.assertIn("action", [column["fieldname"] for column in columns])
		self.assertTrue(rows)
		self.assertEqual({row["ref_name"] for row in rows}, {unit.name})
		self.assertEqual(audit_trail.execute({"ref_name": "KHONG-CO"})[1], [])
