import json
import io
import sys
import os
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import precios as p

BASE = os.path.dirname(os.path.abspath(__file__))

with io.open(os.path.join(BASE, "datos_italia.json"), encoding="utf-8") as f:
    it = json.load(f)["estaciones"]

# Mediana de coords por provincia (ancla de cordura)
prov_pts = defaultdict(list)
for g in it:
    lat = p.parse_precio(g["Latitud"])
    lon = p.parse_precio(g["Longitud (WGS84)"])
    if lat is not None and lon is not None:
        prov_pts[g["Provincia"]].append((lat, lon))


def centro_provincia(prov):
    pts = prov_pts.get(prov)
    if not pts:
        return None
    pts.sort()
    lat = pts[len(pts) // 2][0]
    pts.sort(key=lambda x: x[1])
    lon = pts[len(pts) // 2][1]
    return lat, lon


# Estaciones sospechosas: mismas coords compartidas por >=2 estaciones de MUNICIPIOS distintos
grupos = defaultdict(list)
for g in it:
    grupos[(g["Latitud"], g["Longitud (WGS84)"])].append(g)

malas = []
for k, v in grupos.items():
    if len(v) >= 2 and len({x["Municipio"] for x in v}) > 1:
        malas.extend(v)

print("Sospechosas:", len(malas))

corr = {}
for i, g in enumerate(malas):
    dir_ = g["Dirección"].strip()
    if not dir_:
        print(i, g["IDEESS"], "sin direccion, omitida")
        continue
    q = f"{dir_}, {g['Municipio']}, {g['Provincia']}, Italia"
    try:
        lat, lon = p.geocodificar(q)
    except Exception as e:
        print(i, g["IDEESS"], "geocode fallo:", str(e)[:50])
        time.sleep(1.0)
        continue
    # cordura: dentro de Italia y cerca del centro de su provincia
    centro = centro_provincia(g["Provincia"])
    ok = 35.0 < lat < 48.0 and 5.0 < lon < 19.0
    if centro:
        dist = p.haversine(lat, lon, centro[0], centro[1])
        ok = ok and dist < 100
    if ok:
        corr[g["IDEESS"]] = [round(lat, 6), round(lon, 6)]
        print(i, g["IDEESS"], "OK", g["Municipio"], round(lat, 4), round(lon, 4))
    else:
        print(i, g["IDEESS"], "fuera de cordura, omitida")
    time.sleep(1.0)

with open(os.path.join(BASE, "correcciones_it.json"), "w", encoding="utf-8") as f:
    json.dump(corr, f, ensure_ascii=False, indent=0)
print("TOTAL correcciones:", len(corr))
