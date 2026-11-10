"""RPC tracecore.v1.hai.* (FEAT-062; FR-M13-02, FR-M13-04, FR-M12-07, NFR-AVAIL-05, NFR-SEC-09; UC-47; A-141 f, g):
phiên thẻ PDA idempotent + phát lại offline, Cổng khoa theo khoa, response chỉ có mã BN che."""

import uuid
from datetime import timedelta

import frappe
from frappe.utils import add_days, getdate, now_datetime, today

from tracecore.hai_surveillance.tests import factories as f
from tracecore.tests.factories import make_employee, make_user
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.v1 import hai as api
from tracecore.v1 import station as station_api

CARD = "MS-R12-CARD"
STATION = "TR-MS-PDA"
TS = "2026-11-10T09:00:00+07:00"
CODE = "BN-API-00004821"


def make_census_station():
	if not frappe.db.exists("Zone Station", STATION):
		zone = frappe.get_doc(
			{"doctype": "Zone Station", "zone_station_name": "MS Ward zone", "is_zone": 1, "zone_type": "Department"}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Zone Station",
				"is_zone": 0,
				"is_active": 1,
				"zone_station_name": "MS Ward PDA",
				"parent_zone": zone.name,
				"functions": [{"station_function": "CENSUS"}],
			}
		).insert(ignore_permissions=True, set_name=STATION)
	return STATION


class HaiApiCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)
		self.ward = f.make_ward("MS Khoa Hồi sức API")
		self.other = f.make_ward("MS Khoa khác API")
		for department in (self.ward, self.other):
			frappe.db.delete("Ward Daily Census", {"department": department})
			frappe.db.delete("Device Episode", {"department": department})
		self.r12 = f.make_dept_user("ms-api-r12@example.com", f.R12, self.ward)
		self.r11 = make_user("ms-api-r11@example.com", [f.R11])
		self.r13 = make_user("ms-api-r13@example.com", [f.R13])
		self.yesterday = str(getdate(add_days(today(), -1)))

	def headers(self, key=None, **extra):
		return request_headers({"X-Idempotency-Key": key or str(uuid.uuid4()), **extra})

	def census_args(self, **values):
		args = {
			"department": self.ward,
			"census_date": self.yesterday,
			"patient_count": 18,
			"vent_count": 9,
			"cvc_count": 11,
			"urinary_catheter_count": 12,
			"admissions": 3,
			"client_ts": TS,
		}
		args.update(values)
		return args


class TestPortal(HaiApiCase):
	def portal(self, fn, key=None, **kwargs):
		frappe.local.response.pop("http_status_code", None)
		with self.headers(key):
			return fn(**kwargs)

	def test_context_scoped_to_own_department(self):
		frappe.set_user(self.r12)
		result = api.portal_context()
		self.assertEqual([row["name"] for row in result["departments"]], [self.ward])
		self.assertEqual(result["department"], self.ward)
		self.assertEqual(result["census_date"], self.yesterday)
		self.assertIsNone(result["census"])
		self.assertTrue(result["missing"])
		with self.assertRaises(frappe.PermissionError):
			api.portal_context(department=self.other)

	def test_r11_sees_every_inpatient_ward(self):
		frappe.set_user(self.r11)
		names = [row["name"] for row in api.portal_context()["departments"]]
		self.assertIn(self.ward, names)
		self.assertIn(self.other, names)

	def test_r13_has_no_access(self):
		frappe.set_user(self.r13)
		with self.assertRaises(frappe.PermissionError):
			api.portal_context()

	def test_census_create_then_duplicate_then_edit(self):
		frappe.set_user(self.r12)
		created = self.portal(api.census_upsert_portal, **self.census_args())
		self.assertTrue(created["ok"], created)
		name = created["census"]["name"]
		self.assertEqual(created["census"]["source"], "Manual")
		dup = self.portal(api.census_upsert_portal, **self.census_args(patient_count=20))
		self.assertFalse(dup["ok"])
		self.assertEqual(dup["error"]["code"], "CENSUS_DUPLICATE")
		self.assertEqual(frappe.local.response.get("http_status_code"), 409)
		edited = self.portal(api.census_upsert_portal, **self.census_args(patient_count=20, census=name))
		self.assertEqual(edited["census"]["patient_count"], 20)

	def test_count_invalid_names_field(self):
		frappe.set_user(self.r12)
		result = self.portal(api.census_upsert_portal, **self.census_args(urinary_catheter_count=21))
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "CENSUS_COUNT_INVALID")
		self.assertEqual(result["error"]["items"], ["urinary_catheter_count"])

	def test_other_department_rejected(self):
		frappe.set_user(self.r12)
		result = self.portal(api.census_upsert_portal, **self.census_args(department=self.other))
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "HAI_NOT_ALLOWED")
		self.assertFalse(frappe.db.exists("Ward Daily Census", {"department": self.other}))

	def test_same_key_replays_response(self):
		frappe.set_user(self.r12)
		key = str(uuid.uuid4())
		first = self.portal(api.census_upsert_portal, key=key, **self.census_args())
		second = self.portal(api.census_upsert_portal, key=key, **self.census_args())
		self.assertEqual(first, second)
		self.assertEqual(frappe.db.count("Ward Daily Census", {"department": self.ward}), 1)

	def test_episode_open_close_masked(self):
		frappe.set_user(self.r12)
		opened = self.portal(
			api.device_episode_portal,
			action="open",
			department=self.ward,
			device_type="Ventilator",
			patient_code=CODE,
			birth_year=1960,
			sex="Male",
			inserted_on=str(add_days(today(), -4)),
			client_ts=TS,
		)
		self.assertTrue(opened["ok"], opened)
		self.assertEqual(opened["episode"]["patient_code_masked"], "***4821")
		self.assertNotIn(CODE, frappe.as_json(opened))
		context = api.portal_context()
		self.assertEqual([row["name"] for row in context["episodes"]], [opened["episode"]["name"]])
		self.assertNotIn(CODE, frappe.as_json(context))
		closed = self.portal(
			api.device_episode_portal, action="close", episode=opened["episode"]["name"], removed_on=today(), client_ts=TS
		)
		self.assertEqual((closed["episode"]["status"], closed["episode"]["device_days"]), ("Closed", 5))

	def test_episode_bad_dates(self):
		frappe.set_user(self.r12)
		opened = self.portal(
			api.device_episode_portal,
			action="open",
			department=self.ward,
			device_type="Ventilator",
			patient_code=CODE,
			inserted_on=today(),
			client_ts=TS,
		)
		result = self.portal(
			api.device_episode_portal,
			action="close",
			episode=opened["episode"]["name"],
			removed_on=str(add_days(today(), -1)),
			client_ts=TS,
		)
		self.assertEqual(result["error"]["code"], "DEVICE_EPISODE_DATE_INVALID")

	def test_episode_of_other_department_cannot_be_closed(self):
		episode = f.make_episode(self.other)
		frappe.set_user(self.r12)
		result = self.portal(api.device_episode_portal, action="close", episode=episode.name, removed_on=today(), client_ts=TS)
		self.assertEqual(result["error"]["code"], "HAI_NOT_ALLOWED")

	def test_bundle_status_in_context(self):
		episode = f.make_episode(self.ward)
		f.post_bundle(episode, "Fail")
		frappe.set_user(self.r12)
		row = api.portal_context()["episodes"][0]
		self.assertEqual(row["bundle_result"], "Fail")
		self.assertEqual(row["bundle_template"], f.bundle_template("VAP"))


