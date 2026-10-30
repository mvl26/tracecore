"""Giao diện driver dữ liệu máy (ADR-007): mỗi hãng/định dạng một driver ``fetch_cycles(since) -> list[CycleData]``."""

from dataclasses import dataclass, field


@dataclass
class CycleData:
	"""Một chu trình máy rửa/tiệt khuẩn như agent gửi lên ``tracecore.v1.load.ingest_machine_data``.

	Giờ là chuỗi ISO 8601 có múi giờ; ``parameters`` = ``[{parameter_name, value}]`` (value giữ nguyên chuỗi máy xuất,
	server tự đổi dấu phẩy thập phân); ``result`` ∈ ``Pass``/``Fail``/None.
	"""

	cycle_ref: str
	load_id: str | None = None
	program: str | None = None
	started_at: str | None = None
	ended_at: str | None = None
	parameters: list = field(default_factory=list)
	alerts: list = field(default_factory=list)
	result: str | None = None

	def as_payload(self, driver):
		return {
			"cycle_ref": self.cycle_ref,
			"load_id": self.load_id,
			"program": self.program,
			"started_at": self.started_at,
			"ended_at": self.ended_at,
			"parameters": list(self.parameters),
			"alerts": list(self.alerts),
			"result": self.result,
			"driver": driver,
		}


class Driver:
	"""Driver nhận ``options`` (các khóa của mục ``[machine:<TB-####>]`` trong agent.ini, trừ ``driver``)."""

	name = "base"

	def __init__(self, options):
		self.options = dict(options or {})

	def fetch_cycles(self, since=None):
		raise NotImplementedError
