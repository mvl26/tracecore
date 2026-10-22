"""Phiên bản dụng cụ khi đổi phương pháp tương thích và cảnh báo BOM (FEAT-014 Task 2; FR-M1-01.3; A-06 I1, I3).

Review Focus 3: phiên bản tăng đúng một lần cho mỗi thay đổi thật của tập phương pháp; mọi loại bộ có BOM hiện
hành chứa dụng cụ nhận cảnh báo; gói và bộ đang giữa chu trình không đổi.
"""

import frappe
from frappe import _
from frappe.utils import add_days, nowdate

from tracecore.core import step_gate
from tracecore.core.audit import AuditLogImmutableError
from tracecore.instrument import bom, catalog, versions
from tracecore.tests.factories import (
	make_bom,
	make_instrument,
	make_pack,
	make_set_type,
	make_t4_ready_set,
)
from tracecore.tests.utils import IsolatedTestCase

# Instrument, Set Unit, Pack liên kết Item, Batch, Department, User của ERPNext; site CI chưa chạy Setup Wizard
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def _set_methods(code, methods, **fields):
	doc = frappe.get_doc("Instrument", code)
	doc.set("compatible_methods", [{"method": method} for method in methods])
	doc.update(fields)
	doc.save()
	return doc


def _set_type_comments(set_type):
	"""Comment cảnh báo đổi phiên bản dụng cụ trên timeline loại bộ (bỏ Comment "BOM version N saved…" của FEAT-015)."""
	return frappe.get_all(
		"Comment",
		filters={
			"reference_doctype": "Instrument Set Type",
			"reference_name": set_type,
			"comment_type": "Info",
			"content": ["not like", "BOM version%"],
		},
		pluck="content",
	)


def _messages():
	return [frappe.parse_json(m) if isinstance(m, str) else m for m in frappe.get_message_log()]


