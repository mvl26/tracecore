import json

import frappe

from tracecore.core import print as core_print
from tracecore.tests.factories import make_item, make_label_items, make_printer, make_roll
from tracecore.tests.utils import IsolatedTestCase

# label_type_loaded → Item, roll_loaded_by → User kéo theo test record Item, Email Account → Company…
# cần Setup Wizard; site CI mới chưa chạy wizard nên bỏ phụ thuộc này (dữ liệu tạo qua factories).
test_ignore = ["Item", "User"]


def _printer_doc(**values):
	return frappe.get_doc(
		{"doctype": "Printer", "printer_name": "Test printer", "station": "TR-004", **values}
	)


class TestPrinter(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.steam, self.plasma = make_label_items()

	def test_defaults_and_name(self):
		doc = _printer_doc().insert()
		self.assertRegex(doc.name, r"^PRN-\d{3}$")
		self.assertEqual(
			(doc.port, doc.language, doc.dpi, doc.supports_unicode, doc.is_active, doc.host),
			(9100, "ZPL", 300, 0, 1, None),
		)
		self.assertIsNone(doc.label_type_loaded)

	def test_printer_requires_station_not_zone(self):
		with self.assertRaises(frappe.ValidationError):
			_printer_doc(station="ZONE-CLEAN").insert()
		with self.assertRaises(frappe.ValidationError):
			_printer_doc(station="TR-999").insert()
		self.assertTrue(_printer_doc(station="TR-004").insert())

	def test_label_type_must_be_label_item(self):
		packaging = make_item("VT-BAO-GOI", "Packaging", method="Steam").name
		with self.assertRaises(frappe.ValidationError):
			_printer_doc(label_type_loaded=packaging).insert()
		self.assertTrue(_printer_doc(label_type_loaded=self.steam).insert())

	def test_label_type_requires_compatible_method(self):
		no_method = make_item("VT-NHAN-KHONG-PP", "Label").name
		with self.assertRaises(frappe.ValidationError):
			_printer_doc(label_type_loaded=no_method).insert()

	def test_port_and_dpi_must_be_valid(self):
		for field, value in (("port", 0), ("port", 70000), ("dpi", 0)):
			with self.assertRaises(frappe.ValidationError, msg=f"{field}={value}"):
				_printer_doc(**{field: value}).insert()

	def test_roll_fields_are_not_editable_by_hand(self):
		fresh = _printer_doc(roll_code="CN-00001", roll_loaded_by="Administrator").insert()
		self.assertFalse(fresh.roll_code)
		self.assertFalse(fresh.roll_loaded_by)
		doc = frappe.get_doc("Printer", make_printer("TR-004", self.steam))
		for field, value in (
			("roll_code", "CN-00001"),
			("roll_loaded_on", "2026-10-20 08:00:00"),
			("roll_loaded_by", "Administrator"),
		):
			doc.set(field, value)
			with self.assertRaises(frappe.ValidationError, msg=field):
				doc.save()
			doc.reload()

	def test_roll_fields_survive_a_save_from_the_form(self):
		printer = make_printer("TR-004", self.steam)
		core_print.set_roll(printer, make_roll(self.plasma))
		doc = frappe.get_doc("Printer", printer)
		# form Desk gửi lại roll_loaded_on dạng chuỗi
		doc.roll_loaded_on = str(doc.roll_loaded_on)
		doc.host = "10.0.0.9"
		doc.save()
		self.assertEqual(frappe.db.get_value("Printer", printer, "host"), "10.0.0.9")

	def test_system_manager_may_declare_loaded_label_type(self):
		printer = make_printer("TR-004", self.steam)
		doc = frappe.get_doc("Printer", printer)
		doc.label_type_loaded = self.plasma
		doc.save()
		self.assertEqual(frappe.db.get_value("Printer", printer, "label_type_loaded"), self.plasma)

	def test_audit_log_records_printer_changes(self):
		printer = make_printer("TR-004", self.steam)
		self.assertTrue(
			frappe.db.exists("Audit Log", {"ref_doctype": "Printer", "ref_name": printer, "action": "Create"})
		)
		doc = frappe.get_doc("Printer", printer)
		doc.label_type_loaded = self.plasma
		doc.save()
		audit = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "Printer", "ref_name": printer, "action": "Update"},
			fields=["old_value", "new_value"],
		)
		self.assertEqual(len(audit), 1)
		self.assertEqual(json.loads(audit[0].old_value), {"label_type_loaded": self.steam})
		self.assertEqual(json.loads(audit[0].new_value), {"label_type_loaded": self.plasma})

	def test_printer_cannot_be_deleted(self):
		printer = make_printer("TR-004", self.steam)
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Printer", printer, ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Printer", printer))

	def test_permissions(self):
		perms = {
			p.role: p
			for p in frappe.get_all(
				"DocPerm", filters={"parent": "Printer"}, fields=["role", "read", "write", "create", "delete"]
			)
		}
		self.assertEqual(set(perms), {"System Manager", "TC R10", "TC R01", "TC R02"})
		for role in ("System Manager", "TC R10"):
			self.assertTrue(perms[role].write and perms[role].create, msg=role)
		for role in ("TC R01", "TC R02"):
			self.assertTrue(perms[role].read and not perms[role].write, msg=role)
		self.assertFalse(any(p.delete for p in perms.values()))


