"""Phản hồi khoa và đề nghị NC khi phiếu giám sát ghi sổ (FEAT-060; FR-M12-08, FR-M12-09, BRU-AUD-005)."""


def after_submit(doc):
	"""Gọi từ ``sessions.on_submit``."""
