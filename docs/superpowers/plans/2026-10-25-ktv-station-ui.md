# Native KTV R04 station workspace

Approved: KTV demo T3/T4, direct station entry with three operational counters, queue dialogs, scan, images/BOM, checklists, step gates and linked T3-to-T4 navigation. Keep Admin unchanged. Rename lookup to Tra cứu dụng cụ and personal overrides to Đề nghị của tôi; place override request at blocked set. Work on codex/tracecore-role-admin-ui, no merge.

- [x] Test role/step isolation, queue gate/cycle filtering and own-request scope before implementation (first run: missing module, five errors).
- [x] Add read-only ktv workspace and scan-context adapter using existing permissions and business sources. No demo numbers, no lifecycle updates through this adapter.
- [x] Vue KtvWorkspace separate from Admin shell. R04 default T3; T3/T4 side navigation, counters/inline queues, actual BOM/images, read and operational states, offline/loading/error, lookup and personal requests.
- [x] Use existing station login/heartbeat/logout and pack RPC contracts, bearer in memory only. Freeze idempotency payloads across uncertain retries. Card schema/capability unavailability blocks writes explicitly. Assembly writes remain deferred, as specified below.
- [x] Backend API and frontend contract tests; build; browser tests for navigation, scan, context/checklist, live read-only mode and mocked T4 operation contracts. No mocked or live T3 completion claimed.
- [x] Publish local build and document dependency limits accurately. Commit/push existing feature branch without merge after final review.

Backend boundary: current branch has only FEAT-018 T3 stub, while develop contains FEAT-020 assembly RPC. This UI change must not merge/cherry-pick another business feature, fabricate submitted assembly records or bypass card/PIN checks. Capabilities report genuine backend/schema availability; T3 operational controls stay disabled until that service is installed. Existing T4 service remains authoritative.

Local bench is a separate, older checkout. It also lacks full M8 override service and Employee card schema. Personal requests show an explicit unavailable state there; no fabricated requests or local-only approval logic. The existing Instrument Set Type schema was reloaded to add its already-defined missing image columns required by the BOM API. No global migrate or lifecycle data update was run.
