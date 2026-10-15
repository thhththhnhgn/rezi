/* ULTRA GAMING VPN — service worker
 * Cache-first for static shell assets, network-only for everything dynamic.
 * API, subscriptions and tunnel paths are NEVER cached.
 */
var CACHE = "ultra-v4.0.0";
// Only the HTML shell and the icon are precached. Scripts and styles are
// deliberately NOT precached: they carry a ?v= version and must always be
// revalidated, otherwise a redeploy leaves the browser running the old panel.
var SHELL = [
  "/panel/",
  "/assets/icon.svg",
  "/manifest.webmanifest"
];

self.addEventListener("install", function (e) {
  e.waitUntil(
    caches.open(CACHE).then(function (c) {
      return Promise.all(SHELL.map(function (u) {
        return c.add(u).catch(function () { /* ignore individual misses */ });
      }));
    }).then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function (e) {
  e.waitUntil(
    caches.keys().then(function (ks) {
      return Promise.all(ks.map(function (k) {
        return k === CACHE ? null : caches.delete(k);
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function (e) {
  var req = e.request;
  if (req.method !== "GET") return;

  var url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // never cache dynamic or sensitive endpoints
  if (url.pathname.indexOf("/api/") === 0 ||
      url.pathname.indexOf("/sub/") === 0 ||
      url.pathname.indexOf("/u/") === 0 ||
      url.pathname === "/__ping") return;

  if (SHELL.indexOf(url.pathname) === -1) return;

  e.respondWith(
    caches.match(req).then(function (hit) {
      var net = fetch(req).then(function (res) {
        if (res && res.status === 200) {
          var copy = res.clone();
          caches.open(CACHE).then(function (c) { c.put(req, copy); });
        }
        return res;
      }).catch(function () { return hit; });
      return hit || net;
    })
  );
});
