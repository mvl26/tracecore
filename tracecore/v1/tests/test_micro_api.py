"""RPC màn SCR-59 và xem mã người bệnh (FEAT-067 AC-6, AC-11, AC-13, AC-15; FR-M14-02, FR-M14-05; A-136 Q5, Q7)."""

import json
import uuid

import frappe

from tracecore.core import notification
from tracecore.microbiology import isolates
from tracecore.microbiology.tests.factories import make_organism, make_rule, new_isolate
from tracecore.tests.factories import make_department, make_user
from tracecore.tests.utils import IsolatedTestCase, bru, request_headers
from tracecore.ui import ksnk
from tracecore.v1 import micro
from tracecore.v1 import patient_code as reveal_api

PATIENT = "BN0007777"
TS = "2026-11-09T10:00:00+07:00"


def _key():
	return {"X-Idempotency-Key": str(uuid.uuid4())}


class TestMicroApi(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		make_organism()
		notification.ensure_default_rules()
		frappe.db.delete("MDRO Rule", {"rule_code": ["not like", "T-%"]})
		self.department = make_department("Khoa Hồi sức vi sinh")
		self.r11 = make_user("micro-api-r11@example.com", ["TC R11"])
		self.r13 = make_user("micro-api-r13@example.com", ["TC R13"])
		self.addCleanup(frappe.set_user, "Administrator")

	def values(self, lab="M-1"):
		return {
			"lab_sample_id": lab,
			"organism": "KPN",
			"patient_code": PATIENT,
			"birth_year": 1955,
			"sex": "Female",
			"department": self.department,
			"specimen_type": "Blood",
			"collected_on": "2026-08-12",
		}

	def test_screen_is_registered_in_the_micro_group(self):
		screen = next(item for item in ksnk.SCREENS if item["slug"] == "vi-sinh")
		self.assertEqual((screen["scr"], screen["uc"], screen["group"]), ("SCR-59", "UC-51", "micro"))
		frappe.set_user(make_user("micro-api-r12@example.com", ["TC R12"]))
		with self.assertRaises(frappe.PermissionError):
			micro.overview()

	def test_manual_entry_needs_preview_then_confirmation(self):
		make_rule("T-CRE", label="CRE")
		frappe.set_user(self.r11)
		susceptibility = json.dumps([{"antibiotic": "mem", "result": "r", "mic": ">8"}])
		preview = micro.manual_preview(json.dumps(self.values()), susceptibility)
		self.assertTrue(preview["ok"])
		self.assertEqual(preview["preview"]["patient_code_masked"], "***7777")
		self.assertEqual(preview["preview"]["mdro_labels"], ["CRE"])
		self.assertNotIn(PATIENT, json.dumps(preview))
		self.assertFalse(frappe.db.exists(isolates.DOCTYPE, {"lab_sample_id": "M-1"}))
		with request_headers(_key()):
			refused = micro.manual_entry(
				values=json.dumps(self.values()), susceptibility=susceptibility, confirm=0, client_ts=TS
			)
		self.assertFalse(refused["ok"])
		with request_headers(_key()):
			saved = micro.manual_entry(
				values=json.dumps(self.values()),
				susceptibility=susceptibility,
				confirm=1,
				client_ts="2026-11-09T10:00:00+07:00",
			)
		self.assertTrue(saved["ok"])
		doc = frappe.get_doc(isolates.DOCTYPE, saved["isolate"])
		self.assertEqual((doc.source, doc.confirmed_by, doc.mdro_flags), ("Manual", self.r11, "CRE"))
		self.assertTrue(
			frappe.db.exists("Audit Log", {"action": "Manual Entry", "ref_name": doc.name, "user": self.r11})
		)

	def test_manual_entry_reports_problems_inline(self):
		frappe.set_user(self.r11)
		bad = {**self.values(), "organism": "zzz", "collected_on": "2099-01-01"}
		result = micro.manual_preview(json.dumps(bad), json.dumps([{"antibiotic": "MEM", "result": "X"}]))
		self.assertFalse(result["ok"])
		self.assertTrue(result["error"]["reason"])
		missing = micro.manual_preview(json.dumps({"organism": "kpn"}), "[]")
		self.assertFalse(missing["ok"])

	def test_r13_cannot_enter_results(self):
		frappe.set_user(self.r13)
		with self.assertRaises(frappe.PermissionError):
			micro.manual_preview(json.dumps(self.values()), "[]")

	@bru("BRU-HAI-005")
	def test_overview_masks_patients_and_hides_rows_from_r13(self):
		make_rule("T-CRE", label="CRE")
		new_isolate(lab="O-1", patient=PATIENT, collected_on="2026-08-01", results=(("MEM", "R"),))
		new_isolate(lab="O-2", patient=PATIENT, collected_on="2026-08-20", results=(("MEM", "S"),))
		frappe.set_user(self.r11)
		data = micro.overview(year=2026, quarter=3)
		self.assertTrue(data["can_import"])
		self.assertNotIn(PATIENT, json.dumps(data, default=str))
		rows = {row["lab_sample_id"]: row for row in data["recent"]}
		self.assertEqual(rows["O-2"]["history"], ["CRE"])
		self.assertEqual(rows["O-1"]["patient_code_masked"], "***7777")
		self.assertNotIn("patient_code_hash", rows["O-1"])
		self.assertTrue(rows["O-1"]["pending"])
		self.assertGreaterEqual(data["pending"]["count"], 1)
		self.assertEqual(data["antibiogram"]["organism"], "kpn")
		frappe.set_user(self.r13)
		summary = micro.overview(year=2026, quarter=3)
		self.assertEqual((summary["recent"], summary["pending"], summary["can_import"]), ([], None, False))
		self.assertEqual(summary["antibiogram"]["first_isolates"], 1)

	def test_badge_counts_unread_mdro_alerts_of_the_user(self):
		make_rule("T-CRE", label="CRE")
		new_isolate(lab="B-1", results=(("MEM", "R"),))
		from tracecore.microbiology import alerts

		self.assertEqual(alerts.badges(self.r11), {"vi-sinh": 1})
		self.assertEqual(alerts.badges(self.r13), {"vi-sinh": 0})

	def test_reveal_rpc_and_history_rpc(self):
		doc = new_isolate(lab="R-1", patient=PATIENT, results=(("MEM", "R"),))
		make_rule("T-CRE", label="CRE")
		frappe.set_user(self.r11)
		with request_headers(_key()):
			refused = reveal_api.reveal(doctype=isolates.DOCTYPE, name=doc.name, reason="", client_ts=TS)
		self.assertFalse(refused["ok"])
		with request_headers(_key()):
			shown = reveal_api.reveal(
				doctype=isolates.DOCTYPE, name=doc.name, reason="Đối chiếu kết quả", client_ts=TS
			)
		self.assertEqual(shown["patient_code"], PATIENT)
		history = micro.mdro_history(json.dumps([doc.patient_code_hash]))
		self.assertEqual(history["history"], {doc.patient_code_hash: []})
		frappe.set_user(self.r13)
		with self.assertRaises(frappe.PermissionError):
			micro.mdro_history("[]")
