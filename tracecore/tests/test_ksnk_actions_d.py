"""Thao tác trên bản ghi ở SCR-54, 62, 64, 65 (A-131): khối hiển thị một bản ghi luôn đủ thao tác hợp lệ theo trạng thái
và quyền (xem/sửa/hủy-sửa đổi form, In, Tạo mới), không bao giờ chỉ còn chữ; R13 chỉ xem form/In."""

import json
import uuid

import frappe

from tracecore.compliance_audit import chemicals
from tracecore.compliance_audit.tests import chemical_factories as cf
from tracecore.occupational_safety import dashboard as exposure_dashboard
from tracecore.tests.factories import make_department, make_user
from tracecore.tests.js_harness import run_js
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.v1 import environment, food_safety, ic_chemical

SHELL = "public/js/ksnk/ksnk_shell.js"
SCR54 = "public/js/ksnk/scr_54_hoa_chat.js"
SCR62 = "public/js/ksnk/scr_62_moi_truong.js"
SCR64 = "public/js/ksnk/scr_64_phoi_nhiem.js"
SCR65 = "public/js/ksnk/scr_65_attp.js"
TS = "2026-11-10T10:00:00+07:00"
ALL = {"write": True, "create": True}
READ_ONLY = {"write": False, "create": False}


class TestScr54Actions(IsolatedTestCase):
	def run54(self, script):
		return run_js(self, [SHELL, SCR54], [["TcKsnk"], ["TcKsnkScr54"]], script)

	def test_saved_manual_entry_keeps_form_cancel_amend_and_print(self):
		out = self.run54(
			"""
			const s = TcKsnkScr54;
			emit({
				writer: s.chemicalActions({name: "HC-2026-00001", docstatus: 1, can_write: true}),
				reader: s.chemicalActions({name: "HC-2026-00001", docstatus: 1, can_write: false}),
				batch: s.batchActions("IB-0001"),
				message: s.savedHtml("Saved", s.chemicalActions({name: "HC-2026-00001", docstatus: 1, can_write: true}), TcKsnk.esc),
			});
			"""
		)
		self.assertIn("/app/ic-chemical-consumption/HC-2026-00001", out["writer"])
		self.assertIn("Open form to cancel or amend", out["writer"])
		self.assertIn("/printview?doctype=IC%20Chemical%20Consumption", out["writer"])
		self.assertIn("View form", out["reader"])
		self.assertNotIn("cancel or amend", out["reader"])
		self.assertIn("/app/import-batch/IB-0001", out["batch"])
		self.assertIn('role="status"', out["message"])
		self.assertIn("/app/ic-chemical-consumption/HC-2026-00001", out["message"])


class TestScr62Actions(IsolatedTestCase):
	def run62(self, script):
		return run_js(self, [SHELL, SCR62], [["TcKsnk"], ["TcKsnkScr62"]], script)

	def test_sample_rows_and_pending_nc_have_form_and_print(self):
		out = self.run62(
			"""
			const s = TcKsnkScr62;
			const esc = TcKsnk.esc;
			const sample = {name: "XN-2026-00131", environment_zone: "VV-0001", environment_zone_name: "Phòng mổ 3",
				sample_type: "Air", result_value: 12, unit: "CFU", limit_applied: "<= 10", result: "Fail",
				sampled_on: "2026-10-20"};
			const base = {month: "2026-10", samples: [sample], pending_nc: [sample]};
			const writer = {...base, can_decide: true, perms: {"Environmental Sample": {write: true, create: true},
				"Environmental Limit": {write: true, create: true}}};
			const reader = {...base, can_decide: false, perms: {"Environmental Sample": {write: false, create: false}}};
			emit({
				rowWriter: s.samplesHtml(writer, esc),
				rowReader: s.samplesHtml(reader, esc),
				pendingWriter: s.pendingHtml(writer, esc),
				pendingReader: s.pendingHtml(reader, esc),
				limitsWriter: s.limitsHtml(writer, esc),
				limitsReader: s.limitsHtml(reader, esc),
			});
			"""
		)
		self.assertIn("Open form to cancel or amend", out["rowWriter"])
		self.assertIn("/printview?doctype=Environmental%20Sample&amp;name=XN-2026-00131", out["rowWriter"])
		self.assertIn("View form", out["rowReader"])
		self.assertNotIn("cancel or amend", out["rowReader"])
		self.assertIn("<th>Action</th>", out["rowWriter"])
		# khối mẫu Không đạt luôn có lối mở form/In, kể cả người không quyết định NC
		for key in ("pendingWriter", "pendingReader"):
			self.assertIn("/app/environmental-sample/XN-2026-00131", out[key])
			self.assertIn("/printview?doctype=Environmental%20Sample", out[key])
		self.assertIn("/app/environmental-limit/new", out["limitsWriter"])
		self.assertNotIn("/app/environmental-limit/new", out["limitsReader"])


