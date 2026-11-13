"""FEAT-099 (A-158): Page tc-flow, giao diện người dùng cho luồng xử lý dụng cụ, dùng lại màn trạm hiện có."""

import json
import re
import subprocess
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.tests import js_harness
from tracecore.tests.js_harness import run_js

# lớp con của khung gọi hoặc ghi đè các method này của TraceCoreStation; đổi tên ở Page station thì test này báo
HOST_METHODS = [
	"adoptStationAddress",
	"applyStation",
	"openStation",
	"renderStationPills",
	"renderNetStatus",
	"activateSession",
	"clearSession",
	"focus",
	"switchStation",
	"endSession",
	"storeNotice",
	"rpcRead",
	"failureCause",
	"isOffline",
	"show",
	"hide",
	"dispose",
]

SHELL = "public/js/tc_flow_shell.js"
LEAD = "public/js/tc_flow_lead.js"
PAGE_DIR = Path(frappe.get_app_path("tracecore", "ui", "page", "tc_flow"))

STATIONS = """
const stations = [
	{ name: "TR-008", label: "Usage OR", station_no: 8, functions: ["USE"], implemented: true },
	{ name: "TR-002", label: "T2 Wash", station_no: 2, functions: ["WASH_LOAD", "WASH_UNLOAD"], implemented: true },
	{ name: "TR-001", label: "Receiving", station_no: 1, functions: ["RECEIVE"], implemented: true },
	{ name: "TR-020", label: "Linen", station_no: 20, functions: ["LINEN"], implemented: true },
	{ name: "TR-004", label: "Pack", station_no: 4, functions: ["PACK"], implemented: false },
	{ name: "TR-005", label: "Sterilize", station_no: 5, functions: ["STERI_LOAD"], implemented: true },
	{ name: "TR-05B", label: "Release", station_no: 5, functions: ["STERI_UNLOAD"], implemented: true },
];
"""


def run(testcase, body):
	return run_js(testcase, [SHELL], [["TcFlow"]], STATIONS + body)


