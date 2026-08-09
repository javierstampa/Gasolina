from flask import Flask, request, jsonify, send_from_directory, abort
import precios as p
import os
import threading
import time
import json
import datetime

app = Flask(__name__, static_folder="static", static_url_path="/static")

LOCK = threading.Lock()
CACHE = {"ts": 0, "data": None, "fecha": None}
CACHE_IT = {"ts": 0, "data": None, "fecha": None}
TTL = 60 * 60 * 6  # 6 horas
SNAP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "datos.json")
SNAP_IT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "datos_italia.json")


def _snapshot_save(gasolineras, fecha):
    try:
        with open(SNAP, "w", encoding="utf-8") as f:
            json.dump({"fecha": fecha, "estaciones": gasolineras}, f, ensure_ascii=False)
    except Exception:
        pass


def _snapshot_load():
    try:
        with open(SNAP, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data["estaciones"], data.get("fecha", "snapshot")
    except Exception:
        return [], "snapshot"


def _cargar(force=False):
    """Sirve el snapshot (lo genera y sube la máquina local a diario).
    Solo descarga de la API REST si el snapshot falta (emergencia)."""
    with LOCK:
        if not (force or not CACHE["data"] or (time.time() - CACHE["ts"] > TTL)):
            return CACHE["data"] or [], CACHE["fecha"] or "desconocida"

        gasolineras, fecha = _snapshot_load()
        if not gasolineras:
            try:
                gasolineras, fecha = p.descargar_datos()
            except Exception:
                gasolineras, fecha = [], "desconocida"
        if not gasolineras:
            gasolineras = _desde_db()
            if not fecha or fecha == "desconocida":
                fecha = "BD local"
        if gasolineras:
            try:
                p.init_db()
                p.guardar_precios(gasolineras, fecha)
            except Exception:
                pass
            _snapshot_save(gasolineras, fecha)
            CACHE["data"] = gasolineras
            CACHE["fecha"] = fecha
            CACHE["ts"] = time.time()
        return CACHE["data"] or [], CACHE["fecha"] or "desconocida"


def _snapshot_it_save(gasolineras, fecha):
    try:
        with open(SNAP_IT, "w", encoding="utf-8") as f:
            json.dump({"fecha": fecha, "dia": datetime.date.today().isoformat(),
                       "estaciones": gasolineras}, f, ensure_ascii=False)
    except Exception:
        pass


def _snapshot_it_load():
    try:
        with open(SNAP_IT, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data["estaciones"], data.get("fecha", "snapshot"), data.get("dia", "")
    except Exception:
        return [], "snapshot", ""


def _cargar_italia(force=False):
    """Sirve el snapshot de Italia. Solo descarga los CSV si el snapshot falta."""
    with LOCK:
        if not (force or not CACHE_IT["data"] or (time.time() - CACHE_IT["ts"] > TTL)):
            return CACHE_IT["data"] or [], CACHE_IT["fecha"] or "desconocida"

        gasolineras, fecha, _ = _snapshot_it_load()
        if not gasolineras:
            try:
                gasolineras, fecha = p.descargar_datos_italia()
            except Exception:
                gasolineras, fecha = [], "desconocida"
        if gasolineras:
            try:
                p.init_db()
                p.guardar_precios(gasolineras, fecha)
            except Exception:
                pass
            _snapshot_it_save(gasolineras, fecha)
            CACHE_IT["data"] = gasolineras
            CACHE_IT["fecha"] = fecha
            CACHE_IT["ts"] = time.time()
        return CACHE_IT["data"] or [], CACHE_IT["fecha"] or "desconocida"


def _desde_db():
    """Recupera estaciones desde la BD si la descarga remota falla."""
    import sqlite3
    try:
        with sqlite3.connect(p._db()) as c:
            rows = c.execute("SELECT ideess, rotulo, direccion, municipio, provincia, latitud, longitud, horario FROM estaciones").fetchall()
        out = []
        for ideess, rotulo, direccion, municipio, provincia, lat, lon, horario in rows:
            out.append({
                "IDEESS": ideess, "Rótulo": rotulo or "", "Dirección": direccion or "",
                "Municipio": municipio or "", "Provincia": provincia or "",
                "Latitud": str(lat).replace(".", ",") if lat is not None else "",
                "Longitud (WGS84)": str(lon).replace(".", ",") if lon is not None else "",
                "Horario": horario or "",
            })
        return out
    except Exception:
        return []


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/fuels")
def api_fuels():
    pais = request.args.get("pais", "espana")
    if pais == "italia":
        return jsonify([{"id": k, "label": p.FUELS[k]} for k in p.FUELS_ITALIA])
    return jsonify([{"id": k, "label": v} for k, v in p.FUELS.items()])


@app.route("/api/stations")
def api_stations():
    lat = request.args.get("lat", type=float)
    lon = request.args.get("lon", type=float)
    fuel = request.args.get("fuel", "Precio Gasolina 95 E5")
    sort = request.args.get("sort", "balance")
    radius = request.args.get("radius", 60, type=float)
    top = request.args.get("top", 50, type=int)
    open_only = request.args.get("open") == "1"
    scope = request.args.get("scope", "cerca")
    pais = request.args.get("pais", "espana")

    if scope == "pais":
        lat = lon = None
        if sort == "distancia":
            sort = "precio"
    elif lat is None or lon is None:
        return jsonify({"error": "lat y lon requeridos"}), 400

    if pais == "italia":
        gasolineras, fecha = _cargar_italia()
    else:
        gasolineras, fecha = _cargar()
    p.init_db()

    rows = []
    for g in gasolineras:
        precio = p.parse_precio(g.get(fuel, ""))
        if precio is None or precio <= 0:
            continue
        g_lat = p.parse_precio(g.get("Latitud", ""))
        g_lon = p.parse_precio(g.get("Longitud (WGS84)", ""))
        if g_lat is None or g_lon is None:
            continue
        if scope == "pais":
            dist = 0.0
        else:
            dist = p.haversine(lat, lon, g_lat, g_lon)
            if dist > radius:
                continue
        horario = g.get("Horario", "")
        if open_only and not p.abierta_ahora(horario):
            continue
        rows.append({
            "ideess": g.get("IDEESS", ""),
            "rotulo": g.get("Rótulo", ""),
            "direccion": g.get("Dirección", ""),
            "municipio": g.get("Municipio", ""),
            "provincia": g.get("Provincia", ""),
            "horario": horario,
            "lat": g_lat,
            "lon": g_lon,
            "precio": round(precio, 3),
            "dist": round(dist, 2),
            "tend": " ",
            "abierta": p.abierta_ahora(horario),
            "es_24h": p.es_24h(horario),
        })

    # "Precio" y "Balance" consideran TODAS las estaciones del radio.
    # Solo "Distancia" y "Todo el país" recortan a los candidatos más cercanos.
    if scope == "pais":
        rows.sort(key=lambda x: (x["precio"], x["provincia"]))
        rows = rows[:max(top * 3, 120)]
    elif sort == "distancia":
        rows.sort(key=lambda x: (x["dist"], x["precio"]))
        rows = rows[:max(top * 3, 120)]

    precios_list = [x["precio"] for x in rows]
    dists_list = [x["dist"] for x in rows]
    if precios_list:
        min_p, max_p = min(precios_list), max(precios_list)
        min_d, max_d = min(dists_list), max(dists_list)
        for x in rows:
            sp = 100 * (1 - (x["precio"] - min_p) / (max_p - min_p)) if max_p > min_p else 100
            sd = 100 * (1 - (x["dist"] - min_d) / (max_d - min_d)) if max_d > min_d else 100
            x["score"] = round((sp + sd) / 2, 1)

    if sort == "precio":
        rows.sort(key=lambda x: (x["precio"], x["dist"]))
    elif sort == "distancia":
        rows.sort(key=lambda x: (x["dist"], x["precio"]))
    else:
        rows.sort(key=lambda x: (-x["score"], x["precio"]))

    final = rows[:top]
    for x in final:
        x["tend"] = p.tend_str(x["ideess"], fuel)

    return jsonify({"fecha": fecha, "fuel": fuel, "sort": sort, "scope": scope,
                    "pais": pais, "total": len(rows), "stations": final})


@app.route("/api/station")
def api_station():
    ideess = request.args.get("ideess", "")
    if not ideess:
        return jsonify({"error": "ideess requerido"}), 400
    pais = request.args.get("pais", "")
    if not pais:
        pais = "italia" if ideess.startswith("IT_") else "espana"
    if pais == "italia":
        gasolineras, fecha = _cargar_italia()
    else:
        gasolineras, fecha = _cargar()
    g = next((x for x in gasolineras if x.get("IDEESS") == ideess), None)
    if g is None:
        return jsonify({"error": "Estación no encontrada"}), 404
    precios = []
    for campo, label in p.FUELS.items():
        precio = p.parse_precio(g.get(campo, ""))
        if precio is None or precio <= 0:
            continue
        precios.append({
            "fuel": campo, "label": label, "precio": round(precio, 3),
            "tend": p.tend_str(ideess, campo),
        })
    return jsonify({
        "ideess": ideess,
        "rotulo": g.get("Rótulo", ""),
        "direccion": g.get("Dirección", ""),
        "municipio": g.get("Municipio", ""),
        "provincia": g.get("Provincia", ""),
        "localidad": g.get("Localidad", ""),
        "horario": g.get("Horario", ""),
        "lat": p.parse_precio(g.get("Latitud", "")),
        "lon": p.parse_precio(g.get("Longitud (WGS84)", "")),
        "precios": sorted(precios, key=lambda x: x["precio"]),
        "fecha": fecha,
        "abierta": p.abierta_ahora(g.get("Horario", "")),
        "es_24h": p.es_24h(g.get("Horario", "")),
    })


@app.route("/api/history")
def api_history():
    ideess = request.args.get("ideess", "")
    fuel = request.args.get("fuel", "")
    if not ideess or not fuel:
        return jsonify({"error": "ideess y fuel requeridos"}), 400
    return jsonify({"ideess": ideess, "fuel": fuel,
                    "data": p.historial(ideess, fuel)})


@app.route("/api/route")
def api_route():
    origen = request.args.get("origen", "")
    destino = request.args.get("destino", "")
    fuel = request.args.get("fuel", "Precio Gasoleo A")
    radio = request.args.get("radio", 3.0, type=float)
    pais = request.args.get("pais", "espana")
    if not origen or not destino:
        return jsonify({"error": "origen y destino requeridos"}), 400

    pais_sufijo = "Italia" if pais == "italia" else "España"
    import requests as _rq
    lat1, lon1 = p.geocodificar(origen + ", " + pais_sufijo)
    lat2, lon2 = p.geocodificar(destino + ", " + pais_sufijo)
    url = f"https://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=full&geometries=geojson"
    r = _rq.get(url, headers={"User-Agent": "fuelprices-web/1.0"}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("code") != "Ok":
        return jsonify({"error": "No se pudo calcular la ruta"}), 400
    route = data["routes"][0]
    coords = route["geometry"]["coordinates"]
    km_total = round(route["distance"] / 1000, 1)

    # Prefiltro por caja delimitadora de la ruta para acelerar el cálculo
    min_lon = min(c[0] for c in coords) - radio / 111.0
    max_lon = max(c[0] for c in coords) + radio / 111.0
    min_lat = min(c[1] for c in coords) - radio / 111.0
    max_lat = max(c[1] for c in coords) + radio / 111.0
    step = max(1, len(coords) // 40)

    gasolineras, fecha = _cargar_italia() if pais == "italia" else _cargar()
    cands = []
    for g in gasolineras:
        precio = p.parse_precio(g.get(fuel, ""))
        if precio is None or precio <= 0:
            continue
        g_lat = p.parse_precio(g.get("Latitud", ""))
        g_lon = p.parse_precio(g.get("Longitud (WGS84)", ""))
        if g_lat is None or g_lon is None:
            continue
        if not (min_lat <= g_lat <= max_lat and min_lon <= g_lon <= max_lon):
            continue
        dist = p._distancia_a_ruta(g_lat, g_lon, coords[::step])
        if dist <= radio:
            cands.append({
                "ideess": g.get("IDEESS", ""),
                "rotulo": g.get("Rótulo", ""),
                "direccion": g.get("Dirección", ""),
                "municipio": g.get("Municipio", ""),
                "provincia": g.get("Provincia", ""),
                "horario": g.get("Horario", ""),
                "lat": g_lat, "lon": g_lon,
                "precio": round(precio, 3),
                "desvio": round(dist, 2),
                "abierta": p.abierta_ahora(g.get("Horario", "")),
            })
    cands.sort(key=lambda x: (x["precio"], x["desvio"]))
    return jsonify({
        "origen": {"lat": lat1, "lon": lon1, "label": origen},
        "destino": {"lat": lat2, "lon": lon2, "label": destino},
        "km": km_total,
        "geometry": coords,
        "stations": cands[:30],
        "fecha": fecha,
        "fuel": fuel,
        "pais": pais,
    })


@app.route("/api/geocode")
def api_geocode():
    q = request.args.get("q", "")
    if not q:
        return jsonify({"error": "q requerido"}), 400
    pais = request.args.get("pais", "espana")
    pais_sufijo = "Italia" if pais == "italia" else "España"
    try:
        lat, lon = p.geocodificar(q + ", " + pais_sufijo)
        return jsonify({"lat": lat, "lon": lon, "label": q, "pais": pais})
    except Exception as e:
        return jsonify({"error": str(e)}), 404


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    try:
        pais = request.args.get("pais", "espana")
        if pais == "italia":
            _cargar_italia(force=True)
            return jsonify({"ok": True, "fecha": CACHE_IT["fecha"],
                            "estaciones": len(CACHE_IT["data"])})
        _cargar(force=True)
        return jsonify({"ok": True, "fecha": CACHE["fecha"],
                        "estaciones": len(CACHE["data"])})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Servidor en http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
