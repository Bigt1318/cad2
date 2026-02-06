// ============================================================================
// FORD-CAD — Service Worker
// Enables push notifications only - NO caching for real-time dispatch
// ============================================================================

const CACHE_NAME = 'fordcad-v4';
const STATIC_ASSETS = [
    // Minimal caching - only images/icons, never HTML or JS
    '/static/images/logo.png',
];

// Force cleanup of old caches on load
self.addEventListener('install', (event) => {
    console.log('[SW] Installing v4 - minimal caching mode');
    self.skipWaiting();
});


// Activate: clean ALL old caches
self.addEventListener('activate', (event) => {
    console.log('[SW] Activating v4 - cleaning all caches');
    event.waitUntil(
        caches.keys().then((keys) => {
            // Delete ALL caches to ensure fresh content
            return Promise.all(keys.map(k => caches.delete(k)));
        })
    );
    self.clients.claim();
});

// Fetch: Network only for everything (no caching for real-time dispatch)
self.addEventListener('fetch', (event) => {
    // Let all requests go straight to network - no caching
    // This is a real-time dispatch system, caching causes problems
    return;
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