class TestTcFlowShell(FrappeTestCase):
	def test_address_stays_on_the_new_page(self):
		out = run(
			self,
			"""emit({
				home: TcFlow.path(null),
				station: TcFlow.path("TR 001"),
				dept: TcFlow.path(null, "Khoa A - MD"),
				deptStation: TcFlow.path("TR-008", "K1"),
				deptParam: TcFlow.departmentParam("?department=K1&station=TR-008"),
				manage: TcFlow.path(null, null, "instruments"),
				manageParam: TcFlow.manageParam("?manage=instruments"),
				param: TcFlow.stationParam("?station=TR-001&x=1"),
				none: TcFlow.stationParam(""),
			});""",
		)
		# địa chỉ của giao diện mới là /app/tracecore/home (người dùng chọn 13/11/2026)
		self.assertEqual(out["home"], "/app/tracecore/home")
		self.assertEqual(out["station"], "/app/tracecore/home?station=TR%20001")
		self.assertEqual(out["param"], "TR-001")
		self.assertEqual(out["dept"], "/app/tracecore/home?department=Khoa%20A%20-%20MD")
		self.assertEqual(out["deptStation"], "/app/tracecore/home?department=K1&station=TR-008")
		self.assertEqual(out["deptParam"], "K1")
		self.assertEqual(out["manage"], "/app/tracecore/home?manage=instruments")
		self.assertEqual(out["manageParam"], "instruments")
		self.assertIsNone(out["none"])

	def test_station_lists_keep_only_the_instrument_flow(self):
		out = run(
			self,
			"""emit({
				ktv: TcFlow.ktvStations(stations).map((s) => s.name),
				dept: TcFlow.deptStations(stations).map((s) => s.name),
				flow: TcFlow.flowStations(stations).map((s) => s.name),
				modes: [TcFlow.mode(stations[0]), TcFlow.mode(stations[1]), TcFlow.mode(null)],
				labels: TcFlow.ktvStations(stations).map((s) => TcFlow.stationLabel(s)),
			});""",
		)
		# trạm đồ vải và trạm chưa có màn không vào danh sách; thứ tự theo số trạm
		self.assertEqual(out["ktv"], ["TR-001", "TR-002", "TR-005", "TR-05B"])
		self.assertEqual(out["dept"], ["TR-008"])
		# rail của kỹ thuật viên có đủ T1 đến T8 như hàng nút trạm của Page station
		self.assertEqual(out["flow"], ["TR-001", "TR-002", "TR-005", "TR-05B", "TR-008"])
		self.assertEqual(out["modes"], ["dept", "ktv", "ktv"])
		self.assertEqual(out["labels"][:2], ["T1 Receiving", "T2 Wash"])

	def test_stepper_marks_done_and_current_steps(self):
		out = run(self, """emit(TcFlow.stepper(stations, "TR-005"));""")
		self.assertEqual([step["no"] for step in out], [1, 2, 5, 8])
		self.assertEqual([step["state"] for step in out], ["done", "done", "current", "todo"])
		self.assertEqual(out[0]["label"], "T1 Receiving")

	def test_stock_counts_and_trace_rows(self):
		out = run(
			self,
			"""const overview = {
				at_department: [
					{ cycle_id: "CY-1", set_name: "A", expiry: "2026-12-01", expiring: false },
					{ cycle_id: "CY-2", set_name: "B", expiry: "2026-11-15", expiring: true },
				],
				waiting_return: [{ cycle_id: "CY-3", set_name: "C" }],
			};
			const chain = { cycle_id: "CY-1", set_id: "S-1", events: [
				{ step: "T2", label: "Wash", at: "2026-11-01 08:10:00", user: "a@x", user_name: "An",
					equipment: "MR-01", ref_name: "LR-1", result: "Pass" },
				{ step: "T8", label: "Use", at: "2026-11-02 09:41:00", user: "b@x", user_name: null, ref_name: null },
			] };
			emit({
				counts: TcFlow.stockCounts(overview),
				empty: TcFlow.stockCounts(null),
				server: TcFlow.stockCounts({ ...overview, par: { min: 6, max: 10 },
					counts: { held: 8, reprocessing: 1, recall_pending: 2, waiting_return: 0 } }),
				rows: TcFlow.traceRows(chain),
				byCycle: TcFlow.traceArgs(" cy-261101-0001 "),
				bySet: TcFlow.traceArgs("(01)0893(21)DB01-007"),
			});""",
		)
		self.assertEqual(
			out["counts"], {"held": 2, "reprocessing": 0, "recall": 0, "waiting": 1, "par": None}
		)
		self.assertEqual(out["empty"], {"held": 0, "reprocessing": 0, "recall": 0, "waiting": 0, "par": None})
		# số liệu do máy chủ đếm: bộ ở khoa kèm cơ số, đang tái xử lý, chờ xác nhận thu hồi, chờ KSNK lấy
		self.assertEqual(
			out["server"], {"held": 8, "reprocessing": 1, "recall": 2, "waiting": 0, "par": [6, 10]}
		)
		self.assertEqual(out["rows"][0]["step"], "T2")
		self.assertEqual(out["rows"][0]["detail"], "Wash · LR-1 · Pass")
		self.assertEqual(out["rows"][0]["who"], "MR-01 / An")
		self.assertEqual(out["rows"][1]["who"], "b@x")
		self.assertEqual(out["byCycle"], {"cycle_id": "CY-261101-0001"})
		self.assertEqual(out["bySet"], {"set_id": "(01)0893(21)DB01-007"})

	def test_count_up_runs_from_zero_to_the_real_number(self):
		"""Mở màn Bộ tại khoa và cơ số: số chạy từ 0 tới giá trị thật, chậm dần, không vượt đích."""
		out = run(
			self,
			"""const steps = [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1].map((p) => TcFlow.countAt(16, p));
			emit({
				steps,
				clamp: [TcFlow.countAt(16, -1), TcFlow.countAt(16, 5)],
				zero: [TcFlow.countAt(0, 0.5), TcFlow.countAt(null, 0.5), TcFlow.countAt(-3, 1)],
				one: TcFlow.countAt(1, 1),
				ms: TcFlow.COUNT_MS,
			});""",
		)
		steps = out["steps"]
		self.assertEqual(steps[0], 0)
		self.assertEqual(steps[-1], 16)
		self.assertEqual(steps, sorted(steps))
		# chậm dần: nửa đầu đi được nhiều hơn nửa sau
		self.assertGreater(steps[3], 16 - steps[3])
		self.assertEqual(out["clamp"], [0, 16])
		self.assertEqual(out["zero"], [0, 0, 0])
		self.assertEqual(out["one"], 1)
		self.assertGreaterEqual(out["ms"], 400)
		self.assertLessEqual(out["ms"], 1200)

	def test_stock_screen_animates_and_respects_reduced_motion(self):
		css = (PAGE_DIR / "tc_flow.css").read_text(encoding="utf-8")
		source = (PAGE_DIR / "tc_flow.js").read_text(encoding="utf-8")
		self.assertIn('data-count="', source)
		self.assertIn("TcFlow.countAt(", source)
		self.assertIn("requestAnimationFrame", source)
		# người dùng tắt chuyển động: hiện ngay số thật, không chạy số, không trượt
		self.assertIn("(prefers-reduced-motion: reduce)", source)
		self.assertIn("@keyframes tcf-rise", css)
		reduced = css[css.index("prefers-reduced-motion") :]
		self.assertIn("animation: none", reduced)
		# số trong ô không làm ô co giãn khi đang chạy
		self.assertIn("tabular-nums", css)
		# không giữ lớp ghép sau hiệu ứng: will-change và fill forwards làm chữ mờ ở màn hình phóng 125 %
		self.assertNotIn("will-change", css)
		self.assertNotRegex(css, r"animation:[^;]*\b(both|forwards)\b")

	def test_write_helpers_for_the_pickup_request(self):
		"""FEAT-100: client_ts ISO 8601 có offset và X-Idempotency-Key dạng UUID v4."""
		out = run(
			self,
			"""const bytes = Array.from({ length: 16 }, (_, index) => index * 16 + 5);
			emit({
				ts: TcFlow.clientTs(new Date(2026, 10, 13, 15, 20, 5)),
				fixed: TcFlow.uuid(bytes),
				random: [TcFlow.uuid(), TcFlow.uuid()],
				tones: ["Waiting", "Partly received", "Received"].map((s) => TcFlow.returnTone(s)),
			});""",
		)
		self.assertRegex(out["ts"], r"^2026-11-13T15:20:05[+-]\d{2}:\d{2}$")
		uuid4 = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
		self.assertRegex(out["fixed"], uuid4)
		for value in out["random"]:
			self.assertRegex(value, uuid4)
		self.assertNotEqual(*out["random"])
		self.assertEqual(out["tones"], ["warn", "info", "pass"])

	def test_return_pane_sends_the_request_through_the_idempotent_rpc(self):
		html = (PAGE_DIR / "tc_flow.html").read_text(encoding="utf-8")
		source = (PAGE_DIR / "tc_flow.js").read_text(encoding="utf-8")
		self.assertIn("tcf-return", html)
		self.assertIn("tcf-return-body", html)
		self.assertIn('"tracecore.v1.flow.return_overview"', source)
		self.assertIn('"tracecore.v1.flow.request_return"', source)
		self.assertIn('"X-Idempotency-Key"', source)
		self.assertIn("client_ts: TcFlow.clientTs()", source)
		# gửi lại sau lỗi mạng dùng lại đúng khóa và nội dung cũ, không tạo yêu cầu thứ hai
		self.assertIn("this.returnAttempt", source)
		# bảng Yêu cầu đã gửi hôm nay liệt kê từng bộ theo Set ID, không theo mã yêu cầu
		self.assertIn("data.sent_sets", source)
		self.assertNotIn("row.request)", source)
		# thứ tự mục cổng khoa như prototype: bộ tại khoa, quét sử dụng, gửi trả đồ bẩn, tra cứu gói
		self.assertIn('["stock", "work", "return", "issue", "recall", "linen", "trace"]', source)
		# ô chọn và ô tình trạng có nhãn cho trình đọc màn hình
		self.assertIn("aria-label", source[source.index("returnHtml(") :])

	def test_department_portal_has_issue_recall_and_linen_panes(self):
		"""FEAT-101 (A-161): ba mục còn lại của cổng khoa."""
		html = (PAGE_DIR / "tc_flow.html").read_text(encoding="utf-8")
		source = (PAGE_DIR / "tc_flow.js").read_text(encoding="utf-8")
		for pane in ("issue", "recall", "linen"):
			self.assertIn(f"tcf-{pane}-body", html)
			self.assertIn(f'data-action="tcf-{pane}-refresh"', html)
		for method in (
			"tracecore.v1.flow.recall_overview",
			"tracecore.v1.flow.issue_overview",
			"tracecore.v1.flow.request_issue",
			"tracecore.v1.flow.linen_received",
			# xác nhận thu hồi dùng RPC hiện có, không viết RPC ghi mới
			"tracecore.v1.recall.confirm_pack",
		):
			self.assertIn(f'"{method}"', source)
		# đề nghị cấp gửi lại dùng lại khóa cũ; từ chối của RPC thu hồi (HTTP 4xx) hiện inline
		self.assertIn("this.issueAttempt", source)
		self.assertIn("error.body", source)
		# số gói chờ xác nhận ở thanh bên có chữ cho trình đọc màn hình, không chỉ là chấm màu
		self.assertIn("tcf-nav-badge", source)
		self.assertIn("packs waiting for confirmation", source)
		out = run(self, """emit(["Waiting", "Partly issued", "Issued"].map((s) => TcFlow.returnTone(s)));""")
		self.assertEqual(out, ["warn", "info", "pass"])

	def test_lead_workspace_address_and_helpers(self):
		"""FEAT-102 (A-162): khu Trưởng khoa KSNK ở ?lead=<mục>, 7 mục theo prototype #17."""
		out = run(
			self,
			"""emit({
				path: TcFlow.path(null, null, null, "costs"),
				param: TcFlow.leadParam("?lead=costs"),
				unknown: TcFlow.leadParam("?lead=zzz"),
				none: TcFlow.leadParam("?station=TR-001"),
				panes: TcFlow.LEAD_PANES,
				vnd: [TcFlow.vnd(184500), TcFlow.vnd(0), TcFlow.vnd(48000000)],
				pct: [TcFlow.signedPct(-4.2), TcFlow.signedPct(3), TcFlow.signedPct(null)],
				months: [TcFlow.monthShift("2026-01", -1), TcFlow.monthShift("2026-12", 1)],
				tones: ["within", "below", "blocked", "warn", "Locked", "Ready", "New"].map((s) => TcFlow.leadTone(s)),
				codes: TcFlow.stationCodes([
					{ station: "A", station_no: 1 }, { station: "B", station_no: 2 },
					{ station: "C", station_no: 2 }, { station: "X", station_name: "Kho" },
				]),
			});""",
		)
		self.assertEqual(out["path"], "/app/tracecore/home?lead=costs")
		self.assertEqual(out["param"], "costs")
		self.assertEqual(out["unknown"], "overview")
		self.assertIsNone(out["none"])
		self.assertEqual(
			out["panes"], ["overview", "overrides", "recalls", "costs", "equipment", "staff", "log"]
		)
		self.assertEqual(out["vnd"], ["184.500 ₫", "0 ₫", "48.000.000 ₫"])
		self.assertEqual(out["pct"], ["\u22124,2%", "+3,0%", "\u2014"])
		self.assertEqual(out["months"], ["2025-12", "2027-01"])
		self.assertEqual(out["tones"], ["pass", "fail", "fail", "warn", "fail", "pass", "info"])
		self.assertEqual(out["codes"], "T1, T2, Kho")

	def test_lead_screens_show_server_numbers_with_words_for_every_status(self):
		out = run_js(
			self,
			[SHELL, LEAD],
			[["TcFlow"], ["TcFlowLead"]],
			"""const h = { esc, day: (v) => v || "", time: (v) => v || "", hour: (v) => String(v || "").slice(11, 16) };
			const data = {
				date: "2026-11-13",
				decisions: {
					overrides: { count: 1, rows: [{ name: "GD-1", set_unit: "<b>SU</b>", reason: "r" }] },
					recalls: { count: 1, rows: [{ name: "TH-1", pack_count: 4, confirmed_count: 2, trigger: "BI Positive" }] },
					equipment: { count: 0, rows: [] },
					certificates: { count: 0, rows: [] },
				},
				kpis: { reprocessing: 144, cost_per_pack: 184500, open_nc: 3 },
				output: [{ station_name: "Receiving", station_no: 1, count: 156, people: ["An"] }],
				departments: [
					{ department_name: "OR", stock: 8, min: 6, max: 10, state: "within" },
					{ department_name: "ER", stock: 1, min: 2, max: 4, state: "below" },
				],
			};
			emit({
				overview: TcFlowLead.overviewHtml(h, data),
				badges: TcFlowLead.badges(data),
				recalls: TcFlowLead.recallsHtml(h, {
					orders: [{ name: "TH-1", pack_count: 1, lines: [{
						pack: "CY-1", patient_code_masked: "BN09****78", status_at_recall: "Used",
						confirmed: false, action: "Notify Physician",
					}] }],
					incidents: [],
				}),
				overrides: TcFlowLead.overridesHtml(h, {
					can_decide: true,
					requests: [{ name: "GD-1", set_id: "TE01-021", cycles_used: 200, max_cycles: 200 }],
					sets: [{ set_id: "DB01-012", cycles_used: 299, max_cycles: 300, state: "warn",
						forecast: { month: "2026-11", price: 48000000 } }],
				}),
				readonly: TcFlowLead.overridesHtml(h, { can_decide: false, requests: [{ name: "GD-1" }], sets: [] }),
				approve: TcFlowLead.overrideFormHtml(h, "approve", "GD-1", "2026-11-13"),
				reject: TcFlowLead.overrideFormHtml(h, "reject", "GD-1", "2026-11-13"),
				url: TcFlowLead.logReportUrl({ date: "2026-11-13", equipment: "MH-01" }),
				methods: Object.values(TcFlowLead.PANES).map((pane) => pane.method),
				keys: Object.keys(TcFlowLead.PANES),
				panes: TcFlow.LEAD_PANES,
			});""",
		)
		overview = out["overview"]
		self.assertIn('data-count="144"', overview)
		self.assertIn('data-format="vnd"', overview)
		self.assertIn("184.500 ₫", overview)
		self.assertIn("&lt;b&gt;SU", overview)
		self.assertNotIn("<b>SU", overview)
		self.assertIn("2/4", overview)
		# trạng thái có chữ, không chỉ màu
		self.assertIn("Within par level", overview)
		self.assertIn("Below minimum", overview)
		self.assertIn('data-pane="overrides"', overview)
		self.assertEqual(out["badges"], {"overrides": 1, "recalls": 4})
		# mã bệnh nhân chỉ ở dạng che
		self.assertIn("BN09****78", out["recalls"])
		self.assertIn("No incident is open.", out["recalls"])
		self.assertIn('data-action="tcf-override-open"', out["overrides"])
		self.assertIn("200/200 cycles (100%)", out["overrides"])
		self.assertIn("Month 11/2026 · 48.000.000 ₫", out["overrides"])
		self.assertNotIn("tcf-override-open", out["readonly"])
		for name in ("cycles", "until", "reason", "pin"):
			self.assertIn(f"tcf-override-{name}", out["approve"])
		self.assertIn('type="password"', out["approve"])
		self.assertNotIn("tcf-override-cycles", out["reject"])
		self.assertTrue(out["url"].startswith("/app/query-report/Sterilization Log?from_date=2026-11-13"))
		self.assertIn("equipment=MH-01", out["url"])
		self.assertEqual(out["keys"], out["panes"])
		for method in out["methods"]:
			self.assertRegex(method, r"^tracecore\.v1\.lead\.[a-z_]+$")

	def test_lead_workspace_is_wired_into_the_page(self):
		html = (PAGE_DIR / "tc_flow.html").read_text(encoding="utf-8")
		source = (PAGE_DIR / "tc_flow.js").read_text(encoding="utf-8")
		self.assertIn('data-action="tcf-lead"', html)
		self.assertIn("tcf-lead-body", html)
		self.assertIn('data-action="tcf-lead-refresh"', html)
		self.assertIn(LEAD, frappe.get_hooks("page_js")["tc-flow"])
		self.assertIn("TcFlow.leadParam(window.location.search)", source)
		self.assertIn("TcFlowLead.PANES[pane].method", source)
		# duyệt / từ chối ghi đè dùng RPC hiện có của UC-31, không viết RPC ghi mới
		self.assertIn("tracecore.v1.par.override.", source)
		# PIN không giữ lại sau khi gửi
		self.assertIn('pin.value = ""', source)
		lead = Path(frappe.get_app_path("tracecore", *LEAD.split("/"))).read_text(encoding="utf-8")
		for text in (source, lead):
			self.assertNotIn("localStorage", text)
			self.assertNotIn("frappe.msgprint", text)
		self.assertNotIn("patient_code)", lead)

	def test_tracecore_home_opens_the_flow_page(self):
		"""/app/tracecore/home hiện Page tc-flow; /app/tc-flow cũ chuyển về địa chỉ mới, giữ tham số."""
		launcher = (PAGE_DIR.parent / "tracecore" / "tracecore.js").read_text(encoding="utf-8")
		source = (PAGE_DIR / "tc_flow.js").read_text(encoding="utf-8")
		self.assertIn('const TC_FLOW_SUBROUTE = "home";', launcher)
		self.assertIn('frappe.views.pageview.show("tc-flow")', launcher)
		# trang chủ không tải phân hệ (và không đổi địa chỉ) khi đang ở /app/tracecore/home
		self.assertIn("!is_tc_flow_route()", launcher)
		self.assertLess(
			launcher.index("if (is_tc_flow_route())"), launcher.index("wrapper.tc_launcher_load();")
		)
		self.assertIn("TcFlow.BASE + window.location.search", source)
		self.assertIn("frappe.router.route()", source)

	def test_station_kit_is_loaded_in_a_private_scope(self):
		# script của Page station kết thúc bằng gán vào frappe.pages["station"]; nạp riêng không được để lại dấu vết toàn cục
		out = run(
			self,
			"""const source = 'class TraceCoreStation { hello() { return "hi"; } }\\n' +
				'frappe.pages["station"].on_page_load = function () {};';
			globalThis.frappe = { pages: {} };
			const kit = TcFlow.kit(source);
			const cleaned = "station" in frappe.pages;
			const real = { on_page_load: 1 };
			frappe.pages.station = real;
			TcFlow.kit(source);
			emit({
				works: new kit.TraceCoreStation().hello(),
				leaked: typeof TraceCoreStation,
				cleaned,
				kept: frappe.pages.station === real && real.on_page_load === 1,
			});""",
		)
		self.assertEqual(out["works"], "hi")
		self.assertEqual(out["leaked"], "undefined")
		self.assertFalse(out["cleaned"])
		self.assertTrue(out["kept"])

	def test_host_class_never_sends_the_address_back_to_the_old_page(self):
		out = run(
			self,
			"""const log = [];
			globalThis.frappe = {};
			globalThis.TcStationUrl = { remember: (s, no, name) => log.push(["remember", no, name]), storage: () => null };
			class Base {
				constructor(wrapper, barrier) {
					this.wrapper = wrapper; this.barrier = barrier;
					this.root = element(); this.root.querySelector = () => element();
					this.session = { token: "t" };
				}
				adoptStationAddress() { log.push(["OLD-ADDRESS"]); }
				applyStation(station) { this.stationInfo = station; }
				openStation() { log.push(["OLD-OPEN"]); }
				storeNotice(notice) { log.push(["notice", notice.code]); }
				dispose() { log.push(["dispose"]); return Promise.resolve(); }
				show() { log.push(["show"]); }
				renderStationPills(list) { log.push(["pills", list.length]); }
				renderNetStatus(queued) { log.push(["net", queued]); }
				activateSession(session) { this.session = session; }
				clearSession() { this.session = null; }
				focus() { log.push(["focus"]); }
			}
			let covered = false;
			const shell = {
				address: (name) => log.push(["address", name]),
				applied: (host, station) => log.push(["applied", station.name]),
				replaced: (host) => log.push(["replaced", host.wrapper]),
				stations: (host, list) => log.push(["stations", list.length]),
				net: (host) => log.push(["shell-net"]),
				session: (host) => log.push(["session", Boolean(host.session)]),
				covered: () => covered,
			};
			const Host = TcFlow.hostClass(Base, shell);
			const host = new Host("W");
			host.adoptStationAddress({ name: "TR-001", station_no: 1 });
			host.applyStation({ name: "TR-001" });
			host.renderStationPills([1, 2]);
			host.renderNetStatus(3);
			host.activateSession({ token: "x" });
			host.clearSession();
			host.focus();
			covered = true;
			host.focus();
			const next = host.openStation("TR-002", "Wash", { code: "N" });
			emit({
				log,
				station: host.station,
				no: host.stationNo,
				nextIsHost: next instanceof Host && next !== host,
				current: frappe.tc_station === next,
			});""",
		)
		flat = [entry[0] for entry in out["log"]]
		self.assertNotIn("OLD-ADDRESS", flat)
		self.assertNotIn("OLD-OPEN", flat)
		self.assertIn(["address", "TR-001"], out["log"])
		self.assertIn(["remember", 1, "TR-001"], out["log"])
		self.assertIn(["applied", "TR-001"], out["log"])
		self.assertIn(["stations", 2], out["log"])
		self.assertIn(["session", True], out["log"])
		self.assertIn(["session", False], out["log"])
		self.assertEqual(
			flat.count("focus"), 1
		)  # khung đang phủ màn trạm thì ô quét của trạm không giành focus
		self.assertIn(["notice", "N"], out["log"])
		self.assertIn(["address", "TR-002"], out["log"])
		self.assertIn(["replaced", "W"], out["log"])
		self.assertLess(flat.index("dispose"), flat.index("show"))
		self.assertEqual(out["station"], "TR-001")
		self.assertEqual(out["no"], 1)
		self.assertTrue(out["nextIsHost"])


