/* TraceCore station shell service worker (FEAT-001 skeleton).
 * Precache tài sản shell của trạm; điều hướng /app/station network-first.
 * Chưa có outbox IndexedDB (FEAT-009). */
const CACHE_PREFIX = "tracecore-shell-";
const CACHE_NAME = CACHE_PREFIX + "{{ version }}";
const PRECACHE = ["/assets/tracecore/css/tokens.css", "/assets/tracecore/css/tracecore-theme.css"];

self.addEventListener("install", (event) => {
	event.waitUntil(
		caches
			.open(CACHE_NAME)
			.then((cache) => cache.addAll(PRECACHE))
			.then(() => self.skipWaiting())
	);
});

self.addEventListener("activate", (event) => {
	event.waitUntil(
		caches
			.keys()
			.then((keys) =>
				Promise.all(
					keys
						.filter((key) => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME)
						.map((key) => caches.delete(key))
				)
			)
			.then(() => self.clients.claim())
	);
});

self.addEventListener("fetch", (event) => {
	const request = event.request;
	if (request.method !== "GET") return;
	const url = new URL(request.url);
	if (url.origin !== self.location.origin) return;

	if (request.mode === "navigate" && url.pathname.startsWith("/app/station")) {
		event.respondWith(
			fetch(request)
				.then((response) => {
					const copy = response.clone();
					caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
					return response;
				})
				.catch(() => caches.match(request))
		);
		return;
	}

	if (url.pathname.startsWith("/assets/tracecore/")) {
		event.respondWith(caches.match(request).then((hit) => hit || fetch(request)));
	}
});
