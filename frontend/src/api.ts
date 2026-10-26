export interface Screen {
  id: string;
  title: string;
  state: "ready" | "forbidden" | "not_implemented";
}
export interface Space {
  id: string;
  title: string;
  description: string;
  screens: Screen[];
}
export interface Bootstrap {
  user: string;
  full_name: string;
  roles: Space[];
  csrf_token: string;
  admin_overview: boolean;
}
export interface RecordList {
  doctype: string;
  fields: string[];
  rows: Record<string, unknown>[];
  has_more: boolean;
  start: number;
  can_create: boolean;
  can_issue: boolean;
  stations: StationLink[];
}
export interface StationLink {
  name: string;
  label: string;
  step: string;
  url: string;
}

let csrf =
  typeof document === "undefined"
    ? ""
    : document.querySelector<HTMLMetaElement>('meta[name="csrf-token"]')
        ?.content || "";
export function setCSRF(token: string) {
  csrf = token;
}
export function internalPath(path: string): string {
  return /^\/tracecore(?:\/[A-Za-z0-9_\-/%]*)?$/.test(path) &&
    !path.includes("%2f%2f")
    ? path
    : "/tracecore";
}
export function passwordResetPath(
  target: string,
  origin: string,
): string | null {
  try {
    const url = new URL(target, origin);
    return url.origin === origin && url.pathname === "/update-password"
      ? url.pathname + url.search
      : null;
  } catch {
    return null;
  }
}
export function readableError(status: number): string {
  if (status === 401) return "Phiên đăng nhập đã hết hạn.";
  if (status === 403) return "Không có quyền thực hiện thao tác này.";
  if (status === 409 || status === 417 || status === 422)
    return "Dữ liệu chưa hợp lệ hoặc đã thay đổi. Kiểm tra và thử lại.";
  if (status === 429)
    return "Đã vượt số lần thử. Vui lòng chờ trước khi thử lại.";
  return "Máy chủ đang gặp sự cố. Thử lại sau.";
}
export class APIError extends Error {
  constructor(public status: number) {
    super(readableError(status));
  }
}
export async function request(
  method: string,
  data: Record<string, unknown> = {},
  post = false,
  raw = false,
  idempotencyKey?: string,
): Promise<any> {
  const url = new URL("/api/method/" + method, window.location.origin);
  const headers: Record<string, string> = { Accept: "application/json" };
  const init: RequestInit = {
    credentials: "same-origin",
    headers,
    method: post ? "POST" : "GET",
    cache: "no-store",
  };
  if (post) {
    headers["Content-Type"] = "application/json";
    if (csrf) headers["X-Frappe-CSRF-Token"] = csrf;
    if (idempotencyKey) headers["X-Idempotency-Key"] = idempotencyKey;
    init.body = JSON.stringify(data);
  } else
    for (const [key, value] of Object.entries(data))
      if (value !== undefined) url.searchParams.set(key, String(value));
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch {
    throw new Error("Không kết nối được máy chủ. Kiểm tra mạng và thử lại.");
  }
  if (!response.ok) {
    if (response.status === 403 && method !== "login") {
      // Frappe returns 403 both for insufficient permission and an expired Guest session.
      const identity = await fetch("/api/method/frappe.auth.get_logged_user", {
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!identity.ok || (await identity.json()).message === "Guest")
        throw new APIError(401);
    }
    if (method === "login" && response.status === 401)
      throw new Error("Tài khoản, mật khẩu hoặc mã xác thực chưa đúng.");
    throw new APIError(response.status);
  }
  const result = await response.json();
  return raw ? result : result.message;
}
export const adminAPI = (
  name: string,
  args: Record<string, unknown> = {},
  post = false,
) => request("tracecore.v1.admin_ui." + name, args, post);

export function createBusinessMutation() {
  let pending: { fingerprint: string; key: string; timestamp: string } | null =
    null;
  return async (method: string, args: Record<string, unknown>) => {
    const fingerprint = method + JSON.stringify(args);
    if (!pending || pending.fingerprint !== fingerprint)
      pending = {
        fingerprint,
        key: crypto.randomUUID(),
        timestamp: new Date().toISOString(),
      };
    try {
      const result = await request(
        method,
        { ...args, client_ts: pending.timestamp },
        true,
        false,
        pending.key,
      );
      pending = null;
      return result;
    } catch (error) {
      // A definitive rejection allows correction; a lost/5xx response must replay identically.
      if (error instanceof APIError && error.status < 500) pending = null;
      throw error;
    }
  };
}
