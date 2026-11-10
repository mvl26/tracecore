"""Màn SCR-54 Hóa chất KSNK & đơn vị thuê ngoài trong Page tc-ksnk (FEAT-066 AC-4, AC-6, AC-8, AC-10; A-131, A-142)."""

from frappe.tests.utils import FrappeTestCase

from tracecore.tests.js_harness import run_js

SHELL = "public/js/ksnk/ksnk_shell.js"
SCR54 = "public/js/ksnk/scr_54_hoa_chat.js"

DATA = """
const litres = (a, b, c, d, e) => ({"Hand Rub": a, "Soap": b, "Surface Disinfectant": c,
	"Instrument Disinfectant": d, "Other": e});
const data = {
	ok: true, year: 2026, quarter: 3, can_write: true, can_import: true, import_kind: "ic_chemical",
	profiles: [{name: "Khoa Dược CSV", file_format: "CSV"}],
	items: [{name: "VST", item_name: "Cồn VST", stock_uom: "Litre"}],
	report: "/app/query-report/IC Chemical Consumption by Department",
	summary: {
		departments: [
			{department: "D1", department_name: "Hồi sức <b>", litres: litres(142, 38.5, 60, 24, 0),
			 sources: ["Stock Entry"], awaiting: 0, awaiting_items: [], no_litre: 0, patient_days: 2300,
			 hand_rub_per_1000: 61.8},
			{department: "D2", department_name: "Nội thận", litres: litres(28, 20, 55, 30, 0),
			 sources: ["Manual Entry", "Import"], awaiting: 1, no_litre: 1, patient_days: null,
			 hand_rub_per_1000: null,
			 awaiting_items: [{period: "2026-08", item: "XP", item_name: "Xà phòng", sources: ["Manual Entry", "Import"]}]},
		],
		total: {litres: litres(1184.5, 612, 743, 318, 0), departments: 32, hand_rub_per_1000: 19},
	},
	vendors: [
		{name: "S1", supplier_name: "Cty vệ sinh A", tc_ic_service_type: "Industrial Cleaning", tc_license_no: "GP-1",
		 tc_license_expiry: "2026-12-12", tc_contract_from: "2026-01-01", tc_contract_to: "2026-12-31",
		 state: "Expiring", days_left: 39, last_session: {name: "GS-2026-01712", score_pct: 88}},
		{name: "S2", supplier_name: "Cty xử lý chất thải C", tc_ic_service_type: "Waste Treatment",
		 tc_license_no: "GP-3", tc_license_expiry: "2026-10-20", state: "Expired", days_left: -21,
		 last_session: null, waste_vendor: "WV-1"},
		{name: "S3", supplier_name: "Cty suất ăn D", tc_ic_service_type: "Catering", tc_license_no: "GP-4",
		 tc_license_expiry: "2027-06-30", state: "Valid", days_left: 240, last_session: null},
	],
	unaudited: ["S3"],
};
const esc = TcKsnk.esc;
"""


