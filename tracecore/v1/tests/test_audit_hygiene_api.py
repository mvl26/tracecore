"""RPC vệ sinh tay theo cơ hội `tracecore.v1.audit.record_opportunity` (FEAT-061 AC-2, AC-6, AC-8; FR-M12-04 .1, FR-M12-10;
NFR-AVAIL-05; BRU-AUD-004)."""

import json
import uuid

import frappe
from frappe.utils import add_days, today

from tracecore.compliance_audit.tests.factories import make_template, make_vst_template
from tracecore.tests.utils import bru
from tracecore.v1 import audit as audit_api
from tracecore.v1.tests.test_audit_session_api import AuditApiCase, call, now_ts

test_ignore = ["Item", "Batch", "Supplier", "Incident CAPA", "Department", "User", "Employee"]


def opp(**values):
	return json.dumps(
		{"uuid": str(uuid.uuid4()), "subject_role": "Nurse", "moment": "1", "action": "Hand Rub", **values}
	)


class HygieneApiCase(AuditApiCase):
	def setUp(self):
		super().setUp()
		self.vst = make_vst_template("T-VST-API", effective_from=add_days(today(), -1))
		self.session_uuid = str(uuid.uuid4())

	def record(self, opportunity=None, key=None, replay=False, **values):
		args = {
			"station": self.station,
			"audit_template": self.vst.name,
			"department": self.dept_a,
			"session_uuid": self.session_uuid,
			"opportunity": opportunity or opp(),
			**values,
		}
		return call(audit_api.record_opportunity, key, replay=replay, **args)

	def finish(self, **values):
		args = {
			"station": self.station,
			"audit_template": self.vst.name,
			"department": self.dept_a,
			"session_uuid": self.session_uuid,
			**values,
		}
		return call(audit_api.submit_session, **args)

	def rows(self):
		return frappe.get_all(
			"Hand Hygiene Opportunity",
			filters={"parenttype": "Audit Session"},
			fields=["parent", "client_uuid"],
		)


class TestRecordOpportunity(HygieneApiCase):
	def test_first_call_opens_a_draft_session_for_the_observer(self):
		observer = self.login("hyg-api-r11a@example.com", "TC R11")
		res = self.record()
		self.assertTrue(res["ok"], res)
		doc = frappe.get_doc("Audit Session", res["name"])
		self.assertEqual(
			(doc.docstatus, doc.observer, doc.client_uuid, doc.department),
			(0, observer, self.session_uuid, self.dept_a),
		)
		self.assertEqual((res["opportunities"], res["actioned"], res["rate"]), (1, 1, 100.0))

	def test_next_calls_add_to_the_same_session_with_a_running_rate(self):
		self.login("hyg-api-r11b@example.com", "TC R11")
		first = self.record()
		self.record(opp(action="Missed", moment="2"))
		third = self.record(opp(action="Hand Wash", moment="3"))
		self.assertEqual(third["name"], first["name"])
		self.assertEqual((third["opportunities"], third["actioned"], third["rate"]), (3, 2, 66.7))
		self.assertEqual(frappe.db.count("Audit Session", {"client_uuid": self.session_uuid}), 1)

	def test_same_key_twenty_times_one_row(self):
		self.login("hyg-api-r11c@example.com", "TC R11")
		key, stamp = str(uuid.uuid4()), now_ts()
		payload = opp()
		first = self.record(payload, key, client_ts=stamp)
		for _ in range(20):
			again = self.record(payload, key, replay=True, client_ts=stamp)
			self.assertEqual(again["name"], first["name"])
		self.assertEqual(len(self.rows()), 1)

	def test_same_opportunity_uuid_with_new_key_is_not_added_twice(self):
		self.login("hyg-api-r11d@example.com", "TC R11")
		payload = opp()
		self.record(payload)
		again = self.record(payload)  # khóa idempotent đã hết hạn nhưng cơ hội cùng UUID
		self.assertEqual(again["opportunities"], 1)
		self.assertEqual(len(self.rows()), 1)

	@bru("BRU-AUD-004")
	def test_observing_yourself_is_rejected_inline_and_nothing_is_saved(self):
		observer = self.login("hyg-api-r11e@example.com", "TC R11")
		res = self.record(opp(subject_employee=observer))
		self.assertIs(res["ok"], False)
		self.assertEqual(res["error"]["code"], "AUDIT_SELF_OBSERVATION")
		self.assertEqual(res["error"]["http_status"], 422)
		self.assertEqual(frappe.db.count("Audit Session", {"client_uuid": self.session_uuid}), 0)

	def test_moment_outside_the_template_is_rejected(self):
		self.login("hyg-api-r11f@example.com", "TC R11")
		res = self.record(opp(moment="9"))
		self.assertEqual((res["ok"], res["error"]["code"]), (False, "AUDIT_OPPORTUNITY_INVALID"))

	def test_missing_session_uuid_is_rejected(self):
		self.login("hyg-api-r11g@example.com", "TC R11")
		res = self.record(session_uuid="")
		self.assertEqual((res["ok"], res["error"]["code"]), (False, "AUDIT_OPPORTUNITY_INVALID"))

	def test_r12_cannot_record_in_another_department(self):
		self.login("hyg-api-r12a@example.com", "TC R12", self.dept_a)
		with self.assertRaises(frappe.PermissionError):
			self.record(department=self.dept_b)

	def test_r12_records_in_own_department(self):
		self.login("hyg-api-r12b@example.com", "TC R12", self.dept_a)
		self.assertTrue(self.record()["ok"])

	def test_a_scored_template_does_not_take_opportunities(self):
		self.login("hyg-api-r11h@example.com", "TC R11")
		res = self.record(audit_template=make_template("T-VST-API-PPE").name)
		self.assertEqual((res["ok"], res["error"]["code"]), (False, "AUDIT_OPPORTUNITY_INVALID"))

	def test_station_without_audit_function_rejected(self):
		self.login("hyg-api-r11i@example.com", "TC R11")
		frappe.db.set_value(
			"Zone Station Function",
			{"parent": self.station, "station_function": "AUDIT"},
			"station_function",
			"USE",
		)
		res = self.record()
		self.assertEqual((res["ok"], res["error"]["code"]), (False, "STATION_WRONG_STEP"))


