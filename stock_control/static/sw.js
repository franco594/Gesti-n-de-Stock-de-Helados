// Service Worker — Sistema de Stock de Helados
// Estrategia: network-first para HTML/JS/CSS (siempre entrega código nuevo);
//             nunca cachear /api/ (datos en tiempo real).
// Al cambiar assets, incrementar CACHE_VERSION para invalidar el cache viejo.

const CACHE_VERSION = "v2";
const CACHE_NAME = `stock-helados-${CACHE_VERSION}`;

// Rutas de assets estáticos a precargar en install
const PRECACHE_URLS = [
    "/",
    "/static/style.css",
    "/static/index.js",
];

// ─── Install: precachear assets conocidos ───────────────────────────────────
self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => cache.addAll(PRECACHE_URLS))
            .then(() => self.skipWaiting())   // activar de inmediato sin esperar
    );
});

// ─── Activate: borrar caches de versiones anteriores ────────────────────────
self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys().then((keys) =>
            Promise.all(
                keys
                    .filter((key) => key !== CACHE_NAME)
                    .map((key) => caches.delete(key))
            )
        ).then(() => self.clients.claim())    // tomar control de tabs existentes
    );
});

// ─── Fetch: network-first, sin cachear /api/ ────────────────────────────────
self.addEventListener("fetch", (event) => {
    const url = new URL(event.request.url);

    // Nunca interceptar peticiones a la API (datos de stock en tiempo real)
    if (url.pathname.startsWith("/api/")) {
        return;
    }

    // Solo manejar GET (no POST, no imports de otro origen)
    if (event.request.method !== "GET" || url.origin !== location.origin) {
        return;
    }

    // Network-first: intentar red; si falla, caer en cache
    event.respondWith(
        fetch(event.request)
            .then((networkResponse) => {
                // Guardar copia fresca en cache solo si la respuesta es válida
                if (networkResponse && networkResponse.status === 200) {
                    const responseToCache = networkResponse.clone();
                    caches.open(CACHE_NAME).then((cache) =>
                        cache.put(event.request, responseToCache)
                    );
                }
                return networkResponse;
            })
            .catch(() => caches.match(event.request))
    );
});
