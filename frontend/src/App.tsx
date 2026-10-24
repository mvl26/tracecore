import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { homeApi, PermissionError, SessionExpiredError } from "./api";
import type { HomeContext, HomeNavigation } from "./api";
import { resolveRoute } from "./routes";

// Home owns Vietnamese presentation; server labels are already translated by Frappe.
const _ = (text: string) => text;
type Phase =
  | "loading"
  | "ready"
  | "error"
  | "permission"
  | "session"
  | "mismatch"
  | "stale";
type Destination = HomeNavigation & { href: string };
type Attention = HomeNavigation & {
  reason: string;
  severity: "critical" | "warning" | "info";
  action_label: string;
};

function destination(
  item: HomeNavigation,
  context: HomeContext
): Destination | null {
  if (!context.capabilities.includes(item.route_key)) return null;
  if (
    item.route_key === "frappe-admin" &&
    !context.shortcuts.some((shortcut) => shortcut.route_key === "frappe-admin")
  )
    return null;
  try {
    return { ...item, href: resolveRoute(item.route_key) };
  } catch {
    return null;
  }
}

function formatTime(timestamp: string, dateOnly = false) {
  const value = new Date(timestamp);
  if (Number.isNaN(value.getTime())) return _("Không rõ thời điểm cập nhật");
  return new Intl.DateTimeFormat("vi-VN", {
    timeZone: "Asia/Ho_Chi_Minh",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    ...(dateOnly ? {} : { hour: "2-digit", minute: "2-digit", hour12: false }),
  }).format(value);
}

function RouteAction({
  item,
  readOnly,
  children,
  className = "",
}: {
  item: Destination;
  readOnly: boolean;
  children: ReactNode;
  className?: string;
}) {
  return readOnly ? (
    <span className={`tc-disabled ${className}`} aria-disabled="true">
      {children}
    </span>
  ) : (
    <a className={className} href={item.href}>
      {children}
    </a>
  );
}

function Sidebar({
  context,
  readOnly,
  online,
  open,
  logout,
  loggingOut,
  close,
}: {
  context: HomeContext | null;
  readOnly: boolean;
  online: boolean;
  open: boolean;
  logout: () => void;
  loggingOut: boolean;
  close: () => void;
}) {
  const navigation =
    context?.navigation.flatMap((item) => {
      const route = destination(item, context);
      return route ? [route] : [];
    }) ?? [];
  return (
    <aside
      id="tc-sidebar"
      className={`tc-sidebar${open ? " tc-sidebar-open" : ""}`}
    >
      <div className="tc-brand">
        <span className="tc-brand-mark" aria-hidden="true">
          +
        </span>
        <span>
          TraceCore<small>{_("Kiểm soát nhiễm khuẩn · CSSD")}</small>
        </span>
      </div>
      <div className="tc-identity">
        {context ? (
          <>
            <strong>{context.user.full_name}</strong>
            <p>{context.user.roles.join(" · ")}</p>
            {context.user.stations.map((station) => (
              <p key={station.name}>
                {station.step} · {station.label}
              </p>
            ))}
          </>
        ) : (
          <strong>{_("Không gian làm việc")}</strong>
        )}
      </div>
      <nav aria-label={_("Điều hướng chính")} onClick={close}>
        <a className="tc-nav-home" href="/tracecore" aria-current="page">
          {_("Trang chủ")}
        </a>
        {navigation.map((item) => (
          <RouteAction key={item.key} item={item} readOnly={readOnly}>
            {item.label}
          </RouteAction>
        ))}
      </nav>
      <div className="tc-sidebar-footer">
        <p className={online ? "tc-connected" : "tc-disconnected"}>
          <span aria-hidden="true">●</span>{" "}
          {online ? _("Trực tuyến") : _("Ngoại tuyến")}
        </p>
        {context && (
          <button
            type="button"
            className="tc-button"
            onClick={logout}
            disabled={!online || loggingOut}
          >
            {loggingOut ? _("Đang đăng xuất…") : _("Đăng xuất")}
          </button>
        )}
      </div>
    </aside>
  );
}