class TestVersions(IsolatedTestCase):
	def test_version_bumps_once_per_real_method_change(self):
		make_instrument("VR-BMP", methods=("Steam 134",))

		doc = _set_methods("VR-BMP", ("Steam 134", "Plasma"))
		self.assertEqual(doc.version_no, 2)
		self.assertTrue(doc.flags.tc_version_bumped)

		# đổi thứ tự dòng, sửa trường khác: tập phương pháp như cũ → giữ phiên bản
		doc = _set_methods("VR-BMP", ("Plasma", "Steam 134"))
		self.assertEqual(doc.version_no, 2)
		self.assertFalse(doc.flags.tc_version_bumped)
		doc = _set_methods("VR-BMP", ("Plasma", "Steam 134"), manufacturer="Aesculap", max_cycles=500)
		self.assertEqual(doc.version_no, 2)

		doc = _set_methods("VR-BMP", ("Steam 134",))
		self.assertEqual(doc.version_no, 3)
		self.assertEqual(frappe.db.get_value("Instrument", "VR-BMP", "version_no"), 3)

		# lưu lại không đổi gì: không tăng
		frappe.get_doc("Instrument", "VR-BMP").save()
		self.assertEqual(frappe.db.get_value("Instrument", "VR-BMP", "version_no"), 3)

	def test_first_method_fill_on_legacy_instrument_keeps_version(self):
		# dụng cụ cũ chưa có phương pháp: điền lần đầu là nhập liệu ban đầu, không phải đổi phiên bản
		make_instrument("VR-LEG", methods=("Steam 134",))
		frappe.db.delete("Instrument Compatible Method", {"parent": "VR-LEG"})
		doc = _set_methods("VR-LEG", ("Steam 134", "Plasma"))
		self.assertEqual(doc.version_no, 1)
		self.assertFalse(doc.flags.tc_version_bumped)
		self.assertEqual(frappe.db.get_value("Instrument", "VR-LEG", "version_no"), 1)

	def test_stale_second_save_does_not_bump_version(self):
		make_instrument("VR-STALE", methods=("Steam 134",))
		first = frappe.get_doc("Instrument", "VR-STALE")
		second = frappe.get_doc("Instrument", "VR-STALE")
		first.set("compatible_methods", [{"method": "Plasma"}])
		first.save()
		self.assertEqual(first.version_no, 2)

		second.set("compatible_methods", [{"method": "EO"}])
		with self.assertRaises(frappe.TimestampMismatchError):
			second.save()
		self.assertEqual(frappe.db.get_value("Instrument", "VR-STALE", "version_no"), 2)
		self.assertEqual(catalog.method_set(frappe.get_doc("Instrument", "VR-STALE")), {"Plasma"})

	def test_bump_helper_ignores_new_documents(self):
		doc = frappe.get_doc(
			{
				"doctype": "Instrument",
				"instrument_code": "VR-NEW",
				"instrument_name": "New",
				"spaulding_class": "Critical",
				"compatible_methods": [{"method": "EO"}],
			}
		)
		self.assertFalse(versions.bump_if_methods_changed(doc))
		doc.insert()
		self.assertEqual(doc.version_no, 1)

	def test_history_keeps_old_versions(self):
		make_instrument("VR-HIS", methods=("Steam 134",))
		_set_methods("VR-HIS", ("Steam 134", "Plasma"))
		_set_methods("VR-HIS", ("Plasma", "Steam 134"), model="BH110")
		_set_methods("VR-HIS", ("Plasma",))

		history = versions.history("VR-HIS")
		self.assertEqual([row["version_no"] for row in history], [1, 2, 3])
		self.assertEqual(
			[row["methods"] for row in history],
			[["Steam 134"], ["Steam 134", "Plasma"], ["Plasma"]],
		)
		for row in history:
			self.assertEqual(set(row), {"version_no", "methods", "changed_on", "changed_by"})
			self.assertEqual(row["changed_by"], frappe.session.user)
			self.assertTrue(row["changed_on"])

		first = versions.snapshot_at("VR-HIS", 1)
		self.assertEqual(catalog.method_set(first), frozenset({"Steam 134"}))
		self.assertEqual(first["version_no"], 1)
		self.assertFalse(first.get("model"))
		second = versions.snapshot_at("VR-HIS", 2)
		self.assertEqual(catalog.method_set(second), frozenset({"Steam 134", "Plasma"}))
		self.assertEqual(second["model"], "BH110")
		self.assertEqual(catalog.method_set(versions.snapshot_at("VR-HIS", 3)), frozenset({"Plasma"}))
		with self.assertRaises(frappe.DoesNotExistError):
			versions.snapshot_at("VR-HIS", 4)

		# lịch sử nằm trong Audit Log append-only: không sửa, không xóa được
		entry = frappe.get_last_doc("Audit Log", filters={"ref_doctype": "Instrument", "ref_name": "VR-HIS"})
		entry.reason = "tamper"
		with self.assertRaises(AuditLogImmutableError):
			entry.save(ignore_permissions=True)
		with self.assertRaises(AuditLogImmutableError):
			frappe.delete_doc("Audit Log", entry.name, ignore_permissions=True)
		self.assertEqual(len(versions.history("VR-HIS")), 3)

	def test_history_of_instrument_without_audit_trail(self):
		make_instrument("VR-OLD", methods=("EO",))
		frappe.db.delete("Audit Log", {"ref_doctype": "Instrument", "ref_name": "VR-OLD"})
		history = versions.history("VR-OLD")
		self.assertEqual([(row["version_no"], row["methods"]) for row in history], [(1, ["EO"])])
		with self.assertRaises(frappe.DoesNotExistError):
			versions.history("VR-NONE")

	def test_method_change_warns_every_bom_using_instrument(self):
		make_instrument("VR-WRN", methods=("Steam 134",))
		steam = make_set_type("VRWS", method="Steam", set_type_name="Steam tray")
		plasma = make_set_type("VRWP", method="Plasma", set_type_name="Plasma tray")
		old_only = make_set_type("VRWO", method="Steam", set_type_name="Old BOM only")
		make_bom(steam, [("VR-WRN", 2)], version=1)
		# dữ liệu có trước FEAT-015: dụng cụ chỉ hấp đã nằm trong BOM loại bộ Plasma (nay bị chặn khi lưu BOM)
		make_bom(plasma, [("VR-OTH", 1), ("VR-WRN", 1)], version=1, legacy=True)
		make_bom(old_only, [("VR-WRN", 1)], version=1)
		make_bom(old_only, [("VR-OTH", 1)], version=2)
		frappe.db.set_value("Instrument Set Type", old_only.name, "current_bom_version", 2)

		usage = catalog.bom_usage("VR-WRN")
		self.assertEqual([row["set_type"] for row in usage], ["VRWP", "VRWS"])
		self.assertEqual(
			set(usage[0]), {"set_type", "set_type_name", "method", "bom_version", "compatible", "scheduled"}
		)
		self.assertFalse(any(row["scheduled"] for row in usage))
		self.assertTrue(all(row["compatible"] is False for row in usage if row["method"] == "Plasma"))

		frappe.clear_messages()
		doc = _set_methods("VR-WRN", ("Plasma",))
		self.assertEqual(doc.version_no, 2)

		for set_type in ("VRWS", "VRWP"):
			comments = _set_type_comments(set_type)
			self.assertEqual(len(comments), 1, msg=set_type)
			self.assertIn("VR-WRN", comments[0])
			self.assertIn("2", comments[0])
		self.assertEqual(_set_type_comments("VRWO"), [])
		# trạng thái sau khi đổi: "không tương thích" (Task 2 review)
		self.assertIn(
			_("The set type (method {0}) is not compatible with the instrument.").format(_("Steam")),
			_set_type_comments("VRWS")[0],
		)

		notes = [m for m in _messages() if "VR-WRN" in str(m.get("message"))]
		self.assertEqual(len(notes), 1, msg=_messages())
		self.assertEqual(notes[0].get("indicator"), "orange")
		self.assertIn("Steam tray", notes[0]["message"])
		self.assertIn("Plasma tray", notes[0]["message"])
		self.assertNotIn("Old BOM only", notes[0]["message"])
		# SCR-01: mỗi loại bộ là link mở form loại bộ
		self.assertIn('href="/app/instrument-set-type/VRWS"', notes[0]["message"])
		self.assertIn('href="/app/instrument-set-type/VRWP"', notes[0]["message"])
		self.assertIn(_("not compatible (set type method {0})").format(_("Steam")), notes[0]["message"])

		result = {row["set_type"]: row["compatible"] for row in doc.flags.tc_bom_usage}
		self.assertEqual(result, {"VRWS": False, "VRWP": True})

		# không đổi tập phương pháp → không cảnh báo thêm
		_set_methods("VR-WRN", ("Plasma",), manufacturer="Other")
		self.assertEqual(len(_set_type_comments("VRWS")), 1)

	def test_notify_returns_usage_and_skips_unused_instrument(self):
		make_instrument("VR-UNU", methods=("Steam 134",))
		frappe.clear_messages()
		doc = _set_methods("VR-UNU", ("EO",))
		self.assertEqual(doc.version_no, 2)
		self.assertEqual(versions.notify_boms(doc), [])
		self.assertFalse([m for m in _messages() if "VR-UNU" in str(m.get("message"))])

	def test_method_change_warns_set_type_with_scheduled_version(self):
		# FEAT-015 S2: dụng cụ chỉ có ở phiên bản BOM đã lên lịch cũng được cảnh báo (FEAT-014 I3)
		make_instrument("VR-SCH", methods=("Steam 134",))
		scheduled = make_set_type("VRSC", method="Steam", set_type_name="Scheduled tray")
		make_bom(scheduled, [("VR-OTH", 1)], version=1)
		make_bom(scheduled, [("VR-OTH", 1), ("VR-SCH", 1)], version=2, effective_from=add_days(nowdate(), 2))

		usage = catalog.bom_usage("VR-SCH")
		self.assertEqual(
			[(row["set_type"], row["bom_version"], row["scheduled"]) for row in usage], [("VRSC", 2, True)]
		)
		frappe.clear_messages()
		_set_methods("VR-SCH", ("Plasma",))
		self.assertEqual(len(_set_type_comments("VRSC")), 1)
		notes = [m for m in _messages() if "VR-SCH" in str(m.get("message"))]
		self.assertIn(_("scheduled BOM version {0}").format(2), notes[0]["message"])

	def test_method_change_does_not_touch_in_flight_cycles(self):
		ready = make_t4_ready_set(method="Steam", bom=(("VR-INF", 1), ("VR-IN2", 1)), with_printer=False)
		pack = make_pack(ready.set_id)
		step_gate.bind_cycle(ready.set_id, pack.name, None)
		unit_fields = ["status", "active_cycle_id", "current_cycle_no", "current_station", "modified"]
		pack_fields = ["status", "method", "docstatus", "modified"]
		unit_before = frappe.db.get_value("Set Unit", ready.set_id, unit_fields, as_dict=True)
		pack_before = frappe.db.get_value("Pack", pack.name, pack_fields, as_dict=True)
		self.assertEqual(unit_before.active_cycle_id, pack.name)
		self.assertEqual(pack_before.status, "Packed")

		doc = _set_methods("VR-INF", ("Plasma",))  # bộ Steam mất tương thích: chỉ cảnh báo
		self.assertEqual(doc.version_no, 2)

		self.assertEqual(
			frappe.db.get_value("Set Unit", ready.set_id, unit_fields, as_dict=True), unit_before
		)
		self.assertEqual(frappe.db.get_value("Pack", pack.name, pack_fields, as_dict=True), pack_before)
		set_type = frappe.db.get_value(
			"Instrument Set Type",
			ready.set_type,
			["name", "current_bom_version", "tray_image"],
			as_dict=True,
		)
		context = bom.pack_context({"set_type": set_type, "station": "T4"})
		self.assertEqual([row["instrument"] for row in context["bom"]], ["VR-INF", "VR-IN2"])
		self.assertEqual(len(_set_type_comments(ready.set_type)), 1)
