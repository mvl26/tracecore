import "@testing-library/jest-dom/vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { HomeContext } from "./api";
import App from "./App";

const context: HomeContext = {
  user: {
    name: "operator@example.test",
    full_name: "Nguyễn Thị An",
    roles: ["TC R03"],
    stations: [
      { name: "TR-001", label: "Tiếp nhận", step: "T1", implemented: true },
    ],
  },
  capabilities: ["station", "search", "set-units"],
  navigation: [{ key: "station", label: "Mở trạm", route_key: "station" }],
  attention: [],
  metrics: [
    { key: "set-units", label: "Bộ dụng cụ", value: 7, route_key: "set-units" },
  ],
  shortcuts: [
    {
      key: "station",
      label: "Mở trạm",
      description: "Tiếp tục công việc tại trạm.",
      route_key: "station",
      badge: null,
    },
    {
      key: "search",
      label: "Quét hoặc tra cứu",
      description: "Tìm bộ dụng cụ, chu trình hoặc thiết bị.",
      route_key: "search",
      badge: null,
    },
  ],
  system: { api_version: 1, server_time: "2026-10-24T12:15:00+07:00" },
  etag: "0123456789abcdef",
};

function respond(payload: unknown = context) {
  return Response.json({ message: payload });
}

function deferredResponse() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}

function addCsrfToken() {
  const token = document.createElement("meta");
  token.name = "csrf-token";
  token.content = "test-csrf";
  document.head.append(token);
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(async () => respond())
  );
  vi.stubGlobal("location", { assign: vi.fn(), pathname: "/tracecore" });
  vi.spyOn(window.navigator, "onLine", "get").mockReturnValue(true);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.querySelector('meta[name="csrf-token"]')?.remove();
});

