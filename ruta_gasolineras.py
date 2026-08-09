import requests
import subprocess
import json
import math
import sys

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
URL_MITECO = "https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes/EstacionesTerrestres/"

ORIGEN = "Calle Cómpeta 6, Málaga"
DESTINO = "Villavieja del Lozoya, Madrid"

RADIO_KM = 3.0  # máximo desvío lateral desde la ruta


def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def geocodificar(direccion):
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": direccion, "format": "json", "limit": 1, "addressdetails": 0}
    r = requests.get(url, params=params, headers={"User-Agent": "fuelprices-app/1.0"}, timeout=15)
    r.raise_for_status()
    data = r.json()
    if not data:
        raise ValueError(f"No se encontró la dirección: {direccion}")
    return float(data[0]["lat"]), float(data[0]["lon"])


def descargar_datos():
    for metodo, fn in [
        ("curl.exe", lambda: subprocess.run(["curl.exe", "-s", "--max-time", "60", URL_MITECO, "-A", UA, "-H", "Accept: application/json"], capture_output=True)),
        ("PowerShell", lambda: subprocess.run(["powershell.exe", "-NoProfile", "-Command", f'(Invoke-RestMethod -Uri \'{URL_MITECO}\' -Headers @{{"User-Agent"="{UA}";"Accept"="application/json"}} -TimeoutSec 60) | ConvertTo-Json -Depth 10 -Compress'], capture_output=True, text=True)),
        ("requests", lambda: requests.get(URL_MITECO, headers={"User-Agent": UA, "Accept": "application/json"}, timeout=60)),
    ]:
        try:
            result = fn()
            if metodo == "requests":
                result.raise_for_status()
                data = result.json()
                break
            if result.returncode != 0:
                continue
            raw = result.stdout
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            data = json.loads(raw)
            break
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError, requests.RequestException):
            continue
    else:
        raise RuntimeError("No se pudo descargar los datos del MITECO.")
    return data.get("ListaEESSPrecio", []), data.get("Fecha", "fecha desconocida")


def parse_precio(s):
    if not s:
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def es_24h(horario):
    if not horario:
        return False
    h = horario.upper()
    return "24H" in h or "24 H" in h or "TODOS LOS DÍAS" in h


def distancia_a_ruta(g_lat, g_lon, coords):
    d_min = float("inf")
    for lon, lat in coords:
        d = haversine(lat, lon, g_lat, g_lon)
        if d < d_min:
            d_min = d
    return d_min


def main():
    print(f"Ruta: {ORIGEN} -> {DESTINO}")
    lat1, lon1 = geocodificar(ORIGEN + ", España")
    lat2, lon2 = geocodificar(DESTINO + ", España")
    print(f"  Origen:  {lat1:.5f}, {lon1:.5f}")
    print(f"  Destino: {lat2:.5f}, {lon2:.5f}")

    print("\nCalculando ruta con OSRM...")
    url = f"https://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=full&geometries=geojson"
    r = requests.get(url, headers={"User-Agent": "fuelprices-app/1.0"}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("code") != "Ok":
        raise RuntimeError("No se pudo calcular la ruta")
    route = data["routes"][0]
    coords = route["geometry"]["coordinates"]
    km_total = route["distance"] / 1000
    print(f"  Ruta calculada: {len(coords)} puntos, {km_total:.0f} km")

    print("\nDescargando precios MITECO...")
    gasolineras, fecha = descargar_datos()
    print(f"  {len(gasolineras)} estaciones - Datos: {fecha}")

    candidatos = []
    for g in gasolineras:
        precio = parse_precio(g.get("Precio Gasoleo A", ""))
        if precio is None or precio <= 0:
            continue
        g_lat = parse_precio(g.get("Latitud", ""))
        g_lon = parse_precio(g.get("Longitud (WGS84)", ""))
        if g_lat is None or g_lon is None:
            continue
        horario = g.get("Horario", "")
        if not es_24h(horario):
            continue
        dist = distancia_a_ruta(g_lat, g_lon, coords)
        if dist <= RADIO_KM:
            candidatos.append({
                "precio": precio,
                "dist": dist,
                "rotulo": g.get("Rótulo", ""),
                "direccion": g.get("Dirección", ""),
                "municipio": g.get("Municipio", ""),
                "provincia": g.get("Provincia", ""),
                "horario": horario,
            })

    candidatos.sort(key=lambda x: (x["precio"], x["dist"]))

    print(f"\nGasolineras Gasóleo A 24h a <= {RADIO_KM} km de la ruta: {len(candidatos)}")
    print(f"\n{'#':<4}{'Precio':>8} {'Desvío':>8}  Estación")
    print("-" * 70)
    for i, c in enumerate(candidatos[:20], 1):
        print(f"{i:<4}{c['precio']:.3f}€ {c['dist']:>6.2f}km  {c['rotulo']}")
        print(f"     {c['direccion']}, {c['municipio']} ({c['provincia']})")
        print(f"     {c['horario']}")

    if candidatos:
        mejor = candidatos[0]
        print("\n" + "=" * 70)
        print("GASOLINERA MÁS BARATA EN RUTA (diésel 24h):")
        print(f"  {mejor['rotulo']}")
        print(f"  {mejor['direccion']}, {mejor['municipio']} ({mejor['provincia']})")
        print(f"  Precio Gasóleo A: {mejor['precio']:.3f} €/L")
        print(f"  Desvío lateral desde la ruta: {mejor['dist']:.2f} km")
        print(f"  Horario: {mejor['horario']}")
        print("=" * 70)


if __name__ == "__main__":
    main()
