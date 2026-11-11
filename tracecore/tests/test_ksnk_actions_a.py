"""Thao tác trên bản ghi của SCR-47..50: luôn có lối mở form / tạo mới / In theo trạng thái và quyền (ADR-002;
`TcKsnk.recordActions`). Quyền thật vẫn kiểm ở RPC / DocPerm."""

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.tests.js_harness import run_js

SHELL = "public/js/ksnk/ksnk_shell.js"
SCR47 = "public/js/ksnk/scr_47_co_cau.js"
SCR48 = "public/js/ksnk/scr_48_ke_hoach.js"
SCR49 = "public/js/ksnk/scr_49_dao_tao.js"
SCR50 = "public/js/ksnk/scr_50_mau_phieu.js"


class TestScr47Actions(FrappeTestCase):
	def _run(self, code):
		return run_js(self, [SHELL, SCR47], [["TcKsnk"], ["TcKsnkScr47"]], code)

	def test_network_block_has_list_link_and_gated_create(self):
		out = self._run(
			"""
			const esc = TcKsnk.esc;
			const base = {departments: []};
			emit({
				can: TcKsnkScr47.networkHtml(Object.assign({}, base, {can_create_member: true}), esc),
				ro: TcKsnkScr47.networkHtml(Object.assign({}, base, {can_create_member: false}), esc),
			});
			"""
		)
		self.assertIn('href="/app/ic-network-member"', out["can"])
		self.assertIn("/app/ic-network-member/new", out["can"])
		self.assertIn('href="/app/ic-network-member"', out["ro"])
		self.assertNotIn("/app/ic-network-member/new", out["ro"])


class TestScr48Actions(FrappeTestCase):
	def _run(self, code):
		return run_js(self, [SHELL, SCR48], [["TcKsnk"], ["TcKsnkScr48"]], code)

	def test_plan_actions_by_state_and_role(self):
		out = self._run(
			"""
			const esc = TcKsnk.esc;
			const mk = (docstatus, extra) => Object.assign({
				plan: {name: "KH-2031-01", docstatus}, can_write_plan: true,
			}, extra || {});
			emit({
				draft: TcKsnkScr48.actionsHtml(mk(0), false, esc),
				posted: TcKsnkScr48.actionsHtml(mk(1), false, esc),
				ro: TcKsnkScr48.actionsHtml(mk(1), true, esc),
				none: TcKsnkScr48.actionsHtml({plan: null, can_create_plan: true}, false, esc),
			});
			"""
		)
		self.assertIn("/app/ic-annual-plan/KH-2031-01", out["draft"])
		self.assertIn("Open form", out["draft"])
		self.assertIn("Open form to cancel or amend", out["posted"])
		self.assertIn("View form", out["ro"])
		self.assertNotIn("Open form", out["ro"])
		self.assertIn("/app/ic-annual-plan/new", out["none"])

	def test_documents_and_meeting_actions(self):
		out = self._run(
			"""
			const esc = TcKsnk.esc;
			const data = {
				documents: [], documents_attention: 0, can_create_document: false,
				meeting: {name: "HOP-2031-01", meeting_date: "2031-10-01", resolutions: []},
				open_resolutions: [], can_write_meeting: true,
			};
			emit({
				docs_ro: TcKsnkScr48.documentsHtml(data, esc),
				docs: TcKsnkScr48.documentsHtml(Object.assign({}, data, {can_create_document: true}), esc),
				meeting: TcKsnkScr48.meetingHtml(data, esc),
				meeting_ro: TcKsnkScr48.meetingHtml(Object.assign({}, data, {can_write_meeting: false}), esc),
			});
			"""
		)
		self.assertNotIn("/app/ic-procedure-document/new", out["docs_ro"])
		self.assertIn("/app/ic-procedure-document/new", out["docs"])
		self.assertIn("/app/ic-committee-meeting/HOP-2031-01", out["meeting"])
		self.assertIn("Open form to cancel or amend", out["meeting"])
		self.assertIn("/printview?doctype=IC%20Committee%20Meeting", out["meeting"])
		self.assertIn("View form", out["meeting_ro"])


