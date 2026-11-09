"""RPC trạm/PDA tracecore.v1.audit.* (FEAT-060 AC-7, AC-8, AC-14 phần server; FR-M12-04, FR-M12-10, NFR-AVAIL-05)."""

import json
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import add_days, today

from tracecore.compliance_audit.tests.factories import answers, make_dept_user, make_template
from tracecore.tests.factories import make_department, make_employee, make_user
from tracecore.tests.utils import IsolatedTestCase, bru, request_headers
from tracecore.v1 import audit as audit_api
from tracecore.v1.tests.station_fixtures import make_station_session

TIME_ZONE = ZoneInfo("Asia/Ho_Chi_Minh")
ALL_PASS = dict.fromkeys(("PNC-01", "PNC-02", "PNC-03", "PNC-04", "PNC-05"), "Pass")
TOKENS = {}


def now_ts(**delta):
	return (datetime.now(TIME_ZONE) + timedelta(**delta)).isoformat(timespec="seconds")


def call(fn, key=None, replay=False, **kwargs):
	frappe.local.response.pop("http_status_code", None)
	kwargs.setdefault("client_ts", now_ts())
	kwargs.setdefault("token", TOKENS.get(frappe.session.user))
	headers = {"X-Idempotency-Key": key or str(uuid.uuid4()), "X-TC-Station": kwargs.get("station")}
	if replay:
		headers["X-TC-Replay"] = "1"
	with request_headers(headers):
		return fn(**kwargs)


class AuditApiCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		TOKENS.clear()
		self.addCleanup(TOKENS.clear)
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)
		self.dept_a = make_department("Audit API Ward A")
		self.dept_b = make_department("Audit API Ward B")
		self.template = make_template("T-API", effective_from=add_days(today(), -1))  # phát lại 4 giờ trước
		make_template("T-API-D", submit=False)
		self.station = (
			frappe.get_doc(
				{
					"doctype": "Zone Station",
					"zone_station_name": "Audit PDA test",
					"parent_zone": "ZONE-DEPT",
					"is_active": 1,
					"functions": [{"station_function": "AUDIT"}],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		self.subject = make_employee(first_name="Observed Nurse").name

	def login(self, email, role, department=None):
		frappe.set_user("Administrator")
		user = make_dept_user(email, role, department) if department else make_user(email, [role])
		employee = make_employee(first_name="Auditor " + email, department=department)
		frappe.db.set_value("Employee", employee.name, "user_id", user)
		TOKENS[user] = make_station_session(user, self.station)["token"]
		frappe.set_user(user)
		return employee.name

	def submit_args(self, **values):
		return {
			"station": self.station,
			"audit_template": self.template.name,
			"department": self.dept_a,
			"answers": json.dumps(answers(**ALL_PASS)),
			"subject_employee": self.subject,
			**values,
		}


class TestAuditPdaApi(AuditApiCase):
	def test_context_lists_approved_scored_templates_and_departments(self):
		observer = self.login("aud-api-r11@example.com", "TC R11")
		res = call(audit_api.context, station=self.station)
		self.assertTrue(res["ok"])
		codes = {row["template_code"] for row in res["templates"]}
		self.assertIn("T-API", codes)
		self.assertNotIn("T-API-D", codes)
		tpl = next(row for row in res["templates"] if row["template_code"] == "T-API")
		self.assertEqual(tpl["name"], self.template.name)
		self.assertEqual([item["item_code"] for item in tpl["items"]][:2], ["PNC-01", "PNC-02"])
		self.assertTrue({self.dept_a, self.dept_b} <= {row["name"] for row in res["departments"]})
		self.assertEqual(res["observer"], observer)

	def test_r12_context_has_only_own_department(self):
		self.login("aud-api-r12@example.com", "TC R12", self.dept_a)
		res = call(audit_api.context, station=self.station)
		self.assertEqual([row["name"] for row in res["departments"]], [self.dept_a])

	def test_submit_session_posts_with_score(self):
		observer = self.login("aud-api-r11b@example.com", "TC R11")
		res = call(audit_api.submit_session, **self.submit_args())
		self.assertTrue(res["ok"], res)
		doc = frappe.get_doc("Audit Session", res["name"])
		self.assertEqual((doc.docstatus, doc.observer, doc.result, doc.score_pct), (1, observer, "Pass", 100))
		self.assertEqual(res["result"], "Pass")

	@bru("BRU-AUD-004")
	def test_self_observation_rejected_inline(self):
		observer = self.login("aud-api-r11c@example.com", "TC R11")
		res = call(audit_api.submit_session, **self.submit_args(subject_employee=observer))
		self.assertIs(res["ok"], False)
		self.assertEqual(res["error"]["code"], "AUDIT_SELF_OBSERVATION")
		self.assertEqual(res["error"]["http_status"], 422)
		self.assertEqual(frappe.db.count("Audit Session", {"observer": observer}), 0)

	def test_r12_cannot_audit_other_department(self):
		self.login("aud-api-r12b@example.com", "TC R12", self.dept_a)
		with self.assertRaises(frappe.PermissionError):
			call(audit_api.submit_session, **self.submit_args(department=self.dept_b))

	def test_station_without_audit_function_rejected(self):
		self.login("aud-api-r11d@example.com", "TC R11")
		frappe.db.set_value(
			"Zone Station Function", {"parent": self.station, "station_function": "AUDIT"}, "station_function", "USE"
		)
		res = call(audit_api.submit_session, **self.submit_args())
		self.assertIs(res["ok"], False)
		self.assertEqual(res["error"]["code"], "STATION_WRONG_STEP")


class TestAuditOfflineReplay(AuditApiCase):
	"""FR-M12-04.1, NFR-AVAIL-05: phát lại hàng đợi offline không tạo bản ghi trùng."""

	def test_same_key_twenty_times_one_session(self):
		self.login("aud-api-r11e@example.com", "TC R11")
		key, stamp = str(uuid.uuid4()), now_ts()
		session_uuid = str(uuid.uuid4())
		args = self.submit_args(session_uuid=session_uuid)
		first = call(audit_api.submit_session, key, client_ts=stamp, **args)
		for _ in range(20):
			again = call(audit_api.submit_session, key, replay=True, client_ts=stamp, **args)
			self.assertEqual(again["name"], first["name"])
		self.assertEqual(frappe.db.count("Audit Session", {"client_uuid": session_uuid}), 1)

	def test_same_session_uuid_new_key_returns_existing(self):
		self.login("aud-api-r11f@example.com", "TC R11")
		session_uuid = str(uuid.uuid4())
		first = call(audit_api.submit_session, **self.submit_args(session_uuid=session_uuid))
		second = call(audit_api.submit_session, **self.submit_args(session_uuid=session_uuid))
		self.assertEqual(first["name"], second["name"])

	def test_replay_four_hours_later_keeps_audit_day(self):
		user = "aud-api-r11g@example.com"
		self.login(user, "TC R11")
		# phiên thẻ mở từ trước khi mất mạng (đăng nhập 5 giờ trước, hạn 8 giờ)
		frappe.db.set_value(
			"Station Session",
			{"user": user, "is_open": 1},
			{"started_at": frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-5)},
		)
		stamp = now_ts(hours=-4)
		res = call(audit_api.submit_session, replay=True, client_ts=stamp, **self.submit_args())
		self.assertTrue(res["ok"], res)
		self.assertEqual(str(frappe.db.get_value("Audit Session", res["name"], "audit_date")), stamp[:10])