class TestScr64Actions(IsolatedTestCase):
	def run64(self, script):
		return run_js(self, [SHELL, SCR64], [["TcKsnk"], ["TcKsnkScr64"]], script)

	def test_exposure_detail_and_vaccination_rows_have_form_actions(self):
		out = self.run64(
			"""
			const s = TcKsnkScr64;
			const esc = TcKsnk.esc;
			const detail = (can_write) => ({name: "PN-2026-00001", status: "New", exposure_type: "Needlestick or Sharps",
				employee_name: "A", followups: [], has_template: true, can_write});
			const rows = [{name: "TC-2026-00001", employee_name: "B", department: "ICU", vaccine: "Hepatitis B",
				dose_no: 1, doses_required: 3, next_due: "2026-12-01", days_left: 20, state: "Due Soon"}];
			const writer = {perms: {"Occupational Exposure": {write: true, create: true},
				"Staff Immunization": {write: true, create: true}}};
			const reader = {perms: {"Staff Immunization": {write: false, create: false}}};
			emit({
				detailWriter: s.detailHtml(detail(true), esc),
				detailReader: s.detailHtml(detail(false), esc),
				immWriter: s.immunizationHtml(rows, esc, writer),
				immReader: s.immunizationHtml(rows, esc, reader),
				createExposure: s.createActions(writer, "Occupational Exposure", "Record exposure"),
				createReader: s.createActions(reader, "Occupational Exposure", "Record exposure"),
			});
			"""
		)
		self.assertIn("/app/occupational-exposure/PN-2026-00001", out["detailWriter"])
		self.assertIn("Open form", out["detailWriter"])
		self.assertIn("View form", out["detailReader"])
		self.assertIn("/app/staff-immunization/TC-2026-00001", out["immWriter"])
		self.assertIn("/app/staff-immunization/new", out["immWriter"])
		self.assertIn("/app/staff-immunization/TC-2026-00001", out["immReader"])
		self.assertIn("View form", out["immReader"])
		self.assertNotIn("/app/staff-immunization/new", out["immReader"])
		self.assertIn("/app/occupational-exposure/new", out["createExposure"])
		self.assertEqual(out["createReader"], "")


