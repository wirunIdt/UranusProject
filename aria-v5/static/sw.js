const CACHE = 'aria-v5-cache-v1';
const OFFLINE_URLS = [
  '/', '/static/aria.css', '/static/aria.js', '/static/manifest.json',
  '/terminal', '/status', '/finance', '/worldmonitor'
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(OFFLINE_URLS)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys.filter(k => k !== CACHE).map(k => caches.delete(k))
    )).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  // API calls: network first, no cache
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(
      fetch(e.request).catch(() =>
        new Response(JSON.stringify({error:'offline',cached:false}),
          {headers:{'Content-Type':'application/json'}})
      )
    );
    return;
  }
  // Static + pages: cache first, fallback network
  e.respondWith(
    caches.match(e.request).then(cached => {
      const network = fetch(e.request).then(res => {
        if (res.ok) caches.open(CACHE).then(c => c.put(e.request, res.clone()));
        return res;
      });
      return cached || network;
    })
  );
});

// Push notifications from server
self.addEventListener('push', e => {
  const data = e.data ? e.data.json() : {};
  e.waitUntil(
    self.registration.showNotification(data.title || 'ARIA Alert', {
      body: data.body || data.message || '',
      icon: '/static/icons/icon.svg',
      badge: '/static/icons/icon.svg',
      tag: data.tag || 'aria',
      data: { url: data.url || '/' },
      vibrate: [200, 100, 200],
    })
  );
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(clients.openWindow(e.notification.data?.url || '/'));
});
