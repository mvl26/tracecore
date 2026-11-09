"""Mã phiên bản dùng chung `<TIỀN TỐ>-<mã>-V<n>` (architecture §5.3.3; A-134).

Mã phiên bản không phải naming series: tên chứng từ ghép từ mã nghiệp vụ và số phiên bản (cùng kiểu `BOM-<TYPE>-V<n>`
của `core.gs1`). Module nghiệp vụ (vd M12 `Audit Template`) gọi hàm ở đây thay vì tự ghép chuỗi.
"""

import re

CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,39}$")


def normalize_code(raw) -> str:
	"""Mã nghiệp vụ viết hoa, chỉ chữ Latin không dấu, số, `-`, `_`; bắt đầu bằng chữ hoặc số. Sai → ValueError."""
	code = str(raw or "").strip().upper()
	if not CODE_PATTERN.match(code):
		raise ValueError(code)
	return code


def make_versioned_code(prefix: str, code: str, version: int) -> str:
	if int(version) < 1:
		raise ValueError(version)
	return f"{prefix}-{normalize_code(code)}-V{int(version)}"
