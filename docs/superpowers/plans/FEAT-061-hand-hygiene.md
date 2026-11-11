# FEAT-061 Vệ sinh tay theo cơ hội (M12, SCR-51) — kế hoạch

> Nguồn: `docs/implementation-plan.md` §3 E-13 (FEAT-061), §6.1 DoD v1.12; `docs/srs.md` FR-M12-02 (.1, .2), FR-M12-04 (.1), FR-M12-05 (.1, .2), FR-M12-10 (.1), FR-M12-11 (.1), FR-M12-14, BRU-AUD-002, BRU-AUD-004, NFR-USAB-03, NFR-AVAIL-05, NFR-MAINT-04; `docs/use-cases.md` UC-43 (bước 1, A2), UC-44 (bước 1–4, 7; A1, A4; E1, E3, E5); `docs/architecture.md` ADR-015, sequence "phiếu PDA" (§6), A-134; `docs/ux-foundations.md` SCR-51 (anchor A4, luồng "Ghi cơ hội vệ sinh tay"); ảnh `docs/design-refs/v1.12/SCR-51_PDA-VeSinhTay.png`.
> Phụ thuộc: FEAT-060 (engine phiếu, đã trên `develop` 62a1fa2), FEAT-009 (outbox), FEAT-051 (Station Function). Sprint S6. Cỡ M.
> Nhánh: `feat/FEAT-061-hand-hygiene` (bench phụ `~/tracecore-f026`, site test `test_f026`).
> Song song FEAT-059/071: file dùng chung (`hooks.py`, `translations/vi.csv`, `station.css`, `core/errors.py`, `core/error_codes.py`, `core/tests/test_errors.py`, `v1/audit.py`) chỉ **nối thêm** khối có comment `FEAT-061`.

## Đã chốt với người dùng (10/11/2026)

- **Q1 — Bộ mẫu khởi tạo: đúng 8 mẫu theo SRS.** SRS FR-M12-02.1 và UC-43 nói "đúng 8 mẫu" (VST, PPE, 4 gói VAP/CLABSI/CAUTI/SSI, VSMT, thuê ngoài). Dòng FEAT-061 trong implementation-plan thêm ATTP, ADR-015 thêm ATTP và Tự đánh giá TT 35/2024. Chọn SRS làm gốc: ATTP thuộc FEAT-070 (FR-M17-01.1), Tự đánh giá thuộc FEAT-072 (FR-M11-13). Sửa dòng FEAT-061 bằng amendment **A-140**.
- **Q2 — Nội dung mục của mẫu (OQ-V12-08 còn mở): tôi soạn bản khởi đầu.** VST = 5 thời điểm WHO; PPE, 4 gói, VSMT, thuê ngoài = vài mục cơ bản theo QĐ 3671, QĐ 3916, TT 16/2018. Tất cả Nháp, ghi `legal_ref`, R01 sửa và duyệt tại bệnh viện. Nội dung là dữ liệu fixtures, không phải hằng số trong code.

## Quyết định thiết kế (mặc định, dùng nếu không bị phản đối)

- **D1 — Không thêm DocType, không đổi ma trận quyền.** `Hand Hygiene Opportunity` (child) và `client_uuid` đã có từ FEAT-060. Quyền R11/R12/R08/R01 theo `Audit Session` hiện có. Số dòng ma trận giữ nguyên 69.
- **D2 — Thời điểm sinh từ mẫu** (ux-foundations "bộ nút thời điểm phải sinh từ mẫu"). Mục của mẫu VST có `item_code` `MOMENT-<n>`; `moment` = chữ số cuối. PDA vẽ nút thời điểm từ các mục này; server chặn `moment` ngoài tập mục của mẫu (`AUDIT_OPPORTUNITY_INVALID`). Mẫu bệnh viện đổi số thời điểm không cần sửa code (giá trị `moment` vẫn 1–5 theo DocType).
- **D3 — Phiếu VST có vòng đời Nháp → Ghi sổ** (UC-44 bước 1 "tạo `Audit Session` Nháp"):
  - `record_opportunity(station, session_uuid, opportunity, audit_template, department, …)` `@idempotent` (key = UUID cơ hội). Lần gọi đầu của một `session_uuid` tạo phiếu Nháp (`client_uuid` = `session_uuid`); mỗi lần gọi thêm đúng một dòng `opportunities`, khử trùng theo `opportunity.uuid` (lưu ở `Hand Hygiene Opportunity.client_uuid`) nên phát lại sau khi khóa idempotent hết hạn vẫn không trùng.
  - `submit_session(session_uuid, …)` hiện có ghi sổ phiếu Nháp cùng `session_uuid` (không cần `answers`). Phiếu chưa có cơ hội nào → chặn `AUDIT_NO_OPPORTUNITY`. Cơ hội gửi sau khi phiếu đã ghi sổ → `AUDIT_SESSION_POSTED`.
  - Hàng đợi offline phát lại theo `client_ts` rồi `seq` (outbox sẵn có) nên các cơ hội luôn đến trước lệnh ghi sổ.
  - Phiếu Nháp bị bỏ dở không vào báo cáo (chỉ `docstatus = 1`). Dọn Nháp quá hạn: ngoài phạm vi, ghi vào follow-up.
