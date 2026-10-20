"""Danh bạ máy in của trạm, kéo từ RPC tracecore.v1.station.config (D11)."""

import logging
import threading

log = logging.getLogger("tracecore_agent")


class PrinterDirectory:
	def __init__(self, cfg, client):
		self.cfg = cfg
		self.client = client
		self._printers = {}
		self._lock = threading.Lock()

	def refresh(self):
		"""Nạp lại danh sách máy in; lỗi (server/mạng) giữ nguyên bản cũ và chỉ ghi log."""
		try:
			station = self.client.station_config() or {}
			printers = {}
			for item in station.get("printers") or []:
				printers[item["name"]] = ((item.get("host") or "").strip(), int(item.get("port") or 9100))
		except Exception as error:  # mất mạng không được dừng agent
			log.warning("could not refresh station config: %s", error)
			return
		with self._lock:
			self._printers = printers

	def resolve(self, name):
		"""(host, port) của máy in; host rỗng = ghi file. Không tên → máy in trong INI; tên lạ → refresh 1 lần rồi None."""
		if not name:
			return self.cfg.printer_host, self.cfg.printer_port
		with self._lock:
			target = self._printers.get(name)
		if target is None:
			self.refresh()
			with self._lock:
				target = self._printers.get(name)
		return target
