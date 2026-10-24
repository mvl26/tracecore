import type { RouteKey } from "./routes";

export interface HomeStation {
  name: string;
  label: string;
  step: "T1" | "T2" | "T3" | "T4" | "T5" | "T5b" | "T6" | "T7";
  implemented: boolean;
}

export interface HomeNavigation {
  key: RouteKey;
  label: string;
  route_key: RouteKey;
}

export interface HomeShortcut extends HomeNavigation {
  description: string;
  badge: null;
}

export interface HomeMetric extends HomeNavigation {
  value: number;
}

export interface HomeContext {
  user: {
    name: string;
    full_name: string;
    roles: string[];
    stations: HomeStation[];
  };
  capabilities: RouteKey[];
  navigation: HomeNavigation[];
  // API v1 does not implement actionable aggregates yet; it always returns [].
  attention: never[];
  metrics: HomeMetric[];
  shortcuts: HomeShortcut[];
  system: { api_version: number; server_time: string };
  etag: string;
}

export class SessionExpiredError extends Error {
  constructor() {
    super("TraceCore session expired");
    this.name = "SessionExpiredError";
  }
}

export class PermissionError extends Error {
  constructor() {
    super("TraceCore permission denied");
    this.name = "PermissionError";
  }
}

export const homeApi = {
  async context(): Promise<HomeContext> {
    const response = await fetch("/api/method/tracecore.v1.home.context", {
      method: "GET",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    if (response.status === 401) throw new SessionExpiredError();
    if (response.status === 403) throw new PermissionError();
    if (!response.ok) {
      throw new Error(`Home context request failed (${response.status})`);
    }
    const payload: { message?: HomeContext | null } = await response.json();
    if (!payload.message) throw new Error("Invalid Home context response");
    return payload.message;
  },
};