- **D4 — Chấm "Theo cơ hội" (BRU-AUD-002).** Đăng ký `scoring.SCORERS["By Opportunity"]`: `score_pct` = cơ hội có hành động / tổng cơ hội (Chà tay cồn hoặc Rửa xà phòng = có hành động; "Không thực hiện" = không). `result`: Đạt/Không đạt theo `pass_threshold` của mẫu nếu có, ngược lại để trống. Tỷ lệ đúng kỹ thuật tách riêng = cơ hội có hành động và `technique_ok` / cơ hội có hành động (mẫu số không gồm "Không thực hiện", FR-M12-05.2). Tính theo cơ hội, không theo người.
- **D5 — Tổng hợp.** Module mới `compliance_audit/hand_hygiene.py` là nguồn duy nhất cho tỷ lệ VST theo khoa × nghề × thời điểm × tháng. `compliance.aggregate` (báo cáo SCR-53, hàm chỉ số) bỏ phiếu "Theo cơ hội" khỏi phần đếm phiếu Đạt/Không đạt và gộp dòng từ `hand_hygiene` (đếm theo cơ hội, cùng dạng dòng: n = số cơ hội, nhãn "Chưa đủ cỡ mẫu" theo `min_sample`). Đây là chỗ duy nhất FEAT-061 chạm vào hành vi engine, vì BRU-AUD-002 đòi mẫu số là cơ hội.
- **D6 — Cỡ mẫu (FR-M12-11).** Với mẫu "Theo cơ hội", `sample_n` của phiếu = số cơ hội đã ghi sổ của khoa-tháng (không phải số phiếu). Mẫu VST khởi tạo `min_sample = 30` theo mục tiêu "≥ 30 cơ hội/khoa/tháng" của UC-44; các mẫu khác để trống (OQ-V12-09, R01 đặt).
- **D7 — Nhãn tỷ lệ VST** luôn một chữ số thập phân ("82,0 %", FR-M12-05.1) theo định dạng số của site; dưới `min_sample` thêm "(n = 8, chưa đủ cỡ mẫu)"; n = 0 → "Không tính" (BRU-RPT-001). Docs lệch nhau: FR-M12-11.1 viết "75 %" cho báo cáo chung; VST theo FR-M12-05.1 (một chữ số thập phân).
- **D8 — Chỉ số M9 (hook `tracecore_ic_indicators`).** Thêm `HAND_HYGIENE_RATE` (cơ hội có hành động / tổng cơ hội) và `HAND_HYGIENE_TECHNIQUE` vào `compliance_audit.indicators.register`; `AUDIT_PASS_RATE` giữ nguyên nhưng không còn đếm phiếu VST (D5). R01 tạo `IC Indicator` trỏ tới các khóa.
- **D9 — Nạp bộ mẫu (NFR-MAINT-04).** `compliance_audit/seed.py` gọi `templates.install_templates` (chỉ chèn mã còn thiếu) từ `after_install` và `after_migrate`. Không dùng `fixtures` của Frappe (migrate nạp lại sẽ đè). Văn bản mục/tiêu đề lưu bằng tiếng Việt lấy từ `translations/vi.csv` qua `_(text, "vi")` (nguồn tiếng Anh trong code, không hard-code tiếng Việt); thiếu bản dịch thì dùng tiếng Anh. Test kiểm mọi chuỗi mẫu đều có bản dịch.
- **D10 — SCR-51 trong Page `station`** (chức năng trạm `AUDIT` sẵn có, không thêm Station Function). Chọn khoa rồi mẫu "Theo cơ hội" ở màn bắt đầu của `AuditForm` mở `HygieneView` (file `public/js/station_hand_hygiene.js`): thanh ngữ cảnh (khoa, vị trí, mã mẫu, số cơ hội + tỷ lệ tạm), chip nghề nghiệp, 5 nút thời điểm, 3 nút hành động (≥ 48 px, có chữ và ký hiệu), danh sách "Vừa ghi", nút Ghi sổ 56 px. **3 chạm**: thời điểm → nghề nghiệp (chip nhớ lựa chọn trước, mặc định lần đầu phải chọn) → hành động; hành động là chạm cuối và gửi ngay. `technique_ok` / `glove_instead` là tùy chọn, bật trước khi chạm hành động, không tính vào 3 chạm. Chặn tự đánh giá khi có `subject_employee` trùng người giám sát bằng alert-error inline (BRU-AUD-004), không lưu. Offline: xếp hàng `tracecore.v1.audit.record_opportunity` (thêm vào `TC_QUEUEABLE`) rồi `submit_session`.
- **D11 — Hiển thị trên SCR-53 (Desk).** `compliance_board` trả thêm `hand_hygiene` (theo nghề, theo thời điểm); `scr_53_tuan_thu.js` vẽ một khối bảng. Script Report mới `Hand Hygiene Compliance` lọc kỳ/khoa/nghề/thời điểm, nhóm theo Khoa / Nghề / Thời điểm / Tháng, xuất Excel/PDF.