function HomeHeader({
  context,
  readOnly,
  refresh,
  refreshing,
}: {
  context: HomeContext | null;
  readOnly: boolean;
  refresh: () => void;
  refreshing: boolean;
}) {
  const search = context?.shortcuts.find((item) => item.route_key === "search");
  const searchRoute = context && search ? destination(search, context) : null;
  return (
    <header className="tc-home-header">
      <div>
        <p className="tc-eyebrow">{_("Trang chủ · Tổng quan công việc")}</p>
        <h1>
          {context
            ? `${_("Xin chào,")} ${context.user.full_name}`
            : _("Trang chủ TraceCore")}
        </h1>
        {context && (
          <div className="tc-context">
            <time dateTime={context.system.server_time}>
              {formatTime(context.system.server_time, true)}
            </time>
            {context.user.roles.length > 0 && (
              <span>{context.user.roles.join(" · ")}</span>
            )}
            {context.user.stations.map((station) => (
              <span key={station.name}>
                {station.step} · {station.label}
              </span>
            ))}
          </div>
        )}
      </div>
      <div className="tc-header-actions">
        {searchRoute && (
          <RouteAction
            item={searchRoute}
            readOnly={readOnly}
            className="tc-button tc-button-primary"
          >
            {search?.label}
          </RouteAction>
        )}
        {context && (
          <button
            type="button"
            className="tc-button"
            disabled={refreshing}
            onClick={refresh}
          >
            {refreshing ? _("Đang cập nhật…") : _("Làm mới")}
          </button>
        )}
      </div>
    </header>
  );
}

