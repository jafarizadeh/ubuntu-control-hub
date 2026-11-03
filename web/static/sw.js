"use strict";
const CACHE = "ubuntu-control-shell-v14-adaptive-cpu-v07";
const ASSETS = ["/", "/index.html", "/style.css", "/ios-controls.css", "/ios-ui.js", "/cpu-details.css", "/cpu-details.js", "/app.js", "/icon.svg", "/icon-180.png", "/icon-192.png", "/icon-512.png", "/manifest.webmanifest", "/assets/ubuntu-logo.svg", "/assets/monitor.svg", "/assets/cpu.svg", "/assets/wifi.svg", "/assets/wifi-off.svg", "/assets/power.svg", "/assets/ubuntu-on.svg", "/assets/ubuntu-off.svg", "/assets/monitor-on.svg", "/assets/monitor-off.svg"];
self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) =>
    Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))));
  self.clients.claim();
});
self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;
  if (!ASSETS.includes(url.pathname)) return;
  event.respondWith(fetch(event.request)
    .then((response) => {
      if (response.ok) {
        const copy = response.clone();
        caches.open(CACHE).then((cache) => cache.put(event.request, copy));
      }
      return response;
    })
    .catch(() => caches.match(event.request))
  );
});