## Acceptance criteria (EARS)

- **AC-1** (FR-M12-02, .1, .2; NFR-MAINT-04): Sau `after_install`/`after_migrate` hệ thống phải có đúng 8 mẫu khởi tạo (VST, PPE, VAP, CLABSI, CAUTI, SSI, VSMT, thuê ngoài) ở trạng thái Nháp, mỗi mẫu có `legal_ref`. Chạy hai lần không tạo trùng; mẫu đã sửa hoặc đã duyệt tại bệnh viện phải giữ nguyên.
- **AC-2** (FR-M12-04, .1; NFR-AVAIL-05): `record_opportunity` phải `@idempotent`. Gửi lại cùng key hoặc cùng `opportunity.uuid` 20 lần phải cho đúng 1 dòng cơ hội. Ghi 20 cơ hội lúc offline rồi phát lại phải ra đủ 20, 0 trùng; phiếu ghi sổ không trùng khi `submit_session` phát lại.
- **AC-3** (FR-M12-05, .1; BRU-AUD-002): 50 cơ hội với 41 có hành động phải ra tỷ lệ 82,0 %. Tỷ lệ tính theo cơ hội, không theo người (cùng một người nhiều cơ hội = nhiều cơ hội).
- **AC-4** (FR-M12-05.2): Tỷ lệ đúng kỹ thuật phải tách riêng và mẫu số không gồm cơ hội "Không thực hiện".
- **AC-5** (FR-M12-05): Phải xem được tỷ lệ theo khoa, nghề nghiệp, thời điểm và tháng; chỉ tính phiếu đã ghi sổ (Nháp/Hủy không tính, FR-M12-14.1); R08/R12 chỉ thấy khoa của mình.
- **AC-6** (FR-M12-10, .1; BRU-AUD-004): `subject_employee` của cơ hội trùng người giám sát phải bị chặn bằng lỗi có mã `AUDIT_SELF_OBSERVATION`, không lưu cơ hội, PDA hiện alert-error inline.
- **AC-7** (FR-M12-11, .1): Khoa–tháng có n < `min_sample` phải hiện "… (n = 8, chưa đủ cỡ mẫu)"; `sample_flag` của phiếu đặt theo số cơ hội của khoa–tháng.
- **AC-8** (UC-44 E3): Phiếu offline tạo trước khi mẫu lên phiên bản mới vẫn ghi sổ được với phiên bản lúc tạo (cơ chế `tc_replay` của FEAT-060 áp dụng cho cả đường VST).
- **AC-9** (NFR-USAB-03; SCR-51): Mỗi cơ hội ≤ 3 chạm (thời điểm, nghề nghiệp, hành động); nút ≥ 48 px, chữ ≥ 16 px, nút Ghi sổ 56 px; trạng thái luôn có chữ hoặc ký hiệu; đủ 4 trạng thái loading / empty / error / offline; chỉ dùng token `--tc-*`. Kiểm bằng test JS Node và test CSS, không chạy E2E.
- **AC-10** (FR-M12-14; hook `tracecore_ic_indicators`): `HAND_HYGIENE_RATE` và `HAND_HYGIENE_TECHNIQUE` có trong registry `core.indicators`, trả (tử, mẫu, cỡ mẫu) đúng.
- **AC-11** (NFR-MAINT-04, D10): Không có tiêu chí chuyên môn mã hóa cứng trong code; nút thời điểm sinh từ mục của mẫu.
- **AC-12**: Mọi chuỗi qua `_()`/`__()` và có trong `translations/vi.csv`. Toàn bộ test của app pass. diff-cover ≥ 70 %. `pre-commit run --all-files` sạch.

