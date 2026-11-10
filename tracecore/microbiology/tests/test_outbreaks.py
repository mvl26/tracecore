"""Điều tra ổ dịch (FEAT-069; FR-M14-09, .1; BRU-MDR-004; UC-53 bước 1-4, A2, E1, E4; UC-50 bước 3-4; A-150 Q3, Q5)."""

import json
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate, today

from tracecore.core.errors import BlockedError
from tracecore.microbiology import clusters, outbreaks
from tracecore.microbiology.tests import outbreak_fixtures as of
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase, bru

VAP = "Ventilator-associated Pneumonia"


class OutbreakCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.icu = of.make_clinical("OD Hồi sức tích cực")
		self.ward = of.make_clinical("OD Khoa Nội")
		self.r01 = make_user("od-r01@example.com", ["TC R01"])
		self.r11 = make_user("od-r11@example.com", ["TC R11"])

	def values(self, **extra):
		return {
			"title": "Cụm CRE tại Hồi sức tích cực",
			"organism_or_disease": "Klebsiella pneumoniae — CRE",
			"department": self.icu,
			"start_date": "2026-11-03",
			"case_definition": "Người bệnh HSTC có CRE từ 18/10",
			**extra,
		}

	def open(self, **extra):
		frappe.set_user(self.r01)
		doc = outbreaks.open_outbreak(self.values(**extra))
		frappe.set_user("Administrator")
		return doc