class TestScr49Actions(FrappeTestCase):
	def _run(self, code):
		return run_js(self, [SHELL, SCR49], [["TcKsnk"], ["TcKsnkScr49"]], code)

	def test_trainee_add_link_gated(self):
		out = self._run(
			"""
			const esc = TcKsnk.esc;
			const data = {trainees: {rows: []}};
			emit({
				can: TcKsnkScr49.traineesHtml(Object.assign({}, data, {can_create_trainee: true}), esc),
				ro: TcKsnkScr49.traineesHtml(Object.assign({}, data, {can_create_trainee: false}), esc),
			});
			"""
		)
		self.assertIn("/app/trainee-induction/new", out["can"])
		self.assertNotIn("/app/trainee-induction/new", out["ro"])

	def test_self_assessment_session_has_form_and_print(self):
		out = self._run(
			"""
			const esc = TcKsnk.esc;
			const imp = {
				template: null, can_write_session: false,
				self_assessment: {year: 2026, previous_year: 2025, both: false, current: {name: "GS-2026-00001", score_pct: 80},
					previous: null, items: []},
			};
			emit({
				ro: TcKsnkScr49.selfAssessmentHtml(imp, esc),
				rw: TcKsnkScr49.selfAssessmentHtml(Object.assign({}, imp, {can_write_session: true}), esc),
			});
			"""
		)
		self.assertIn("/app/audit-session/GS-2026-00001", out["ro"])
		self.assertIn("View form", out["ro"])
		self.assertIn("Open form to cancel or amend", out["rw"])
		self.assertIn("/printview?doctype=Audit%20Session", out["rw"])


class TestScr50Actions(FrappeTestCase):
	def _run(self, code):
		return run_js(self, [SHELL, SCR50], [["TcKsnk"], ["TcKsnkScr50"]], code)

	def test_template_form_link_for_all_roles(self):
		out = self._run(
			"""
			const esc = TcKsnk.esc;
			const detail = {name: "MP-X-V1", docstatus: 1, can_write: true, version_no: 1, can_revise: true};
			const sched = {can_create: false};
			emit({
				rw: TcKsnkScr50.actionsHtml(detail, {can_create: true}, sched, esc, false),
				ro: TcKsnkScr50.actionsHtml(detail, {can_create: true}, sched, esc, true),
			});
			"""
		)
		self.assertIn("/app/audit-template/MP-X-V1", out["rw"])
		self.assertIn("Open form to cancel or amend", out["rw"])
		self.assertIn("New template", out["rw"])
		self.assertIn("/app/audit-template/MP-X-V1", out["ro"])
		self.assertIn("View form", out["ro"])
		self.assertNotIn("New template", out["ro"])
		self.assertNotIn("data-action", out["ro"])


class TestActionFlagsRpc(FrappeTestCase):
	"""Cờ quyền trả về từ RPC (Administrator có đủ quyền)."""

	def test_plan_status_flags(self):
		from tracecore.v1 import ksnk_plan

		frappe.set_user("Administrator")
		out = ksnk_plan.status()
		for key in ("can_write_plan", "can_write_document", "can_create_document", "can_write_meeting"):
			self.assertIn(key, out)
		self.assertTrue(out["can_create_document"])

	def test_structure_training_improvement_flags(self):
		from tracecore.v1 import ksnk_improvement, ksnk_structure, ksnk_training

		frappe.set_user("Administrator")
		self.assertTrue(ksnk_structure.status()["can_create_member"])
		self.assertTrue(ksnk_training.status()["can_create_trainee"])
		out = ksnk_improvement.status()
		for key in ("can_write", "can_write_session", "can_create_session"):
			self.assertIn(key, out)
