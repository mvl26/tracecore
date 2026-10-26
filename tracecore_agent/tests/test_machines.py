"""Dữ liệu máy qua agent (FEAT-024, A-39, ADR-007): driver CSV generic, stub API, vòng quét và gửi lại."""

import pytest

from tracecore_agent import config, drivers
from tracecore_agent.client import ServerClient
from tracecore_agent.drivers.base import CycleData
from tracecore_agent.machines import RETRY_SECONDS, MachineStore, poll_once

CSV = (
	"Cycle;Batch;Program;Start;End;Status;Temp;A0;Alarm\n"
	"1001;ME-261026-01;MH-134;26/10/2026 09:00;26/10/2026 09:45;OK;134,5;;\n"
	"1002;;MH-134;26/10/2026 10:00;26/10/2026 10:40;FAIL;133,0;;Door|Low pressure\n"
)
MACHINE_INI = (
	"[machine:TB-0015]\n"
	"driver = csv_generic\n"
	"path = {path}\n"
	"glob = *.csv\n"
	"delimiter = ;\n"
	"time_format = %d/%m/%Y %H:%M\n"
	"timezone = +07:00\n"
	"col.cycle_ref = Cycle\n"
	"col.load_id = Batch\n"
	"col.program = Program\n"
	"col.started_at = Start\n"
	"col.ended_at = End\n"
	"col.result = Status\n"
	"col.alerts = Alarm\n"
	"result.pass = OK\n"
	"result.fail = FAIL\n"
	"param.Nhiệt độ = Temp\n"
)


@pytest.fixture
def export_dir(tmp_path):
	folder = tmp_path / "export"
	folder.mkdir()
	(folder / "cycles.csv").write_text(CSV, encoding="utf-8")
	return folder


@pytest.fixture
def machine_cfg(ini, export_dir):
	with ini.open("a", encoding="utf-8") as handle:
		handle.write(MACHINE_INI.format(path=export_dir))
	return config.load(ini)


def test_config_reads_machine_sections(machine_cfg, export_dir):
	assert [m.equipment for m in machine_cfg.machines] == ["TB-0015"]
	machine = machine_cfg.machines[0]
	assert machine.driver == "csv_generic"
	assert machine.options["path"] == str(export_dir)
	assert machine.options["param.Nhiệt độ"] == "Temp"


def test_csv_generic_maps_columns_times_results_and_parameters(machine_cfg):
	machine = machine_cfg.machines[0]
	cycles = drivers.make(machine.driver, machine.options).fetch_cycles()
	assert [c.cycle_ref for c in cycles] == ["1001", "1002"]
	first, second = cycles
	assert first.load_id == "ME-261026-01"
	assert second.load_id is None
	assert first.started_at == "2026-10-26T09:00:00+07:00"
	assert first.ended_at == "2026-10-26T09:45:00+07:00"
	assert (first.result, second.result) == ("Pass", "Fail")
	assert first.parameters == [{"parameter_name": "Nhiệt độ", "value": "134,5"}]
	assert second.alerts == ["Door", "Low pressure"]
	payload = first.as_payload("csv_generic")
	assert payload["driver"] == "csv_generic"
	assert payload["cycle_ref"] == "1001"


def test_csv_generic_skips_rows_without_a_cycle_ref(tmp_path):
	folder = tmp_path / "x"
	folder.mkdir()
	(folder / "a.csv").write_text(
		"Cycle,Start\n,2026-10-26T09:00:00+07:00\n7,2026-10-26T09:00:00+07:00\n", "utf-8"
	)
	cycles = drivers.make(
		"csv_generic", {"path": str(folder), "col.cycle_ref": "Cycle", "col.started_at": "Start"}
	).fetch_cycles()
	assert [(c.cycle_ref, c.started_at) for c in cycles] == [("7", "2026-10-26T09:00:00+07:00")]


def test_api_stub_returns_nothing_and_unknown_driver_fails():
	assert drivers.make("api_stub", {}).fetch_cycles() == []
	with pytest.raises(ValueError):
		drivers.make("vendor_x", {})


def test_poll_sends_each_cycle_once(machine_cfg, stub, tmp_path):
	store = MachineStore(str(tmp_path / "machines.sqlite3"))
	client = ServerClient(machine_cfg)
	summary = poll_once(machine_cfg, client, store, now=1000.0)
	assert summary == {"sent": 2, "pending": 0, "rejected": 0, "dropped": 0}
	sent = [r for r in stub.requests if r["method"].endswith("ingest_machine_data")]
	assert [r["body"]["cycle"]["cycle_ref"] for r in sent] == ["1001", "1002"]
	assert sent[0]["body"]["equipment"] == "TB-0015"
	assert sent[0]["body"]["station"] == "TR-004"
	assert poll_once(machine_cfg, client, store, now=1060.0)["sent"] == 0


def test_unmatched_cycles_are_retried_then_dropped(machine_cfg, stub, tmp_path):
	store = MachineStore(str(tmp_path / "machines.sqlite3"))
	client = ServerClient(machine_cfg)
	stub.ingest_status = {"1002": 404, "1001": 409}
	assert poll_once(machine_cfg, client, store, now=1000.0) == {
		"sent": 0,
		"pending": 1,
		"rejected": 1,
		"dropped": 0,
	}
	stub.ingest_status = {}
	assert poll_once(machine_cfg, client, store, now=1060.0)["sent"] == 1
	stub.ingest_status = {"1002": 404}
	store2 = MachineStore(str(tmp_path / "other.sqlite3"))
	poll_once(machine_cfg, client, store2, now=0.0)
	late = poll_once(machine_cfg, client, store2, now=RETRY_SECONDS + 1.0)
	assert late["dropped"] == 1


def test_cycle_payload_defaults():
	cycle = CycleData(cycle_ref="9")
	assert cycle.as_payload("api_stub") == {
		"cycle_ref": "9",
		"load_id": None,
		"program": None,
		"started_at": None,
		"ended_at": None,
		"parameters": [],
		"alerts": [],
		"result": None,
		"driver": "api_stub",
	}