class TestTcFlowStationKit(FrappeTestCase):
	def test_real_station_script_loads_in_a_private_scope(self):
		"""Ghép script như Frappe ghép cho Page station (station.js + page_js) rồi nạp qua TcFlow.kit."""
		node = js_harness.node_or_skip(self)
		paths = [frappe.get_app_path("tracecore", "ui", "page", "station", "station.js")]
		paths += [
			frappe.get_app_path("tracecore", *rel.split("/"))
			for rel in frappe.get_hooks("page_js")["station"]
		]
		body = (
			"const kit = TcFlow.kit(source);\n"
			"const Base = kit.TraceCoreStation;\n"
			"const Host = TcFlow.hostClass(Base, {});\n"
			f"const missing = {json.dumps(HOST_METHODS)}.filter((name) => typeof Base.prototype[name] !== 'function');\n"
			"emit({ kind: typeof Base, missing, leaked: typeof TraceCoreStation, sub: Host.prototype instanceof Base });"
		)
		program = (
			js_harness._PRELUDE
			+ f"load({json.dumps(frappe.get_app_path('tracecore', *SHELL.split('/')))}, ['TcFlow']);\n"
			+ f"sandbox.source = {json.dumps(paths)}.map((p) => fs.readFileSync(p, 'utf8')).join('\\n\\n');\n"
			+ "sandbox.emit = (v) => process.stdout.write(JSON.stringify(v));\n"
			+ f"vm.runInContext({json.dumps(body)}, sandbox);\n"
		)
		done = subprocess.run([node, "-e", program], capture_output=True, text=True, check=False)
		self.assertEqual(done.returncode, 0, done.stderr[-2000:])
		out = json.loads(done.stdout)
		self.assertEqual(out["kind"], "function")
		self.assertEqual(out["missing"], [])
		self.assertEqual(
			out["leaked"], "undefined"
		)  # không để lại lớp toàn cục: mở Page station sau đó không lỗi khai báo trùng
		self.assertTrue(out["sub"])


