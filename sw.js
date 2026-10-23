// Image bodies live only in this browser's Cache Storage, never on the web server.
const CACHE='ootd-device-images-v1',MAX=80;
self.addEventListener('install',()=>self.skipWaiting());
self.addEventListener('activate',event=>event.waitUntil(self.clients.claim()));
self.addEventListener('fetch',event=>{if(event.request.destination!=='image'||new URL(event.request.url).pathname.startsWith('/api/personal'))return;event.respondWith((async()=>{const cache=await caches.open(CACHE);const hit=await cache.match(event.request);if(hit)return hit;const response=await fetch(event.request);if(response.ok||response.type==='opaque'){try{const keys=await cache.keys();for(const key of keys.slice(0,Math.max(0,keys.length-MAX+1)))await cache.delete(key);await cache.put(event.request,response.clone());}catch{}}return response;})());});