## Tasks (TDD — viết test trước, thấy fail rồi mới code)

1. **Chấm "Theo cơ hội" và kiểm cơ hội** (AC-3, AC-4, AC-6, AC-8): `hand_hygiene.py` (`moment_of`, `moments`, `check`, `stats`), đăng ký scorer, nối vào `sessions.validate`/`before_submit`; mã lỗi `AUDIT_NO_OPPORTUNITY`, `AUDIT_OPPORTUNITY_INVALID`, `AUDIT_SESSION_POSTED` (`core/errors.py`, `core/error_codes.py`, `test_errors.py`). Test `compliance_audit/tests/test_hand_hygiene.py` (`@bru("BRU-AUD-002")`, `@bru("BRU-AUD-004")`).
2. **Tổng hợp và cỡ mẫu** (AC-5, AC-7): `hand_hygiene.aggregate/breakdown/rate_label`, sửa `compliance.aggregate` (D5), `sessions.on_submit` (D6). Test `test_hand_hygiene_aggregate.py`.
3. **Bộ mẫu khởi tạo** (AC-1, AC-11, AC-12): `compliance_audit/seed.py`, hook `after_install`/`after_migrate`. Test `test_seed.py` (`@bru("BRU-AUD-001")`).
4. **RPC `record_opportunity`** (AC-2, AC-8): `pda.record_opportunity`, mở rộng `pda.submit`/`pda.context` (`opportunity_templates`), `v1/audit.py`. Test `v1/tests/test_audit_hygiene_api.py`.
5. **Chỉ số M9 và báo cáo** (AC-5, AC-10): `indicators.py`, Script Report `hand_hygiene_compliance`, `compliance_board.hand_hygiene`. Test cùng file task 2 và `test_hygiene_report.py`.
6. **SCR-51 trên Page `station`** (AC-9): `station_hand_hygiene.js`, nối `AuditForm`, `TC_QUEUEABLE`, `station.css`, `hooks.py` `page_js`. Test JS `tests/test_hygiene_screen.py`.
7. **SCR-53 khối VST** (D11): `scr_53_tuan_thu.js`. Test JS nối vào `test_hygiene_screen.py`.
8. **Bản dịch, amendment, kiểm tra cuối** (AC-12): `translations/vi.csv` (nối thêm), amendment A-140 (Revision History `architecture.md`, sửa dòng FEAT-061 `implementation-plan.md`), `pre-commit`, full suite qua khóa chung, `diff-cover`, push `origin` và `github`. Không PR, không merge.

## Ngoài phạm vi (follow-up)

- Dọn phiếu VST Nháp bị bỏ dở quá N ngày.
- E2E Playwright (chỉ chạy khi người dùng bảo), gồm đo ≤ 3 chạm trên PDA 412×915.
- ATTP (FEAT-070), Tự đánh giá (FEAT-072), gói dự phòng gắn đợt thiết bị (FEAT-062).
