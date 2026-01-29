// ============================================================================
// FORD-CAD — Service Worker
// Enables offline support and push notifications
// ============================================================================

const CACHE_NAME = 'fordcad-v1';
const STATIC_ASSETS = [
    '/',
    '/static/style.css',
    '/static/modals.css',
    '/static/css/themes.css',
    '/static/vendor/htmx.min.js',
    '/static/js/bootloader.js',
    '/static/images/logo.png',
];

// Install: cache static assets
self.addEventListener('install', (event) => {
    console.log('[SW] Installing service worker');
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            console.log('[SW] Caching static assets');
            return cache.addAll(STATIC_ASSETS);
        })
    );
    self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener('activate', (event) => {
    console.log('[SW] Activating service worker');
    event.waitUntil(
        caches.keys().then((keys) => {
            return Promise.all(
                keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
            );
        })
    );
    self.clients.claim();
});

// Fetch: network-first for API, cache-first for static
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);
    
    // Skip non-GET requests
    if (event.request.method !== 'GET') return;
    
    // API calls: network only (don't cache dynamic data)
    if (url.pathname.startsWith('/api/') || 
        url.pathname.startsWith('/panel/') ||
        url.pathname.startsWith('/incident/')) {
        return;
    }
    
    // Static assets: cache-first
    if (url.pathname.startsWith('/static/')) {
        event.respondWith(
            caches.match(event.request).then((cached) => {
                return cached || fetch(event.request).then((response) => {
                    // Cache successful responses
                    if (response.ok) {
                        const clone = response.clone();
                        caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
                    }
                    return response;
                });
            })
        );
        return;
    }
    
    // HTML pages: network-first with cache fallback
    event.respondWith(
        fetch(event.request).catch(() => {
            return caches.match(event.request).then((cached) => {
                return cached || caches.match('/');
            });
        })
    );
});

// Push notifications
self.addEventListener('push', (event) => {
    console.log('[SW] Push notification received');
    
    let data = { title: 'FORD-CAD Alert', body: 'New notification' };
    
    try {
        data = event.data.json();
    } catch (e) {
        data.body = event.data?.text() || data.body;
    }
    
    const options = {
        body: data.body,
        icon: '/static/images/logo.png',
        badge: '/static/images/logo.png',
        tag: data.tag || 'fordcad-notification',
        requireInteraction: data.priority === 'high',
        vibrate: [200, 100, 200],
        data: data.data || {},
        actions: [
            { action: 'view', title: 'View' },
            { action: 'dismiss', title: 'Dismiss' }
        ]
    };
    
    event.waitUntil(
        self.registration.showNotification(data.title, options)
    );
});

// Notification click handler
self.addEventListener('notificationclick', (event) => {
    console.log('[SW] Notification clicked:', event.action);
    event.notification.close();
    
    if (event.action === 'dismiss') return;
    
    // Open or focus the app
    event.waitUntil(
        clients.matchAll({ type: 'window' }).then((clientList) => {
            // If app is already open, focus it
            for (const client of clientList) {
                if (client.url.includes(self.location.origin) && 'focus' in client) {
                    return client.focus();
                }
            }
            // Otherwise open new window
            if (clients.openWindow) {
                const url = event.notification.data?.url || '/';
                return clients.openWindow(url);
            }
        })
    );
});

console.log('[SW] Service worker loaded');