class TestOpen(OutbreakCase):
	def test_only_r01_opens(self):
		frappe.set_user(self.r11)
		with self.assertRaises(frappe.PermissionError):
			outbreaks.open_outbreak(self.values())
		doc = self.open()
		self.assertEqual((doc.docstatus, doc.status, doc.opened_by), (1, outbreaks.INVESTIGATING, self.r01))

	def test_required_fields_and_future_start(self):
		frappe.set_user(self.r01)
		for missing in ("title", "organism_or_disease", "department", "start_date"):
			with self.subTest(missing=missing), self.assertRaises(BlockedError) as caught:
				outbreaks.open_outbreak(self.values(**{missing: ""}))
			self.assertEqual(caught.exception.block.code, "OUTBREAK_FIELDS_REQUIRED")
		with self.assertRaises(BlockedError):
			outbreaks.open_outbreak(self.values(start_date=add_days(today(), 2)))

	def test_direct_insert_blocked(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": outbreaks.DOCTYPE, **self.values()}).insert(ignore_permissions=True)

	def test_open_from_cluster_alert_prefills_cases_and_closes_alert(self):
		frappe.db.delete(clusters.ALERT_DOCTYPE)
		frappe.db.delete(clusters.RULE_DOCTYPE)
		frappe.db.delete("HAI Case", {"department": self.icu})
		of.make_rule(infection_site=VAP, min_cases=2)
		first = of.make_case(self.icu, "2026-10-24", "BN-0000005517")
		second = of.make_case(self.icu, "2026-10-30", "BN-0000007730")
		with patch("tracecore.core.notification.emit"):
			alert = clusters.run_daily(getdate("2026-11-03"))[0]
		prefill = outbreaks.prefill_from_alert(alert)
		self.assertEqual(prefill["department"], self.icu)
		self.assertEqual(len(prefill["cases"]), 2)
		doc = self.open(cluster_alert=alert)
		self.assertEqual(doc.source, "Cluster Alert")
		self.assertEqual({row.hai_case for row in doc.cases}, {first, second})
		self.assertEqual(
			frappe.db.get_value(clusters.ALERT_DOCTYPE, alert, ["status", "outbreak_investigation"]),
			(clusters.OPENED, doc.name),
		)


class TestCases(OutbreakCase):
	def test_link_hai_case_isolate_and_manual(self):
		doc = self.open()
		case = of.make_case(self.icu, "2026-10-20", "BN-0000002031")
		suspected = of.make_case(self.icu, "2026-11-02", "BN-0000004821", status="Suspected")
		isolate = of.make_isolate(self.icu, "OD-1", "BN-0000005517", "2026-10-24", mdro=1, flags="CRE")
		frappe.set_user(self.r11)
		outbreaks.add_case(doc.name, "HAI Case", ref=case)
		outbreaks.add_case(doc.name, "HAI Case", ref=suspected)
		outbreaks.add_case(doc.name, "Microbiology Isolate", ref=isolate)
		outbreaks.add_case(
			doc.name, "Manual", patient_code="BN0007730", onset_date="2026-10-30", case_status="Confirmed"
		)
		with self.assertRaises(BlockedError) as caught:
			outbreaks.add_case(doc.name, "HAI Case", ref=case)
		self.assertEqual(caught.exception.block.code, "OUTBREAK_CASE_DUPLICATE")
		with self.assertRaises(BlockedError):
			outbreaks.add_case(doc.name, "Manual", patient_code="", onset_date="2026-10-30")
		rows = outbreaks.detail(doc.name)["cases"]
		self.assertEqual(len(rows), 4)
		by_source = {row["ref"] or row["patient_code_masked"]: row for row in rows}
		self.assertEqual(by_source[case]["state"], "Confirmed")
		self.assertEqual(by_source[suspected]["state"], "Suspected")
		self.assertEqual(by_source[isolate]["onset_date"], getdate("2026-10-24"))
		self.assertEqual(by_source["***7730"]["state"], "Confirmed")
		self.assertNotIn("BN0007730", json.dumps(outbreaks.detail(doc.name), default=str))

	def test_excluded_hai_case_flagged(self):
		doc = self.open()
		case = of.make_case(self.icu, "2026-10-20", "BN-0000002031")
		outbreaks.add_case(doc.name, "HAI Case", ref=case)
		frappe.db.set_value("HAI Case", case, "status", "Excluded")
		row = outbreaks.detail(doc.name)["cases"][0]
		self.assertEqual(row["state"], "Excluded")
		self.assertTrue(row["excluded_at_source"])

	def test_remove_case_needs_reason(self):
		doc = self.open()
		outbreaks.add_case(doc.name, "Manual", patient_code="BN0007730", onset_date="2026-10-30")
		row = frappe.get_doc(outbreaks.DOCTYPE, doc.name).cases[0].name
		with self.assertRaises(BlockedError):
			outbreaks.remove_case(doc.name, row, "")
		after = outbreaks.remove_case(doc.name, row, "Không cùng chủng")
		self.assertEqual(len(after.cases), 0)

	def test_r13_cannot_add(self):
		doc = self.open()
		frappe.set_user(make_user("od-r13@example.com", ["TC R13"]))
		with self.assertRaises(frappe.PermissionError):
			outbreaks.add_case(doc.name, "Manual", patient_code="BN1", onset_date="2026-10-30")


class TestEpiCurve(OutbreakCase):
	def test_curve_counts_by_onset_and_state(self):
		doc = self.open()
		for code, onset, state in (
			("BN0000001", "2026-10-20", "Confirmed"),
			("BN0000002", "2026-10-30", "Confirmed"),
			("BN0000003", "2026-10-30", "Confirmed"),
			("BN0000004", "2026-11-02", "Suspected"),
		):
			outbreaks.add_case(doc.name, "Manual", patient_code=code, onset_date=onset, case_status=state)
		curve = outbreaks.epi_curve(frappe.get_doc(outbreaks.DOCTYPE, doc.name), until="2026-11-03")
		days = {row["date"]: row for row in curve["days"]}
		self.assertEqual(curve["from"], "2026-10-18")
		self.assertEqual(curve["to"], "2026-11-03")
		self.assertEqual(days["2026-10-30"]["confirmed"], 2)
		self.assertEqual(days["2026-11-02"]["suspected"], 1)
		self.assertEqual(days["2026-10-25"]["confirmed"], 0)
		self.assertEqual(curve["max"], 2)

	def test_empty_curve(self):
		doc = self.open()
		curve = outbreaks.epi_curve(frappe.get_doc(outbreaks.DOCTYPE, doc.name), until="2026-11-03")
		self.assertEqual(curve["days"], [])


class TestActionsAndEnd(OutbreakCase):
	def action(self, doc, **extra):
		return outbreaks.add_action(
			doc.name,
			extra.get("description", "Cách ly tiếp xúc toàn bộ ca CRE"),
			extra.get("responsible", self.r11),
			extra.get("due_date", add_days(today(), 3)),
		)

	def test_add_action_creates_outbreak_nc_once(self):
		doc = self.open()
		frappe.set_user(self.r11)
		self.action(doc)
		self.action(doc, description="Sàng lọc người bệnh cùng phòng")
		frappe.set_user("Administrator")
		doc.reload()
		self.assertEqual(len(doc.capas), 1)
		nc = frappe.get_doc("Incident CAPA", doc.capas[0].incident_capa)
		self.assertEqual((nc.incident_type, nc.incident_category), ("Outbreak Control", "Outbreak"))
		self.assertEqual(
			(nc.source_doctype, nc.source_name, nc.department), (outbreaks.DOCTYPE, doc.name, self.icu)
		)
		self.assertEqual(len(nc.actions), 2)
		actions = outbreaks.detail(doc.name)["actions"]
		self.assertEqual([row["description"] for row in actions][1], "Sàng lọc người bệnh cùng phòng")
		self.assertEqual(actions[0]["state"], "Open")

	def test_action_requires_fields(self):
		doc = self.open()
		with self.assertRaises(BlockedError) as caught:
			self.action(doc, responsible="")
		self.assertEqual(caught.exception.block.code, "OUTBREAK_ACTION_INCOMPLETE")

	def test_link_existing_nc(self):
		doc = self.open()
		nc = frappe.get_doc(
			{
				"doctype": "Incident CAPA",
				"incident_type": "Other",
				"severity": "Medium",
				"description": "NC môi trường HSTC",
				"department": self.icu,
			}
		)
		nc.flags.tc_incident = True
		nc.insert(ignore_permissions=True)
		outbreaks.link_nc(doc.name, nc.name)
		with self.assertRaises(BlockedError):
			outbreaks.link_nc(doc.name, nc.name)
		self.assertEqual(
			[row.incident_capa for row in frappe.get_doc(outbreaks.DOCTYPE, doc.name).capas], [nc.name]
		)

	def test_controlled_only_r01(self):
		doc = self.open()
		frappe.set_user(self.r11)
		with self.assertRaises(frappe.PermissionError):
			outbreaks.set_controlled(doc.name)
		frappe.set_user(self.r01)
		self.assertEqual(outbreaks.set_controlled(doc.name).status, outbreaks.CONTROLLED)

	@bru("BRU-MDR-004")
	def test_end_needs_summary(self):
		doc = self.open()
		frappe.set_user(self.r01)
		with self.assertRaises(BlockedError) as caught:
			outbreaks.end_outbreak(doc.name, summary=" ", end_date=today())
		self.assertEqual(caught.exception.block.code, "OUTBREAK_SUMMARY_REQUIRED")

	@bru("BRU-MDR-004")
	def test_end_blocked_while_capa_open_without_reason(self):
		doc = self.open()
		self.action(doc)
		frappe.set_user(self.r01)
		with self.assertRaises(BlockedError) as caught:
			outbreaks.end_outbreak(doc.name, summary="Đã kiểm soát", end_date=today())
		self.assertEqual(caught.exception.block.code, "OUTBREAK_CAPA_OPEN")
		row = frappe.get_doc(outbreaks.DOCTYPE, doc.name).capas[0].name
		ended = outbreaks.end_outbreak(
			doc.name,
			summary="4 ca CRE, không ca mới 14 ngày",
			end_date=today(),
			external_report_ref="CV-123/KSNK",
			open_reasons={row: "Hành động giám sát VST còn chạy theo kế hoạch quý"},
		)
		self.assertEqual((ended.status, ended.external_report_ref), (outbreaks.ENDED, "CV-123/KSNK"))
		self.assertEqual(ended.capas[0].open_reason, "Hành động giám sát VST còn chạy theo kế hoạch quý")

	@bru("BRU-MDR-004")
	def test_end_allowed_when_capa_closed(self):
		doc = self.open()
		self.action(doc)
		nc = frappe.get_doc(outbreaks.DOCTYPE, doc.name).capas[0].incident_capa
		frappe.db.set_value("Incident CAPA", nc, "status", "Closed")
		frappe.set_user(self.r11)
		with self.assertRaises(frappe.PermissionError):
			outbreaks.end_outbreak(doc.name, summary="x", end_date=today())
		frappe.set_user(self.r01)
		ended = outbreaks.end_outbreak(doc.name, summary="Kết thúc", end_date=today())
		self.assertEqual(ended.status, outbreaks.ENDED)
		with self.assertRaises(BlockedError):
			outbreaks.add_case(doc.name, "Manual", patient_code="BN1", onset_date="2026-10-30")

	def test_end_date_before_start_blocked(self):
		doc = self.open()
		frappe.set_user(self.r01)
		with self.assertRaises(BlockedError):
			outbreaks.end_outbreak(doc.name, summary="x", end_date="2026-10-01")

	def test_cancel_r01_with_reason(self):
		doc = self.open()
		frappe.set_user(self.r01)
		with self.assertRaises(BlockedError):
			outbreaks.cancel_outbreak(doc.name, "")
		cancelled = outbreaks.cancel_outbreak(doc.name, "Mở nhầm")
		self.assertEqual((cancelled.docstatus, cancelled.status), (2, outbreaks.CANCELLED))

	def test_desk_edit_blocked(self):
		doc = self.open()
		doc = frappe.get_doc(outbreaks.DOCTYPE, doc.name)
		doc.case_definition = "sửa tay"
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)


class TestSummary(OutbreakCase):
	def test_summary_has_no_patient_data(self):
		doc = self.open()
		outbreaks.add_case(doc.name, "Manual", patient_code="BN0007730", onset_date="2026-10-30")
		rows = outbreaks.summary_rows()
		row = next(item for item in rows if item["name"] == doc.name)
		self.assertEqual(row["case_count"], 1)
		self.assertNotIn("cases", row)
		self.assertNotIn("7730", json.dumps(row, default=str))

	@bru("BRU-HAI-005")
	def test_case_child_has_no_name_or_plain_code(self):
		path = (
			Path(frappe.get_app_path("tracecore")) / "microbiology/doctype/outbreak_case/outbreak_case.json"
		)
		fields = [row["fieldname"] for row in json.loads(path.read_text())["fields"]]
		self.assertNotIn("patient_code", fields)
		self.assertFalse([name for name in fields if "name" in name])
