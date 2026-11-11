"""Thao tác trên bản ghi ở SCR-53, 56, 57, 58: luôn đủ lối mở form / hủy-sửa đổi / In / Tạo mới theo trạng thái và quyền
(ADR-002: nhập, sửa chi tiết mở form Desk; quyền thật kiểm ở RPC / DocPerm)."""

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.tests.js_harness import run_js

SHELL = "public/js/ksnk/ksnk_shell.js"
SCR53 = "public/js/ksnk/scr_53_tuan_thu.js"
SCR56 = "public/js/ksnk/scr_56_ca_nkbv.js"
SCR57 = "public/js/ksnk/scr_57_nkvm.js"
SCR58 = "public/js/ksnk/scr_58_bao_cao_nkbv.js"

DATA = """
const esc = TcKsnk.esc;
const sess = {name: "PGS-2031-00001", department: "ICU", template_title: "VST", score_pct: 90, result: "Pass"};
const board = (extra) => Object.assign({recent: [sess], pending: [], can_decide: false, can_write: true,
	can_create: true}, extra || {});
const hcase = {name: "CA-2031-00001", docstatus: 1, status: "Confirmed", patient_code_masked: "***4821", reporting_period: "2031-10",
	isolates: [], time_check: "Not applicable", period_locked: false};
const hdata = (extra) => Object.assign({cases: [hcase], periods: [], can_decide: true, can_reveal: false,
	can_write: true, can_create: true}, extra || {});
const surgery = {name: "PT-2031-00001", outcome: "Under Surveillance", followups: [], hai_case: null, window_over: false,
	period_locked: false, patient_code_masked: "***6612"};
"""


class TestActionsBackend(FrappeTestCase):
	def test_screens_return_permission_flags(self):
		from tracecore.v1 import audit, hai_case, ssi

		frappe.set_user("Administrator")
		for payload, doctype in (
			(audit.compliance_board(), "Audit Session"),
			(hai_case.screen(), "HAI Case"),
			(ssi.screen(), "Surgical Surveillance"),
		):
			self.assertEqual(payload["can_write"], bool(frappe.has_permission(doctype, "write")))
			self.assertEqual(payload["can_create"], bool(frappe.has_permission(doctype, "create")))


class TestActionsB(FrappeTestCase):
	def run_it(self, files, names, code):
		return run_js(self, [SHELL, *files], [["TcKsnk"], *names], DATA + code)

	def test_scr53_recent_audits_have_form_print_and_create(self):
		out = self.run_it(
			[SCR53],
			[["TcKsnkScr53"]],
			"""emit({full: TcKsnkScr53.recentHtml(board(), esc),
				ro: TcKsnkScr53.recentHtml(board({can_write: false, can_create: false}), esc),
				empty: TcKsnkScr53.recentHtml(board({recent: []}), esc)});""",
		)
		self.assertIn("Open form to cancel or amend", out["full"])
		self.assertIn("/printview?doctype=Audit%20Session&amp;name=PGS-2031-00001", out["full"])
		self.assertIn("/app/audit-session/new", out["full"])
		self.assertIn("View form", out["ro"])
		self.assertNotIn("/app/audit-session/new", out["ro"])
		self.assertIn("/app/audit-session/new", out["empty"])  # rỗng vẫn có lối Tạo mới

	def test_scr53_pending_nc_keeps_form_link(self):
		out = self.run_it(
			[SCR53],
			[["TcKsnkScr53"]],
			"""const p = {name: "PGS-2031-00002", department: "ICU", failed_items: [{question: "Q"}]};
			emit({html: TcKsnkScr53.pendingHtml(board({pending: [p], can_decide: true}), esc, null)});""",
		)
		self.assertIn('data-action="open-nc"', out["html"])
		self.assertIn("/app/audit-session/PGS-2031-00002", out["html"])

	def test_scr56_detail_form_print_by_docstatus_and_role(self):
		out = self.run_it(
			[SCR56],
			[["TcKsnkScr56"]],
			"""const s = TcKsnkScr56;
			emit({sub: s.detailHtml(hcase, hdata(), esc),
				draft: s.detailHtml(Object.assign({}, hcase, {docstatus: 0, status: "Suspected"}), hdata(), esc),
				cancelled: s.detailHtml(Object.assign({}, hcase, {docstatus: 2}), hdata(), esc),
				ro: s.detailHtml(hcase, hdata({can_write: false, can_create: false, can_decide: false}), esc),
				list: s.listHtml([hcase], esc, null, hdata()),
				listRo: s.listHtml([hcase], esc, null, hdata({can_create: false}))});""",
		)
		self.assertIn("Open form to cancel or amend", out["sub"])
		self.assertIn("/printview?doctype=HAI%20Case", out["sub"])
		self.assertIn(">Open form<", out["draft"])
		self.assertIn("Open form to amend", out["cancelled"])
		self.assertNotIn("/printview", out["cancelled"])
		self.assertIn("View form", out["ro"])
		self.assertIn("/app/hai-case/new", out["list"])
		self.assertNotIn("/app/hai-case/new", out["listRo"])

	def test_scr57_selected_surgery_has_form_and_print(self):
		out = self.run_it(
			[SCR57],
			[["TcKsnkScr57"]],
			"""const s = TcKsnkScr57;
			emit({sel: s.actionsHtml(surgery, esc, {can_write: true}),
				ro: s.actionsHtml(surgery, esc, {can_write: false}),
				none: s.actionsHtml(null, esc, {can_write: true}),
				linked: s.followupsHtml(Object.assign({}, surgery, {hai_case: "CA-2031-00001",
					case_status: {status: "Confirmed", docstatus: 1}}), {definitions: []}, esc)});""",
		)
		self.assertIn("/app/surgical-surveillance/PT-2031-00001", out["sel"])
		self.assertIn("/printview?doctype=Surgical%20Surveillance", out["sel"])
		self.assertIn("View form", out["ro"])
		self.assertNotIn("/app/surgical-surveillance/", out["none"])
		self.assertIn('data-action="save"', out["none"])
		self.assertIn("/app/hai-case/CA-2031-00001", out["linked"])

	def test_scr58_cluster_alert_has_form_for_every_role(self):
		out = self.run_it(
			[SCR58],
			[["TcKsnkClusterBanner"]],
			"""const b = {configured: true, can_review: true, open_link: "/app/tc-ksnk/o-dich",
				alerts: [{name: "CCA-1", department_name: "HSTC", case_count: 3, key_label: "VAP", window_days: 14,
				min_cases: 3, window_start: "2031-10-21", window_end: "2031-11-03"}]};
			emit({r01: TcKsnkClusterBanner.html(b, esc),
				r13: TcKsnkClusterBanner.html(Object.assign({}, b, {can_review: false}), esc)});""",
		)
		self.assertIn("/app/cluster-alert/CCA-1", out["r01"])
		self.assertIn("Mark as reviewed", out["r01"])
		self.assertIn("View form", out["r13"])
		self.assertNotIn("Mark as reviewed", out["r13"])
