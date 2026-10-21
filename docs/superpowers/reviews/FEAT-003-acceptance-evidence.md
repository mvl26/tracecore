# FEAT-003 acceptance evidence

Review branch: `feat/FEAT-003-rbac-station-auth`; Task 7 baseline: `04a222eaed7ce29cc2c47a369b29289fef60de6f`.
Environment: isolated `/home/tien2003/tracecore-codex`, Frappe/ERPNext/HRMS v15, MariaDB/Redis, cached Chromium.
Developer site: `tracecore-codex.local` on port 8100; integration site: `test_codex`.

## Acceptance-to-evidence map

Acceptance IDs below identify the FEAT-003 plan decisions A1–A8 and their concrete verification; they do not introduce new FR/BRU identifiers.

| Acceptance | FR / BRU / NFR | Executable evidence | Scope and limits |
| --- | --- | --- | --- |
| A1: R01–R10 SEC matrix, deterministic fixture, amendments and no delete | FR-M9-05; NFR-SEC-07 | `tracecore.tests.test_permissions`: ten roles/40 baseline DocTypes, symbol mapping, amendment precedence, audit immutability, generator/fixture equality; effective Zone Station/Equipment/Process Program permissions compared with the generated matrix | Future DocTypes stay in the matrix but receive no Custom DocPerm until present. R08 departmental filtering on future business documents is not certified by these tests. |
| A2: native web password + 2FA for privileged roles | FR-M9-05; NFR-SEC-01 | `test_privileged_roles_require_two_factor_auth`; account `test_settings_lock_after_fifth_failure_and_two_factor_roles`; native password-recovery + OTP login integration test; all live browser fixtures complete Frappe's real OTP challenge when enabled | Developer accounts receive generated private OTP seeds; production 2FA settings and authorization checks remain enabled. Native `All` role also requests OTP on this bench. |
| A3: unique normalized active Employee card and protected PIN fields | FR-M4-01 (partial); FR-M9-09 | account `test_card_normalized_and_duplicate_rejected`; `test_employee_auth_custom_fields_are_secure` checks unique card, hidden Password/no-copy PIN and read-only/no-copy reset flag; `TestStationDemoData` verifies reusable Employee/card, normalization and dev-only guards | HRMS Employee extension only; broader personnel UI/history belongs to FEAT-036. Card scans use keyboard/reader events; no physical reader was available. |
| A4/A5: opaque hashed bearer, absolute eight-hour/idle ten-minute expiry, one open session per Employee | FR-M9-08; NFR-SEC-01 | `tracecore.core.tests.test_station_auth`; `tracecore.v1.tests.test_station_security`: native Guest dispatch, replay/session checks, token hashing, wrong station/actor guards, second-station replacement; live `test_live_second_station_replaces_first_and_idle_revokes` | Live browser uses real server replacement and logout. Its idle test advances the controller's last-human-activity timestamp; exact server idle/absolute boundaries are exercised by integration tests rather than an eight-hour wait. |
| A6: valid station competency and temporary access <=24h | FR-M4-03 (partial); BRU-HR-001 | `@bru("BRU-HR-001")` on `test_login_requires_active_competency_and_returns_one_time_token`; model tests reject excessive temporary duration and missing reason/approver; inactive card/user/station and competency checks; demo has valid competency at TR-004 and TR-005 | Competency foundation only. Certificate/requirement workflows and complete SCR-20 UI remain FEAT-037. |
| A7: bcrypt PIN, three failures/Redis five-minute lock, bound single-use 120s proof | FR-M9-09; NFR-SEC-01 | station-auth `test_pin_is_bcrypt_and_three_failures_lock_for_five_minutes`; security `test_verify_pin_issues_hashed_120s_single_use_bound_proof`, expiry/revocation/other-session tests; account R02 reset and forced-change tests | No reusable demo PIN is seeded. Existing integration tests use disposable test PINs and assert secrets do not enter audit responses. |
| A8: minimum ten-character password, day-90 expiry, fifth-failure lock, secure resets and leaving-employee disable | FR-M9-09; NFR-SEC-08 (disable subset) | `tracecore.core.tests.test_account`: native update entry point, day-90 boundary, old-value changes, forced reset, real OTP recovery, explicit R10 authorization including Administrator, R02 proof, employee unlink/disable/concurrent state checks | Quarterly rights reviews and <=5-minute anomalous-login alerts are not implemented/certified in this slice; NFR-SEC-08 remains partial. |
| Auth/role/credential changes retain immutable history without secret plaintext | FR-M9-05; NFR-SEC-03 (auth subset); BRU-ID-006 | account audit assertions and no-delete tests; station-auth login/reject/logout audits; immutable Audit Log and matrix tests; server-packed identity comes from bearer actor, not client/cookie identity | This certifies the FEAT-003 authentication subset, not every application module's entire audit trail. |
| Locked shell, identity/roles, dedicated T4 CI input, safe logout and stale-response isolation | FR-M9-08; FR-M9-05; FEAT-018 regression | `tests_e2e/test_station_auth.py` runs real production JS in Chromium with routed RPCs; Node `scripts/tests/station_auth.test.js`; live `test_live_card_identity_t4_indicator_and_logout`; live smoke/T4 suite | Live tests exercise Frappe/MariaDB/Redis. Existing packing E2E intercepts only the physical printer-agent HTTP boundary; no physical label quality/reader hardware claim is made. |
| Idempotent private dev/test preparation | Task 7 | `TestStationDemoData`; `TestE2ePrepareGuard`: repeat seeds/preparation, generated/reused card+OTP, encrypted native OTP storage, mode-0600 env output, no stdout credential disclosure, production guard, temporary explicit R10 restored after success and exception | `BENCH_DIR` and `TC_E2E_ENV` must target the intended isolated bench. No fixed production password/PIN/token/OTP seed is shipped. |

