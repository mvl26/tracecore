"""Quét dữ liệu máy và gửi lên server (FEAT-024, A-39 b, d; ADR-007).

Mỗi lượt: driver của từng máy trong agent.ini trả các chu trình; chu trình chưa gửi được gửi lên
``tracecore.v1.load.ingest_machine_data``. Trạng thái từng (máy, chu trình) lưu trong SQLite của agent:
- ``sent``: server đã nhận (không gửi lại);
- ``pending``: chưa khớp lô/mẻ (404) hoặc lỗi mạng/server — gửi lại lượt sau, quá ``RETRY_SECONDS`` thì ``dropped``;
- ``rejected``: server từ chối hẳn (409/422, vd đã có dữ liệu nhập tay) — không gửi lại, ghi log.
"""

import logging
import sqlite3
import time

from tracecore_agent import drivers
from tracecore_agent.client import ServerError

log = logging.getLogger("tracecore_agent")
RETRY_SECONDS = 24 * 3600
FINAL = ("sent", "rejected", "dropped")
RETRY_HTTP = (404,)


class MachineStore:
	def __init__(self, path):
		self.db = sqlite3.connect(path, isolation_level=None)
		self.db.execute(
			"""create table if not exists machine_cycles (
				equipment text not null, cycle_ref text not null, status text not null,
				first_seen real not null, last_try real, detail text,
				primary key (equipment, cycle_ref))"""
		)

	def get(self, equipment, cycle_ref):
		row = self.db.execute(
			"select status, first_seen from machine_cycles where equipment = ? and cycle_ref = ?",
			(equipment, cycle_ref),
		).fetchone()
		return row

	def mark(self, equipment, cycle_ref, status, now, detail=None):
		self.db.execute(
			"""insert into machine_cycles (equipment, cycle_ref, status, first_seen, last_try, detail)
			values (?, ?, ?, ?, ?, ?)
			on conflict (equipment, cycle_ref) do update set status = excluded.status,
				last_try = excluded.last_try, detail = excluded.detail""",
			(equipment, cycle_ref, status, now, now, detail),
		)


def _send(client, machine, cycle):
	"""``sent`` | ``pending`` | ``rejected`` cho một chu trình."""
	try:
		client.ingest_machine_data(machine.equipment, cycle.as_payload(machine.driver))
	except ServerError as error:
		if error.status in RETRY_HTTP or error.status >= 500:
			return "pending", str(error)
		if error.status in (401, 403):
			log.warning("machine %s: agent not allowed: %s", machine.equipment, error)
			return "pending", str(error)
		log.warning("machine %s cycle %s rejected: %s", machine.equipment, cycle.cycle_ref, error)
		return "rejected", str(error)
	except OSError as error:  # mất mạng: gửi lại lượt sau
		return "pending", str(error)
	return "sent", None


def poll_once(cfg, client, store, now=None):
	"""Một lượt quét mọi máy; trả số chu trình ``{sent, pending, rejected, dropped}`` của lượt này."""
	now = time.time() if now is None else now
	summary = {"sent": 0, "pending": 0, "rejected": 0, "dropped": 0}
	for machine in cfg.machines:
		try:
			cycles = drivers.make(machine.driver, machine.options).fetch_cycles()
		except Exception as error:  # driver lỗi không được dừng agent
			log.warning("machine %s: driver %s failed: %s", machine.equipment, machine.driver, error)
			continue
		for cycle in cycles:
			known = store.get(machine.equipment, cycle.cycle_ref)
			if known and known[0] in FINAL:
				continue
			if known and now - known[1] > RETRY_SECONDS:
				store.mark(
					machine.equipment, cycle.cycle_ref, "dropped", now, "not matched within retry window"
				)
				log.warning("machine %s cycle %s dropped: never matched", machine.equipment, cycle.cycle_ref)
				summary["dropped"] += 1
				continue
			status, detail = _send(client, machine, cycle)
			if known:
				store.db.execute(
					"update machine_cycles set status = ?, last_try = ?, detail = ? where equipment = ? and cycle_ref = ?",
					(status, now, detail, machine.equipment, cycle.cycle_ref),
				)
			else:
				store.mark(machine.equipment, cycle.cycle_ref, status, now, detail)
			summary[status] += 1
	return summary
