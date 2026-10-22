# FEAT-003 Task 4 — station API and RPC authorization

Status: **DONE_WITH_CONCERNS**. All 116 final focused/regression tests and applicable pre-commit checks pass. Nonblocking validation limits are recorded below.

## Scope and environment

- Authorized isolated bench: `/home/tien2003/tracecore-codex` in WSL `Ubuntu-22.04`.
- Repository: `/home/tien2003/tracecore-codex/apps/tracecore`.
- Branch: `feat/FEAT-003-rbac-station-auth`; starting HEAD: `b32936373ae3a052406633b95d0726760d961046`.
- Test site: `test_codex` only. No migration, deployment, merge, push, account message or external publication was performed.
- Normal development bench `/home/tien2003/tracecore-dev` and tracked `D:/tracecore` source were not changed. `D:/tracecore/.feat003-staging/task4` was used for apply_patch edits, followed by mechanical copies to the isolated bench. Static formatting was performed by existing pre-commit hooks.
- The parent authorized the missing core PIN proof implementation and subsequent consolidation of the existing Task5 proof path into the station proof path.

## Resulting API contracts

`tracecore.v1.station.login/logout/heartbeat/verify_pin` are Guest-allowed POST-only endpoints. All four require `client_ts` through the existing ISO-8601-with-offset parser and its 400 error contract. Nonscalar login credentials/station or PIN produce generic 400 validation errors without echoing the supplied secret. Missing/invalid/closed/expired/idle station tokens use stable structured session errors and HTTP 401. Invalid cards and incorrect PIN use 403; the third failed PIN locks for five minutes and returns 429. Forced PIN change remains 409.

Login accepts `card_id`, `station`, `client_ts`; its successful `session` object contains the opaque token once, display name, employee/user/station identifiers, business roles and expiry. The database contains only SHA-256 of the bearer token. Auth audit events carry the parsed UTC client timestamp. Login and PIN proof responses deliberately do not use the persistent Idempotency Key response cache, which would retain plaintext credentials. Repeated explicit logins replace the old session rather than retrieving a stored token response. Heartbeat remains an overwrite-style session activity update; logout closes an authenticated session once.

Subsequent kiosk calls pass `token` as a body argument. Standard `Authorization: Bearer` is deliberately not advertised or supported for station tokens: local Frappe `validate_auth()` interprets it as OAuth and rejects Guest before dispatch. A regression calls the real native `validate_auth()` and `execute_cmd()` with a POST request and body token to verify the supported transport.

Pack `scan/generate_cycle_id/reprint_label/void` and the kiosk path of `printer.set_roll` require a live station session, even from an Administrator/System Manager Frappe login. The guard runs before idempotency lookup, authenticates and touches the station session, rejects a conflicting station with `SESSION_STATION_MISMATCH`/403, checks the session actor's roles, and calls existing code as the session user. It restores the original Frappe caller in `finally`, on success or exception. Pack station, `packed_by_user` and audit actor therefore derive from the session. Extra client employee/user/packed-by fields do not override them. Native Python positional calls remain supported by argument binding.

Existing business validation, Pack idempotency keys/rejection replay statuses, timestamp/skew behavior, maintenance, indicators, reprint/void and printer waiting-label behavior remain in the existing FEAT-018 implementation. Explicit-printer Desk operations retain their R10/System Manager authorization. Existing `station.config`, `agent.heartbeat`, `print.test_label` and `print.ack` machine paths retain their TC Agent/API-key and station-binding checks; no station-human proof substitutes for machine credentials.

## Canonical PIN proof

`station.verify_pin(token, pin, client_ts)` now returns `{ok: true, proof, expires_in: 120}`. Proof values are random opaque strings. Redis keys include their SHA-256, and Redis values contain only the session, employee and user identifiers. The proof is never included in database/audit records or a persistent idempotency response.

`station_auth.consume_pin_proof(token, proof)` authenticates the current live session and rejects forced PIN reset state, then performs atomic Redis MULTI/EXEC GET+DELETE. It checks session, employee and user binding and rejects missing, expired, consumed or mismatched proofs with `PIN_PROOF_INVALID`/403. Native Redis calls avoid local wrapper caching and do not depend on Redis 6.2 GETDEL.

The duplicated Task5 `account.issue_reset_proof` public producer and account-proof Redis namespace were removed. R02 `account.reset_password/reset_pin` now accept `proof` plus `token` and consume the canonical station proof, retaining the actual assigned R02 role and current Frappe-user/session-user equality requirements. The existing R10 web reset path is unchanged. All existing Task5 proof regressions were migrated to `station.verify_pin`. Forced PIN reset validation uses the current Employee locking read, preserving revocation semantics even if an earlier ordinary read established an old transaction snapshot.

