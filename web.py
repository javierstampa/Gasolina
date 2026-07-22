from flask import Flask, request, render_template_string, jsonify
import precios as p
import math

app = Flask(__name__)

HTML = r"""
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Gasolina cerca de ti</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0d1117; color: #e6edf3; padding: 16px; }
  h1 { font-size: 1.4rem; margin-bottom: 16px; color: #58a6ff; }
  .form { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }
  .form input { flex: 1; min-width: 160px; padding: 10px 14px; border: 1px solid #30363d; border-radius: 8px; background: #161b22; color: #e6edf3; font-size: 1rem; }
  .form button, .form .btn-gps { padding: 10px 18px; border: none; border-radius: 8px; font-size: 1rem; cursor: pointer; }
  .form button { background: #238636; color: #fff; }
  .form .btn-gps { background: #1f6feb; color: #fff; }
  .form button:hover { background: #2ea043; }
  .form .btn-gps:hover { background: #388bfd; }
  .opts { display: flex; gap: 12px; margin-bottom: 16px; align-items: center; }
  .opts label { cursor: pointer; }
  .opts input[type=radio] { margin-right: 4px; }
  .info { color: #8b949e; font-size: 0.85rem; margin-bottom: 12px; }
  table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  th { text-align: left; padding: 8px 6px; border-bottom: 1px solid #30363d; color: #8b949e; font-weight: 600; }
  td { padding: 10px 6px; border-bottom: 1px solid #21262d; vertical-align: top; }
  .precio { font-weight: 700; font-size: 1rem; color: #7ee787; white-space: nowrap; }
  .dist { white-space: nowrap; }
  .tend { font-size: 1.1rem; }
  .rotulo { font-weight: 600; }
  .dir { color: #8b949e; font-size: 0.8rem; }
  .num { color: #8b949e; text-align: center; width: 24px; }
  .section { margin-top: 20px; }
  .section h2 { font-size: 1.1rem; margin-bottom: 8px; color: #f0883e; }
  .error { color: #f85149; background: #2d1215; padding: 12px; border-radius: 8px; margin-bottom: 12px; }
  .loading { display: none; color: #8b949e; text-align: center; padding: 40px; }
  .badge { display: inline-block; background: #21262d; padding: 2px 8px; border-radius: 12px; font-size: 0.75rem; color: #8b949e; }
</style>
</head>
<body>
<h1>Gasolina cerca de ti</h1>

<form class="form" method="post">
  <input type="text" name="direccion" placeholder="Dirección o población" value="{{ direccion or '' }}">
  <button type="submit">Buscar</button>
  <button type="submit" name="gps" value="1" class="btn-gps">Usar mi ubicación</button>
</form>

<div class="opts">
  <label><input type="radio" name="orden" value="balance" {{ 'checked' if orden=='balance' else '' }} onchange="this.form.submit()"> Balance</label>
  <label><input type="radio" name="orden" value="precio" {{ 'checked' if orden=='precio' else '' }} onchange="this.form.submit()"> Precio</label>
  <label><input type="radio" name="orden" value="distancia" {{ 'checked' if orden=='distancia' else '' }} onchange="this.form.submit()"> Distancia</label>
  <span class="badge">{{ fecha }}</span>
</div>

{% if error %}
<div class="error">{{ error }}</div>
{% endif %}

{% for comb, rows in resultados %}
<div class="section">
  <h2>{{ comb }}</h2>
  <table>
    <tr>
      <th></th><th>Precio</th><th>Dist</th><th>Tend</th><th>Estación</th>
    </tr>
    {% for r in rows %}
    <tr>
      <td class="num">{{ loop.index }}</td>
      <td class="precio">{{ "%.3f"|format(r.precio) }}€</td>
      <td class="dist">{{ "%.1f"|format(r.dist) }}km</td>
      <td class="tend">{{ r.tend }}</td>
      <td>
        <div class="rotulo">{{ r.rotulo }}</div>
        <div class="dir">{{ r.direccion }}, {{ r.municipio }} ({{ r.provincia }})</div>
      </td>
    </tr>
    {% endfor %}
  </table>
</div>
{% endfor %}

<div class="loading" id="loading">Cargando...</div>
<script>
document.querySelector('form').addEventListener('submit', function() {
  document.getElementById('loading').style.display = 'block';
});
document.querySelectorAll('.opts input').forEach(function(el) {
  el.addEventListener('change', function() {
    document.querySelector('form').submit();
  });
});
</script>
</body>
</html>
"""


