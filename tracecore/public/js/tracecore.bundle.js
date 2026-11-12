// Bundle Desk của TraceCore (app_include_js, tên có hash khi build): hàm dùng chung tracecore.codes.* (FEAT-005),
// hộp thoại sửa hạn lưu loại gói tracecore.shelf_life.* (FEAT-015) và hộp thoại cấp Set ID / in thẻ tracecore.set_unit.*
// (FEAT-016, dùng ở list Set Unit, form Set Unit và form loại bộ); thanh lý và chuyển trạng thái thủ công
// tracecore.admin.* (FEAT-004, form Set Unit và Pack); ô quét chung trên List View tracecore.list_scan.* (FEAT-006);
// nút xuất PDF nền / khóa kỳ trên báo cáo sổ tiệt khuẩn tracecore.report_export.* (FEAT-007); hộp thoại R02 hủy lô rửa /
// mẻ nhập sai tracecore.run_cancel.* (A-112); in PDF qua hộp thoại In window.tcPrintPdf (A-114, dùng cả ở Page station);
// thanh truy cập nhanh trên navbar window.TcQuickNav (NAV-05, nạp trước tc_launcher.js); địa chỉ trạm theo số
// window.TcStationUrl (NAV-07, dùng ở Page station, trang chủ và Trợ giúp trạm).
import "./tc_page_cache.js";
import "./tc_print_pdf.js";
import "./tc_codes.js";
import "./tc_desk_call.js";
import "./tc_admin_actions.js";
import "./tc_shelf_life.js";
import "./tc_set_unit.js";
import "./tc_station_url.js";
import "./tc_quick_nav.js";
import "./tc_launcher.js";
import "./tc_list_scan.js";
import "./tc_report_export.js";
import "./tc_run_cancel.js";