# Địa chỉ IP dạng chữ thuộc dải cục bộ/không định tuyến. Printer.host còn được Station Agent trên máy kiosk dùng
# (cầu nối 127.0.0.1 tới máy in USB, máy in APIPA 169.254.x.x), nên lưu Printer KHÔNG chặn các host này; chỉ đường
# in từ server (core.print_server, lúc gửi) từ chối gửi tới chúng khi site không bật cờ (A-05).
LOCAL_HOSTS = (
	"127.0.0.1",
	"127.1",  # socket hiểu là 127.0.0.1
	"2130706433",  # 127.0.0.1 dạng số nguyên
	"::1",
	"[::1]",
	"::ffff:127.0.0.1",
	"169.254.169.254",
	"169.254.10.20",
	"fe80::1",
	"0.0.0.0",
)


class TestPrinterHost(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.steam, self.plasma = make_label_items()
		frappe.conf.pop("tracecore_allow_local_printers", None)

	def test_agent_local_hosts_saved_without_site_flag(self):
		for host in LOCAL_HOSTS:
			self.assertTrue(_printer_doc(host=host).insert(), msg=host)
		doc = _printer_doc(host="10.0.0.9").insert()
		doc.host = "127.0.0.1"
		doc.save()
		self.assertEqual(frappe.db.get_value("Printer", doc.name, "host"), "127.0.0.1")

	def test_lan_ip_and_hostnames_allowed(self):
		for host in ("10.0.0.9", "192.168.1.50", "172.16.4.2", "printer.local", "zebra-t4", "localhost"):
			self.assertTrue(_printer_doc(host=host).insert(), msg=host)

	def test_existing_loopback_printer_set_roll_works_but_server_refuses_to_send(self):
		from unittest.mock import patch

		from tracecore.core import print_server

		printer = make_printer("TR-004", self.steam)
		frappe.db.set_value("Printer", printer, "host", "127.0.0.1")  # máy in của agent đã có từ trước

		result = core_print.set_roll(printer, make_roll(self.plasma))
		self.assertEqual(result["label_type"], self.plasma)
		self.assertEqual(frappe.db.get_value("Printer", printer, "label_type_loaded"), self.plasma)

		self.assertIsNone(print_server.printer_address(printer))
		job = core_print.create_job("TR-004", "^XA^XZ", None, "object-label", printer=printer)
		with (
			patch.object(print_server.socket, "create_connection") as connect,
			patch.object(print_server.frappe.db, "commit"),
		):
			print_server.dispatch_job(job)
		connect.assert_not_called()
