const cacheName = "aster-static-v1";

const staticAssets = [
    "/static/img/favicon.svg",
    "/static/pwa/manifest.webmanifest",
    "/static/pwa/icons/icon-192.png",
    "/static/pwa/icons/icon-512.png"
];

self.addEventListener("install", event => {
    event.waitUntil(
        caches.open(cacheName).then(cache => {
            return cache.addAll(staticAssets);
        })
    );
});

self.addEventListener("activate", event => {
    event.waitUntil(
        caches.keys().then(cacheNames => {
            return Promise.all(
                cacheNames
                    .filter(name => name !== cacheName)
                    .map(name => caches.delete(name))
            );
        })
    );
});

self.addEventListener("fetch", event => {
    if (event.request.method !== "GET") {
        return;
    }

    const requestUrl = new URL(event.request.url);
    if (
        requestUrl.origin !== self.location.origin ||
        !staticAssets.includes(requestUrl.pathname)
    ) {
        return;
    }

    event.respondWith(
        caches.match(event.request).then(cachedResponse => {
            return cachedResponse || fetch(event.request);
        })
    );
});
