"""Desk SCR-22 (FEAT-039 Task 6): Client Script của Maintenance Record và nút trên form Equipment.

Kiểm phần đọc được bằng Python: mọi chuỗi qua __() có dòng vi.csv, không chữ Việt/hex trong code, lỗi chặn ghi sổ hiện
kết quả → lý do → hành động ngay trên form, nút gọi đúng phương thức server, mọi nhãn trường/lựa chọn của DocType (và
chuỗi Python mới) có bản dịch, danh sách hiện chữ cho mọi trạng thái.
"""

import json
import os
import re

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.tests.test_station_page import JS_STRING, other_app_translations, vi_translations

APP_PATH = frappe.get_app_path("tracecore")
EQUIPMENT_DIR = os.path.join(APP_PATH, "equipment", "doctype")
FORM_JS = os.path.join(EQUIPMENT_DIR, "maintenance_record", "maintenance_record.js")
LIST_JS = os.path.join(EQUIPMENT_DIR, "maintenance_record", "maintenance_record_list.js")
EQUIPMENT_JS = os.path.join(EQUIPMENT_DIR, "equipment", "equipment.js")
JSONS = (
	os.path.join(EQUIPMENT_DIR, "maintenance_record", "maintenance_record.json"),
	os.path.join(EQUIPMENT_DIR, "maintenance_part", "maintenance_part.json"),
	os.path.join(EQUIPMENT_DIR, "maintenance_affected_load", "maintenance_affected_load.json"),
)
EQUIPMENT_NEW_FIELDS = ("calibration_due", "maintenance_due", "lock_reason")
# chuỗi nguồn của dịch vụ/controller mới (Python), kèm ngữ cảnh dịch nếu có
PYTHON_STRINGS = (
	("Cost", None),
	("Downtime (hours)", None),
	("Cycle (months)", None),
	("SLA (hours)", None),
	("{0} cannot be negative.", None),
	("Row {0}: quantity and rate cannot be negative.", None),
	("Equipment {0} is retired; an incident cannot be recorded for it.", None),
	("A reason is required to abandon a record.", None),
	("Only a draft record that is not already abandoned can be abandoned.", None),
	("An abandoned record cannot be closed.", None),
	("The post-repair check result is required to close an incident.", None),
	("A certificate is required to close an inspection or calibration record.", None),
	("Valid Until is required to close an inspection or calibration record.", None),
	("Valid Until cannot be before Performed On.", None),
	("Equipment {0} is locked: {1}", None),
	("{0} of equipment {1} is planned for {2}", None),
	("Inspection Expired", "Equipment"),
	("Calibration Expired", "Equipment"),
	("Preventive", "Maintenance Record"),
	("Inspection", "Maintenance Record"),
	("Calibration", "Maintenance Record"),
	("Incident", "Maintenance Record"),
	("Calibration has expired", None),
	("Equipment {0} was due for calibration on {1}.", None),
	("Use another machine, or call R02 for a temporary unlock.", None),
)
VIETNAMESE = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.I)


def _read(path):
	with open(path, encoding="utf-8") as handle:
		return handle.read()


def _translated(text, ours, others, context=None):
	return bool(ours.get(text) or (context and ours.get(f"{text}:{context}")) or others.get(text))


class TestMaintenanceDeskAssets(FrappeTestCase):
	def test_strings_translated_and_no_hard_coded_text_or_colour(self):
		ours, others = vi_translations(), other_app_translations()
		for path in (FORM_JS, LIST_JS, EQUIPMENT_JS):
			script = _read(path)
			strings = sorted({match[1] for match in JS_STRING.findall(script)})
			missing = [s for s in strings if not _translated(s, ours, others, "Maintenance Record")]
			self.assertFalse(missing, f"{os.path.basename(path)}: thiếu dòng vi.csv {missing}")
			for number, line in enumerate(script.splitlines(), 1):
				code = line.split("//", 1)[0]
				self.assertFalse(VIETNAMESE.search(code), f"{number}: {line}")
				self.assertNotRegex(code, r"#[0-9a-fA-F]{3,6}\b", f"{number}: {line}")

	def test_doctype_labels_and_options_are_translated(self):
		ours, others = vi_translations(), other_app_translations()
		missing = []
		for path in (*JSONS, os.path.join(EQUIPMENT_DIR, "equipment", "equipment.json")):
			meta = json.loads(_read(path))
			texts = [meta["name"]]
			for field in meta["fields"]:
				if meta["name"] == "Equipment" and field["fieldname"] not in EQUIPMENT_NEW_FIELDS:
					continue  # chỉ kiểm trường FEAT-039 thêm; trường FEAT-038 do test của FEAT-038 giữ
				texts += [field.get("label"), field.get("description")]
				if field["fieldtype"] == "Select":
					texts.extend((field.get("options") or "").split("\n"))
			missing += [text for text in texts if text and not _translated(text, ours, others, meta["name"])]
		self.assertFalse(sorted(set(missing)), "thiếu dòng vi.csv")

	def test_python_strings_are_translated(self):
		ours, others = vi_translations(), other_app_translations()
		missing = [text for text, context in PYTHON_STRINGS if not _translated(text, ours, others, context)]
		self.assertFalse(missing, f"thiếu dòng vi.csv {missing}")

	def test_blocking_error_is_inline_result_reason_action(self):
		script = _read(FORM_JS)
		self.assertIn("alert alert-danger", script)
		for key in ("error.title", "error.reason", "error.action"):
			self.assertIn(key, script)
		self.assertIn("frappe.validated = false", script)
		self.assertNotIn("frappe.msgprint", script)
		self.assertNotIn("frappe.show_alert", script)

	def test_form_abandons_through_the_server_method_and_shows_the_machine_status(self):
		script = _read(FORM_JS)
		self.assertIn('frm.call("abandon"', script)
		self.assertIn('frappe.db.get_value("Equipment"', script)

	def test_equipment_form_opens_incident_and_maintenance_records(self):
		script = _read(EQUIPMENT_JS)
		self.assertIn('frappe.new_doc("Maintenance Record"', script)
		for record_type in ('"Incident"', '"Preventive"'):
			self.assertIn(record_type, script)

	def test_list_indicator_has_text_for_every_state(self):
		script = _read(LIST_JS)
		for state in ("Planned", "Overdue", "Incident open", "Abandoned", "Closed", "Cancelled"):
			self.assertIn(f'__("{state}")', script)
