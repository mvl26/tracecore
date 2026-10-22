# FEAT-003 Task 5 report

Status: DONE

Commit: `340f490e8022d1da531c04dc96e3ab2fbc70de91`

Branch: `feat/FEAT-003-rbac-station-auth`

Base: `26cc740`

Repository: `/home/tien2003/tracecore-codex/apps/tracecore`

Only the isolated Codex bench and its `test_codex` site were used. No files under `/home/tien2003/tracecore-dev` or tracked source under `D:/tracecore` were modified. Windows `.feat003-staging` was used for sandbox-safe `apply_patch` edits followed by mechanical copies. The pre-existing untracked `.superpowers/` brief was preserved; this report is an untracked handoff artifact, not part of the implementation commit.

## Files

- `tracecore/core/account.py`: password policy and expiry, native recovery override, old-secret changes, authorized resets, single-use station PIN proofs, lifecycle guards, offboarding and secret-free audit events.
- `tracecore/core/tests/test_account.py`: 19 focused integration/regression tests.
- `tracecore/fixtures/custom_field.json`: Employee `tc_pin_reset_required` check field. Existing PIN storage remains the encrypted Password field containing bcrypt.
- `tracecore/hooks.py`: User/Employee lifecycle and no-delete hooks, login expiry enforcement, native password method override, policy application after migration.
- `tracecore/setup/install.py`: password/lockout settings and native role-based OTP App 2FA configuration.
- `tracecore/setup/provision.py`: R10-only provisioning, minimum password validation, password-date initialization.
- `tracecore/translations/vi.csv`: Vietnamese account/PIN/password error strings and reset field label.
- `tracecore/v1/station.py`: privileged PIN verification refuses a reset PIN until changed.

## Test-first evidence

Before implementation:

```sh
cd /home/tien2003/tracecore-codex
bench --site test_codex run-tests --module tracecore.core.tests.test_account --skip-test-records
```

Result: `Ran 15 tests in 0.010s`, `FAILED (failures=15)`. Each test's setup explicitly asserted that the missing account lifecycle module existed, producing `AssertionError: unexpectedly None : Task 5 account lifecycle is missing` rather than import errors.

First implementation run: 12/15 passed, 3 errors. Evidence identified two concrete causes: Redis returns bytes that must be decoded before Frappe JSON parsing; ERPNext requires a relieving date for status Left. Both were fixed without changing the account requirements. The original suite subsequently passed `15 tests in 48.778s`.

Additional self-review regression tests were written and run before their fixes:

```sh
bench --site test_codex run-tests --module tracecore.core.tests.test_account --test test_document_save_cannot_bypass_credential_reset_state --test test_pin_change_audit_uses_authenticated_station_employee --test test_native_password_recovery_clears_forced_expiry --skip-test-records
```

Result: `Ran 3 tests in 12.993s`, `FAILED (failures=2)`. Native recovery already passed. The two failing assertions demonstrated that an Employee document could clear PIN reset state and that PIN change audit attributed the action to the surrounding web/kiosk user instead of the authenticated station employee.

```sh
bench --site test_codex run-tests --module tracecore.core.tests.test_account --test test_document_save_cannot_extend_password_expiry --skip-test-records
```

Result: `Ran 1 test in 2.485s`, `FAILED (failures=1)`, `PermissionError not raised`. This demonstrated a document-save bypass of the password reset date. Guards were then added and PIN change execution was scoped through `as_session_user`.

## Implementation details

- Minimum password length is 10 on account actions, initial User passwords, provisioning, and the overridden Frappe password-change/recovery endpoint. Existing User form password writes are rejected in favor of the old-password/proof-checked account actions.
- Password expiry uses the actual native `User.last_password_reset_date` Date field, with application validation at `date_diff >= 90`. Missing dates fall back to User creation. The login hook also rejects expired direct login operations. Native recovery remains functional through a request-local marker set only after the native old-password/recovery-key verifier succeeds.
- Frappe v15's `LoginManager.force_user_to_reset_password` uses `date_diff > setting`; therefore the setting is **89**, yielding expiry on day **90**, not day 91. No invented `password_expiry` field was added.
- Frappe v15's `LoginAttemptTracker.is_user_allowed` uses `failed_count > setting`; therefore the setting is **4**, yielding denial after the **fifth** consecutive failure. The 300-second lockout and actual tracker boundaries are tested.
- Native OTP App 2FA is enabled for TC R01/R02/R09/R10 and disabled on the other TC R01..R10 roles. Restricted-IP bypass is disabled. Installation and migration apply these native role settings.
- Self-service password and PIN changes require the old secret. Password changes update the native date and invalidate linked station sessions. PIN changes clear the forced-change flag and audit as the station employee.
- R10 resets are permitted. R02 resets require a server-issued, 120-second PIN proof bound to the current user and a live station session. A raw User, Employee name, station bearer token, missing proof, expired proof, consumed proof, wrong actor or closed session is rejected. Proof keys contain SHA-256 of random tokens; proof values contain only user/session identifiers. Atomic Redis MULTI/EXEC GET-and-DELETE ensures one consumer and avoids requiring Redis 6.2 GETDEL.
- Password resets write the native reset date to `1900-01-01`, forcing the next native login through password recovery. PIN resets set persistent Employee reset state, which cannot be cleared by a generic document save; privileged PIN verification returns `PIN_CHANGE_REQUIRED` until the old-PIN-checked change succeeds.
- Employee card IDs are trimmed, uppercased and checked for uniqueness in addition to the existing database unique field.
- Card disable closes every open linked station session. Status Left also disables the card and linked User; the native User lifecycle clears web sessions and the app closes station sessions. Offboarding of a linked enabled User requires R10.
- User creation/enable/disable is guarded at the document layer, including calls using `ignore_permissions=True`; provisioning also checks R10. User, Employee and the existing Station Session/Audit Log no-delete protections preserve history.
- Credential audit payloads contain event names and access-state metadata only. No plaintext password, PIN, encrypted hash, recovery token or reset proof is written to app audit events. Tests inspect audit bodies for old/new secret leakage.