describe("Home", () => {
  it("renders identity, attention, metrics and authorized shortcuts", async () => {
    render(<App />);
    expect(
      await screen.findByRole("heading", { name: "Xin chào, Nguyễn Thị An" })
    ).toBeVisible();
    expect(screen.getAllByText("TC R03").length).toBeGreaterThan(0);
    expect(screen.getAllByText("T1 · Tiếp nhận").length).toBeGreaterThan(0);
    expect(screen.getByRole("region", { name: "Cần chú ý" })).toHaveTextContent(
      "Không có việc cần chú ý."
    );
    expect(
      screen.getByRole("region", { name: "Chỉ số tổng quan" })
    ).toHaveTextContent("7Bộ dụng cụ");
    const shortcuts = screen.getByRole("region", { name: "Truy cập nhanh" });
    expect(
      within(shortcuts).getByRole("link", { name: /Mở trạm/ })
    ).toHaveAttribute("href", "/app/station");
    expect(screen.getByRole("link", { name: "Trang chủ" })).toHaveAttribute(
      "aria-current",
      "page"
    );
  });

  it.each(["capability", "shortcut"])(
    "does not render Frappe Admin without its %s",
    async (missing) => {
      const admin = {
        key: "frappe-admin",
        label: "Frappe Admin",
        route_key: "frappe-admin",
        description: "Quản trị hệ thống.",
        badge: null,
      } as const;
      vi.mocked(fetch).mockResolvedValue(
        respond({
          ...context,
          capabilities:
            missing === "capability"
              ? context.capabilities
              : [...context.capabilities, "frappe-admin"],
          navigation: [...context.navigation, admin],
          shortcuts:
            missing === "shortcut"
              ? context.shortcuts
              : [...context.shortcuts, admin],
        })
      );
      render(<App />);
      await screen.findByRole("heading", { name: /Xin chào/ });
      expect(screen.queryByText("Frappe Admin")).not.toBeInTheDocument();
    }
  );

  it("renders Frappe Admin only with capability and matching shortcut", async () => {
    const admin = {
      key: "frappe-admin",
      label: "Frappe Admin",
      route_key: "frappe-admin",
      description: "Quản trị hệ thống.",
      badge: null,
    } as const;
    vi.mocked(fetch).mockResolvedValue(
      respond({
        ...context,
        capabilities: [...context.capabilities, "frappe-admin"],
        navigation: [...context.navigation, admin],
        shortcuts: [...context.shortcuts, admin],
      })
    );
    render(<App />);
    const shortcuts = await screen.findByRole("region", {
      name: "Truy cập nhanh",
    });
    expect(
      within(shortcuts).getByRole("link", { name: /Frappe Admin/ })
    ).toHaveAttribute("href", "/app");
  });

  it("renders a Home-shaped skeleton while loading", () => {
    vi.mocked(fetch).mockReturnValue(new Promise(() => {}));
    render(<App />);
    expect(screen.getByRole("main")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("status")).toHaveTextContent("Đang tải trang chủ");
    expect(
      screen.getByRole("region", { name: "Đang tải chỉ số" })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Đang tải truy cập nhanh" })
    ).toBeInTheDocument();
  });

  it("renders inline retry on API failure", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response("private detail", { status: 500 })
    );
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Không thể tải trang chủ."
    );
    expect(screen.queryByText("private detail")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Thử lại" }));
    expect(
      await screen.findByRole("heading", { name: /Xin chào/ })
    ).toBeVisible();
  });

  it("labels stale cached content with its timestamp and disables business actions", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: /Xin chào/ });
    vi.mocked(fetch).mockRejectedValueOnce(
      new TypeError("Network unavailable")
    );
    fireEvent.click(screen.getByRole("button", { name: "Làm mới" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Dữ liệu đã lưu");
    expect(within(alert).getByRole("time")).toHaveAttribute(
      "datetime",
      context.system.server_time
    );
    expect(alert).toHaveTextContent("24/10/2026");
    expect(alert).toHaveTextContent("12:15");
    expect(
      screen.queryByRole("link", { name: /Mở trạm/ })
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Chỉ số tổng quan" })
    ).toHaveTextContent("7");
  });

  it("uses text as well as color for severity", async () => {
    // Forward-compatible presentation fixture only: API v1 currently always returns [].
    vi.mocked(fetch).mockResolvedValue(
      respond({
        ...context,
        attention: [
          {
            key: "release",
            label: "Mẻ chờ giải phóng",
            reason: "Cần kiểm tra kết quả.",
            severity: "warning",
            route_key: "station",
            action_label: "Kiểm tra",
          },
          {
            key: "blocked",
            label: "Thiết bị bị khóa",
            reason: "Chưa có test ngày.",
            severity: "critical",
            route_key: "station",
            action_label: "Xem thiết bị",
          },
        ],
      })
    );
    render(<App />);
    const attention = await screen.findByRole("region", { name: "Cần chú ý" });
    expect(attention).toHaveTextContent("Cảnh báo");
    expect(attention).toHaveTextContent("Khẩn cấp");
    expect(attention).toHaveTextContent("Cần kiểm tra kết quả.");
    expect(
      within(attention).getByRole("link", { name: "Kiểm tra" })
    ).toHaveAttribute("href", "/app/station");
  });

  it("omits empty metric and shortcut containers", async () => {
    vi.mocked(fetch).mockResolvedValue(
      respond({
        ...context,
        capabilities: [],
        navigation: [],
        metrics: [],
        shortcuts: [],
      })
    );
    render(<App />);
    await screen.findByText("Không có việc cần chú ý.");
    expect(
      screen.queryByRole("region", { name: "Chỉ số tổng quan" })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Truy cập nhanh" })
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("Bạn chưa có lối tắt được phân quyền.")
    ).toBeVisible();
  });

  it("clears prior content on permission revocation and offers retry", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: /Xin chào/ });
    vi.mocked(fetch).mockResolvedValueOnce(new Response("", { status: 403 }));
    fireEvent.click(screen.getByRole("button", { name: "Làm mới" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Quyền truy cập đã thay đổi."
    );
    expect(screen.queryByText("Nguyễn Thị An")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Chỉ số tổng quan" })
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Thử lại" }));
    expect(
      await screen.findByRole("heading", { name: /Xin chào/ })
    ).toBeVisible();
  });

  it("clears content and redirects an expired session to login", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response("", { status: 401 }));
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Phiên đăng nhập đã hết hạn."
    );
    expect(window.location.assign).toHaveBeenCalledWith(
      "/login?redirect-to=%2Ftracecore"
    );
  });

  it("retains read-only content offline and requires a fresh response on reconnect", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: /Xin chào/ });
    act(() => window.dispatchEvent(new Event("offline")));
    expect(screen.getByRole("alert")).toHaveTextContent("Ngoại tuyến");
    expect(
      screen.queryByRole("link", { name: /Mở trạm/ })
    ).not.toBeInTheDocument();
    act(() => window.dispatchEvent(new Event("online")));
    await within(
      screen.getByRole("region", { name: "Truy cập nhanh" })
    ).findByRole("link", { name: /Mở trạm/ });
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(2);
  });

  it("shows an offline explanation before any successful load", async () => {
    vi.spyOn(window.navigator, "onLine", "get").mockReturnValue(false);
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Chưa có dữ liệu đã lưu"
    );
    expect(fetch).not.toHaveBeenCalled();
  });

  it("rejects unknown or unauthorized routes in every payload section", async () => {
    vi.mocked(fetch).mockResolvedValue(
      respond({
        ...context,
        capabilities: [...context.capabilities, "https://evil.test"],
        navigation: [
          {
            key: "unsafe",
            label: "Liên kết lạ",
            route_key: "https://evil.test",
          },
        ],
        metrics: [
          {
            key: "equipment",
            label: "Thiết bị ẩn",
            value: 9,
            route_key: "equipment",
          },
        ],
        shortcuts: [
          {
            key: "unsafe",
            label: "Liên kết lạ",
            description: "Không được mở",
            route_key: "https://evil.test",
          },
        ],
      })
    );
    render(<App />);
    await screen.findByRole("heading", { name: /Xin chào/ });
    expect(screen.queryByText("Liên kết lạ")).not.toBeInTheDocument();
    expect(screen.queryByText("Thiết bị ẩn")).not.toBeInTheDocument();
  });

  it("requires a controlled reload for incompatible API versions", async () => {
    vi.mocked(fetch).mockResolvedValue(
      respond({ ...context, system: { ...context.system, api_version: 2 } })
    );
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Phiên bản ứng dụng cần được cập nhật."
    );
    expect(screen.getByRole("button", { name: "Tải lại trang" })).toBeVisible();
    expect(
      screen.queryByRole("region", { name: "Truy cập nhanh" })
    ).not.toBeInTheDocument();
  });

  it("opens and closes compact navigation with an explicit menu button", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: /Xin chào/ });
    const button = screen.getByRole("button", { name: "Mở menu" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(button);
    expect(screen.getByRole("button", { name: "Đóng menu" })).toHaveAttribute(
      "aria-expanded",
      "true"
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveFocus();
  });

  it("preserves keyboard focus on Escape when compact navigation is closed", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: /Xin chào/ });
    const refresh = screen.getByRole("button", { name: "Làm mới" });
    refresh.focus();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(refresh).toHaveFocus();
  });

  it.each(["refresh-first", "logout-first"])(
    "blocks context loads during logout and cannot restore Home after success (%s)",
    async (ordering) => {
      addCsrfToken();
      render(<App />);
      await screen.findByRole("heading", { name: /Xin chào/ });
      const refresh = deferredResponse();
      const logout = deferredResponse();
      const duringLogout = deferredResponse();
      vi.mocked(fetch)
        .mockReturnValueOnce(refresh.promise)
        .mockReturnValueOnce(logout.promise)
        .mockReturnValueOnce(duringLogout.promise);
      fireEvent.click(screen.getByRole("button", { name: "Làm mới" }));
      fireEvent.click(screen.getByRole("button", { name: "Đăng xuất" }));
      // A reconnect can start a load even when the refresh button is disabled.
      act(() => window.dispatchEvent(new Event("online")));
      if (ordering === "refresh-first") {
        await act(async () => {
          refresh.resolve(respond());
        });
      }
      await act(async () => {
        logout.resolve(Response.json({ message: "ok" }));
      });
      await act(async () => {
        if (ordering === "logout-first") refresh.resolve(respond());
        duringLogout.resolve(respond());
      });
      expect(window.location.assign).toHaveBeenCalledWith("/login");
      expect(
        screen.queryByRole("heading", { name: /Xin chào/ })
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("region", { name: "Truy cập nhanh" })
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("link", { name: /Mở trạm/ })
      ).not.toBeInTheDocument();
      act(() => window.dispatchEvent(new Event("online")));
      expect(fetch).toHaveBeenCalledTimes(3);
    }
  );

  it.each(["refresh-first", "logout-first"])(
    "recovers refresh after a canceled context request and failed logout (%s)",
    async (ordering) => {
      addCsrfToken();
      render(<App />);
      await screen.findByRole("heading", { name: /Xin chào/ });
      const refresh = deferredResponse();
      const logout = deferredResponse();
      vi.mocked(fetch)
        .mockReturnValueOnce(refresh.promise)
        .mockReturnValueOnce(logout.promise);
      fireEvent.click(screen.getByRole("button", { name: "Làm mới" }));
      fireEvent.click(screen.getByRole("button", { name: "Đăng xuất" }));
      if (ordering === "refresh-first") {
        await act(async () => {
          refresh.resolve(respond());
        });
      }
      await act(async () => {
        logout.resolve(new Response("", { status: 500 }));
      });
      if (ordering === "logout-first") {
        await act(async () => {
          refresh.resolve(respond());
        });
      }
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Không thể đăng xuất."
      );
      const retryRefresh = screen.getByRole("button", { name: "Làm mới" });
      expect(retryRefresh).toBeEnabled();
      fireEvent.click(retryRefresh);
      await screen.findByRole("button", { name: "Làm mới" });
      expect(fetch).toHaveBeenCalledTimes(4);
      expect(window.location.assign).not.toHaveBeenCalled();
      expect(screen.getByRole("heading", { name: /Xin chào/ })).toBeVisible();
    }
  );

  it("recovers inline retry after failed logout cancels a stale refresh", async () => {
    addCsrfToken();
    render(<App />);
    await screen.findByRole("heading", { name: /Xin chào/ });
    vi.mocked(fetch).mockRejectedValueOnce(
      new TypeError("Network unavailable")
    );
    fireEvent.click(screen.getByRole("button", { name: "Làm mới" }));
    await screen.findByRole("button", { name: "Thử lại" });
    const refresh = deferredResponse();
    const logout = deferredResponse();
    vi.mocked(fetch)
      .mockReturnValueOnce(refresh.promise)
      .mockReturnValueOnce(logout.promise);
    fireEvent.click(screen.getByRole("button", { name: "Thử lại" }));
    fireEvent.click(screen.getByRole("button", { name: "Đăng xuất" }));
    await act(async () => {
      logout.resolve(new Response("", { status: 500 }));
    });
    await act(async () => {
      refresh.resolve(respond());
    });
    const retry = screen.getByRole("button", { name: "Thử lại" });
    expect(retry).toBeEnabled();
    fireEvent.click(retry);
    await within(
      screen.getByRole("region", { name: "Truy cập nhanh" })
    ).findByRole("link", { name: /Mở trạm/ });
    expect(fetch).toHaveBeenCalledTimes(5);
  });

  it("keeps successful logout final even if the login navigation is blocked", async () => {
    addCsrfToken();
    render(<App />);
    await screen.findByRole("heading", { name: /Xin chào/ });
    vi.mocked(window.location.assign).mockImplementationOnce(() => {
      throw new Error("Navigation blocked");
    });
    vi.mocked(fetch).mockResolvedValueOnce(Response.json({ message: "ok" }));
    fireEvent.click(screen.getByRole("button", { name: "Đăng xuất" }));
    await screen.findByText("Phiên đăng nhập đã hết hạn.");
    await act(async () => {
      window.dispatchEvent(new Event("online"));
    });
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(
      screen.queryByRole("heading", { name: /Xin chào/ })
    ).not.toBeInTheDocument();
  });

  it.each(["before-rejection", "after-rejection"])(
    "keeps cached actions read-only when reconnect occurs %s after offline during logout",
    async (ordering) => {
      addCsrfToken();
      render(<App />);
      await screen.findByRole("heading", { name: /Xin chào/ });
      const logout = deferredResponse();
      const freshContext = deferredResponse();
      vi.mocked(fetch)
        .mockReturnValueOnce(logout.promise)
        .mockReturnValueOnce(freshContext.promise);
      fireEvent.click(screen.getByRole("button", { name: "Đăng xuất" }));
      act(() => window.dispatchEvent(new Event("offline")));
      expect(screen.queryAllByRole("link", { name: /Mở trạm/ })).toHaveLength(
        0
      );
      if (ordering === "before-rejection") {
        act(() => window.dispatchEvent(new Event("online")));
        expect(fetch).toHaveBeenCalledTimes(2);
      }
      await act(async () => {
        logout.resolve(new Response("", { status: 503 }));
      });
      if (ordering === "after-rejection") {
        act(() => window.dispatchEvent(new Event("online")));
      }
      expect(screen.queryAllByRole("link", { name: /Mở trạm/ })).toHaveLength(
        0
      );
      expect(
        screen.queryAllByRole("link", { name: /Quét hoặc tra cứu/ })
      ).toHaveLength(0);
      expect(screen.getByText("Dữ liệu đã lưu chỉ để xem.")).toBeVisible();
      expect(
        screen.getByRole("region", { name: "Chỉ số tổng quan" })
      ).toHaveTextContent("7");
      if (ordering === "before-rejection") {
        fireEvent.click(screen.getByRole("button", { name: "Thử lại" }));
      }
      expect(fetch).toHaveBeenCalledTimes(3);
      expect(screen.queryAllByRole("link", { name: /Mở trạm/ })).toHaveLength(
        0
      );
      await act(async () => {
        freshContext.resolve(
          respond({
            ...context,
            metrics: [{ ...context.metrics[0], value: 8 }],
          })
        );
      });
      expect(
        within(
          screen.getByRole("region", { name: "Truy cập nhanh" })
        ).getByRole("link", { name: /Mở trạm/ })
      ).toBeVisible();
      expect(
        screen.getByRole("region", { name: "Chỉ số tổng quan" })
      ).toHaveTextContent("8");
      expect(
        screen.queryByText("Dữ liệu đã lưu chỉ để xem.")
      ).not.toBeInTheDocument();
      expect(window.location.assign).not.toHaveBeenCalled();
    }
  );

  it("logs out with the independent CSRF boot token and clears Home", async () => {
    const token = document.createElement("meta");
    token.name = "csrf-token";
    token.content = "test-csrf";
    document.head.append(token);
    render(<App />);
    await screen.findByRole("heading", { name: /Xin chào/ });
    vi.mocked(fetch).mockResolvedValueOnce(Response.json({ message: "ok" }));
    fireEvent.click(screen.getByRole("button", { name: "Đăng xuất" }));
    await screen.findByRole("alert");
    expect(fetch).toHaveBeenLastCalledWith("/api/method/logout", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "X-Frappe-CSRF-Token": "test-csrf",
      },
    });
    expect(window.location.assign).toHaveBeenCalledWith("/login");
    expect(
      screen.queryByRole("region", { name: "Chỉ số tổng quan" })
    ).not.toBeInTheDocument();
  });

  it("fails closed when the CSRF boot token is missing", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: /Xin chào/ });
    fireEvent.click(screen.getByRole("button", { name: "Đăng xuất" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Không thể đăng xuất."
    );
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(window.location.assign).not.toHaveBeenCalled();
  });

  it("shows an inline failure when logout is rejected without pretending it succeeded", async () => {
    const token = document.createElement("meta");
    token.name = "csrf-token";
    token.content = "test-csrf";
    document.head.append(token);
    render(<App />);
    await screen.findByRole("heading", { name: /Xin chào/ });
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response("private detail", { status: 500 })
    );
    fireEvent.click(screen.getByRole("button", { name: "Đăng xuất" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Không thể đăng xuất."
    );
    expect(window.location.assign).not.toHaveBeenCalled();
    expect(screen.queryByText("private detail")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Xin chào/ })).toBeVisible();
  });
});
