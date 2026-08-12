import time

import app as webapp

t0 = time.time()

try:
    webapp._cargar(force=True)
    print(f"[preload] Espana OK: {len(webapp.CACHE.get('data') or [])} estaciones ({time.time() - t0:.1f}s)")
except Exception as e:
    print(f"[preload] Espana: {e}")

try:
    webapp._cargar_italia(force=True)
    print(f"[preload] Italia OK: {len(webapp.CACHE_IT.get('data') or [])} estaciones")
except Exception as e:
    print(f"[preload] Italia: {e}")
