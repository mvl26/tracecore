"""Driver API mẫu (ADR-007): chỗ cắm cho API hãng khi có danh sách máy kết nối (D-04); chưa đọc gì, chỉ ghi log."""

import logging

from tracecore_agent.drivers.base import Driver

log = logging.getLogger("tracecore_agent")


class ApiStubDriver(Driver):
	name = "api_stub"

	def fetch_cycles(self, since=None):
		log.info("api_stub: no vendor API driver configured yet; nothing fetched")
		return []
