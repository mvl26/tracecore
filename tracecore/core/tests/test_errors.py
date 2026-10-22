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
				"COUNT_OUT_OF_RANGE",
				"COUNTER_INIT_INVALID",
				"ETCHING_INVALID",
				"BOM_EMPTY",
				"BOM_LINE_INVALID",
				"BOM_TOO_LARGE",
				"BOM_EFFECTIVE_DATE_INVALID",
				"SHELF_LIFE_INVALID",
				"SET_TYPE_BOM_INVALID",
				"DEPARTMENT_INVALID",
				"MAX_CYCLES_INVALID",
				"PRINTER_NOT_NETWORK",
			),
			404: (
				"SET_NOT_FOUND",
				"PACK_NOT_FOUND",
				"ROLL_NOT_FOUND",
				"EQUIPMENT_NOT_FOUND",
				"CODE_NOT_FOUND",
				"INSTRUMENT_NOT_FOUND",
				"SET_TYPE_NOT_FOUND",
				"BOM_VERSION_NOT_FOUND",
			),
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
				"CODE_DISABLED",
				"INSTRUMENT_RETIRED",
				"INSTRUMENT_IN_BOM",
				"FEATURE_DISABLED",
				"GIAI_ALREADY_ASSIGNED",
				"GIAI_NOT_ASSIGNED",
				"GS1_PREFIX_NOT_CONFIGURED",
				"BOM_VERSION_CONFLICT",
				"SET_TYPE_CODE_EXISTS",
				"SET_SERIES_EXHAUSTED",
				"SET_DISPOSED",
				"TAG_PRINT_PENDING",
				"TAG_MISMATCH",
			),
		}
		table = {code: status for status, codes in expected.items() for code in codes}
		self.assertEqual(errors.HTTP_STATUS, table)

	def test_http_status_instrument_not_found(self):
		# FEAT-014 A-06 I12: v1.instrument.get_image với mã dụng cụ không có
		self.assertEqual(errors.HTTP_STATUS["INSTRUMENT_NOT_FOUND"], 404)
		self.assertEqual(Block("INSTRUMENT_NOT_FOUND", "t", "r", "a").http_status, 404)

	def test_http_status_feat015_codes(self):
		# FEAT-015 A-07 (S4, S5, S7, S11, S13): mã mới của loại bộ / phiên bản BOM, cùng bảng ADR-003
		for code, status in {
			"SET_TYPE_NOT_FOUND": 404,
			"BOM_VERSION_NOT_FOUND": 404,
			"BOM_EMPTY": 422,
			"BOM_LINE_INVALID": 422,
			"BOM_TOO_LARGE": 422,
			"BOM_EFFECTIVE_DATE_INVALID": 422,
			"SHELF_LIFE_INVALID": 422,
			"BOM_VERSION_CONFLICT": 409,
			"SET_TYPE_CODE_EXISTS": 409,
		}.items():
			self.assertEqual(Block(code, "t", "r", "a").http_status, status, msg=code)

	def test_http_status_new_codes(self):
		# FEAT-016 G16 (A-09): cấp Set ID hàng loạt; SET_SERIES_EXHAUSTED: hết dải 999 999 giữa lô (review Task 1)
		for code, status in {
			"SET_TYPE_BOM_INVALID": 422,
			"DEPARTMENT_INVALID": 422,
			"MAX_CYCLES_INVALID": 422,
			"SET_SERIES_EXHAUSTED": 409,
			# Task 4/5: in thẻ/nhãn khay, quét kiểm tra; thẻ Set ID chỉ in qua đường server (ruling Task 4)
			"SET_DISPOSED": 409,
			"TAG_PRINT_PENDING": 409,
			"TAG_MISMATCH": 409,
			"PRINTER_NOT_NETWORK": 422,
			"GS1_PREFIX_NOT_CONFIGURED": 409,
		}.items():
			self.assertEqual(errors.HTTP_STATUS.get(code), status, msg=code)
			self.assertEqual(BlockedError(Block(code, "t", "r", "a")).http_status_code, status, msg=code)

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
