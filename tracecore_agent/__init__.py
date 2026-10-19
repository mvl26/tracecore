"""TraceCore Station Agent (ADR-006): dịch vụ Python chạy trên PC trạm.

Bản tối giản FEAT-001: ``GET /health``, ``POST /print`` (hàng đợi SQLite, in TCP 9100 hoặc
ghi file .zpl + .png khi chưa có máy in), lệnh ``hello`` in một nhãn thử. Chỉ dùng thư viện chuẩn.
"""

__version__ = "0.1.0"
