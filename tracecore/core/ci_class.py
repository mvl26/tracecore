"""Loại chỉ thị hóa học của loại bộ (A-154, FR-M1-03.9, FR-M2-07.2).

``Instrument Set Type.ci_class`` là ``Not Needed`` (Không cần), ``4``, ``5``, ``6`` hoặc trống (chưa khai). M1 (lưu loại
bộ, ô gợi ý chỉ thị mặc định) và M2 (T4 đóng gói) cùng dùng luật ở đây để không import chéo.
"""

NOT_REQUIRED = "Not Needed"
CHOICES = (NOT_REQUIRED, "4", "5", "6")
DEFAULT_CLASSES = ("5", "6")  # chưa khai: luật trước A-154 (FR-M2-07.2 loại 5/6)
PACK_CLASSES = ("4", "5", "6")  # mọi loại có thể đặt trong gói (dữ liệu offline của T4)


def is_required(setting) -> bool:
	"""Loại bộ có cần lô chỉ thị trong gói không: chỉ ``Not Needed`` là không."""
	return setting != NOT_REQUIRED


def classes_for(setting) -> tuple[str, ...]:
	"""Các loại chỉ thị T4 nhận cho loại bộ khai `setting`: trống → 5/6; 4/5/6 → đúng loại đó; Không cần → rỗng."""
	if not setting:
		return DEFAULT_CLASSES
	if setting == NOT_REQUIRED:
		return ()
	return (setting,)
