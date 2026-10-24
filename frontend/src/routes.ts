const ROUTES = {
  search: "/tracecore/search",
  station: "/app/station",
  "set-units": "/app/set-unit",
  packs: "/app/pack",
  equipment: "/app/equipment",
  "par-levels": "/app/par-level",
  "frappe-admin": "/app",
} as const;

export type RouteKey = keyof typeof ROUTES;

export function resolveRoute(routeKey: string): string {
  if (!Object.prototype.hasOwnProperty.call(ROUTES, routeKey)) {
    throw new Error("Unknown TraceCore route");
  }
  return ROUTES[routeKey as RouteKey];
}
