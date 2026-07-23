/*
 * CowriePay service worker (SRS 2.5 — ships as a Progressive Web App).
 *
 * Strategy, and the reasoning behind it:
 *
 *   app shell        cache-first. The HTML, CSS and JS rarely change and a
 *                    cached shell is what makes the app open instantly and
 *                    survive a dropped connection on a Lagos commute.
 *
 *   API requests     network-only, never cached. This is a payments app. A
 *                    stale balance or a cached quote is worse than an error
 *                    message, and FR 2.1 locks a quote for 60 seconds
 *                    specifically so it cannot be reused after that.
 *
 * The offline fallback is a page that says the app is offline, not a cached
 * version of the balance screen — showing someone an old balance they might act
 * on would be the wrong kind of helpful.
 */

const VERSION = "cowrie-v1";
const SHELL = `${VERSION}-shell`;

const PRECACHE = ["/pay", "/offline", "/manifest.webmanifest", "/icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => !key.startsWith(VERSION)).map((key) => caches.delete(key)))
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Never serve money data from a cache.
  if (url.pathname.startsWith("/api/")) return;

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(SHELL).then((cache) => cache.put(request, copy));
          return response;
        })
        .catch(() =>
          caches.match(request).then((cached) => cached || caches.match("/offline"))
        )
    );
    return;
  }

  event.respondWith(
    caches.match(request).then(
      (cached) =>
        cached ||
        fetch(request).then((response) => {
          if (response.ok && response.type === "basic") {
            const copy = response.clone();
            caches.open(SHELL).then((cache) => cache.put(request, copy));
          }
          return response;
        })
    )
  );
});
