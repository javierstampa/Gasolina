import subprocess
import json
import argparse
import math
import sqlite3
import datetime
import os
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import requests

URL_MITECO = "https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes/EstacionesTerrestres/"
URL_ANAGRAFICA_IT = "https://www.mimit.gov.it/images/exportCSV/anagrafica_impianti_attivi.csv"
URL_PREZZI_IT = "https://www.mimit.gov.it/images/exportCSV/prezzo_alle_8.csv"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

COMBUSTIBLES = ["Precio Gasolina 95 E5", "Precio Gasoleo A"]
ETIQUETAS = {"Precio Gasolina 95 E5": "Gasolina 95", "Precio Gasoleo A": "Gasóleo A"}

FUELS = {
    "Precio Gasolina 95 E5": "Gasolina 95",
    "Precio Gasolina 95 E10": "Gasolina 95 E10",
    "Precio Gasolina 95 E5 Premium": "Gasolina 95 Premium",
    "Precio Gasolina 95 E85": "Gasolina 95 E85",
    "Precio Gasolina 98 E5": "Gasolina 98",
    "Precio Gasolina 98 E10": "Gasolina 98 E10",
    "Precio Gasoleo A": "Gasóleo A",
    "Precio Gasoleo Premium": "Gasóleo Premium",
    "Precio Gasoleo B": "Gasóleo B",
    "Precio Biodiesel": "Biodiésel",
    "Precio Bioetanol": "Bioetanol",
    "Precio Gases licuados del petróleo": "GLP",
    "Precio Gas Natural Comprimido": "GNC",
    "Precio Gas Natural Licuado": "GNL",
    "Precio Hidrogeno": "Hidrógeno",
    "Precio Adblue": "AdBlue",
    "Precio Diésel Renovable": "Diésel Renovable",
    "Precio Gasolina Renovable": "Gasolina Renovable",
    "Precio Biogas Natural Comprimido": "Biogás GNC",
    "Precio Biogas Natural Licuado": "Biogás GNL",
    "Precio Amoniaco": "Amoniaco",
    "Precio Metanol": "Metanol",
}

# Mapea los carburantes de los CSV del MIMIT a las claves normalizadas del proyecto.
IT_FUEL_MAP = {
    "Benzina": "Precio Gasolina 95 E5",
    "Gasolio": "Precio Gasoleo A",
    "GPL": "Precio Gases licuados del petróleo",
    "Metano": "Precio Gas Natural Comprimido",
    "GNL": "Precio Gas Natural Licuado",
    "HVO": "Precio Diésel Renovable",
    "HVOlution": "Precio Diésel Renovable",
    "HVO100": "Precio Diésel Renovable",
    "HVO eco diesel": "Precio Diésel Renovable",
    "Blue Diesel": "Precio Gasoleo Premium",
    "Supreme Diesel": "Precio Gasoleo Premium",
    "Hi-Q Diesel": "Precio Gasoleo Premium",
    "HiQ Perform+": "Precio Gasoleo Premium",
    "Gasolio Premium": "Precio Gasoleo Premium",
    "Gasolio speciale": "Precio Gasoleo Premium",
}

FUELS_ITALIA = [
    "Precio Gasolina 95 E5",
    "Precio Gasoleo A",
    "Precio Gasoleo Premium",
    "Precio Diésel Renovable",
    "Precio Gases licuados del petróleo",
    "Precio Gas Natural Comprimido",
    "Precio Gas Natural Licuado",
]

DB_PATH = None


def _db():
    global DB_PATH
    if DB_PATH is None:
        DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "precios.db")
    return DB_PATH


