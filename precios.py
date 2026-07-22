import subprocess
import json
import argparse
import math
from collections import defaultdict

import requests

URL_MITECO = "https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes/EstacionesTerrestres/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

COMBUSTIBLES = ["Precio Gasolina 95 E5", "Precio Gasoleo A"]
ETIQUETAS = {"Precio Gasolina 95 E5": "Gasolina 95", "Precio Gasoleo A": "Gasóleo A"}


def _usos():
    print("""
USOS:
  gasolina.exe                                                      Resumen de precios
  gasolina.exe --gps                                                Usa tu ubicación GPS
  gasolina.exe --cerca "San Agustín del Guadalix"                   Ranking por distancia
  gasolina.exe --gps -t 15                                          Más resultados
  gasolina.exe --gps --ordenar precio                               Ordenar por precio

  --radio       Radio de búsqueda en km (default: 50)
  --top / -t    Número de resultados (default: 10)
  --ordenar     balance | precio | distancia
  --no-pause    No esperar Enter al final
""")


def _descargar_json():
    for metodo, fn in [
        ("curl.exe", lambda: subprocess.run(["curl.exe", "-s", "--max-time", "30", URL_MITECO, "-A", UA, "-H", "Accept: application/json"], capture_output=True)),
        ("PowerShell", lambda: subprocess.run(["powershell.exe", "-NoProfile", "-Command", f'(Invoke-RestMethod -Uri \'{URL_MITECO}\' -Headers @{{"User-Agent"="{UA}";"Accept"="application/json"}} -TimeoutSec 30) | ConvertTo-Json -Depth 10 -Compress'], capture_output=True, text=True)),
    ]:
        try:
            result = fn()
            if result.returncode != 0:
                continue
            raw = result.stdout
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            return json.loads(raw)
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
            continue
    raise RuntimeError("No se pudo descargar los datos.")


def descargar_datos():
    data = _descargar_json()
    return data.get("ListaEESSPrecio", []), data.get("Fecha", "fecha desconocida")


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
    r = requests.get(url, headers={"User-Agent": "fuelprices-app/1.0"}, timeout=30)
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
        print(f"{comb:<20} {media:>7.3f}€ {min(precios):>7.3f}€ {max(precios):>7.3f}€ {len(precios):>6}")


def _calcular_score(precio, dist, min_precio, max_precio, min_dist, max_dist):
    rango_p = max_precio - min_precio
    rango_d = max_dist - min_dist
    sp = 100 * (1 - (precio - min_precio) / rango_p) if rango_p > 0 else 100
    sd = 100 * (1 - (dist - min_dist) / rango_d) if rango_d > 0 else 100
    return (sp + sd) / 2


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

        print(f"    {'#':<3} {'Precio':>8} {'Dist':>7} {'Score':>6}  Estación")
        print(f"    {'-'*3:<3} {'-'*8:>8} {'-'*7:>7} {'-'*6:>6}  {'-'*42}")
        for i, cnd in enumerate(candidatos[:top], 1):
            g = cnd["gasolinera"]
            dist_str = f"{cnd['dist']:.1f}km" if cnd["dist"] < 100 else f"{cnd['dist']:.0f}km"
            print(f"    {i:<3} {cnd['precio']:.3f}€ {dist_str:>7} {cnd['score']:>5.0f}  {g.get('Rótulo', '')}")
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

    if args.gps:
        print("Obteniendo ubicación por GPS...")
        lat, lon = detectar_ubicacion()
        print(f"  Coordenadas: {lat:.5f}, {lon:.5f}")
        cerca_ranking(gasolineras, lat, lon, args)
    elif args.cerca:
        print(f"Buscando: {args.cerca}...")
        lat, lon = geocodificar(args.cerca + ", España")
        print(f"  Coordenadas: {lat:.5f}, {lon:.5f}")
        cerca_ranking(gasolineras, lat, lon, args)
    else:
        _interactivo(gasolineras, args)


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--cerca", metavar="DIRECCIÓN",
                        help="Dirección de origen para ordenar por distancia real")
    parser.add_argument("--radio", type=int, default=50,
                        help="Radio de búsqueda en km (default: 50)")
    parser.add_argument("--top", "-t", type=int, default=10,
                        help="Número de resultados (default: 10)")
    parser.add_argument("--ordenar", choices=["balance", "precio", "distancia"], default="balance",
                        help='Criterio de ordenación (default: balance)')
    parser.add_argument("--gps", action="store_true", help="Usar ubicación GPS de Windows")
    parser.add_argument("--no-pause", action="store_true", help="No esperar Enter al final")
    args = parser.parse_args()

    if args.gps and args.cerca:
        print("Usa --gps o --cerca, no ambos.")
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
