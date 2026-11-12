"""RPC tracecore.v1.wastewater.* cho SCR-67 Nước thải y tế (FEAT-095; FR-M15-08..13; UC-58; AC-095-02, 11, 14;
A-153 W7)."""

import uuid

import frappe

from tracecore.environmental_hygiene.tests import factories as ef
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.v1 import wastewater as api

FULL = {"pH": 7.1, "COD": 48, "Coliforms": 3000, "Salmonella": "KPH"}


class TestWastewaterApi(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.db.delete("Wastewater Point")
		self.point = ef.make_point().name
		self.permit = ef.make_permit("T-API", rows=ef.rows_for(self.point), valid_until="2027-01-31")
		self.failed = ef.make_monitoring(self.point, {**FULL, "Coliforms": 9300}, sampled_on="2026-09-22")
		ef.make_lab("T Công ty Phân tích B", "VIMCERTS 087", "2026-10-01")
		self.r01 = make_user("ww-api-r01@example.com", ["TC R01"])
		self.r11 = make_user("ww-api-r11@example.com", ["TC R11"])
		self.r13 = make_user("ww-api-r13@example.com", ["TC R13"])
		self.r08 = make_user("ww-api-r08@example.com", ["TC R08"])
		self.r02 = make_user("ww-api-r02@example.com", ["TC R02"])
		frappe.db.set_single_value("IC Program Settings", "ic_department", ef.make_department("T Khoa KSNK"))

	def call(self, fn, **kwargs):
		with request_headers({"X-Idempotency-Key": str(uuid.uuid4())}):
			return fn(client_ts="2026-11-12T09:00:00+07:00", **kwargs)

	def test_overview_for_r11_has_permit_schedule_latest_alerts_and_labs(self):
		frappe.set_user(self.r11)
		data = api.overview(year="2026", on="2026-11-02")
		self.assertFalse(data["summary_only"])
		self.assertEqual(data["permits"][0]["name"], self.permit.name)
		self.assertEqual(data["permits"][0]["days_to_expiry"], 90)
		self.assertTrue(data["permits"][0]["expiring"])
		self.assertEqual(data["schedule"][0]["point"], self.point)
		self.assertEqual(data["latest"][0]["name"], self.failed.name)
		self.assertIn("Coliforms", [row["parameter"] for row in data["latest"][0]["results"]])
		self.assertIn(self.point, [row["point"] for row in data["flagged"]])
		self.assertIn("VIMCERTS 087", [row["vimcerts_no"] for row in data["labs"] if row["expired"]])
		self.assertFalse(data["can_decide"])
		self.assertTrue(data["perms"]["Wastewater Monitoring"]["create"])
		self.assertFalse(data["perms"]["Wastewater Permit"]["create"])
		self.assertEqual(api.schedule(year="2026", on="2026-11-02")[0]["point"], self.point)

	def test_r13_gets_summary_only_and_r08_is_rejected(self):
		"""AC-095-14."""
		frappe.set_user(self.r13)
		data = api.overview(year="2026", on="2026-11-02")
		self.assertTrue(data["summary_only"])
		self.assertNotIn("latest", data)
		self.assertEqual(data["kpis"]["flagged"], 1)
		frappe.set_user(self.r08)
		with self.assertRaises(frappe.PermissionError):
			api.overview()

	def test_r02_reads_but_cannot_create_a_round(self):
		frappe.set_user(self.r02)
		self.assertFalse(api.overview(year="2026")["perms"]["Wastewater Monitoring"]["create"])
		doc = frappe.new_doc("Wastewater Monitoring")
		doc.update({"wastewater_point": self.point, "sampled_on": "2026-10-20", "supplier": ef.make_lab()})
		with self.assertRaises(frappe.PermissionError):
			doc.insert()

	def test_parameters_and_template_for_the_form(self):
		frappe.set_user(self.r11)
		rows = api.parameters(point=self.point, sampled_on="2026-10-20")
		self.assertEqual(rows["permit"], self.permit.name)
		self.assertEqual(rows["results"][0]["parameter"], "pH")
		self.assertTrue(api.template(standard="QCVN 28:2010/BTNMT", column="B", point=self.point))

	def test_only_r01_opens_or_dismisses_nc_through_rpc(self):
		"""AC-095-11."""
		frappe.set_user(self.r11)
		with self.assertRaises(frappe.PermissionError):
			self.call(api.open_nc, monitoring=self.failed.name)
		frappe.set_user(self.r01)
		blocked = self.call(api.dismiss_nc, monitoring=self.failed.name, reason="")
		self.assertEqual((blocked["ok"], blocked["error"]["code"]), (False, "REASON_REQUIRED"))
		result = self.call(api.open_nc, monitoring=self.failed.name)
		self.assertTrue(result["ok"])
		self.assertEqual(
			frappe.db.get_value("Incident CAPA", result["incident"], "source_name"), self.failed.name
		)

	def test_new_permit_version_is_r01_only(self):
		frappe.set_user(self.r11)
		with self.assertRaises(frappe.PermissionError):
			self.call(api.new_permit_version, permit=self.permit.name)
		frappe.set_user(self.r01)
		result = self.call(api.new_permit_version, permit=self.permit.name)
		self.assertEqual((result["ok"], result["name"]), (True, "GPMT-T-API-V2"))