class TestScr65Actions(IsolatedTestCase):
	def run65(self, script):
		return run_js(self, [SHELL, SCR65], [["TcKsnk"], ["TcKsnkScr65"]], script)

	def test_every_single_record_block_keeps_actions(self):
		out = self.run65(
			"""
			const s = TcKsnkScr65;
			const esc = TcKsnk.esc;
			const perms = {
				"Foodborne Event": {write: true, create: true},
				"Food Handler Health Check": {write: true, create: true},
				"IC Education Session": {write: true, create: true},
				"Environmental Sample": {write: true, create: true},
				"IC Procedure Document": {write: true, create: true},
			};
			const data = {
				can_decide: false, can_publish: false, outbreak_ready: false, perms,
				pending_events: [{name: "NDTP-2026-002", event_date: "2026-11-02", location: "Căng tin",
					affected_count: 4, nc_status: "Suggested", outbreak_status: "Suggested", threshold_applied: 3}],
				handlers: [{name: "SKTP-2026-00001", full_name: "NV 1", unit: "Bếp", checked_on: "2026-01-01",
					next_due: "2027-01-01", state: "Valid", fit_for_work: "Fit"}],
				sessions: [{name: "GDS-2026-00001", session_date: "2026-11-01", department: "A", title: "T",
					audience: "Patient Families", attendee_count: 5}],
				food_samples: [{name: "XN-2026-00200", sampled_on: "2026-11-01", result: "Pass"}],
				materials: [{name: "TLTT-1", doc_code: "TT-01", title: "Rửa tay", version_no: 1, status: "Draft", qr: "x"}],
				quarter: {label: "Q4"},
			};
			const reader = {...data, perms: {}};
			emit({
				events: s.eventsHtml(data, esc),
				handlers: s.handlersHtml(data, esc),
				sessions: s.sessionsHtml(data, esc),
				food: s.foodHtml(data, esc),
				materials: s.materialsHtml(data, esc),
				readerEvents: s.eventsHtml(reader, esc),
				readerSessions: s.sessionsHtml(reader, esc),
				create: s.createActions(data, "Foodborne Event", "Record food poisoning event"),
				createReader: s.createActions(reader, "Foodborne Event", "Record food poisoning event"),
			});
			"""
		)
		self.assertIn("/app/foodborne-event/NDTP-2026-002", out["events"])
		self.assertIn("Open form to cancel or amend", out["events"])
		self.assertIn("/app/food-handler-health-check/SKTP-2026-00001", out["handlers"])
		self.assertIn("/app/ic-education-session/GDS-2026-00001", out["sessions"])
		self.assertIn("/app/environmental-sample/XN-2026-00200", out["food"])
		self.assertIn("/app/ic-procedure-document/TLTT-1", out["materials"])
		self.assertIn("/app/foodborne-event/NDTP-2026-002", out["readerEvents"])
		self.assertIn("View form", out["readerEvents"])
		self.assertIn("/app/ic-education-session/GDS-2026-00001", out["readerSessions"])
		self.assertIn("/app/foodborne-event/new", out["create"])
		self.assertEqual(out["createReader"], "")


class TestActionPermissionFlags(IsolatedTestCase):
	"""RPC trả cờ quyền (frappe.has_permission) để màn quyết định hiện nút; quyền thật vẫn kiểm ở DocPerm."""

	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")

	def assert_perm_flags(self, perms, doctypes):
		for doctype in doctypes:
			self.assertEqual(set(perms[doctype]), {"write", "create"}, doctype)
			self.assertTrue(perms[doctype]["write"] and perms[doctype]["create"], doctype)

	def test_environment_overview_returns_perms(self):
		data = environment.overview()
		self.assert_perm_flags(
			data["perms"], ["Environmental Sample", "Environment Zone", "Sampling Plan", "Environmental Limit"]
		)

	def test_food_safety_overview_returns_perms(self):
		data = food_safety.overview()
		self.assert_perm_flags(
			data["perms"],
			[
				"Foodborne Event",
				"Food Handler Health Check",
				"IC Education Session",
				"Environmental Sample",
				"IC Procedure Document",
			],
		)

	def test_exposure_dashboard_returns_perms(self):
		data = exposure_dashboard.build()
		self.assert_perm_flags(data["perms"], ["Occupational Exposure", "Staff Immunization"])

	def test_manual_entry_returns_record_flags(self):
		department = make_department("KSNK Test Khoa thao tác hóa chất")
		item = cf.make_chemical("TC-HC-ACT", "Hand Rub")
		r09 = make_user("ic-chem-actions-r09@example.com", ["TC R09"])
		frappe.set_user(r09)
		values = json.dumps(
			{
				"period": frappe.utils.today()[:7],
				"department": department,
				"item": item,
				"qty": 2,
				"source_note": "Sổ khoa",
			}
		)
		with request_headers({"X-Idempotency-Key": str(uuid.uuid4())}):
			saved = ic_chemical.manual_entry(values=values, confirm=1, client_ts=TS)
		self.assertTrue(saved["ok"])
		self.assertEqual(saved["docstatus"], 1)
		self.assertTrue(saved["can_write"])
		self.assertEqual(frappe.db.get_value(chemicals.DOCTYPE, saved["name"], "docstatus"), 1)
