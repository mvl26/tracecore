"""Thao tác trên từng bản ghi ở SCR-59, SCR-60, SCR-61: luôn có lối mở form / In / Tạo mới theo quyền và trạng thái."""

from frappe.tests.utils import FrappeTestCase

from tracecore.tests.js_harness import run_js
from tracecore.tests.test_ksnk_page import SHELL

SCR59 = "public/js/ksnk/scr_59_vi_sinh.js"
SCR60 = "public/js/ksnk/scr_60_cach_ly.js"
SCR61 = "public/js/ksnk/scr_61_o_dich.js"


class TestScr59Actions(FrappeTestCase):
	def run59(self, script):
		return run_js(self, [SHELL, SCR59], [["TcKsnk"], ["TcKsnkScr59"]], script)

	def test_isolate_row_opens_form_and_prints(self):
		out = self.run59(
			"""
			const html = TcKsnkScr59.recentHtml([{name: "VS-0001", patient_code_masked: "***12", department: "D",
				specimen_type: "Blood", organism: "O", is_mdro: 0, is_first_isolate: 1, history: []}], TcKsnk.esc);
			emit({form: html.includes('/app/microbiology-isolate/VS-0001'), print: html.includes("/printview?doctype=Microbiology%20Isolate")});
			"""
		)
		self.assertTrue(out["form"])
		self.assertTrue(out["print"])

	def test_rules_create_link_follows_permission(self):
		out = self.run59(
			"""
			const yes = TcKsnkScr59.rulesHtml({rules: {approved: 1, draft: 0, can_create: true}}, TcKsnk.esc);
			const no = TcKsnkScr59.rulesHtml({rules: {approved: 1, draft: 0, can_create: false}}, TcKsnk.esc);
			emit({yes: yes.includes("/app/mdro-rule/new"), no: no.includes("/app/mdro-rule/new"), list: no.includes('href="/app/mdro-rule"')});
			"""
		)
		self.assertTrue(out["yes"])
		self.assertFalse(out["no"])
		self.assertTrue(out["list"])


class TestScr60Actions(FrappeTestCase):
	def run60(self, script):
		return run_js(self, [SHELL, SCR60], [["TcKsnk"], ["TcKsnkScr60"]], script)

	def test_order_rows_have_form_and_print_for_readonly_and_writers(self):
		out = self.run60(
			"""
			const base = {can_read_orders: true, can_cancel: false, mdro_close: false,
				orders: [{name: "CL-0001", department: "D", precaution_type: "Contact", start_at: "2031-01-02 08:00:00", days: 1}]};
			const writer = TcKsnkScr60.ordersHtml({...base, can_write: true}, TcKsnk.esc);
			const reader = TcKsnkScr60.ordersHtml({...base, can_write: false}, TcKsnk.esc);
			emit({
				w_cancel: writer.includes("Open form to cancel or amend"),
				r_view: reader.includes("View form") && !reader.includes("Open form to cancel"),
				r_form: reader.includes("/app/isolation-order/CL-0001"),
				r_print: reader.includes("/printview?doctype=Isolation%20Order&amp;name=CL-0001"),
			});
			"""
		)
		self.assertTrue(out["w_cancel"])
		self.assertTrue(out["r_view"])
		self.assertTrue(out["r_form"])
		self.assertTrue(out["r_print"])


class TestScr61Actions(FrappeTestCase):
	def run61(self, script):
		return run_js(self, [SHELL, SCR61], [["TcKsnk"], ["TcKsnkScr61"]], script)

	def test_outbreak_detail_and_report_rows_have_form_links(self):
		out = self.run61(
			"""
			const d = {name: "OD-0001", docstatus: 1, title: "T", status: "Ended", curve: [], cases: [], actions: [],
				incidents: [], departments: []};
			const data = {current: d, can_own: true, can_work: true, can_edit_outbreak: true, can_edit_report: false,
				print_outbreak: "/printview?x=", reports: [{name: "KB-0001", state: "Waiting", docstatus: 1,
				department: "D", diagnosed_on: "2031-01-01 08:00:00", due_by: "2031-01-02 08:00:00"}],
				diseases: [], departments: [], missing_groups: []};
			const detail = TcKsnkScr61.detailHtml(data, TcKsnk.esc);
			const reports = TcKsnkScr61.reportsHtml(data, TcKsnk.esc);
			emit({
				cancel: detail.includes("Open form to cancel or amend"),
				form: detail.includes("/app/outbreak-investigation/OD-0001"),
				report_view: reports.includes("View form") && reports.includes("/app/notifiable-disease-report/KB-0001"),
				report_print: reports.includes("doctype=Notifiable%20Disease%20Report"),
			});
			"""
		)
		self.assertTrue(out["cancel"])
		self.assertTrue(out["form"])
		self.assertTrue(out["report_view"])
		self.assertTrue(out["report_print"])
