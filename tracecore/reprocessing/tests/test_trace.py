"""Truy xuất hai chiều (FEAT-028, UC-14, FR-M2-19 .1-.4, NFR-SEC-02): hash mã BN, chuỗi sự kiện, quyền, báo cáo."""

import json

import frappe

from tracecore.core import crypto
from tracecore.reprocessing import trace, usage
from tracecore.reprocessing.report.pack_trace import pack_trace
from tracecore.reprocessing.tests.test_usage import issue
from tracecore.tests import factories
from tracecore.tests.factories import make_department, make_employee, make_user
from tracecore.tests.utils import IsolatedTestCase

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

T8 = "TR-008"
PATIENT = "BN12345678"


class TraceCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.dept = make_department("Khoa truy xuất A")
		self.other = make_department("Khoa truy xuất B")
		self.nurse = make_employee(first_name="Điều dưỡng truy xuất", department=self.dept).name
		self.equipment = factories.make_sterilizer(name="Máy hấp truy xuất").name
		program = factories.make_sterilize_program(self.equipment)
		self.load = factories.make_load(self.equipment, program, [factories.make_load_ready_pack()]).name
		self.pack = issue(factories.make_stocked_pack(), self.dept)
		frappe.db.set_value("Pack", self.pack.name, "load", self.load, update_modified=False)
		self.usage = usage.confirm(self.pack.name, T8, self.nurse, patient_code=PATIENT, surgery_code="CA-9")
		self.addCleanup(frappe.set_user, "Administrator")

	def chain(self, result):
		self.assertEqual(len(result["chains"]), 1, result)
		return result["chains"][0]


class TestPatientHash(TraceCase):
	def test_hash_is_stored_normalised_and_never_the_code(self):
		stored = frappe.db.get_value("Usage Record", self.usage["usage"], "patient_code_hash")
		self.assertEqual(stored, crypto.patient_hash(PATIENT))
		self.assertEqual(crypto.patient_hash("  bn12345678 "), stored)
		self.assertNotIn(PATIENT, stored)
		self.assertEqual(len(stored), 64)

	def test_patch_fills_missing_hashes(self):
		from tracecore.patches.v0_1 import backfill_patient_code_hash

		frappe.db.set_value(
			"Usage Record", self.usage["usage"], "patient_code_hash", None, update_modified=False
		)
		backfill_patient_code_hash.execute()
		self.assertEqual(
			frappe.db.get_value("Usage Record", self.usage["usage"], "patient_code_hash"),
			crypto.patient_hash(PATIENT),
		)


class TestQuery(TraceCase):
	def test_patient_code_returns_the_full_chain_t1_to_t8(self):
		# FR-M2-19, .1, .3: bệnh nhân → Cycle ID → Set ID → mẻ → máy → người
		chain = self.chain(trace.query(patient_code=PATIENT))
		self.assertEqual(
			(chain["set_id"], chain["cycle_id"], chain["load"]),
			(self.pack.set_unit, self.pack.name, self.load),
		)
		self.assertEqual(chain["equipment"], self.equipment)
		steps = [event["step"] for event in chain["events"]]
		for step in ("T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8"):
			self.assertIn(step, steps)
		times = [event["at"] for event in chain["events"]]
		self.assertEqual(times, sorted(times))
		for event in chain["events"]:
			self.assertIn("user", event)
			self.assertIn("station", event)
		usage_event = next(event for event in chain["events"] if event["step"] == "T8")
		self.assertEqual(usage_event["department"], self.dept)
		self.assertNotIn(PATIENT, json.dumps(trace.query(patient_code=PATIENT), default=str))
		self.assertTrue(chain["patient_code_masked"])

	def test_same_chain_from_set_id_cycle_id_load_and_equipment(self):
		# hai chiều: từ Set ID / Cycle ID / mẻ / máy cũng ra cùng chuỗi
		for criteria in (
			{"cycle_id": self.pack.name},
			{"set_id": self.pack.set_unit},
			{"load": self.load},
			{"equipment": self.equipment},
		):
			chains = trace.query(**criteria)["chains"]
			self.assertIn(self.pack.name, [chain["cycle_id"] for chain in chains], criteria)

	def test_load_lists_every_pack_with_status_and_masked_patient(self):
		# FR-M2-19.2
		chains = {chain["cycle_id"]: chain for chain in trace.query(load=self.load)["chains"]}
		self.assertEqual(chains[self.pack.name]["pack_status"], "Used")
		self.assertTrue(chains[self.pack.name]["patient_code_masked"])

	def test_user_and_date_range(self):
		on = frappe.utils.getdate()
		found = trace.query(user="Administrator", from_date=on, to_date=on)["chains"]
		self.assertIn(self.pack.name, [chain["cycle_id"] for chain in found])
		empty = trace.query(user="Administrator", from_date="2001-01-01", to_date="2001-01-02")
		self.assertEqual(empty["chains"], [])

	def test_no_result_suggests_other_criteria(self):
		# FR-M2-19.4, UC-14 E1
		result = trace.query(patient_code="KHONG-CO-BN")
		self.assertEqual(result["chains"], [])
		self.assertTrue(result["suggestion"])

	def test_criteria_are_required(self):
		with self.assertRaises(frappe.ValidationError):
			trace.query()


class TestAccess(TraceCase):
	def test_ward_user_sees_only_own_department(self):
		own = make_user("tx-r08-a@example.com", ["TC R08"])
		make_employee(first_name="R08 A", department=self.dept, user_id=own)
		foreign = make_user("tx-r08-b@example.com", ["TC R08"])
		make_employee(first_name="R08 B", department=self.other, user_id=foreign)
		frappe.set_user(own)
		self.chain(trace.query(cycle_id=self.pack.name))
		frappe.set_user(foreign)
		self.assertEqual(trace.query(cycle_id=self.pack.name)["chains"], [])

	def test_other_roles_are_refused(self):
		frappe.set_user(make_user("tx-r03@example.com", ["TC R03"]))
		with self.assertRaises(frappe.PermissionError):
			trace.query(cycle_id=self.pack.name)


class TestTranslations(IsolatedTestCase):
	def test_report_filters_columns_and_step_labels_are_translated(self):
		import os

		from tracecore.tests.test_station_page import JS_STRING, other_app_translations, vi_translations

		ours, others = vi_translations(), other_app_translations()
		path = os.path.join(
			frappe.get_app_path("tracecore"), "reprocessing", "report", "pack_trace", "pack_trace.js"
		)
		with open(path, encoding="utf-8") as handle:
			strings = {match[1] for match in JS_STRING.findall(handle.read())}
		strings |= {label for _field, label, *_rest in pack_trace.COLUMNS}
		strings |= set(trace.STEP_LABELS.values()) | {"Pack Trace"}
		missing = sorted(
			s for s in strings if not (ours.get(f"{s}:Pack Trace") or ours.get(s) or others.get(s))
		)
		self.assertFalse(missing, f"thiếu dòng vi.csv {missing}")


class TestReport(TraceCase):
	def test_report_rows_are_events_with_columns(self):
		columns, rows, _message = pack_trace.execute({"cycle_id": self.pack.name})
		self.assertIn("step", [column["fieldname"] for column in columns])
		self.assertGreaterEqual(len(rows), 8)
		self.assertEqual({row["cycle_id"] for row in rows}, {self.pack.name})
		self.assertNotIn(PATIENT, json.dumps(rows, default=str))
