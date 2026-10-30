"""Driver dữ liệu máy (FEAT-024, ADR-007): đăng ký theo tên dùng trong ``driver = …`` của agent.ini."""

from tracecore_agent.drivers.api_stub import ApiStubDriver
from tracecore_agent.drivers.csv_generic import CsvGenericDriver

DRIVERS = {driver.name: driver for driver in (CsvGenericDriver, ApiStubDriver)}


def make(name, options):
	"""Driver `name` với `options`; tên lạ → ValueError."""
	if name not in DRIVERS:
		raise ValueError(f"Unknown machine driver: {name}")
	return DRIVERS[name](options)