class TestOfflineHygieneSession(HygieneApiCase):
	"""FR-M12-04.1, NFR-AVAIL-05: ghi 20 cơ hội lúc offline rồi đồng bộ đủ 20, không trùng."""

	def test_twenty_opportunities_then_post_syncs_without_duplicates(self):
		self.login("hyg-api-r11j@example.com", "TC R11")
		queue = [
			(str(uuid.uuid4()), opp(moment=str(n % 5 + 1), action="Hand Rub" if n % 4 else "Missed"))
			for n in range(20)
		]
		for key, payload in queue:
			self.record(payload, key, replay=True)
		for key, payload in queue:  # đồng bộ lần hai (mạng chập chờn): cùng khóa, không thêm dòng
			self.record(payload, key, replay=True)
		self.assertEqual(len(self.rows()), 20)
		post = self.finish()
		self.assertTrue(post["ok"], post)
		self.assertEqual(post["score_pct"], 75.0)
		doc = frappe.get_doc("Audit Session", post["name"])
		self.assertEqual((doc.docstatus, len(doc.opportunities)), (1, 20))
		again = self.finish()
		self.assertEqual(again["name"], post["name"])
		self.assertEqual(frappe.db.count("Audit Session", {"client_uuid": self.session_uuid}), 1)

	def test_opportunity_after_posting_is_rejected(self):
		self.login("hyg-api-r11k@example.com", "TC R11")
		self.record()
		self.assertTrue(self.finish()["ok"])
		late = self.record()
		self.assertEqual((late["ok"], late["error"]["code"]), (False, "AUDIT_SESSION_POSTED"))
		self.assertEqual(late["error"]["http_status"], 409)

	def test_post_without_any_opportunity_is_rejected(self):
		self.login("hyg-api-r11l@example.com", "TC R11")
		res = self.finish()
		self.assertEqual((res["ok"], res["error"]["code"]), (False, "AUDIT_NO_OPPORTUNITY"))
		self.assertEqual(frappe.db.count("Audit Session", {"client_uuid": self.session_uuid}), 0)

	def test_other_users_cannot_post_my_draft(self):
		self.login("hyg-api-r11m@example.com", "TC R11")
		self.record()
		self.login("hyg-api-r11n@example.com", "TC R11")
		res = self.finish()
		self.assertEqual((res["ok"], res["error"]["code"]), (False, "AUDIT_NOT_ALLOWED"))

	def test_session_started_before_a_new_template_version_still_posts(self):
		"""UC-44 E3: phiếu offline giữ phiên bản tại lúc tạo dù mẫu đã lên V2 giữa chừng."""
		from tracecore.compliance_audit import templates

		user = "hyg-api-r11o@example.com"
		self.login(user, "TC R11")
		self.record(replay=True)
		frappe.set_user("Administrator")
		new = templates.new_version(self.vst.name)
		new.effective_from = today()
		new.save()
		new.submit()
		frappe.set_user(user)
		post = self.finish()
		self.assertTrue(post["ok"], post)
		self.assertEqual(frappe.db.get_value("Audit Session", post["name"], "audit_template"), self.vst.name)


class TestHygieneContext(HygieneApiCase):
	def test_context_lists_opportunity_templates_with_moments_from_items(self):
		self.login("hyg-api-r11q@example.com", "TC R11")
		res = call(audit_api.context, station=self.station)
		codes = {row["template_code"] for row in res["opportunity_templates"]}
		self.assertIn("T-VST-API", codes)
		row = next(row for row in res["opportunity_templates"] if row["template_code"] == "T-VST-API")
		self.assertEqual([m["moment"] for m in row["moments"]], ["1", "2", "3", "4", "5"])
		self.assertEqual(row["moments"][0]["label"], "Moment 1")
		self.assertNotIn(
			"T-VST-API", {t["template_code"] for t in res["templates"]}
		)  # SCR-52 chỉ chấm theo mục

	def test_snapshot_carries_opportunity_templates_for_offline(self):
		from tracecore.v1 import sync as sync_api

		self.login("hyg-api-r11r@example.com", "TC R11")
		res = call(sync_api.snapshot, station=self.station)
		self.assertIn("T-VST-API", {row["template_code"] for row in res["opportunity_templates"]})
