import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import errors
from tracecore.core.errors import Block, BlockedError


class TestErrors(FrappeTestCase):
	def test_block_http_status_from_code(self):
		self.assertEqual(Block("SET_NOT_FOUND", "t", "r", "a").http_status, 404)
		self.assertEqual(Block("CI_LOT_INVALID", "t", "r", "a").http_status, 422)
		self.assertEqual(Block("GATE_PREV_NOT_PASSED", "t", "r", "a").http_status, 409)
		# mã không có trong bảng: xung đột trạng thái nghiệp vụ
		self.assertEqual(Block("X", "t", "r", "a").http_status, 409)
		error = BlockedError(Block("PACK_NOT_FOUND", "t", "r", "a"))
		self.assertEqual(error.http_status_code, 404)

	def test_http_status_table_matches_decision_d3(self):
		expected = {
			422: (
				"STATION_WRONG_STEP",
				"SCAN_INVALID",
				"BOM_INCOMPLETE",
				"CI_LOT_INVALID",
				"CI_LOT_EXPIRED",
				"PACK_TYPE_INVALID",
				"REASON_REQUIRED",
				"MAINT_ACTION_REQUIRED",
				"MAINT_OIL_LOT_REQUIRED",
				"ROLL_NOT_LABEL",
				"LABEL_RENDER_FAILED",
				"PROGRAM_MODEL_MISMATCH",
				"PROGRAM_COPY_INVALID",
			),
			404: ("SET_NOT_FOUND", "PACK_NOT_FOUND", "ROLL_NOT_FOUND", "EQUIPMENT_NOT_FOUND"),
			409: (
				"STATUS_INVALID_FOR_STATION",
				"ACTIVE_CYCLE_EXISTS",
				"GATE_PREV_NOT_PASSED",
				"SET_TYPE_GTIN_MISSING",
				"PAR_EXCEEDED",
				"MAINT_OVERDUE",
				"REPRINT_WINDOW_EXPIRED",
				"PACK_NOT_VOIDABLE",
				"ROLL_PRINTER_AMBIGUOUS",
				"STATION_INACTIVE",
				"EQUIPMENT_NOT_RETIRABLE",
				"EQUIPMENT_RETIRED",
				"PROGRAM_CODE_EXISTS",
			),
		}
		table = {code: status for status, codes in expected.items() for code in codes}
		self.assertEqual(errors.HTTP_STATUS, table)

	def test_block_as_dict(self):
		self.assertEqual(
			Block("X", "t", "r", "a").as_dict(),
			{"code": "X", "title": "t", "reason": "r", "action": "a", "http_status": 409},
		)

	def test_block_as_dict_keeps_optional_keys_when_set(self):
		block = Block("BOM_INCOMPLETE", "t", "r", "a", items=[{"instrument": "KC-1"}], redo_step="T3")
		self.assertEqual(
			block.as_dict(),
			{
				"code": "BOM_INCOMPLETE",
				"title": "t",
				"reason": "r",
				"action": "a",
				"http_status": 422,
				"items": [{"instrument": "KC-1"}],
				"redo_step": "T3",
			},
		)
		# danh sách rỗng vẫn là giá trị (khác None)
		self.assertEqual(Block("X", "t", "r", "a", items=[]).as_dict()["items"], [])

	def test_blocked_error_carries_block(self):
		block = Block("SET_NOT_FOUND", "Set not found", "Set X does not exist.", "Rescan the tag.")
		error = BlockedError(block)
		self.assertIsInstance(error, frappe.ValidationError)
		self.assertIs(error.block, block)
		# traceback lạc vẫn đọc được: str(error) là lý do
		self.assertEqual(str(error), "Set X does not exist.")
		with self.assertRaises(BlockedError) as caught:
			raise error
		self.assertEqual(caught.exception.http_status_code, 404)