def ranking(gasolineras, lat, lon, orden, top=15, radio=100):
    args = type("Args", (), {"ordenar": orden, "radio": radio, "top": top})()
    resultados = []
    for c in p.COMBUSTIBLES:
        candidatos = []
        for g in gasolineras:
            precio = p.parse_precio(g.get(c, ""))
            if precio is None or precio <= 0:
                continue
            g_lat = p.parse_precio(g.get("Latitud", ""))
            g_lon = p.parse_precio(g.get("Longitud (WGS84)", ""))
            if g_lat is None or g_lon is None:
                continue
            dist = p.haversine(lat, lon, g_lat, g_lon)
            if dist > radio:
                continue
            candidatos.append({
                "precio": precio,
                "gasolinera": g,
                "ideess": g.get("IDEESS", ""),
                "lat": g_lat,
                "lon": g_lon,
                "dist_recta": dist,
            })
        if not candidatos:
            continue
        candidatos.sort(key=lambda x: x["dist_recta"])
        candidatos = candidatos[:max(top * 3, 30)]
        distancias = p.osrm_distancias(lat, lon, candidatos)
        for i, cnd in enumerate(candidatos):
            cnd["dist"] = distancias[i] if i < len(distancias) else cnd["dist_recta"]
        if orden == "precio":
            candidatos.sort(key=lambda x: x["precio"])
        elif orden == "distancia":
            candidatos.sort(key=lambda x: x["dist"])
        else:
            precios_list = [x["precio"] for x in candidatos]
            dists_list = [x["dist"] for x in candidatos]
            min_p, max_p = min(precios_list), max(precios_list)
            min_d, max_d = min(dists_list), max(dists_list)
            for cnd in candidatos:
                cnd["score"] = p._calcular_score(cnd["precio"], cnd["dist"], min_p, max_p, min_d, max_d)
            candidatos.sort(key=lambda x: -x["score"])
        filas = []
        for cnd in candidatos[:top]:
            g = cnd["gasolinera"]
            t = p.tend_str(cnd["ideess"], c)
            filas.append({
                "precio": cnd["precio"],
                "dist": cnd["dist"],
                "tend": t,
                "rotulo": g.get("Rótulo", ""),
                "direccion": g.get("Dirección", ""),
                "municipio": g.get("Municipio", ""),
                "provincia": g.get("Provincia", ""),
            })
        resultados.append((p.ETIQUETAS[c], filas))
    return resultados


@app.route("/", methods=["GET", "POST"])
def index():
    direccion = request.form.get("direccion", "")
    usar_gps = request.form.get("gps")
    orden = request.form.get("orden", "balance")
    error = None
    resultados = []
    fecha = ""

    if request.method == "POST" or (request.args.get("gps") or request.args.get("direccion")):
        if request.method == "GET":
            direccion = request.args.get("direccion", "")
            usar_gps = request.args.get("gps")
            orden = request.args.get("orden", "balance")

        try:
            gasolineras, fecha = p.descargar_datos()
            p.init_db()
            p.guardar_precios(gasolineras, fecha)
            fecha = fecha.replace(" ", " &nbsp; ")

            if usar_gps:
                lat, lon = p.detectar_ubicacion()
            elif direccion:
                lat, lon = p.geocodificar(direccion + ", España")
            else:
                lat, lon = p.detectar_ubicacion()

            resultados = ranking(gasolineras, lat, lon, orden)
        except Exception as e:
            error = str(e)

    return render_template_string(HTML, direccion=direccion, orden=orden,
                                   fecha=fecha, error=error, resultados=resultados)


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    print(f"Servidor en http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port)