## RED evidence

All commands were wrapped with `wsl.exe -d Ubuntu-22.04 -e bash -lc '...'` and authorized sandbox escalation. Bench commands below ran from `/home/tien2003/tracecore-codex`; repository commands ran from its `apps/tracecore` folder.

1. Before implementation:

   `bench --site test_codex run-tests --module tracecore.v1.tests.test_station_security --skip-test-records`

   `Ran 10 tests in 22.199s; FAILED (failures=7, errors=13)`. Assertions showed missing timestamps accepted, unauthenticated Pack calls returning business lookup errors instead of SESSION_INVALID, Guest whitelist rejection, missing roles schema and missing proof fields. One generate subcase used a fixed old timestamp and reached clock-skew validation; the fixture was corrected to current UTC before continuing.

2. Corrected isolated bearer RED before implementation:

   `bench --site test_codex run-tests --module tracecore.v1.tests.test_station_security --test test_all_pack_rpcs_require_live_session_even_for_frappe_admin --skip-test-records`

   `Ran 1 test in 2.928s; FAILED (failures=4)`. All four actions reached business logic (`PACK_NOT_FOUND` or `SCAN_INVALID`) without a station token.

3. Credential schema RED before adding validation:

   `bench --site test_codex run-tests --module tracecore.v1.tests.test_station_security --test test_auth_schema_rejects_nonscalar_credentials_without_echoing_them --skip-test-records`

   `Ran 1 test in 2.236s; FAILED (errors=2)`: malformed card dict reached `.strip()` and raised AttributeError rather than a generic 400; the secondary assertion-context error followed that unexpected exception. Added explicit scalar validation and confirmed the complete module green.

4. Canonical proof integration RED:

   `bench --site test_codex run-tests --module tracecore.core.tests.test_account --test test_r02_reset_requires_single_use_live_station_pin_proof --test test_station_verify_pin_is_the_only_public_proof_producer --skip-test-records`

   `Ran 2 tests in 12.381s; FAILED (failures=1, errors=1)`: account reset did not accept `token`, and the duplicate public proof producer still existed. Implementation then removed the duplicate and delegated to the canonical consumer.

5. Positional-call RED before guard normalization:

   `bench --site test_codex run-tests --module tracecore.v1.tests.test_station_security --test test_guard_preserves_positional_python_call_contract --skip-test-records`

   `Ran 1 test in 1.656s; FAILED (failures=1)`: the valid positional station call produced SESSION_STATION_MISMATCH because the initial guard read keyword arguments only. Binding the wrapped signature corrected it.

6. Current-read PIN reset state RED during self-review:

   `bench --site test_codex run-tests --module tracecore.v1.tests.test_station_security --test test_pin_proof_uses_locked_reset_state_after_waiting_on_employee --skip-test-records`

   After correcting two database-spy signature errors without production changes, the meaningful RED was `Ran 1 test in 2.387s; FAILED (failures=1)`, `AssertionError: True is not false`. An injected old ordinary snapshot of `tc_pin_reset_required` allowed proof issuance after the current locked Employee row required a PIN change. `require_pin_changed` now obtains the authoritative locking read; the final security module verifies both issuance and consumption reject that state.

## Validation history

- Initial green implementation: security 9/10; one station mismatch case exposed a local variable named `_` shadowing translation. Corrected the variable and reran.
- Security suite passed 11 tests (24.287s), then passed 13 tests (41.176s) after body-token native dispatch and positional-call coverage.
- First FEAT-018 Pack run: 46/48 passed. Two wrong-step tests still supplied a TR-004 session while asking for TR-003; updated those fixtures to obtain a legitimate session at the tested non-T4 station, retaining their original STATION_WRONG_STEP/422 assertions. That run measured P95 243ms, max 331ms for AC-15.
- Full sequential run initially recorded account 29/30 with a native OTP verification error; investigation and final rerun evidence are recorded in the final validation section.
- All applicable pre-commit hooks passed on the 12 Task4 files before the final current-read proof regression: whitespace, conflicts, AST, debug statements, Ruff import/lint/format, Bandit, architecture and BRU checks. Non-applicable JSON/TOML/YAML/JS/CSS hooks skipped.

## Final validation, commit and self-review

Final commands, all on `test_codex`:

```sh
cd /home/tien2003/tracecore-codex
bench --site test_codex run-tests --module tracecore.v1.tests.test_station_security --skip-test-records
bench --site test_codex run-tests --module tracecore.core.tests.test_account --skip-test-records
bench --site test_codex run-tests --module tracecore.core.tests.test_station_auth --skip-test-records
bench --site test_codex run-tests --module tracecore.v1.tests.test_pack_api --skip-test-records
bench --site test_codex run-tests --module tracecore.v1.tests.test_agent_api --skip-test-records
bench --site test_codex run-tests --module tracecore.v1.tests.test_station_api --skip-test-records
```

Final results by module:

| Module | Tests | Result | Time |
| --- | ---: | --- | ---: |
| Station security | 14 | OK | 23.319s |
| Account lifecycle and native recovery/OTP | 30 | OK | 88.278s |
| Core station auth | 6 | OK | 10.710s |
| FEAT-018 Pack APIs | 48 | OK | 112.770s |
| TC Agent APIs | 9 | OK | 3.838s |
| Station config APIs | 9 | OK | 4.661s |
| Total | **116** | **OK** | |

Pack AC-15: **P95 364ms**, max 408ms, under the 1-second threshold. The final Pack run included all final guard/body-token/positional-call changes. Subsequent production changes only hardened proof reset-state validation, which Pack does not call, and updated explanatory docstrings.

The initial agent/config regression attempt failed during fixture User creation because Task5 now requires an explicit R10 assignment, including Administrator. The fixtures now give Administrator its explicit test role. Two agent tests also created secondary test users while acting as the agent; their provisioning is now explicitly performed as the R10 fixture before switching to the tested actor. Existing machine endpoint authorization assertions are unchanged. No production TC Agent code was changed.

The first combined run had one native TOTP verification failure (`Incorrect Verification code`) in the existing real-login account regression. Its test and production login/recovery implementation were unchanged. The trace confirmed failure in native `pyotp.TOTP.verify`, not the new station proof path. The same isolated regression passed (`Ran 1 test in 3.701s; OK`), then the complete final account module passed all 30 tests, including that real OTP test (3.59s). No speculative production recovery fix or OTP bypass was introduced. The cause was not reproduced, so a clock-boundary or native defaults/cache timing explanation remains a hypothesis, not an asserted diagnosis.

Static checks:

```sh
cd /home/tien2003/tracecore-codex/apps/tracecore
pre-commit run --files tracecore/core/account.py tracecore/core/errors.py tracecore/core/station_auth.py tracecore/core/tests/test_account.py tracecore/core/tests/test_station_auth.py tracecore/v1/station.py tracecore/v1/_common.py tracecore/v1/pack.py tracecore/v1/printer.py tracecore/v1/tests/test_pack_api.py tracecore/v1/tests/test_station_security.py tracecore/v1/tests/station_fixtures.py tracecore/v1/tests/test_agent_api.py tracecore/v1/tests/test_station_api.py
git diff --cached --check
```

Result: **exit 0**, all applicable hooks passed. Earlier import/format hook rewrites were followed by clean complete reruns. The last test-only agent fixture correction also passed its own applicable hooks and nine tests. Frappe bench may return shell exit 0 even after unittest failures; all reported success claims above are based on explicit `Ran N tests` / `OK` output, not shell exit code alone.

Self-review checked staged file scope, bearer removal before idempotency hashing/storage, live authentication and actor-role checks before replay, restoration on errors, native Guest dispatch, inability to spoof Pack actor/station, proof hashing/TTL/atomic consumption, Employee/session/user binding, forced PIN-change revocation, and preservation of TC Agent/Desk behavior. New test files are mode 100644. Existing tracked file modes are preserved.

Nonblocking concerns and handoff requirements:

- The native OTP integration had one intermittent initial failure and passed both the isolated rerun and final full module. It remains documented because its root cause was not reproduced.
- Concurrency validation is deterministic locking/current-read regression plus real atomic Redis consumption; no live two-database-connection scheduler race was run. Existing Task5 deterministic revocation/current-read tests remain green.
- The broad application suite, browser shell and Task6 E2E flow were not run. Task6 callers must send `client_ts` for all four station auth endpoints, body `token` for kiosk Pack/printer calls, and use `station.verify_pin`'s `proof` plus `token` for R02 account resets. The removed `account.issue_reset_proof` endpoint must not be used.
- Full feature-wide coverage/RTM, browser work and final integration remain Task6/7 responsibilities; no deployment or merge was performed.

Commit: **`1e025f5036462fa1df3c19d973ace0f9f9ddc44b`** — `feat(v1): API phiên và xác minh PIN trạm`.

Committed exactly 14 Task4 files, 623 insertions and 158 deletions. Final `git status --short` contains only the preserved untracked `.superpowers/` handoff directory; no tracked worktree changes remain. This report stays in that handoff directory and is not included among tracked production/test changes.