function AttentionList({
  context,
  readOnly,
}: {
  context: HomeContext;
  readOnly: boolean;
}) {
  // API v1 returns []; tolerate a future aggregate only when its complete presentation shape is present.
  const attention = (context.attention as unknown[])
    .filter((item): item is Attention => {
      if (!item || typeof item !== "object") return false;
      const entry = item as Partial<Attention>;
      return (
        typeof entry.key === "string" &&
        typeof entry.route_key === "string" &&
        typeof entry.label === "string" &&
        typeof entry.reason === "string" &&
        typeof entry.action_label === "string" &&
        ["critical", "warning", "info"].includes(entry.severity ?? "")
      );
    })
    .flatMap((item) => {
      const route = destination(item, context);
      return route ? [{ ...item, ...route }] : [];
    });
  const labels = {
    critical: _("Khẩn cấp"),
    warning: _("Cảnh báo"),
    info: _("Thông tin"),
  };
  return (
    <section
      className="tc-card tc-attention"
      aria-labelledby="tc-attention-title"
    >
      <div className="tc-section-heading">
        <h2 id="tc-attention-title">{_("Cần chú ý")}</h2>
        {attention.length > 0 && (
          <span className="tc-count">{attention.length}</span>
        )}
      </div>
      {attention.length === 0 ? (
        <div className="tc-empty">
          <span className="tc-empty-mark" aria-hidden="true">
            ✓
          </span>
          <div>
            <strong>{_("Không có việc cần chú ý.")}</strong>
            <p>
              {_(
                "Các mục cần xử lý được hiển thị theo quyền truy cập của bạn."
              )}
            </p>
          </div>
        </div>
      ) : (
        <ul className="tc-attention-list">
          {attention.map((item) => (
            <li
              key={item.key}
              className={`tc-attention-item tc-severity-${item.severity}`}
            >
              <div>
                <span className="tc-severity">{labels[item.severity]}</span>
                <h3>{item.label}</h3>
                <p>{item.reason}</p>
              </div>
              <RouteAction
                item={item}
                readOnly={readOnly}
                className="tc-button"
              >
                {item.action_label}
              </RouteAction>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function MetricGrid({
  context,
  readOnly,
}: {
  context: HomeContext;
  readOnly: boolean;
}) {
  const metrics = context.metrics
    .flatMap((item) => {
      const route = destination(item, context);
      return route ? [{ ...item, ...route }] : [];
    })
    .slice(0, 6);
  if (metrics.length === 0) return null;
  return (
    <section aria-labelledby="tc-metrics-title">
      <h2 id="tc-metrics-title">{_("Chỉ số tổng quan")}</h2>
      <div className="tc-metric-grid">
        {metrics.map((item) => (
          <RouteAction
            key={item.key}
            item={item}
            readOnly={readOnly}
            className="tc-card tc-metric"
          >
            <strong>{new Intl.NumberFormat("vi-VN").format(item.value)}</strong>
            <span>{item.label}</span>
          </RouteAction>
        ))}
      </div>
    </section>
  );
}

function ShortcutGrid({
  context,
  readOnly,
}: {
  context: HomeContext;
  readOnly: boolean;
}) {
  const shortcuts = context.shortcuts
    .flatMap((item) => {
      const route = destination(item, context);
      return route ? [{ ...item, ...route }] : [];
    })
    .slice(0, 8);
  if (shortcuts.length === 0)
    return (
      <p className="tc-muted">{_("Bạn chưa có lối tắt được phân quyền.")}</p>
    );
  return (
    <section aria-labelledby="tc-shortcuts-title">
      <h2 id="tc-shortcuts-title">{_("Truy cập nhanh")}</h2>
      <div className="tc-shortcut-grid">
        {shortcuts.map((item) => (
          <RouteAction
            key={item.key}
            item={item}
            readOnly={readOnly}
            className="tc-card tc-shortcut"
          >
            <span className="tc-shortcut-heading">
              <strong>{item.label}</strong>
              <span aria-hidden="true">↗</span>
            </span>
            <span>{item.description}</span>
          </RouteAction>
        ))}
      </div>
    </section>
  );
}

function HomeSkeleton() {
  return (
    <div className="tc-home-content">
      <p role="status">{_("Đang tải trang chủ…")}</p>
      <section
        className="tc-card tc-skeleton-attention"
        aria-label={_("Đang tải việc cần chú ý")}
      >
        <div className="tc-skeleton-line" />
        <div className="tc-skeleton-line" />
      </section>
      <section aria-label={_("Đang tải chỉ số")} className="tc-metric-grid">
        {[0, 1, 2, 3].map((key) => (
          <div className="tc-card tc-skeleton-metric" key={key}>
            <div className="tc-skeleton-line" />
          </div>
        ))}
      </section>
      <section
        aria-label={_("Đang tải truy cập nhanh")}
        className="tc-shortcut-grid"
      >
        {[0, 1].map((key) => (
          <div className="tc-card tc-skeleton-shortcut" key={key}>
            <div className="tc-skeleton-line" />
          </div>
        ))}
      </section>
    </div>
  );
}

export default function App() {
  const [context, setContext] = useState<HomeContext | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [online, setOnline] = useState(navigator.onLine);
  const [menuOpen, setMenuOpen] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const [logoutError, setLogoutError] = useState(false);
  // A single versioned in-memory snapshot; never persist identity or records in browser storage.
  const snapshot = useRef<{ version: 1; context: HomeContext } | null>(null);
  const request = useRef(0);
  const menuButton = useRef<HTMLButtonElement>(null);
  const load = useCallback(async (connected = navigator.onLine) => {
    const current = ++request.current;
    if (!connected) {
      setPhase(snapshot.current ? "stale" : "error");
      return;
    }
    setRefreshing(true);
    try {
      const next = await homeApi.context();
      if (current !== request.current) return;
      if (next.system.api_version !== 1) {
        snapshot.current = null;
        setContext(null);
        setPhase("mismatch");
        return;
      }
      snapshot.current = { version: 1, context: next };
      setContext(next);
      setPhase("ready");
    } catch (error) {
      if (current !== request.current) return;
      if (
        error instanceof SessionExpiredError ||
        error instanceof PermissionError
      ) {
        snapshot.current = null;
        setContext(null);
        setPhase(
          error instanceof SessionExpiredError ? "session" : "permission"
        );
        if (error instanceof SessionExpiredError)
          window.location.assign("/login?redirect-to=%2Ftracecore");
      } else {
        setContext(snapshot.current?.context ?? null);
        setPhase(snapshot.current ? "stale" : "error");
      }
    } finally {
      if (current === request.current) setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const goOffline = () => {
      ++request.current;
      setOnline(false);
      setRefreshing(false);
      setPhase(snapshot.current ? "stale" : "error");
    };
    const goOnline = () => {
      setOnline(true);
      void load(true);
    };
    window.addEventListener("offline", goOffline);
    window.addEventListener("online", goOnline);
    return () => {
      ++request.current;
      window.removeEventListener("offline", goOffline);
      window.removeEventListener("online", goOnline);
    };
  }, [load]);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMenuOpen(false);
        menuButton.current?.focus();
      }
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, []);

  const logout = async () => {
    const token = document.querySelector<HTMLMetaElement>(
      'meta[name="csrf-token"]'
    )?.content;
    if (!token) {
      setLogoutError(true);
      return;
    }
    setLoggingOut(true);
    setLogoutError(false);
    ++request.current;
    try {
      const response = await fetch("/api/method/logout", {
        method: "POST",
        credentials: "same-origin",
        headers: { Accept: "application/json", "X-Frappe-CSRF-Token": token },
      });
      if (!response.ok) throw new Error("Logout request failed");
      snapshot.current = null;
      setContext(null);
      setPhase("session");
      window.location.assign("/login");
    } catch {
      setLogoutError(true);
    } finally {
      setLoggingOut(false);
    }
  };
  const readOnly = phase !== "ready" || !online || loggingOut;
  const retry = () => void load(online);
  return (
    <div className="tc-app" data-surface="WEB">
      <a href="#tc-main" className="tc-skip-link">
        {_("Đến nội dung chính")}
      </a>
      <div className="tc-mobile-bar">
        <span>TraceCore</span>
        <button
          ref={menuButton}
          className="tc-button"
          type="button"
          aria-controls="tc-sidebar"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen(!menuOpen)}
        >
          {menuOpen ? _("Đóng menu") : _("Mở menu")}
        </button>
      </div>
      <Sidebar
        context={context}
        readOnly={readOnly}
        online={online}
        open={menuOpen}
        close={() => setMenuOpen(false)}
        logout={() => void logout()}
        loggingOut={loggingOut}
      />
      <main id="tc-main" tabIndex={-1} aria-busy={phase === "loading"}>
        <HomeHeader
          context={context}
          readOnly={readOnly}
          refresh={retry}
          refreshing={refreshing || !online}
        />
        {phase === "loading" ? (
          <HomeSkeleton />
        ) : (
          <div className="tc-home-content">
            {logoutError && (
              <div role="alert" className="tc-alert tc-alert-error">
                {_("Không thể đăng xuất. Vui lòng tải lại trang và thử lại.")}
              </div>
            )}
            {(phase !== "ready" || !online) && (
              <div
                role="alert"
                className={`tc-alert${
                  phase === "stale" || !online
                    ? " tc-alert-warning"
                    : " tc-alert-error"
                }`}
              >
                {!online ? (
                  <>
                    <strong>{_("Ngoại tuyến.")}</strong>{" "}
                    {context
                      ? _(
                          "Dữ liệu đã lưu chỉ để xem. Các thao tác cần kết nối đã tạm khóa."
                        )
                      : _(
                          "Chưa có dữ liệu đã lưu. Kết nối mạng để tải trang chủ."
                        )}
                  </>
                ) : phase === "stale" ? (
                  <>
                    <strong>{_("Dữ liệu đã lưu chỉ để xem.")}</strong>{" "}
                    {_("Không thể cập nhật. Các thao tác đã tạm khóa.")}
                  </>
                ) : phase === "permission" ? (
                  <>
                    <strong>{_("Quyền truy cập đã thay đổi.")}</strong>{" "}
                    {_(
                      "Vui lòng tải lại quyền truy cập để tiếp tục tại Trang chủ."
                    )}
                  </>
                ) : phase === "session" ? (
                  <>
                    <strong>{_("Phiên đăng nhập đã hết hạn.")}</strong>{" "}
                    {_("Đang chuyển đến trang đăng nhập…")}
                  </>
                ) : phase === "mismatch" ? (
                  <>
                    <strong>
                      {_("Phiên bản ứng dụng cần được cập nhật.")}
                    </strong>{" "}
                    {_("Tải lại trang để tiếp tục.")}
                  </>
                ) : (
                  <>
                    <strong>{_("Không thể tải trang chủ.")}</strong>{" "}
                    {_("Kiểm tra kết nối và thử lại.")}
                  </>
                )}
                {context && (
                  <p>
                    {_("Cập nhật lần cuối:")}{" "}
                    <time dateTime={context.system.server_time}>
                      {formatTime(context.system.server_time)}
                    </time>
                  </p>
                )}
                {phase === "mismatch" ? (
                  <button
                    className="tc-button"
                    onClick={() => window.location.reload()}
                  >
                    {_("Tải lại trang")}
                  </button>
                ) : (
                  phase !== "session" && (
                    <button
                      className="tc-button"
                      disabled={!online || refreshing}
                      onClick={retry}
                    >
                      {_("Thử lại")}
                    </button>
                  )
                )}
              </div>
            )}
            {context && (
              <>
                <AttentionList context={context} readOnly={readOnly} />
                <MetricGrid context={context} readOnly={readOnly} />
                <ShortcutGrid context={context} readOnly={readOnly} />
                <p className="tc-updated">
                  {_("Cập nhật lúc")}{" "}
                  <time dateTime={context.system.server_time}>
                    {formatTime(context.system.server_time)}
                  </time>
                </p>
              </>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
