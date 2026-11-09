"""FEAT-060 (SCR-52): thêm chức năng trạm AUDIT (phiếu giám sát trên PDA) vào danh mục và loại vùng Khoa.

Chỉ thêm, không ghi đè danh mục R10 đã sửa (``ensure_station_catalog``)."""

from tracecore.setup.seed import ensure_station_catalog


def execute():
	ensure_station_catalog()