class TestTcFlowPage(FrappeTestCase):
	def test_page_is_registered_with_station_roles(self):
		page = json.loads((PAGE_DIR / "tc_flow.json").read_text(encoding="utf-8"))
		station = json.loads(
			Path(frappe.get_app_path("tracecore", "ui", "page", "station", "station.json")).read_text(
				encoding="utf-8"
			)
		)
		self.assertEqual(page["name"], "tc-flow")
		self.assertEqual(page["module"], "UI")
		self.assertEqual(page["standard"], "Yes")
		self.assertEqual(
			sorted(row["role"] for row in page["roles"]), sorted(row["role"] for row in station["roles"])
		)
		self.assertTrue(frappe.db.exists("Page", "tc-flow"))

	def test_shell_is_attached_to_the_new_page_only(self):
		page_js = frappe.get_hooks("page_js")
		self.assertIn(SHELL, page_js["tc-flow"])
		self.assertNotIn(SHELL, page_js["station"])

	def test_page_reuses_station_code_without_copying_it(self):
		source = (PAGE_DIR / "tc_flow.js").read_text(encoding="utf-8")
		shell = Path(frappe.get_app_path("tracecore", *SHELL.split("/"))).read_text(encoding="utf-8")
		self.assertIn('with_page("station"', source)
		self.assertIn("TcFlow.hostClass(", source)
		# cổng khoa chọn theo khoa (như prototype), không chọn theo trạm; gói tại khoa đọc bằng phiên Desk
		self.assertIn('"tracecore.v1.flow.departments"', source)
		self.assertIn('"tracecore.v1.flow.department_stock"', source)
		self.assertIn('this.fillSelect("dept", this.departments', source)
		self.assertIn("enterDept(", source)
		# quản lý (Dụng cụ và bộ, ...) nằm trong khung mới: phân hệ theo quyền từ navigation.context, màn Desk hiện có
		# mở trong khung và chỉ nhận đường dẫn /app/ do máy chủ trả về
		self.assertIn("context.admin_modules", source)
		self.assertIn("context.role_modules", source)
		# A-162: thẻ Trưởng khoa KSNK mở khu Trưởng khoa trong khung, không chuyển sang /app/tracecore nữa
		self.assertNotIn('window.location.assign("/app/tracecore")', source)
		self.assertNotIn('data-action="tcf-manage"', (PAGE_DIR / "tc_flow.html").read_text(encoding="utf-8"))
		self.assertNotIn('this.enterManage("instruments")', source)
		self.assertIn("this.enterManage(this.manage || manage", source)
		self.assertIn("tcf-frame", source)
		self.assertIn("/^\\/app\\//.test(link.route", source)
		# Page station mở sau sẽ hủy instance trạm của khung: quay lại phải mở lại trạm, không hiện màn đã hủy
		self.assertIn("this.host && this.host.disposed", source)
		self.assertIn('"tracecore.v1.trace.query"', source)
		self.assertIn('"tracecore.v1.navigation.context"', source)
		# không tự gọi RPC ghi của trạm, không đổi trạng thái bộ: mọi thao tác ghi đi qua màn trạm hiện có
		for text in (source, shell):
			self.assertNotIn("/app/station", text)
			self.assertNotRegex(
				text, r"tracecore\.v1\.(receive|wash|assembly|pack|load|release|putaway|issue)\."
			)
			self.assertNotIn("set_value", text)
		# token phiên trạm không được ghi vào bộ nhớ lâu dài
		self.assertNotIn("localStorage", source)

	def test_page_markup_follows_station_ui_rules(self):
		html = (PAGE_DIR / "tc_flow.html").read_text(encoding="utf-8")
		css = (PAGE_DIR / "tc_flow.css").read_text(encoding="utf-8")
		source = (PAGE_DIR / "tc_flow.js").read_text(encoding="utf-8")
		for cls in (
			"tcf-landing",
			"tcf-roles",
			"tcf-rail",
			"tcf-nav",
			"tcf-host",
			"tcf-stock",
			"tcf-trace",
			"tcf-manage",
		):
			self.assertIn(cls, html)
		# lỗi chặn: alert inline theo kết quả → lý do → hành động; không modal, không toast
		self.assertLess(source.index("tcf-alert-title"), source.index("tcf-alert-reason"))
		self.assertLess(source.index("tcf-alert-reason"), source.index("tcf-alert-action"))
		self.assertNotIn("frappe.msgprint", source)
		self.assertNotIn("frappe.show_alert", source)
		self.assertNotIn("frappe.throw", source)
		# chỉ token --tc-*, không hex/px, không gradient, không hover-only
		rules = "\n".join(line for line in css.splitlines() if not line.startswith("@media"))
		self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b|(?<![\w-])\d+(?:\.\d+)?px\b", rules))
		self.assertNotIn("gradient", css)
		self.assertNotIn(":hover", css)
		self.assertIn("prefers-reduced-motion", css)
		# màn hẹp: nút Menu của màn trạm phải còn để mở thanh phiên
		self.assertNotIn(".tc-menu-btn", css)
		self.assertIn("TcFlow.flowStations(this.catalog)", source)
		self.assertIn("var(--tc-touch-min)", css)
		# trạng thái bước không chỉ bằng màu
		self.assertIn("tcf-step-mark", source)
		self.assertIn("aria-current", source)