## Verification record

The Task 7 handoff report at `.superpowers/sdd/task-7-report.md` records the full-suite, coverage, browser and hook commands/results and commit SHA. It also records the initial failing suite and the test-harness causes repaired without relaxing production security.

Final verification:

- Both `test_codex` and `tracecore-codex.local` migrations and `bench build --app tracecore` exited 0. Build emitted the existing caniuse-lite age advisory.
- The complete TraceCore Python suite passed 716/716 in 742.723s with coverage saved. `diff-cover` measured 94/96 changed Python lines, 97%, above the 70% gate.
- The refreshed live Chromium suite passed 51/51 in 192.44s, including native OTP Desk admin/equipment, real station login/T4/logout/replacement and routed frontend auth regressions. An earlier focused live station/smoke/T4 run passed 13/13 in 98.79s.
- Node auth regressions passed 15/15. Focused Pack and four repaired legacy modules passed 21/21, 9/9, 5/5, 6/6 and 19/19 respectively; an earlier affected set passed 61/61.
- All-files pre-commit passed every applicable hook, including architecture, BRU markers, token assets, Ruff, ESLint, Prettier and Bandit. Standalone architecture and BRU checks exited 0 (17/49 catalog markers currently covered).

## Reproduction

Run migrations/build and the full app suite in the isolated bench. Optional coverage/Playwright packages were reused from the local `uv` cache; no network installation was required.

```sh
cd /home/tien2003/tracecore-codex
bench --site test_codex migrate
bench --site tracecore-codex.local migrate
bench build --app tracecore
cd /home/tien2003/tracecore-codex/sites
uv run --offline --no-project --with coverage \
  --python /home/tien2003/tracecore-codex/env/bin/python \
  python -m frappe.utils.bench_helper frappe --site test_codex run-tests --app tracecore --coverage --skip-test-records
```

`--skip-test-records` skips Frappe automatic fixture generation, not test methods. The existing migrated integration site already has the required ERPNext/HRMS dependency records; no TraceCore module is excluded.

```sh
cd /home/tien2003/tracecore-codex/apps/tracecore
BENCH_DIR=/home/tien2003/tracecore-codex \
TC_E2E_ENV=/home/tien2003/tracecore-codex/.task7-e2e.env \
  bash scripts/e2e_prepare.sh tracecore-codex.local
# Export the private env locally; never copy its values into reports or source.
set -a
source /home/tien2003/tracecore-codex/.task7-e2e.env
set +a
TC_BASE_URL=http://127.0.0.1:8100 \
  uv run --offline --no-project --with pytest-playwright \
  --python /home/tien2003/tracecore-codex/env/bin/python pytest tests_e2e -q
node --test scripts/tests/station_auth.test.js
pre-commit run --all-files
python3 scripts/check_architecture.py
python3 scripts/check_bru_coverage.py
diff-cover ../../sites/coverage.xml --compare-branch=04a222eaed7ce29cc2c47a369b29289fef60de6f --fail-under=70
```

Stop at the reviewed branch. No push, merge, cherry-pick or deployment is authorized by this evidence artifact.
