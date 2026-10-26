"""Driver CSV generic (ADR-007, A-39 d): đọc file CSV máy xuất, mỗi dòng một chu trình, ánh xạ cột trong agent.ini.

Khóa cấu hình (mục ``[machine:<TB-####>]``):
- ``path`` (thư mục), ``glob`` (mặc định ``*.csv``), ``delimiter`` (mặc định ``,``), ``encoding`` (mặc định ``utf-8-sig``)
- ``col.<trường>`` cho ``cycle_ref`` (bắt buộc), ``load_id``, ``program``, ``started_at``, ``ended_at``, ``result``,
  ``alerts`` (nhiều cảnh báo cách nhau bởi ``alert_separator``, mặc định ``|``)
- ``time_format`` (``strptime``; trống = ISO 8601) và ``timezone`` (vd ``+07:00``) cho giờ máy không có múi giờ
- ``result.pass`` / ``result.fail``: các giá trị máy ghi cho Đạt / Không đạt (phân tách bằng dấu phẩy)
- ``param.<tên tham số chương trình> = <cột>``
"""

import csv
import glob
import logging
import os
from datetime import datetime, timedelta, timezone

from tracecore_agent.drivers.base import CycleData, Driver

log = logging.getLogger("tracecore_agent")
FIELDS = ("cycle_ref", "load_id", "program", "started_at", "ended_at", "result", "alerts")


def _offset(value):
	"""``+07:00`` → tzinfo; trống → None."""
	value = (value or "").strip()
	if not value:
		return None
	sign = -1 if value.startswith("-") else 1
	hours, _, minutes = value.lstrip("+-").partition(":")
	return timezone(sign * timedelta(hours=int(hours), minutes=int(minutes or 0)))


def _values(option):
	return {item.strip().casefold() for item in (option or "").split(",") if item.strip()}


class CsvGenericDriver(Driver):
	name = "csv_generic"

	def __init__(self, options):
		super().__init__(options)
		self.columns = {field: self.options.get(f"col.{field}") for field in FIELDS}
		if not self.columns["cycle_ref"]:
			raise ValueError("csv_generic needs col.cycle_ref")
		self.parameters = {
			key[len("param.") :]: column for key, column in self.options.items() if key.startswith("param.")
		}
		self.tz = _offset(self.options.get("timezone"))
		self.time_format = (self.options.get("time_format") or "").strip()
		self.passes = _values(self.options.get("result.pass") or "pass")
		self.fails = _values(self.options.get("result.fail") or "fail")

	def _time(self, value):
		value = (value or "").strip()
		if not value:
			return None
		try:
			moment = (
				datetime.strptime(value, self.time_format)
				if self.time_format
				else datetime.fromisoformat(value)
			)
		except ValueError:
			log.warning("csv_generic: cannot read time %r", value)
			return None
		if moment.tzinfo is None and self.tz is not None:
			moment = moment.replace(tzinfo=self.tz)
		return moment.isoformat(timespec="seconds")

	def _result(self, value):
		value = (value or "").strip().casefold()
		if value in self.passes:
			return "Pass"
		if value in self.fails:
			return "Fail"
		return None

	def _cell(self, row, field):
		column = self.columns.get(field)
		return (row.get(column) or "").strip() if column else ""

	def _cycle(self, row):
		ref = self._cell(row, "cycle_ref")
		if not ref:
			return None
		separator = self.options.get("alert_separator") or "|"
		alerts = [text.strip() for text in self._cell(row, "alerts").split(separator) if text.strip()]
		return CycleData(
			cycle_ref=ref,
			load_id=self._cell(row, "load_id") or None,
			program=self._cell(row, "program") or None,
			started_at=self._time(self._cell(row, "started_at")),
			ended_at=self._time(self._cell(row, "ended_at")),
			parameters=[
				{"parameter_name": name, "value": (row.get(column) or "").strip()}
				for name, column in self.parameters.items()
				if (row.get(column) or "").strip()
			],
			alerts=alerts,
			result=self._result(self._cell(row, "result")),
		)

	def fetch_cycles(self, since=None):
		"""Mọi chu trình trong các file khớp ``glob`` (file sửa trước `since` — epoch giây — bị bỏ qua)."""
		folder = os.path.expanduser(self.options.get("path") or "")
		pattern = os.path.join(folder, self.options.get("glob") or "*.csv")
		cycles = []
		for path in sorted(glob.glob(pattern)):
			if since and os.path.getmtime(path) < since:
				continue
			with open(path, encoding=self.options.get("encoding") or "utf-8-sig", newline="") as handle:
				reader = csv.DictReader(handle, delimiter=self.options.get("delimiter") or ",")
				for row in reader:
					cycle = self._cycle(row)
					if cycle:
						cycles.append(cycle)
		return cycles
