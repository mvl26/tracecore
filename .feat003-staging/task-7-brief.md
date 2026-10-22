## Task 7: Devdata, regression và bàn giao review

**Files:** Modify devdata/e2e prepare/tests, RTM if needed.

- [ ] Seed demo Employee/card/competency idempotent, no fixed production secret.
- [ ] Migrate/build dev; unit/integration entire app; Playwright login → T4 → logout.
- [ ] Run coverage, diff-cover >=70, pre-commit, architecture and BRU checks.
- [ ] Produce AC → evidence table for all FR/BRU scope.
- [ ] Stop at verified branch; do not merge/deploy; request review before PR/cherry-pick.

### Binding handoff

- Existing e2e station fixtures now require `TC_E2E_CARD_ID` / `TC_E2E_T4_CARD_ID`, scanning after Desk login. Seed matching active Employee/User/card/competency at TR-004 (and second station where needed) idempotently.
- Never hardcode production passwords, PINs, tokens, or permanent demo secrets. Test/dev credentials must be generated or accepted via environment and restricted to developer/test setup.
- Exercise real site/browser flow where environment permits: card login, identity/roles, T4 set scan, dedicated indicator lot input, logout; second login invalidates first; session expiry/idle where practical.
- Run both test_codex and tracecore-codex.local migrate, asset build, full TraceCore test suite or justified scoped exclusions, changed-code coverage >=70, pre-commit all files, architecture check, BRU/check scripts.
- Verify no changes in ~/tracecore-dev and no merge/deploy/push.
- Create a concise AC/FR/BRU evidence artifact under docs/superpowers/reviews or .superpowers report as appropriate; do not invent compliance for unexercised physical reader hardware.