class TestStation(HaiApiCase):
	def setUp(self):
		super().setUp()
		self.station = make_census_station()
		self.employee = make_employee(
			card=CARD,
			first_name="MS API Network",
			user_id=self.r12,
			department=self.ward,
			company=frappe.db.get_value("Company", {}, "name"),
		).name
		now = now_datetime()
		frappe.get_doc(
			{
				"doctype": "Station Competency",
				"employee": self.employee,
				"station": self.station,
				"valid_from": now - timedelta(hours=1),
				"valid_until": now + timedelta(hours=8),
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
		self.token = station_api.login(CARD, self.station, client_ts=TS)["session"]["token"]

	def call(self, fn, key=None, replay=False, **kwargs):
		frappe.local.response.pop("http_status_code", None)
		kwargs.setdefault("station", self.station)
		kwargs.setdefault("client_ts", TS)
		kwargs.setdefault("token", self.token)
		extra = {"X-TC-Station": self.station}
		if replay:
			extra["X-TC-Replay"] = "1"
		with self.headers(key, **extra):
			return fn(**kwargs)

	def test_context_snapshot(self):
		f.make_census(self.ward, add_days(today(), -2), patients=17)
		result = self.call(api.context)
		self.assertTrue(result["ok"], result)
		self.assertEqual([row["name"] for row in result["departments"]], [self.ward])
		self.assertEqual(result["prefill"]["patient_count"], 17)

	def test_census_upsert_and_offline_replay(self):
		key = str(uuid.uuid4())
		# phát lại offline kiểm phiên thẻ tại `client_ts`: dùng giờ hiện tại (sau lúc đăng nhập)
		ts = now_datetime().strftime("%Y-%m-%dT%H:%M:%S+07:00")
		first = self.call(api.census_upsert, key=key, **self.census_args(client_ts=ts))
		self.assertTrue(first["ok"], first)
		again = self.call(api.census_upsert, key=key, replay=True, **self.census_args(client_ts=ts))
		self.assertEqual(first, again)
		self.assertEqual(frappe.db.count("Ward Daily Census", {"department": self.ward}), 1)

	def test_device_episode_open(self):
		result = self.call(
			api.device_episode,
			action="open",
			department=self.ward,
			device_type="Central Line",
			patient_code=CODE,
			inserted_on=today(),
		)
		self.assertTrue(result["ok"], result)
		self.assertEqual(result["episode"]["device_type"], "Central Line")
		self.assertNotIn(CODE, frappe.as_json(result))

	def test_unknown_action(self):
		result = self.call(api.device_episode, action="delete", episode="x")
		self.assertFalse(result["ok"])