## Exact validation commands and results

All commands below ran in the isolated WSL Ubuntu-22.04 distribution. The Windows wrapper was `wsl -d Ubuntu-22.04 -- bash -lc "..."` with the required sandbox escalation. The default WSL distribution was not used after its initial discovery error (it was docker-desktop, not Ubuntu).

```sh
cd /home/tien2003/tracecore-codex
bench --site test_codex migrate
```

Result: completed successfully, including fixtures and `after_migrate` policy hook; only `test_codex` migrated.

```sh
cd /home/tien2003/tracecore-codex/apps/tracecore
pre-commit run --files tracecore/core/account.py tracecore/core/tests/test_account.py tracecore/hooks.py tracecore/setup/install.py tracecore/setup/provision.py tracecore/fixtures/custom_field.json tracecore/translations/vi.csv tracecore/v1/station.py
```

Result: final run exit 0. All applicable hooks passed: whitespace, conflict, AST, JSON, debug statements, Ruff imports/lint/format, Bandit, architecture rules and BRU coverage. Non-applicable TOML/YAML/JS/CSS hooks skipped. Earlier formatter runs changed only the two new Python files; those changes were staged and the complete checks rerun successfully.

```sh
cd /home/tien2003/tracecore-codex
bench --site test_codex run-tests --module tracecore.core.tests.test_account --skip-test-records
bench --site test_codex run-tests --module tracecore.core.tests.test_station_auth --skip-test-records
bench --site test_codex run-tests --module tracecore.tests.test_provision --skip-test-records
bench --site test_codex run-tests --module tracecore.tests.test_install --skip-test-records
```

Results: **19 account tests OK (67.270s); 6 station-auth tests OK (10.351s); 4 provisioning tests OK (1.261s); 3 installation tests OK (0.026s)**. Total: **32 tests passed**.

After the final portable Redis atomic-consumption refactor, all relevant pre-commit checks were rerun and passed, followed by:

```sh
bench --site test_codex run-tests --module tracecore.core.tests.test_account --test test_r02_reset_requires_single_use_live_station_pin_proof --test test_proof_expires_and_is_bound_to_actor_and_open_session --skip-test-records
```

Result: **2 tests OK (5.746s)**, verifying the exact changed proof-consumption path, expiry, replay, actor/session binding.

```sh
cd /home/tien2003/tracecore-codex/apps/tracecore
git diff --cached --check
git commit -m 'feat(auth): quản trị tài khoản và vô hiệu nhân viên'
chmod 644 tracecore/core/account.py tracecore/core/tests/test_account.py
git add tracecore/core/account.py tracecore/core/tests/test_account.py
git commit --amend --no-edit
git rev-parse HEAD
git status --short
git diff HEAD --check
```

Result: final commit `340f490e8022d1da531c04dc96e3ab2fbc70de91`; exactly eight Task 5 files, 604 insertions / 1 deletion; both new Python files are mode 100644. No tracked worktree changes remain; only the preserved untracked `.superpowers/` handoff directory exists. The last amendment changed file modes only, after verified code had been committed.

## Self-review and concerns

- Re-read Task 5 brief and checked every binding decision against implementation/test coverage.
- Inspected actual local Frappe v15 source to verify settings names, strict comparison boundaries, recovery verification and native disabled-User session clearing.
- Searched every production `verify_pin` caller: station privilege verification and proof issuance enforce forced PIN change; the dedicated change operation intentionally allows the old temporary PIN so it can be replaced.
- Reviewed staged diff, scope, audit payloads, no-delete behavior, role checks, proof storage, Redis atomicity and recovery marker cleanup. No unrelated tracked files changed.
- Frappe's built-in `Administrator` remains the bootstrap/recovery exception to the R10 business-role guard. Ordinary System Manager/TC role users still need TC R10. This is intentional framework administration compatibility, not an R02 reset bypass.
- Expiry follows the native Date field's calendar-day semantics, with the application boundary tested at days 89 and 90. This does not introduce timestamp-based credential-age tracking.
- Actual interactive OTP enrollment/browser login was not exercised. Native 2FA settings and exact selected role flags were verified against database and Frappe source; real OTP delivery/enrollment remains native Frappe behavior.
- No blocking concerns remain. The full broad app suite was not run; the requested account tests plus directly affected station/provision/install modules and all relevant pre-commit checks passed.