class TestKsnkScr54(FrappeTestCase):
	def _run(self, code):
		return run_js(self, [SHELL, SCR54], [["TcKsnk"], ["TcKsnkScr54"]], DATA + code)

	def test_vietnamese_number_format(self):
		out = self._run(
			"""emit({a: TcKsnkScr54.num(1184.5), b: TcKsnkScr54.num(61.8), c: TcKsnkScr54.num(null),
				d: TcKsnkScr54.num(88, 0), e: TcKsnkScr54.date("2026-12-12")});"""
		)
		self.assertEqual(
			(out["a"], out["b"], out["c"], out["d"], out["e"]), ("1.184,5", "61,8", "—", "88", "12/12/2026")
		)

	def test_chemicals_table_with_sources_awaiting_and_total(self):
		html = self._run("""emit({html: TcKsnkScr54.chemicalsHtml(data, esc)});""")["html"]
		for text in (
			"142,0",
			"61,8",
			"Hồi sức &lt;b&gt;",
			"Stock Entry",
			"Awaiting confirmation",
			"No litre conversion",
			"No denominator yet",
			"Whole hospital (32 departments)",
			"1.184,5",
			'class="is-total"',
			"Preferred source",
			"1 item(s) have two sources",
			'data-action="choose"',
			"08/2026",
		):
			self.assertIn(text, html)
		self.assertNotIn("Hồi sức <b>", html)

	def test_read_only_user_sees_no_choose_or_entry_buttons(self):
		out = self._run(
			"""const ro = Object.assign({}, data, {can_write: false, can_import: false});
			emit({chem: TcKsnkScr54.chemicalsHtml(ro, esc), bar: TcKsnkScr54.toolbarHtml(ro, esc)});"""
		)
		self.assertNotIn('data-action="choose"', out["chem"])
		self.assertIn("Waiting for the materials accountant", out["chem"])
		self.assertNotIn('data-action="manual"', out["bar"])
		self.assertNotIn('data-action="import"', out["bar"])
		self.assertIn("Quarterly chemical report", out["bar"])
		self.assertIn("year=2026&amp;quarter=3", out["bar"])

	def test_vendor_table_states_in_text_and_expired_warning(self):
		html = self._run("""emit({html: TcKsnkScr54.vendorsHtml(data, esc)});""")["html"]
		for text in (
			"39 days left",
			"Expired",
			"Valid",
			"GS-2026-01712",
			"88 %",
			"Not audited this quarter",
			"Waste vendor record",
			"License expired: Cty xử lý chất thải C.",
			"only warns",
			"01/01/2026\u201331/12/2026",  # gạch nối khoảng ngày (en dash)
		):
			self.assertIn(text, html)
		empty = self._run(
			"""emit({html: TcKsnkScr54.vendorsHtml(Object.assign({}, data, {vendors: []}), esc)});"""
		)["html"]
		self.assertIn("No outsourced vendor yet", empty)

	def test_import_panel_and_manual_form(self):
		out = self._run(
			"""
			const check = {total: 5, valid: 2, existing: [], issues: [{row: 4, field: "department", reason: "Department X does not exist."}]};
			emit({
				fresh: TcKsnkScr54.importHtml(data, {profile: "Khoa Dược CSV"}, esc),
				checked: TcKsnkScr54.importHtml(data, {profile: "Khoa Dược CSV", file_url: "/private/files/a.csv",
					file_name: "a.csv", check}, esc),
				manual: TcKsnkScr54.manualHtml(data, {esc, departments: [{name: "D1", department_name: "Hồi sức"}]}),
				preview: TcKsnkScr54.previewHtml({period: "2026-08", department_name: "Hồi sức", item_name: "Cồn VST",
					qty: 4.5, uom: "Litre", litres: 4.5, source_note: "Sổ khoa", other_sources: ["Import"]}, esc),
			});
			"""
		)
		self.assertIn('data-action="check" disabled', out["fresh"])
		self.assertIn("Save 2 valid rows", out["checked"])
		self.assertIn('role="alert"', out["checked"])
		self.assertIn("Department X does not exist.", out["checked"])
		for text in ('data-manual="source_note"', 'value="2026-07"', 'value="2026-09"', "Cồn VST (Litre)"):
			self.assertIn(text, out["manual"])
		self.assertIn("4,50 Litre (4,5 L)", out["preview"])
		self.assertIn("already has data from Import", out["preview"])
		self.assertIn('data-action="confirm"', out["preview"])

	def test_page_html_and_registration(self):
		out = self._run(
			"""emit({html: TcKsnkScr54.pageHtml(data, esc), registered: window.TcKsnkScreens["hoa-chat"] === TcKsnkScr54});"""
		)
		self.assertTrue(out["registered"])
		self.assertIn("IC chemicals by department", out["html"])
		self.assertIn("Outsourced vendors", out["html"])
		self.assertIn('data-region="message"', out["html"])
