const CACHE_NAME = {{ cache_name|tojson }};
const OFFLINE_URL = {{ offline_url|tojson }};
const CORE_ASSETS = {{ core_assets|tojson }};

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => cache.addAll(CORE_ASSETS))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys()
            .then(keys => Promise.all(
                keys
                    .filter(key => key.startsWith('gamelibrary-pwa-') && key !== CACHE_NAME)
                    .map(key => caches.delete(key))
            ))
            .then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', event => {
    const request = event.request;
    if (request.method !== 'GET') return;

    const url = new URL(request.url);
    if (url.origin !== self.location.origin) return;

    if (request.mode === 'navigate') {
        event.respondWith(
            fetch(request).catch(() => caches.match(OFFLINE_URL))
        );
        return;
    }

    const cacheableAsset = (
        url.pathname.startsWith('/pwa/icon-')
        || request.destination === 'style'
        || request.destination === 'script'
        || request.destination === 'font'
    );
    if (!cacheableAsset) return;

    event.respondWith((async () => {
        const cache = await caches.open(CACHE_NAME);
        const cached = await cache.match(request);
        const update = fetch(request).then(response => {
            if (response.ok && response.type === 'basic') {
                cache.put(request, response.clone());
            }
            return response;
        });
        if (cached) {
            event.waitUntil(update.catch(() => undefined));
            return cached;
        }
        return update;
    })());
});

self.addEventListener('message', event => {
    if (event.data === 'SKIP_WAITING') self.skipWaiting();
});
