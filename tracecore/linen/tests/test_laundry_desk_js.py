"""Form Laundry Batch trên Desk: nút Hoàn tất lô gửi client_ts ISO 8601 có offset và báo đúng lý do server trả về."""

from tracecore.tests.js_harness import run_js
from tracecore.tests.utils import IsolatedTestCase

FORM = "public/js/laundry_batch.js"
NAMES = ["laundry_payload", "laundry_error"]
SETUP = """
globalThis.tracecore = {codes: {client_ts: () => "2026-11-12T09:30:00+07:00"}};
const frm = {doc: {name: "LG-2026-00001"}};
"""


class TestLaundryDeskComplete(IsolatedTestCase):
	def _run(self, code):
		return run_js(self, [FORM], [NAMES], SETUP + code)

	def test_payload_has_client_ts_with_offset(self):
		out = self._run(
			"""emit(laundry_payload(frm, {dryer: "MS-01", clean_ok: "Pass", dry_ok: "Fail"}));"""
		)
		self.assertEqual(out["client_ts"], "2026-11-12T09:30:00+07:00")
		self.assertEqual((out["batch"], out["clean_ok"], out["dry_ok"]), ("LG-2026-00001", 1, 0))

	def test_error_uses_blocked_result_then_server_message(self):
		out = self._run(
			"""emit({
				block: laundry_error({message: {ok: false, error: {reason: "Máy sấy chưa sẵn sàng"}}}),
				server: laundry_error({_server_messages: JSON.stringify([JSON.stringify(
					{message: "client_ts must be ISO 8601 with a UTC offset: 2026-11-12"})])}),
				exc: laundry_error({exception: "frappe.exceptions.PermissionError: Not permitted"}),
				empty: laundry_error({})});"""
		)
		self.assertEqual(out["block"]["reason"], "Máy sấy chưa sẵn sàng")
		self.assertIn("client_ts must be ISO 8601", out["server"]["reason"])
		self.assertIn("Not permitted", out["exc"]["reason"])
		self.assertIn("Check your permissions", out["empty"]["reason"])