def init_db():
    with sqlite3.connect(_db()) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS precios (
                ideess TEXT NOT NULL,
                combustible TEXT NOT NULL,
                precio REAL NOT NULL,
                fecha_dato TEXT NOT NULL,
                ultima_vista TEXT NOT NULL,
                PRIMARY KEY (ideess, combustible, fecha_dato)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS estaciones (
                ideess TEXT PRIMARY KEY,
                rotulo TEXT,
                direccion TEXT,
                municipio TEXT,
                provincia TEXT,
                latitud REAL,
                longitud REAL,
                horario TEXT
            )
        """)


def guardar_precios(gasolineras, fecha_dato):
    now = datetime.datetime.now().isoformat(timespec="minutes")
    with sqlite3.connect(_db()) as c:
        for g in gasolineras:
            ideess = g.get("IDEESS", "")
            if not ideess:
                continue
            c.execute("""
                INSERT OR IGNORE INTO estaciones (ideess, rotulo, direccion, municipio, provincia, latitud, longitud, horario)
                VALUES (?,?,?,?,?,?,?,?)
            """, (
                ideess, g.get("Rótulo", ""), g.get("Dirección", ""),
                g.get("Municipio", ""), g.get("Provincia", ""),
                parse_precio(g.get("Latitud", "")),
                parse_precio(g.get("Longitud (WGS84)", "")),
                g.get("Horario", "")
            ))
            for campo, valor in g.items():
                if not campo.startswith("Precio "):
                    continue
                precio = parse_precio(valor)
                if precio is None or precio <= 0:
                    continue
                row = c.execute(
                    "SELECT precio FROM precios WHERE ideess=? AND combustible=? ORDER BY fecha_dato DESC LIMIT 1",
                    (ideess, campo)
                ).fetchone()
                if row and row[0] == precio:
                    c.execute(
                        "UPDATE precios SET ultima_vista=? WHERE ideess=? AND combustible=? AND fecha_dato=?",
                        (now, ideess, campo, fecha_dato)
                    )
                else:
                    c.execute(
                        "INSERT OR REPLACE INTO precios (ideess, combustible, precio, fecha_dato, ultima_vista) VALUES (?,?,?,?,?)",
                        (ideess, campo, precio, fecha_dato, now)
                    )


def tendencia(ideess, campo):
    with sqlite3.connect(_db()) as c:
        rows = c.execute(
            "SELECT precio FROM precios WHERE ideess=? AND combustible=? ORDER BY fecha_dato DESC LIMIT 2",
            (ideess, campo)
        ).fetchall()
    if len(rows) < 2:
        return " "
    p1, p2 = rows[0][0], rows[1][0]
    if p1 > p2:
        return "+"
    if p1 < p2:
        return "-"
    return "="


def precio_actual(ideess, combustible):
    with sqlite3.connect(_db()) as c:
        row = c.execute(
            "SELECT precio FROM precios WHERE ideess=? AND combustible=? ORDER BY fecha_dato DESC LIMIT 1",
            (ideess, combustible)
        ).fetchone()
    return row[0] if row else None


def historial(ideess, combustible, limite=400):
    with sqlite3.connect(_db()) as c:
        rows = c.execute(
            "SELECT fecha_dato, precio FROM precios WHERE ideess=? AND combustible=? ORDER BY fecha_dato ASC",
            (ideess, combustible)
        ).fetchall()
    out = []
    seen = None
    for fecha, precio in rows:
        if precio == seen:
            continue
        seen = precio
        out.append({"fecha": fecha, "precio": precio})
        if len(out) >= limite:
            break
    return out


def es_24h(horario):
    if not horario:
        return False
    h = horario.upper()
    return "24H" in h or "24 H" in h or "TODOS LOS DÍAS" in h


def _dias_incluye(expr_dias, hoy):
    """Comprueba si el día actual (L,M,X,J,V,S,D) está incluido en una expresión de días."""
    expr = expr_dias.upper()
    if hoy in expr:
        return True
    orden = "LMXJVSD"
    if "-" in expr:
        ini, fin = expr.split("-", 1)
        if ini in orden and fin in orden:
            i0, i1 = orden.index(ini), orden.index(fin)
            return hoy in orden[i0:i1 + 1]
    return False


def abierta_ahora(horario):
    """Estima si la estación está abierta ahora según su horario 'L-D: 07:00-22:00'."""
    if not horario:
        return None
    if es_24h(horario):
        return True
    ahora = datetime.datetime.now().strftime("%A").lower()
    mapa = {
        "monday": "L", "tuesday": "M", "wednesday": "X", "thursday": "J",
        "friday": "V", "saturday": "S", "sunday": "D",
    }
    hoy = mapa.get(ahora)
    if not hoy:
        return None
    actual = datetime.datetime.now().hour * 60 + datetime.datetime.now().minute
    for bloque in horario.split(";"):
        bloque = bloque.strip()
        if not bloque or ":" not in bloque:
            continue
        dias, horas = bloque.split(":", 1)
        if not _dias_incluye(dias, hoy):
            continue
        rangos = [x.strip() for x in horas.split(";") if x.strip()]
        for rango in rangos:
            if "-" not in rango:
                continue
            ini, fin = rango.split("-", 1)
            try:
                def _min(t):
                    t = t.strip().replace(".", ":")
                    if ":" not in t:
                        t = t + ":00"
                    hh, mm = t.split(":")[:2]
                    return int(hh) * 60 + int(mm)
                i0, i1 = _min(ini), _min(fin)
            except ValueError:
                continue
            if i1 < i0:
                if actual >= i0 or actual < i1:
                    return True
            elif i0 <= actual < i1:
                return True
    return False


def _usos():
    print("""
USOS:
  gasolina.exe                                                      Resumen de precios
  gasolina.exe --gps                                                Usa tu ubicación GPS
  gasolina.exe --cerca "San Agustín del Guadalix"                   Ranking por distancia
  gasolina.exe --ruta "Origen" "Destino"                            Gasolineras en ruta
  gasolina.exe --gps -t 15                                          Más resultados
  gasolina.exe --gps --ordenar precio                               Ordenar por precio
  gasolina.exe --ruta "Madrid" "Valencia" --ordenar precio          Más baratas en ruta

  --radio       Radio de búsqueda en km (default: 50)
  --top / -t    Número de resultados (default: 10)
  --ordenar     balance | precio | distancia
  --no-pause    No esperar Enter al final
""")


def _descargar_json():
    for metodo, fn in [
        ("curl.exe", lambda: subprocess.run(["curl.exe", "-s", "--max-time", "30", URL_MITECO, "-A", UA, "-H", "Accept: application/json"], capture_output=True)),
        ("PowerShell", lambda: subprocess.run(["powershell.exe", "-NoProfile", "-Command", f'(Invoke-RestMethod -Uri \'{URL_MITECO}\' -Headers @{{"User-Agent"="{UA}";"Accept"="application/json"}} -TimeoutSec 30) | ConvertTo-Json -Depth 10 -Compress'], capture_output=True, text=True)),
        ("requests", lambda: requests.get(URL_MITECO, headers={"User-Agent": UA, "Accept": "application/json"}, timeout=30)),
    ]:
        try:
            result = fn()
            if metodo == "requests":
                result.raise_for_status()
                return result.json()
            if result.returncode != 0:
                continue
            raw = result.stdout
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            return json.loads(raw)
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        except requests.RequestException:
            continue
    raise RuntimeError("No se pudo descargar los datos.")


def descargar_datos():
    data = _descargar_json()
    return data.get("ListaEESSPrecio", []), data.get("Fecha", "fecha desconocida")


def _descargar_csv(url):
    r = requests.get(url, headers={"User-Agent": UA, "Accept": "text/csv"}, timeout=60)
    r.raise_for_status()
    return r.content


def _csv_filas(content):
    text = content.decode("latin-1", errors="replace")
    out = []
    for line in text.splitlines():
        line = line.rstrip("\r")
        if line.strip():
            out.append(line)
    return out


def descargar_datos_italia():
    """Descarga los CSV del MIMIT (en paralelo) y los normaliza con las mismas claves que España."""
    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_an = ex.submit(_descargar_csv, URL_ANAGRAFICA_IT)
        fut_pr = ex.submit(_descargar_csv, URL_PREZZI_IT)
        content_an = fut_an.result()
        content_pr = fut_pr.result()
    filas_an = _csv_filas(content_an)
    filas_pr = _csv_filas(content_pr)

    fecha = "desconocida"
    for line in filas_an:
        m = re.match(r"\s*Estrazione del (\d{4}-\d{2}-\d{2})", line)
        if m:
            fecha = m.group(1)
            break

    header = None
    estaciones_raw = []
    for line in filas_an:
        if line.startswith("Estrazione del"):
            continue
        if line.startswith("idImpianto"):
            header = line.split("|")
            continue
        if header is None:
            continue
        vals = line.split("|")
        if len(vals) < len(header):
            continue
        estaciones_raw.append(dict(zip(header, vals)))

    # Precios: (idImpianto, combustible) -> (dtComu, isSelf, precio)
    mejores = {}
    header_pr = None
    for line in filas_pr:
        if line.startswith("Estrazione del"):
            continue
        if line.startswith("idImpianto"):
            header_pr = line.split("|")
            continue
        if header_pr is None:
            continue
        vals = line.split("|")
        if len(vals) < 5:
            continue
        row = dict(zip(header_pr, vals))
        fuel = IT_FUEL_MAP.get(row.get("descCarburante", "").strip())
        if not fuel:
            continue
        precio = parse_precio(row.get("prezzo", ""))
        if precio is None or precio <= 0:
            continue
        try:
            dt = datetime.datetime.strptime(row.get("dtComu", "").strip(), "%d/%m/%Y %H:%M:%S")
        except ValueError:
            continue
        try:
            isself = int(row.get("isSelf", "0") or "0")
        except ValueError:
            isself = 0
        clave = (row.get("idImpianto", "").strip(), fuel)
        actual = mejores.get(clave)
        if actual is None or (dt, isself) >= (actual[0], actual[1]):
            mejores[clave] = (dt, isself, precio)

    precios_por_imp = defaultdict(dict)
    for (id2, fuel), (dt, isself, precio) in mejores.items():
        precios_por_imp[id2][fuel] = "{:.3f}".format(precio)

    estaciones = []
    for r in estaciones_raw:
        id_imp = r.get("idImpianto", "").strip()
        if not id_imp:
            continue
        lat = parse_precio((r.get("Latitudine") or "").strip())
        lon = parse_precio((r.get("Longitudine") or "").strip())
        if lat is None or lon is None:
            continue
        rotulo = (r.get("Nome Impianto") or r.get("Gestore") or "").strip()
        rotulo = " ".join(rotulo.split())
        st = {
            "IDEESS": "IT_" + id_imp,
            "Rótulo": rotulo,
            "Dirección": (r.get("Indirizzo") or "").strip(),
            "Municipio": (r.get("Comune") or "").strip(),
            "Provincia": (r.get("Provincia") or "").strip(),
            "Latitud": "{:.6f}".format(lat).replace(".", ","),
            "Longitud (WGS84)": "{:.6f}".format(lon).replace(".", ","),
            "Horario": "",
        }
        st.update(precios_por_imp.get(id_imp, {}))
        estaciones.append(st)

    return _aplicar_correcciones(estaciones), fecha


def _aplicar_correcciones(estaciones):
    """Corrige coordenadas erróneas/duplicadas del MIMIT usando correcciones_it.json."""
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "correcciones_it.json")
        with open(path, encoding="utf-8") as f:
            corr = json.load(f)
    except Exception:
        return estaciones
    for st in estaciones:
        c = corr.get(st.get("IDEESS", ""))
        if c:
            st["Latitud"] = "{:.6f}".format(c[0]).replace(".", ",")
            st["Longitud (WGS84)"] = "{:.6f}".format(c[1]).replace(".", ",")
    return estaciones


def parse_precio(precio_str):
    if not precio_str:
        return None
    precio_str = precio_str.replace(",", ".").strip()
    try:
        return float(precio_str)
    except ValueError:
        return None


def detectar_ubicacion():
    url = "http://ip-api.com/json/?fields=lat,lon,status"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "success":
        raise RuntimeError("No se pudo obtener ubicación por IP")
    return float(data["lat"]), float(data["lon"])


def geocodificar(direccion):
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": direccion, "format": "json", "limit": 1, "addressdetails": 0}
    r = requests.get(url, params=params, headers={"User-Agent": "fuelprices-app/1.0"}, timeout=15)
    r.raise_for_status()
    data = r.json()
    if not data:
        raise ValueError(f"No se encontró la dirección: {direccion}")
    return float(data[0]["lat"]), float(data[0]["lon"])


def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def osrm_distancias(origen_lat, origen_lon, destinos):
    N = len(destinos)
    if N == 0:
        return []
    if N == 1:
        dst_lon, dst_lat = destinos[0]["lon"], destinos[0]["lat"]
        url = f"https://router.project-osrm.org/route/v1/driving/{origen_lon},{origen_lat};{dst_lon},{dst_lat}?overview=false"
        r = requests.get(url, headers={"User-Agent": "fuelprices-app/1.0"}, timeout=15)
        r.raise_for_status()
        data = r.json()
        if data.get("code") == "Ok":
            return [data["routes"][0]["distance"] / 1000]
        return [None]

    coords = f"{origen_lon},{origen_lat}"
    for d in destinos:
        coords += f";{d['lon']},{d['lat']}"
    url = f"https://router.project-osrm.org/table/v1/driving/{coords}?sources=0&annotations=distance"
    r = requests.get(url, headers={"User-Agent": "fuelprices-app/1.0"}, timeout=60)
    r.raise_for_status()
    data = r.json()
    if data.get("code") != "Ok":
        return [None] * N
    distancias = data.get("distances", [[]])
    if not distancias or not distancias[0]:
        return [None] * N
    return [d / 1000 if d is not None else None for d in distancias[0]]


def resumen(gasolineras):
    comb_prices = defaultdict(list)
    for g in gasolineras:
        for campo in COMBUSTIBLES:
            precio = parse_precio(g.get(campo, ""))
            if precio is not None and precio > 0:
                comb_prices[ETIQUETAS[campo]].append(precio)

    print(f"Total estaciones: {len(gasolineras)}\n")
    print(f"{'Combustible':<20} {'Media':>8} {'Min':>8} {'Max':>8} {'#':>6}")
    print("-" * 50)
    for comb, precios in sorted(comb_prices.items()):
        media = sum(precios) / len(precios)
        print(f"{comb:<20} {media:>7.3f}eur {min(precios):>7.3f}eur {max(precios):>7.3f}eur {len(precios):>6}")


def _calcular_score(precio, dist, min_precio, max_precio, min_dist, max_dist):
    rango_p = max_precio - min_precio
    rango_d = max_dist - min_dist
    sp = 100 * (1 - (precio - min_precio) / rango_p) if rango_p > 0 else 100
    sd = 100 * (1 - (dist - min_dist) / rango_d) if rango_d > 0 else 100
    return (sp + sd) / 2


def tend_str(ideess, campo):
    t = tendencia(ideess, campo)
    return t


def cerca_ranking(gasolineras, lat, lon, args):
    radio_km = args.radio
    top = args.top

    for c in COMBUSTIBLES:
        print(f"\n  --- {ETIQUETAS[c]} ---\n")

        candidatos = []
        for g in gasolineras:
            precio = parse_precio(g.get(c, ""))
            if precio is None or precio <= 0:
                continue
            g_lat = parse_precio(g.get("Latitud", ""))
            g_lon = parse_precio(g.get("Longitud (WGS84)", ""))
            if g_lat is None or g_lon is None:
                continue
            dist_recta = haversine(lat, lon, g_lat, g_lon)
            if dist_recta > radio_km:
                continue
            candidatos.append({
                "precio": precio,
                "gasolinera": g,
                "ideess": g.get("IDEESS", ""),
                "lat": g_lat,
                "lon": g_lon,
                "dist_recta": dist_recta,
            })

        candidatos.sort(key=lambda x: x["dist_recta"])
        candidatos = candidatos[:max(top * 3, 30)]

        if not candidatos:
            print("    No hay estaciones cerca.\n")
            continue

        distancias_carretera = osrm_distancias(lat, lon, candidatos)
        for i, cnd in enumerate(candidatos):
            cnd["dist"] = distancias_carretera[i] if i < len(distancias_carretera) else cnd["dist_recta"]

        precios_list = [x["precio"] for x in candidatos]
        dists_list = [x["dist"] for x in candidatos]
        min_p, max_p = min(precios_list), max(precios_list)
        min_d, max_d = min(dists_list), max(dists_list)

        for cnd in candidatos:
            cnd["score"] = _calcular_score(cnd["precio"], cnd["dist"], min_p, max_p, min_d, max_d)

        orden = getattr(args, "ordenar", "balance")
        if orden == "precio":
            key = lambda x: x["precio"]
        elif orden == "distancia":
            key = lambda x: x["dist"]
        else:
            key = lambda x: -x["score"]

        candidatos.sort(key=key)

        print(f"    {'#':<3} {'Precio':>8} {'Dist':>7} {'Score':>6} {'Tend':>4}  Estación")
        print(f"    {'-'*3:<3} {'-'*8:>8} {'-'*7:>7} {'-'*6:>6} {'-'*4:>4}  {'-'*42}")
        for i, cnd in enumerate(candidatos[:top], 1):
            g = cnd["gasolinera"]
            dist_str = f"{cnd['dist']:.1f}km" if cnd["dist"] < 100 else f"{cnd['dist']:.0f}km"
            t = tend_str(cnd["ideess"], c)
            print(f"    {i:<3} {cnd['precio']:.3f}eur {dist_str:>7} {cnd['score']:>5.0f} {t:>4}  {g.get('Rótulo', '')}")
            print(f"        {g.get('Dirección', '')}, {g.get('Municipio', '')} ({g.get('Provincia', '')})")
            if g.get("Horario"):
                print(f"        {g['Horario']}")
            print()


def _distancia_a_ruta(g_lat, g_lon, coords):
    dist_min = float("inf")
    for lon, lat in coords:
        d = haversine(lat, lon, g_lat, g_lon)
        if d < dist_min:
            dist_min = d
    return dist_min


def ruta_ranking(gasolineras, lat1, lon1, lat2, lon2, args):
    print("Calculando ruta...")
    url = f"https://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=full&geometries=geojson"
    r = requests.get(url, headers={"User-Agent": "fuelprices-app/1.0"}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("code") != "Ok":
        raise RuntimeError("No se pudo calcular la ruta")
    coords = data["routes"][0]["geometry"]["coordinates"]
    print(f"  Ruta calculada ({len(coords)} puntos, buscando en radio de {args.radio}km)\n")
    radio_km = args.radio
    top = args.top

    for c in COMBUSTIBLES:
        print(f"  --- {ETIQUETAS[c]} ---\n")
        candidatos = []
        for g in gasolineras:
            precio = parse_precio(g.get(c, ""))
            if precio is None or precio <= 0:
                continue
            g_lat = parse_precio(g.get("Latitud", ""))
            g_lon = parse_precio(g.get("Longitud (WGS84)", ""))
            if g_lat is None or g_lon is None:
                continue
            dist = _distancia_a_ruta(g_lat, g_lon, coords)
            if dist <= radio_km:
                candidatos.append({
                    "precio": precio,
                    "gasolinera": g,
                    "ideess": g.get("IDEESS", ""),
                    "lat": g_lat,
                    "lon": g_lon,
                    "dist": dist,
                })

        if not candidatos:
            print("    No hay estaciones cerca de la ruta.\n")
            continue

        orden = getattr(args, "ordenar", "balance")
        if orden == "precio":
            candidatos.sort(key=lambda x: x["precio"])
        elif orden == "distancia":
            candidatos.sort(key=lambda x: x["dist"])
        else:
            precios_list = [x["precio"] for x in candidatos]
            min_p, max_p = min(precios_list), max(precios_list)
            for cnd in candidatos:
                cnd["score"] = 100 * (1 - (cnd["precio"] - min_p) / (max_p - min_p)) if max_p > min_p else 100
            candidatos.sort(key=lambda x: -x["score"])

        print(f"    {'#':<3} {'Precio':>8} {'Dist':>7} {'Tend':>4}  Estación")
        print(f"    {'-'*3:<3} {'-'*8:>8} {'-'*7:>7} {'-'*4:>4}  {'-'*42}")
        for i, cnd in enumerate(candidatos[:top], 1):
            g = cnd["gasolinera"]
            t = tend_str(cnd["ideess"], c)
            print(f"    {i:<3} {cnd['precio']:.3f}eur {cnd['dist']:.1f}km {t:>4}  {g.get('Rótulo', '')}")
            print(f"        {g.get('Dirección', '')}, {g.get('Municipio', '')} ({g.get('Provincia', '')})")
            if g.get("Horario"):
                print(f"        {g['Horario']}")
            print()


def _preguntar_orden(args):
    while True:
        opcion = input("Ordenar por (p)recio o (d)istancia? [p/d]: ").strip().lower()
        if opcion in ("p", "precio"):
            args.ordenar = "precio"
            args.radio = 100
            break
        if opcion in ("d", "distancia"):
            args.ordenar = "distancia"
            args.radio = 50
            break


def _interactivo(gasolineras, args):
    while True:
        print()
        entrada = input("Presiona Enter para usar GPS, o escribe una dirección: ").strip()
        if not entrada:
            print("Obteniendo ubicación por GPS...")
            try:
                lat, lon = detectar_ubicacion()
                break
            except Exception as e:
                print(f"  {e}")
                print("  Escribe una dirección manualmente.")
                continue
        else:
            print(f"Buscando: {entrada}...")
            try:
                lat, lon = geocodificar(entrada + ", España")
                break
            except Exception as e:
                print(f"  ERROR: {e}. Intenta de nuevo.")
                continue
    _preguntar_orden(args)
    print(f"  Coordenadas: {lat:.5f}, {lon:.5f}")
    cerca_ranking(gasolineras, lat, lon, args)


def _ejecutar(args):
    print("Descargando datos...", end=" ")
    gasolineras, fecha = descargar_datos()
    print(f"OK ({len(gasolineras)} estaciones) - Datos: {fecha}")

    init_db()
    guardar_precios(gasolineras, fecha)

    if args.gps:
        print("Obteniendo ubicación por GPS...")
        lat, lon = detectar_ubicacion()
        print(f"  Coordenadas: {lat:.5f}, {lon:.5f}")
        cerca_ranking(gasolineras, lat, lon, args)
    elif args.ruta:
        orig_addr, dest_addr = args.ruta
        print(f"Ruta: {orig_addr} -> {dest_addr}")
        lat1, lon1 = geocodificar(orig_addr + ", España")
        lat2, lon2 = geocodificar(dest_addr + ", España")
        print(f"  Origen: {lat1:.5f}, {lon1:.5f}")
        print(f"  Destino: {lat2:.5f}, {lon2:.5f}")
        ruta_ranking(gasolineras, lat1, lon1, lat2, lon2, args)
    elif args.cerca:
        print(f"Buscando: {args.cerca}...")
        lat, lon = geocodificar(args.cerca + ", España")
        print(f"  Coordenadas: {lat:.5f}, {lon:.5f}")
        cerca_ranking(gasolineras, lat, lon, args)
    else:
        resumen(gasolineras)


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--cerca", metavar="DIRECCIÓN",
                        help="Dirección de origen para ordenar por distancia real")
    parser.add_argument("--ruta", nargs=2, metavar=("ORIGEN", "DESTINO"),
                        help="Buscar gasolineras en ruta de ORIGEN a DESTINO")
    parser.add_argument("--radio", type=int, default=50,
                        help="Radio de búsqueda en km (default: 50)")
    parser.add_argument("--top", "-t", type=int, default=10,
                        help="Número de resultados (default: 10)")
    parser.add_argument("--ordenar", choices=["balance", "precio", "distancia"], default="balance",
                        help='Criterio de ordenación (default: balance)')
    parser.add_argument("--gps", action="store_true", help="Usar ubicación GPS de Windows")
    parser.add_argument("--no-pause", action="store_true", help="No esperar Enter al final")
    args = parser.parse_args()

    if sum([bool(args.gps), bool(args.cerca), bool(args.ruta)]) > 1:
        print("Usa solo uno de: --gps, --cerca, --ruta.")
        return

    try:
        _ejecutar(args)
    except Exception as e:
        print(f"\nERROR: {e}")

    if not args.no_pause:
        try:
            input("\nPresiona Enter para salir...")
        except EOFError:
            pass


if __name__ == "__main__":
    main()
