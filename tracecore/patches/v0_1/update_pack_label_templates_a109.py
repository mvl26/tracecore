"""A-109: rút gọn nhãn gói trên site đã cài; chỉ thay mẫu mẫu còn đúng bản cũ, mẫu R10 đã sửa giữ nguyên."""

from tracecore.setup.label_templates import upgrade_sample_pack_templates


def execute():
	upgrade_sample_pack_templates()
