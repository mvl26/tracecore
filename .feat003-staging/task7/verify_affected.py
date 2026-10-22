import re
import subprocess
from pathlib import Path

bench = Path("/home/tien2003/tracecore-codex")
cases = {
	"tracecore.core.tests.test_account": ["test_recovery_keeps_guest_session_until_password_and_real_otp_login", "test_only_r10_can_create_disable_users_even_ignore_permissions", "test_install_bootstrap_allows_creation_but_not_account_reset"],
	"tracecore.core.tests.test_idempotency": [],
	"tracecore.core.tests.test_errors": [],
	"tracecore.core.tests.test_station_models": [],
	"tracecore.admin_reports.doctype.zone_station.test_zone_station": ["test_permissions_match_e8"],
	"tracecore.equipment.doctype.equipment.test_equipment": ["test_permissions_match_q7"],
	"tracecore.equipment.doctype.process_program.test_process_program": ["test_permissions_match_q7", "test_r02_cannot_write_process_program"],
	"tracecore.equipment.tests.test_norms": ["test_r02_cannot_set_use_default_norms"],
	"tracecore.tests.test_devdata": [],
	"tracecore.tests.test_station_page": [],
}
failed = False
for module, tests in cases.items():
	command = ["bench", "--site", "test_codex", "run-tests", "--module", module, "--skip-test-records"]
	for test in tests:
		command.extend(["--test", test])
	result = subprocess.run(command, cwd=bench, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
	log = Path("/tmp/feat003-task7-affected-" + module.rsplit(".", 1)[-1] + ".log")
	log.write_text(result.stdout)
	passed = not result.returncode and bool(re.search(r"\nOK\s*(?:\n|$)", result.stdout)) and "FAILED (" not in result.stdout
	print(module, "PASS" if passed else "FAIL", "; ".join(re.findall(r"(?:Ran \d+ tests? in [^\n]+|FAILED \([^\n]+)", result.stdout)), flush=True)
	if not passed:
		print(result.stdout[-6000:], flush=True)
		failed = True
raise SystemExit(1 if failed else 0)
