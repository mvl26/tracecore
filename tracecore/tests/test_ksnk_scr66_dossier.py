"""SCR-66 khối gói hồ sơ KSNK cho đoàn kiểm tra (FEAT-074; FR-M9-30; A-152): trạng thái bằng chữ, dấu Tạm, phần chỉ
Excel, danh sách trống."""

from frappe.tests.utils import FrappeTestCase

from tracecore.tests.js_harness import run_js
from tracecore.tests.test_ksnk_page import SCR66, SHELL

DATA = """
const esc = TcKsnk.esc;
const data = {year: 2031, period: "2031-10"};
const sections = [
	{key: "indicators", label: "Indicators", in_pdf: true},
	{key: "hai_cases", label: "HAI cases", in_pdf: false},
];
"""


class TestScr66Dossier(FrappeTestCase):
	def run_block(self, script):
		return run_js(self, [SHELL, SCR66], [["TcKsnk"], ["TcKsnkScr66"]], DATA + script)

	def test_dossier_list_status_and_provisional(self):
		out = self.run_block(
			"""
			const html = TcKsnkScr66.dossierHtml({sections, dossiers: [
				{name: "XH-2031-00001", months: "2031-01..2031-10", status: "Completed", provisional: true,
				 sha256: "abcdef0123456789", file: "/private/files/XH-2031-00001.zip"},
				{name: "XH-2031-00002", months: "2031-01..2031-02", status: "Failed", provisional: false,
				 error: "Dossier section leaky was not exported"},
			]}, data, esc);
			emit({html});
			"""
		)
		html = out["html"]
		self.assertIn('value="2031-01"', html)
		self.assertIn('value="2031-10"', html)
		self.assertIn('data-dossier-section="hai_cases"', html)
		self.assertIn("Excel only", html)
		self.assertIn("Completed", html)
		self.assertIn("Provisional", html)
		self.assertIn("abcdef012345…", html)
		self.assertIn("/private/files/XH-2031-00001.zip", html)
		self.assertIn("Failed", html)
		self.assertIn("leaky", html)
		self.assertIn('data-action="dossier-export"', html)

	def test_empty_list(self):
		out = self.run_block(
			"""
			emit({html: TcKsnkScr66.dossierHtml({sections, dossiers: []}, {year: 2031}, esc)});
			"""
		)
		self.assertIn("No dossier exported yet.", out["html"])
		self.assertIn('value="2031-12"', out["html"])
