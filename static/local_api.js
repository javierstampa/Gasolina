/* GasAll local API: porta a JS la lógica del backend Flask (app.py + precios.py).
   Se ejecuta DENTRO de la app (WKWebView). Sobrescribe window.fetch para /api/*.
   En Node se exporta como módulo para poder testear el cálculo. */
(function (global) {
  "use strict";

  var FUELS = {
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
  };
  var FUELS_ITALIA = [
    "Precio Gasolina 95 E5",
    "Precio Gasoleo A",
    "Precio Gasoleo Premium",
    "Precio Diésel Renovable",
    "Precio Gases licuados del petróleo",
    "Precio Gas Natural Comprimido",
    "Precio Gas Natural Licuado",
  ];
  var IT_FUEL_MAP = {
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
  };

  /* ---------- utilidades ---------- */
  function parsePrecio(v) {
    if (v === null || v === undefined || v === "") return null;
    var f = parseFloat(String(v).replace(",", ".").trim());
    return isNaN(f) ? null : f;
  }
  function haversine(lat1, lon1, lat2, lon2) {
    var R = 6371;
    var dlat = (lat2 - lat1) * Math.PI / 180;
    var dlon = (lon2 - lon1) * Math.PI / 180;
    var a = Math.sin(dlat / 2) * Math.sin(dlat / 2) +
      Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
      Math.sin(dlon / 2) * Math.sin(dlon / 2);
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  }
  function es24h(horario) {
    if (!horario) return false;
    var h = String(horario).toUpperCase();
    return h.indexOf("24H") >= 0 || h.indexOf("24 H") >= 0 || h.indexOf("TODOS LOS DÍAS") >= 0;
  }
  function diasIncluye(expr, hoy) {
    var e = String(expr).toUpperCase();
    if (e.indexOf(hoy) >= 0) return true;
    var orden = "LMXJVSD";
    if (e.indexOf("-") >= 0) {
      var partes = e.split("-");
      var ini = partes[0].trim(), fin = partes[1].trim();
      var i0 = orden.indexOf(ini), i1 = orden.indexOf(fin);
      if (i0 >= 0 && i1 >= 0) return orden.slice(i0, i1 + 1).indexOf(hoy) >= 0;
    }
    return false;
  }
  function minuto(hhmm) {
    var t = String(hhmm).trim().replace(".", ":");
    if (t.indexOf(":") < 0) t += ":00";
    var p = t.split(":");
    return parseInt(p[0], 10) * 60 + parseInt(p[1], 10);
  }
  function abiertaAhora(horario) {
    if (!horario) return null;
    if (es24h(horario)) return true;
    var mapa = { sun: "D", mon: "L", tue: "M", wed: "X", thu: "J", fri: "V", sat: "S" };
    var hoy = mapa[new Date().toString().slice(0, 3).toLowerCase()];
    if (!hoy) return null;
    var ahora = new Date();
    var actual = ahora.getHours() * 60 + ahora.getMinutes();
    var bloques = String(horario).split(";");
    for (var i = 0; i < bloques.length; i++) {
      var b = bloques[i].trim();
      if (!b || b.indexOf(":") < 0) continue;
      var colon = b.indexOf(":");
      var dias = b.slice(0, colon);
      var horas = b.slice(colon + 1);
      if (!diasIncluye(dias, hoy)) continue;
      var rangos = horas.split(";");
      for (var j = 0; j < rangos.length; j++) {
        var rango = rangos[j].trim();
        if (rango.indexOf("-") < 0) continue;
        var partes = rango.split("-");
        var i0 = minuto(partes[0]), i1 = minuto(partes[1]);
        if (isNaN(i0) || isNaN(i1)) continue;
        if (i1 < i0) {
          if (actual >= i0 || actual < i1) return true;
        } else if (i0 <= actual && actual < i1) {
          return true;
        }
      }
    }
    return false;
  }

  /* ---------- historial (localStorage) ---------- */
  function histKey(ideess, fuel) { return "hist:" + ideess + ":" + fuel; }
  function histGet(ideess, fuel) {
    try { return JSON.parse(global.localStorage.getItem(histKey(ideess, fuel))) || []; }
    catch (e) { return []; }
  }
  function histSet(ideess, fuel, arr) {
    try { global.localStorage.setItem(histKey(ideess, fuel), JSON.stringify(arr)); } catch (e) {}
  }
  function recordHistory(ideess, fuel, precio, fecha) {
    var arr = histGet(ideess, fuel);
    var last = arr.length ? arr[arr.length - 1] : null;
    if (last && last.fecha === fecha) {
      if (last.precio !== precio) { last.precio = precio; histSet(ideess, fuel, arr); }
      return;
    }
    arr.push({ fecha: fecha || "hoy", precio: precio });
    if (arr.length > 400) arr = arr.slice(-400);
    histSet(ideess, fuel, arr);
  }
  function historial(ideess, fuel) {
    var arr = histGet(ideess, fuel);
    var out = [], seen = null;
    for (var i = 0; i < arr.length; i++) {
      if (arr[i].precio === seen) continue;
      seen = arr[i].precio;
      out.push({ fecha: arr[i].fecha, precio: arr[i].precio });
      if (out.length >= 400) break;
    }
    return out;
  }
  function tendStr(ideess, fuel) {
    var arr = historial(ideess, fuel);
    if (arr.length < 2) return " ";
    var p1 = arr[arr.length - 1].precio, p2 = arr[arr.length - 2].precio;
    if (p1 > p2) return "+";
    if (p1 < p2) return "-";
    return "=";
  }

  /* ---------- normalización Italia (port de precios.py) ---------- */
  function normalizeItaly(anagraficaCSV, prezzoCSV, correcciones) {
    var fecha = "desconocida";
    var header = null, estacionesRaw = [];
    var lines = anagraficaCSV.replace(/\r/g, "").split("\n");
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      var m = line.match(/Estrazione del\s+(\d{4}-\d{2}-\d{2})/);
      if (m) { fecha = m[1]; continue; }
      if (/^idImpianto/.test(line)) { header = line.split("|"); continue; }
      if (!header) continue;
      var vals = line.split("|");
      if (vals.length < header.length) continue;
      var obj = {};
      for (var j = 0; j < header.length; j++) obj[header[j]] = vals[j];
      estacionesRaw.push(obj);
    }
    var mejores = {};
    header = null;
    var pLines = prezzoCSV.replace(/\r/g, "").split("\n");
    for (var k = 0; k < pLines.length; k++) {
      var pl = pLines[k];
      if (/^idImpianto/.test(pl)) { header = pl.split("|"); continue; }
      if (!header) continue;
      var pvals = pl.split("|");
      if (pvals.length < 5) continue;
      var prow = {};
      for (var j2 = 0; j2 < header.length; j2++) prow[header[j2]] = pvals[j2];
      var fuel = IT_FUEL_MAP[String(prow.descCarburante || "").trim()];
      if (!fuel) continue;
      var precio = parsePrecio(prow.prezzo);
      if (precio === null || precio <= 0) continue;
      var dt;
      try {
        var dm = String(prow.dtComu || "").trim().match(/(\d{2})\/(\d{2})\/(\d{4}) (\d{2}):(\d{2}):(\d{2})/);
        if (!dm) continue;
        dt = new Date(+dm[3], +dm[2] - 1, +dm[1], +dm[4], +dm[5], +dm[6]).getTime();
      } catch (e) { continue; }
      var isself = parseInt(prow.isSelf, 10) || 0;
      var clave = (String(prow.idImpianto || "").trim()) + "\u0001" + fuel;
      var actual = mejores[clave];
      if (!actual || dt > actual[0] || (dt === actual[0] && isself >= actual[1])) {
        mejores[clave] = [dt, isself, precio];
      }
    }
    var preciosPorImp = {};
    Object.keys(mejores).forEach(function (c) {
      var sp = c.indexOf("\u0001");
      var id2 = c.slice(0, sp), f = c.slice(sp + 1);
      if (!preciosPorImp[id2]) preciosPorImp[id2] = {};
      preciosPorImp[id2][f] = mejores[c][2].toFixed(3);
    });
    var out = [];
    for (var n = 0; n < estacionesRaw.length; n++) {
      var r = estacionesRaw[n];
      var idImp = String(r.idImpianto || "").trim();
      if (!idImp) continue;
      var lat = parsePrecio(String(r.Latitudine || "").trim());
      var lon = parsePrecio(String(r.Longitudine || "").trim());
      if (lat === null || lon === null) continue;
      var rotulo = String(r["Nome Impianto"] || r.Gestore || "").trim().replace(/\s+/g, " ");
      var st = {
        IDEESS: "IT_" + idImp,
        "Rótulo": rotulo,
        "Dirección": String(r.Indirizzo || "").trim(),
        "Municipio": String(r.Comune || "").trim(),
        "Provincia": String(r.Provincia || "").trim(),
        "Latitud": lat.toFixed(6).replace(".", ","),
        "Longitud (WGS84)": lon.toFixed(6).replace(".", ","),
        "Horario": "",
      };
        var ppx = preciosPorImp[idImp];
        if (ppx) {
          Object.keys(ppx).forEach(function (f2) { st[f2] = ppx[f2]; });
        }
      out.push(st);
    }
    correcciones = correcciones || {};
    out.forEach(function (st) {
      var c = correcciones[st.IDEESS];
      if (c && Array.isArray(c) && c.length >= 2) {
        st["Latitud"] = c[0].toFixed(6).replace(".", ",");
        st["Longitud (WGS84)"] = c[1].toFixed(6).replace(".", ",");
      }
    });
    return { estaciones: out, fecha: fecha };
  }

  /* ---------- endpoints (port de app.py) ---------- */
  function apiFuels(pais) {
    if (pais === "italia") {
      return FUELS_ITALIA.map(function (k) { return { id: k, label: FUELS[k] }; });
    }
    return Object.keys(FUELS).map(function (k) { return { id: k, label: FUELS[k] }; });
  }

  function apiStations(q, es, it, fechaEs, fechaIt) {
    var lat = q.lat ? parseFloat(q.lat) : null;
    var lon = q.lon ? parseFloat(q.lon) : null;
    var fuel = q.fuel || "Precio Gasolina 95 E5";
    var sort = q.sort || "balance";
    var radius = q.radius ? parseFloat(q.radius) : 60;
    var top = q.top ? parseInt(q.top, 10) : 50;
    var openOnly = q.open === "1";
    var scope = q.scope || "cerca";
    var pais = q.pais || "espana";

    var gasolineras, fecha;
    if (pais === "italia") { gasolineras = it; fecha = fechaIt; }
    else { gasolineras = es; fecha = fechaEs; }

    if (scope === "pais") { lat = null; lon = null; if (sort === "distancia") sort = "precio"; }
    else if (lat === null || lon === null) return { error: "lat y lon requeridos" };

    var rows = [];
    for (var i = 0; i < gasolineras.length; i++) {
      var g = gasolineras[i];
      var precio = parsePrecio(g[fuel]);
      if (precio === null || precio <= 0) continue;
      var gLat = parsePrecio(g["Latitud"]);
      var gLon = parsePrecio(g["Longitud (WGS84)"]);
      if (gLat === null || gLon === null) continue;
      var dist = 0;
      if (scope !== "pais") {
        dist = haversine(lat, lon, gLat, gLon);
        if (dist > radius) continue;
      }
      var horario = g["Horario"] || "";
      if (openOnly && !abiertaAhora(horario)) continue;
      rows.push({
        ideess: g.IDEESS || "", rotulo: g["Rótulo"] || "", direccion: g["Dirección"] || "",
        municipio: g["Municipio"] || "", provincia: g["Provincia"] || "", horario: horario,
        lat: gLat, lon: gLon, precio: Math.round(precio * 1000) / 1000,
        dist: Math.round(dist * 100) / 100, tend: " ",
        abierta: abiertaAhora(horario), es_24h: es24h(horario),
      });
    }

    if (scope === "pais") {
      rows.sort(function (a, b) { return a.precio - b.precio || a.provincia.localeCompare(b.provincia); });
      rows = rows.slice(0, Math.max(top * 3, 120));
    } else if (sort === "distancia") {
      rows.sort(function (a, b) { return a.dist - b.dist || a.precio - b.precio; });
      rows = rows.slice(0, Math.max(top * 3, 120));
    }

    var preciosList = rows.map(function (x) { return x.precio; });
    var distsList = rows.map(function (x) { return x.dist; });
    var minP = Math.min.apply(null, preciosList), maxP = Math.max.apply(null, preciosList);
    var minD = Math.min.apply(null, distsList), maxD = Math.max.apply(null, distsList);
    rows.forEach(function (x) {
      var sp = maxP > minP ? 100 * (1 - (x.precio - minP) / (maxP - minP)) : 100;
      var sd = maxD > minD ? 100 * (1 - (x.dist - minD) / (maxD - minD)) : 100;
      x.score = Math.round((sp + sd) / 2 * 10) / 10;
    });

    if (sort === "precio") rows.sort(function (a, b) { return a.precio - b.precio || a.dist - b.dist; });
    else if (sort === "distancia") rows.sort(function (a, b) { return a.dist - b.dist || a.precio - b.precio; });
    else rows.sort(function (a, b) { return (b.score - a.score) || a.precio - b.precio; });

    var final = rows.slice(0, top);
    final.forEach(function (x) {
      x.tend = tendStr(x.ideess, fuel);
      recordHistory(x.ideess, fuel, x.precio, fecha);
    });

    return { fecha: fecha, fuel: fuel, sort: sort, scope: scope, pais: pais, total: rows.length, stations: final };
  }

  function apiStation(ideess, es, it, fechaEs, fechaIt) {
    var pais = String(ideess).indexOf("IT_") === 0 ? "italia" : "espana";
    var gasolineras, fecha;
    if (pais === "italia") { gasolineras = it; fecha = fechaIt; }
    else { gasolineras = es; fecha = fechaEs; }
    var g = null;
    for (var i = 0; i < gasolineras.length; i++) {
      if (gasolineras[i].IDEESS === ideess) { g = gasolineras[i]; break; }
    }
    if (!g) return { error: "Estación no encontrada" };
    var precios = [];
    Object.keys(FUELS).forEach(function (campo) {
      var precio = parsePrecio(g[campo]);
      if (precio === null || precio <= 0) return;
      precios.push({ fuel: campo, label: FUELS[campo], precio: Math.round(precio * 1000) / 1000, tend: tendStr(ideess, campo) });
      recordHistory(ideess, campo, Math.round(precio * 1000) / 1000, fecha);
    });
    precios.sort(function (a, b) { return a.precio - b.precio; });
    return {
      ideess: ideess, rotulo: g["Rótulo"] || "", direccion: g["Dirección"] || "",
      municipio: g["Municipio"] || "", provincia: g["Provincia"] || "",
      localidad: g["Localidad"] || "", horario: g["Horario"] || "",
      lat: parsePrecio(g["Latitud"]), lon: parsePrecio(g["Longitud (WGS84)"]),
      precios: precios, fecha: fecha,
      abierta: abiertaAhora(g["Horario"]), es_24h: es24h(g["Horario"]),
    };
  }

  function apiHistory(ideess, fuel) {
    return { ideess: ideess, fuel: fuel, data: historial(ideess, fuel) };
  }

  function apiGeocode(q, pais) {
    var cc = pais === "italia" ? "it" : "es";
    var url = "https://nominatim.openstreetmap.org/search?format=json&limit=1&countrycodes=" + cc +
      "&q=" + encodeURIComponent(q + ", " + (pais === "italia" ? "Italia" : "España"));
    return fetch(url, { headers: { "Accept": "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data || !data.length) throw new Error("No se encontró la dirección: " + q);
        return { lat: parseFloat(data[0].lat), lon: parseFloat(data[0].lon), label: q, pais: pais };
      });
  }

  function apiRoute(p, es, it, fechaEs, fechaIt) {
    var pais = p.pais || "espana";
    var cc = pais === "italia" ? "it" : "es";
    var suf = pais === "italia" ? "Italia" : "España";
    var fuel = p.fuel || "Precio Gasoleo A";
    var radio = p.radio ? parseFloat(p.radio) : 3.0;
    var geoc = function (q) {
      return fetch("https://nominatim.openstreetmap.org/search?format=json&limit=1&countrycodes=" + cc +
        "&q=" + encodeURIComponent(q + ", " + suf), { headers: { "Accept": "application/json" } })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (!data || !data.length) throw new Error("No se encontró: " + q);
          return [parseFloat(data[0].lat), parseFloat(data[0].lon)];
        });
    };
    return Promise.all([geoc(p.origen), geoc(p.destino)]).then(function (pts) {
      var lat1 = pts[0][0], lon1 = pts[0][1], lat2 = pts[1][0], lon2 = pts[1][1];
      var url = "https://router.project-osrm.org/route/v1/driving/" + lon1 + "," + lat1 + ";" + lon2 + "," + lat2 +
        "?overview=full&geometries=geojson";
      return fetch(url, { headers: { "User-Agent": "gasall-app/1.0" } })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (!data.routes || !data.routes.length) throw new Error("No se pudo calcular la ruta");
          var route = data.routes[0];
          var coords = route.geometry.coordinates;
          var kmTotal = Math.round(route.distance / 1000 * 10) / 10;
          var gasolineras = pais === "italia" ? it : es;
          var fecha = pais === "italia" ? fechaIt : fechaEs;

          var minLon = Infinity, maxLon = -Infinity, minLat = Infinity, maxLat = -Infinity;
          coords.forEach(function (c) {
            minLon = Math.min(minLon, c[0]); maxLon = Math.max(maxLon, c[0]);
            minLat = Math.min(minLat, c[1]); maxLat = Math.max(maxLat, c[1]);
          });
          minLon -= radio / 111.0; maxLon += radio / 111.0;
          minLat -= radio / 111.0; maxLat += radio / 111.0;
          var step = Math.max(1, Math.floor(coords.length / 40));
          var sampled = [];
          for (var i = 0; i < coords.length; i += step) sampled.push(coords[i]);

          var cands = [];
          for (var j = 0; j < gasolineras.length; j++) {
            var g = gasolineras[j];
            var precio = parsePrecio(g[fuel]);
            if (precio === null || precio <= 0) continue;
            var gLat = parsePrecio(g["Latitud"]);
            var gLon = parsePrecio(g["Longitud (WGS84)"]);
            if (gLat === null || gLon === null) continue;
            if (!(minLat <= gLat && gLat <= maxLat && minLon <= gLon && gLon <= maxLon)) continue;
            var dist = distRuta(gLat, gLon, sampled);
            if (dist <= radio) {
              cands.push({
                ideess: g.IDEESS || "", rotulo: g["Rótulo"] || "", direccion: g["Dirección"] || "",
                municipio: g["Municipio"] || "", provincia: g["Provincia"] || "",
                horario: g["Horario"] || "", lat: gLat, lon: gLon,
                precio: Math.round(precio * 1000) / 1000, desvio: Math.round(dist * 100) / 100,
                abierta: abiertaAhora(g["Horario"]),
              });
            }
          }
          cands.sort(function (a, b) { return a.precio - b.precio || a.desvio - b.desvio; });
          return {
            origen: { lat: lat1, lon: lon1, label: p.origen },
            destino: { lat: lat2, lon: lon2, label: p.destino },
            km: kmTotal, geometry: coords, stations: cands.slice(0, 30),
            fecha: fecha, fuel: fuel, pais: pais,
          };
        });
    });
  }
  function distRuta(gLat, gLon, sampled) {
    var min = Infinity;
    for (var i = 0; i < sampled.length; i++) {
      var d = haversine(sampled[i][1], sampled[i][0], gLat, gLon);
      if (d < min) min = d;
    }
    return min;
  }

  /* ---------- estado de datos + carga ---------- */
  var DATA = { es: [], it: [], fechaEs: "", fechaIt: "" };

  function loadData() {
    return Promise.all([
      fetch("/data/datos.json?_=" + Date.now()).then(function (r) { return r.json(); }),
      fetch("/data/anagrafica.csv?_=" + Date.now()).then(function (r) { return r.text(); }),
      fetch("/data/prezzo.csv?_=" + Date.now()).then(function (r) { return r.text(); }),
      fetch("/data/correcciones_it.json?_=" + Date.now()).then(function (r) { return r.json(); }).catch(function () { return {}; }),
    ]).then(function (res) {
      var es = res[0];
      DATA.es = es.ListaEESSPrecio || es.estaciones || [];
      DATA.fechaEs = es.Fecha || es.fecha || "desconocida";
      var it = normalizeItaly(res[1], res[2], res[3]);
      DATA.it = it.estaciones;
      DATA.fechaIt = it.fecha;
      return { fechaEs: DATA.fechaEs, estaciones: DATA.es.length, fechaIt: it.fecha, it: it.estaciones.length };
    });
  }

  var core = {
    FUELS: FUELS,
    FUELS_ITALIA: FUELS_ITALIA,
    parsePrecio: parsePrecio,
    haversine: haversine,
    abiertaAhora: abiertaAhora,
    es24h: es24h,
    normalizeItaly: normalizeItaly,
    apiFuels: apiFuels,
    apiStations: apiStations,
    apiStation: apiStation,
    apiHistory: apiHistory,
    apiGeocode: apiGeocode,
    apiRoute: apiRoute,
    loadData: loadData,
    getData: function () { return DATA; },
    recordHistory: recordHistory,
    historial: historial,
    tendStr: tendStr,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = core;
    return;
  }

  /* ---------- navegador: sobrescribir fetch ---------- */
  var isNativeApp = global.location && (global.location.protocol === "gasall:" || global.__GASALL_NATIVE__ === true);
  if (!isNativeApp) return; // solo actúa dentro de la app (no toca la web en servidores)

  global.__GASALL_DATA = DATA;
  global.__gasallLoadData = loadData;

  var realFetch = global.fetch.bind(global);

  function respond(body, status) {
    return Promise.resolve(new Response(JSON.stringify(body), {
      status: status || 200,
      headers: { "Content-Type": "application/json" },
    }));
  }
  function handleApi(u, opts) {
    var urlObj = new URL(u, "gasall://app");
    var q = {};
    urlObj.searchParams.forEach(function (v, k) { q[k] = v; });
    var path = urlObj.pathname;
    var pais = q.pais || "espana";

    if (path === "/api/fuels") return respond(apiFuels(pais));
    if (path === "/api/stations") return respond(apiStations(q, DATA.es, DATA.it, DATA.fechaEs, DATA.fechaIt));
    if (path === "/api/station") return respond(apiStation(q.ideess || "", DATA.es, DATA.it, DATA.fechaEs, DATA.fechaIt));
    if (path === "/api/history") return respond(apiHistory(q.ideess || "", q.fuel || ""));
    if (path === "/api/geocode") return apiGeocode(q.q || "", pais).then(respond).catch(function (e) { return respond({ error: e.message }, 404); });
    if (path === "/api/route") return apiRoute(q, DATA.es, DATA.it, DATA.fechaEs, DATA.fechaIt).then(respond).catch(function (e) { return respond({ error: e.message }, 400); });
    if (path === "/api/refresh") {
      var method = opts && opts.method ? opts.method.toUpperCase() : "GET";
      if (method === "POST") return doRefresh(pais);
    }
    return realFetch(u, opts);
  }

  function doRefresh(pais) {
    var webkit = global.webkit && global.webkit.messageHandlers && global.webkit.messageHandlers.gasall;
    if (webkit) {
      return new Promise(function (resolve, reject) {
        global.__gasallRefreshResolve = resolve;
        global.__gasallRefreshReject = reject;
        var t = setTimeout(function () { reject(new Error("Tiempo de espera agotado")); }, 120000);
        global.__gasallRefreshTimer = t;
        webkit.postMessage({ type: "refresh", pais: pais });
      });
    }
    // Sin puente nativo (p. ej. test en Node o navegador): recarga los datos servidos.
    return loadData().then(function (r) {
      return respond({ ok: true, fecha: DATA.fechaEs, estaciones: DATA.es.length, italia: DATA.it.length });
    });
  }

  global.__gasallRefreshDone = function (res) {
    if (global.__gasallRefreshTimer) clearTimeout(global.__gasallRefreshTimer);
    if (res && res.error) {
      if (global.__gasallRefreshReject) global.__gasallRefreshReject(new Error(res.error));
      return;
    }
    // Recargar datos tras el refresco nativo
    loadData().then(function () {
      if (global.__gasallRefreshResolve) global.__gasallRefreshResolve(respond({ ok: true, fecha: res.fecha, estaciones: res.estaciones, italia: res.italia }));
    }).catch(function (e) {
      if (global.__gasallRefreshReject) global.__gasallRefreshReject(new Error(e.message || "Error al refrescar"));
    });
  };

  global.fetch = function (url, opts) {
    var u = typeof url === "string" ? url : (url && url.url);
    if (typeof u === "string" && u.indexOf("/api/") === 0) return handleApi(u, opts);
    return realFetch(url, opts);
  };

  // Cargar datos iniciales en paralelo al arranque de la web
  loadData().catch(function (e) { console.error("GasAll: no se pudieron cargar los datos", e); });
})(typeof window !== "undefined" ? window : globalThis);
