(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const FUEL_DEFAULT = "Precio Gasolina 95 E5";
  const CAPITALS = { espana: { lat: 40.4168, lon: -3.7038, label: "España" }, italia: { lat: 41.9028, lon: 12.4964, label: "Italia" } };

  const state = {
    map: null,
    markers: new L.LayerGroup(),
    current: null,
    fuel: FUEL_DEFAULT,
    sort: "balance",
    scope: "cerca",
    pais: "espana",
    radius: parseInt(load("radius")) || 60,
    openOnly: false,
    favsOnly: false,
    stations: [],
    favorites: load("favorites") || [],
    vehicle: load("vehicle") || { tank: 50, cons: 6.0, dist: 500 },
    route: null,
    historyChart: null,
    radiusCircle: null,
  };

  /* ---------------- Utilidades ---------------- */
  function load(k) {
    try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; }
  }
  function save(k, v) {
    try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {}
  }
  function fmtPrecio(p) { return p.toFixed(3).replace(".", ",") + " €"; }
  function fmtDist(d) { return d < 100 ? d.toFixed(1) + " km" : Math.round(d) + " km"; }
  function esc(s) {
    return String(s || "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function tendCls(t) {
    if (t === "+") return "up";
    if (t === "-") return "down";
    return "flat";
  }
  function tendArrow(t) {
    if (t === "+") return "↑";
    if (t === "-") return "↓";
    return "·";
  }
  async function getJSON(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error((await r.json()).error || "Error de red");
    return r.json();
  }
  function showLoading() { $("loading").classList.remove("hidden"); }
  function hideLoading() { $("loading").classList.add("hidden"); }
  function toast(msg) {
    const el = document.createElement("div");
    el.style.cssText = "position:fixed;bottom:120px;left:50%;transform:translateX(-50%);z-index:4000;background:#1d2630;border:1px solid #2b3644;padding:10px 18px;border-radius:10px;font-size:0.9rem;box-shadow:0 4px 20px rgba(0,0,0,.5)";
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 2600);
  }

  /* ---------------- Inicialización ---------------- */
  function init() {
    state.map = L.map("map", { zoomControl: false, attributionControl: true }).setView([40.4168, -3.7038], 6);
    L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
      attribution: '&copy; OpenStreetMap &copy; CARTO',
      subdomains: "abcd",
      maxZoom: 19,
    }).addTo(state.map);
    L.control.zoom({ position: "bottomright" }).addTo(state.map);
    state.map.addLayer(state.markers);

    buildFuelChips();
    loadRouteFuelOptions();
    applyVehicleForm();
    initEvents();

    // Cargar vista por defecto
    if (navigator.geolocation) {
      useGPS(true);
    } else {
      searchAndCenter("");
    }
  }

  function buildFuelChips() {
    getJSON("/api/fuels?pais=" + state.pais).then((fuels) => {
      const wrap = $("fuel-chips");
      wrap.innerHTML = "";
      let active = state.fuel;
      if (!fuels.some((f) => f.id === active)) {
        active = fuels[0] ? fuels[0].id : FUEL_DEFAULT;
        state.fuel = active;
      }
      fuels.forEach((f) => {
        const b = document.createElement("button");
        b.className = "chip" + (f.id === active ? " active" : "");
        b.textContent = f.label;
        b.dataset.fuel = f.id;
        b.onclick = () => {
          wrap.querySelectorAll(".chip").forEach((c) => c.classList.remove("active"));
          b.classList.add("active");
          state.fuel = f.id;
          refreshStations();
        };
        wrap.appendChild(b);
      });
    });
  }

  function loadRouteFuelOptions() {
    getJSON("/api/fuels?pais=" + state.pais).then((fuels) => {
      const sel = $("route-fuel");
      sel.innerHTML = "";
      fuels.forEach((f) => {
        const o = document.createElement("option");
        o.value = f.id;
        o.textContent = f.label;
        if (f.id === "Precio Gasoleo A") o.selected = true;
        sel.appendChild(o);
      });
    });
  }

  function initEvents() {
    $("btn-gps").onclick = () => useGPS();
    $("search").addEventListener("input", onSearchInput);
    $("search").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); doSearch($("search").value); } });

    $("sort-seg").querySelectorAll("button").forEach((b) => {
      b.onclick = () => {
        $("sort-seg").querySelectorAll("button").forEach((x) => x.classList.remove("active"));
        b.classList.add("active");
        state.sort = b.dataset.sort;
        refreshStations();
      };
    });

    $("scope-seg").querySelectorAll("button").forEach((b) => {
      b.onclick = () => {
        $("scope-seg").querySelectorAll("button").forEach((x) => x.classList.remove("active"));
        b.classList.add("active");
        state.scope = b.dataset.scope;
        if (state.scope === "pais") {
          state.sort = "precio";
          $("sort-seg").querySelectorAll("button").forEach((x) => x.classList.toggle("active", x.dataset.sort === "precio"));
        }
        refreshStations();
      };
    });

    $("country-seg").querySelectorAll("button").forEach((b) => {
      b.onclick = () => {
        $("country-seg").querySelectorAll("button").forEach((x) => x.classList.remove("active"));
        b.classList.add("active");
        if (b.dataset.pais === state.pais) return;
        state.pais = b.dataset.pais;
        switchCountry();
      };
    });

    $("chk-open").onchange = (e) => { state.openOnly = e.target.checked; refreshStations(); };
    $("chk-favs").onchange = (e) => { state.favsOnly = e.target.checked; refreshStations(); };

    $("sel-radius").onchange = (e) => {
      state.radius = parseInt(e.target.value) || 60;
      save("radius", state.radius);
      refreshStations();
    };

    $("panel-toggle").onclick = toggleListPanel;
    $("list-header").onclick = toggleListPanel;

    $("bottom-nav").querySelectorAll("button").forEach((b) => {
      b.onclick = () => switchView(b.dataset.view);
    });

    $("sheet-close").onclick = closeDetail;
    $("btn-route").onclick = doRoute;
    $("btn-refresh").onclick = refreshData;
    $("btn-save-vehicle").onclick = saveVehicle;

    state.map.on("click", () => closeDetail());

    // Redimensionar lista
    new MutationObserver(refreshListMeta).observe($("list-meta"), { attributes: true });
  }

  /* ---------------- GPS / Búsqueda ---------------- */
  function useGPS(initial) {
    if (!navigator.geolocation) { toast("Geolocalización no disponible"); return; }
    showLoading();
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const { latitude, longitude } = pos.coords;
        state.current = { lat: latitude, lon: longitude, label: "Mi ubicación" };
        $("search").value = "Mi ubicación";
        centerAndLoad(state.current);
        hideLoading();
      },
      (err) => {
        hideLoading();
        toast("No se pudo obtener tu ubicación: " + err.message);
        if (initial) searchAndCenter("");
      },
      { enableHighAccuracy: true, timeout: 12000 }
    );
  }

  function onSearchInput() {
    const q = $("search").value.trim();
    if (q.length < 3) { $("search-suggestions").classList.add("hidden"); return; }
    const cc = state.pais === "italia" ? "it" : "es";
    const url = "https://nominatim.openstreetmap.org/search?format=json&limit=6&countrycodes=" + cc + "&q=" + encodeURIComponent(q);
    fetch(url, { headers: { "Accept": "application/json" } })
      .then((r) => r.json())
      .then((res) => {
        const box = $("search-suggestions");
        box.innerHTML = "";
        res.forEach((item) => {
          const d = document.createElement("div");
          d.className = "item";
          d.innerHTML = esc(item.display_name.split(",").slice(0, 3).join(", "));
          d.onclick = () => {
            state.current = { lat: parseFloat(item.lat), lon: parseFloat(item.lon), label: item.display_name };
            $("search").value = item.display_name.split(",")[0];
            box.classList.add("hidden");
            centerAndLoad(state.current);
          };
          box.appendChild(d);
        });
        box.classList.toggle("hidden", res.length === 0);
      })
      .catch(() => {});
  }

  function doSearch(q) {
    if (!q.trim()) return;
    $("search-suggestions").classList.add("hidden");
    showLoading();
    getJSON("/api/geocode?q=" + encodeURIComponent(q) + "&pais=" + state.pais).then((data) => {
      state.current = data;
      $("search").value = data.label.split(",")[0];
      centerAndLoad(state.current);
    }).catch((e) => { hideLoading(); toast(e.message); }).finally(hideLoading);
  }

  function searchAndCenter(q) {
    if (q) doSearch(q);
    else {
      state.current = { lat: 40.4168, lon: -3.7038, label: "España" };
      centerAndLoad(state.current);
    }
  }

  function switchCountry() {
    const cap = CAPITALS[state.pais];
    state.current = cap;
    $("search").value = cap.label;
    state.scope = "cerca";
    $("scope-seg").querySelectorAll("button").forEach((x) => x.classList.toggle("active", x.dataset.scope === "cerca"));
    buildFuelChips();
    loadRouteFuelOptions();
    centerAndLoad(state.current);
  }

  function centerAndLoad(pt) {
    state.map.setView([pt.lat, pt.lon], 12);
    refreshStations();
  }

  /* ---------------- Estaciones ---------------- */
  function updateRadiusUI() {
    $("radius-row").classList.toggle("hidden", state.scope !== "cerca");
  }

  async function refreshStations() {
    if (!state.current) return;
    showLoading();
    $("sel-radius").value = state.radius;
    updateRadiusUI();
    const params = new URLSearchParams({
      fuel: state.fuel, sort: state.sort, top: 50,
      open: state.openOnly ? "1" : "0",
      scope: state.scope, pais: state.pais,
    });
    if (state.scope === "cerca") {
      params.set("lat", state.current.lat);
      params.set("lon", state.current.lon);
      params.set("radius", state.radius);
    }
    try {
      const data = await getJSON("/api/stations?" + params.toString());
      let stations = data.stations;
      if (state.favsOnly) stations = stations.filter((s) => state.favorites.includes(s.ideess));
      state.stations = stations;
      $("list-meta").textContent = state.scope === "pais"
        ? data.fecha
        : data.fecha + " · radio " + state.radius + " km";
      $("list-title").textContent = state.scope === "pais"
        ? (state.pais === "italia" ? "🇮🇹 Más baratas de Italia" : "🇪🇸 Más baratas de España")
        : "Gasolineras";
      renderList();
      renderMarkers();
      if (state.radiusCircle) state.map.removeLayer(state.radiusCircle);
      state.radiusCircle = null;
      if (state.scope === "cerca" && state.current) {
        state.radiusCircle = L.circle([state.current.lat, state.current.lon], {
          radius: state.radius * 1000, color: "#3b82f6", weight: 1.5, opacity: 0.45,
          dashArray: "6 6", fillOpacity: 0.06,
        }).addTo(state.map);
      }
      if (state.scope === "pais" && stations.length) {
        const bounds = L.latLngBounds(stations.map((s) => [s.lat, s.lon]));
        state.map.fitBounds(bounds, { padding: [40, 40] });
      }
    } catch (e) {
      toast(e.message);
    } finally {
      hideLoading();
    }
  }

  function renderList() {
    const list = $("station-list");
    list.innerHTML = "";
    $("list-empty").style.display = state.stations.length ? "none" : "block";
    state.stations.forEach((s, i) => {
      const row = document.createElement("div");
      row.className = "station-row";
      const distHtml = state.scope === "pais"
        ? `<div class="dist">${esc(s.provincia)}</div>`
        : `<div class="dist">${fmtDist(s.dist)}</div>`;
      row.innerHTML =
        `<div class="rank">${i + 1}</div>` +
        `<div class="info"><div class="rotulo">${esc(s.rotulo)}</div>` +
        `<div class="dir">${esc(s.direccion)}, ${esc(s.municipio)}</div></div>` +
        distHtml +
        `<div class="price">${fmtPrecio(s.precio)}</div>` +
        `<div class="tend ${tendCls(s.tend)}">${tendArrow(s.tend)}</div>`;
      row.onclick = () => openDetail(s.ideess, s);
      list.appendChild(row);
    });
  }

  function markerColor(precio, min, max) {
    // Verde (barato) -> amarillo -> rojo (caro)
    const t = max > min ? (precio - min) / (max - min) : 0.5;
    const r = Math.round(34 + t * 205);
    const g = Math.round(197 - t * 142);
    const b = 94;
    return `rgb(${r},${g},${b})`;
  }

  function renderMarkers() {
    state.markers.clearLayers();
    if (!state.stations.length) return;
    const precios = state.stations.map((s) => s.precio);
    const min = Math.min(...precios), max = Math.max(...precios);

    state.stations.forEach((s) => {
      const color = markerColor(s.precio, min, max);
      const icon = L.divIcon({
        className: "",
        html: `<div style="background:${color};border:2px solid #fff;border-radius:50%;width:20px;height:20px;box-shadow:0 2px 6px rgba(0,0,0,.5)"></div>`,
        iconSize: [20, 20],
        iconAnchor: [10, 10],
      });
      const m = L.marker([s.lat, s.lon], { icon }).addTo(state.markers);
      m.bindPopup(`<b>${esc(s.rotulo)}</b><br>${fmtPrecio(s.precio)} · ${fmtDist(s.dist)}`, { closeButton: false });
      m.on("click", () => openDetail(s.ideess, s));
    });
  }

  function toggleListPanel() {
    $("list-panel").classList.toggle("minimized");
    $("panel-toggle").textContent = $("list-panel").classList.contains("minimized") ? "↑ Lista" : "↓ Mapa";
  }

  function refreshListMeta() {}

  /* ---------------- Detalle ---------------- */
  async function openDetail(ideess, s) {
    showLoading();
    try {
      const d = await getJSON("/api/station?ideess=" + encodeURIComponent(ideess));
      const isFav = state.favorites.includes(ideess);
      const body = $("detail-body");

      let prices = d.precios.map((p) =>
        `<div class="price-item"><span class="fuel">${esc(p.label)}</span>` +
        `<span class="val">${fmtPrecio(p.precio)}</span>` +
        (p.tend !== " " ? `<span class="tend ${tendCls(p.tend)}">${tendArrow(p.tend)}</span>` : "") +
        `</div>`).join("");

      body.innerHTML = `
        <div class="detail-title">${esc(d.rotulo)}</div>
        <div class="detail-addr">${esc(d.direccion)}, ${esc(d.municipio)} (${esc(d.provincia)})</div>
        <div>
          ${d.abierta === true ? '<span class="badge open">● Abierta ahora</span>' : d.abierta === false ? '<span class="badge closed">● Cerrada ahora</span>' : ""}
          ${d.es_24h ? '<span class="badge info">24h</span>' : ""}
          ${d.horario ? `<span class="badge info">${esc(d.horario)}</span>` : ""}
        </div>
        <div class="detail-actions">
          <button id="btn-fav" class="${isFav ? "fav active" : "fav"}">${isFav ? "★ Favorita" : "☆ Guardar"}</button>
          <button id="btn-directions">🧭 Cómo llegar</button>
          <button id="btn-share">↗ Compartir</button>
        </div>
        <div class="section-title">Precios</div>
        <div class="price-grid">${prices || '<div class="hist-empty">Sin precios</div>'}</div>
        <div class="section-title">Historial de precios</div>
        <div class="chart-wrap"><canvas id="hist-chart"></canvas></div>
        <div class="hist-empty" id="hist-msg"></div>
        <div class="section-title">Tu coste estimado</div>
        <div id="cost-estimate"></div>
      `;

      $("btn-fav").onclick = () => {
        const idx = state.favorites.indexOf(ideess);
        if (idx >= 0) state.favorites.splice(idx, 1);
        else state.favorites.push(ideess);
        save("favorites", state.favorites);
        $("btn-fav").classList.toggle("active");
        $("btn-fav").textContent = state.favorites.includes(ideess) ? "★ Favorita" : "☆ Guardar";
        toast(state.favorites.includes(ideess) ? "Añadida a favoritas" : "Eliminada de favoritas");
        refreshStations();
      };
      $("btn-directions").onclick = () => {
        if (!state.current) return;
        const url = `https://www.google.com/maps/dir/?api=1&origin=${state.current.lat},${state.current.lon}&destination=${d.lat},${d.lon}`;
        window.open(url, "_blank");
      };
      $("btn-share").onclick = () => {
        const url = `${location.origin}/#/estacion/${d.ideess}`;
        navigator.clipboard?.writeText(url);
        toast("Enlace copiado");
      };

      renderCostEstimate(d);
      loadHistory(ideess, state.fuel);

      $("detail-sheet").classList.remove("hidden");
    } catch (e) {
      toast(e.message);
    } finally {
      hideLoading();
    }
  }

  function renderCostEstimate(d) {
    const v = state.vehicle;
    const el = $("cost-estimate");
    if (!el) return;
    const sel = d.precios.find((x) => x.fuel === state.fuel) || d.precios[0];
    const precio = sel ? sel.precio : null;
    if (!precio) { el.innerHTML = '<p class="dim">Sin precio disponible.</p>'; return; }
    const costeDeposito = v.tank * precio;
    const costeRuta = v.cons && v.dist ? (v.dist / 100) * v.cons * precio : null;
    el.innerHTML =
      `<div class="price-item"><span class="fuel">Llenar depósito (${v.tank} L) · ${esc(sel.label)}</span><span class="val">${costeDeposito.toFixed(2).replace(".", ",")} €</span></div>` +
      (costeRuta ? `<div class="price-item"><span class="fuel">Coste aprox. ${v.dist} km</span><span class="val">${costeRuta.toFixed(2).replace(".", ",")} €</span></div>` : "");
  }

  async function loadHistory(ideess, fuel) {
    const msg = $("hist-msg");
    try {
      const data = await getJSON(`/api/history?ideess=${encodeURIComponent(ideess)}&fuel=${encodeURIComponent(fuel)}`);
      if (!data.data.length) { msg.textContent = "Sin historial registrado todavía."; return; }
      const labels = data.data.map((x) => x.fecha.split(" ")[0]);
      const values = data.data.map((x) => x.precio);
      if (state.historyChart) state.historyChart.destroy();
      state.historyChart = new Chart($("hist-chart"), {
        type: "line",
        data: { labels, datasets: [{ data: values, borderColor: "#3b82f6", backgroundColor: "rgba(59,130,246,.15)", fill: true, tension: 0.3, pointRadius: 0 }] },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: { ticks: { color: "#8a94a3", maxTicksLimit: 5 }, grid: { color: "#2b3644" } },
            y: { ticks: { color: "#8a94a3", callback: (v) => v.toFixed(3) }, grid: { color: "#2b3644" } },
          },
        },
      });
    } catch (e) {
      msg.textContent = "Error al cargar historial.";
    }
  }

  function closeDetail() {
    $("detail-sheet").classList.add("hidden");
  }

  /* ---------------- Vistas ---------------- */
  function switchView(view) {
    $("bottom-nav").querySelectorAll("button").forEach((b) =>
      b.classList.toggle("active", b.dataset.view === view));
    closeDetail();
    ["view-route", "view-favorites", "view-more"].forEach((v) => $(v).classList.add("hidden"));
    if (view === "route") $("view-route").classList.remove("hidden");
    if (view === "favorites") { $("view-favorites").classList.remove("hidden"); renderFavorites(); }
    if (view === "more") { $("view-more").classList.remove("hidden"); updateDataInfo(); }
    $("list-panel").classList.toggle("hidden", view !== "stations");
    $("filterbar").classList.toggle("hidden", view !== "stations");
    $("panel-toggle").classList.toggle("hidden", view !== "stations");
  }

  function renderFavorites() {
    const list = $("fav-list");
    list.innerHTML = "";
    $("fav-empty").style.display = state.favorites.length ? "none" : "block";
    if (!state.favorites.length) return;
    // Cargar detalles de cada favorita
    state.favorites.forEach(async (id) => {
      try {
        const d = await getJSON("/api/station?ideess=" + encodeURIComponent(id));
        const precio = d.precios.length ? d.precios[0].precio : null;
        const row = document.createElement("div");
        row.className = "fav-row";
        row.innerHTML =
          `<span class="star">⭐</span>` +
          `<div><div>${esc(d.rotulo)}</div><div class="dim">${esc(d.municipio)}</div></div>` +
          (precio ? `<span class="p">${fmtPrecio(precio)}</span>` : "");
        row.onclick = () => { switchView("stations"); openDetail(d.ideess, null); };
        list.appendChild(row);
      } catch (e) {}
    });
  }

  /* ---------------- Ruta ---------------- */
  async function doRoute() {
    const origen = $("route-origin").value.trim();
    const destino = $("route-dest").value.trim();
    if (!origen || !destino) { toast("Indica origen y destino"); return; }
    showLoading();
    try {
      const data = await getJSON(`/api/route?origen=${encodeURIComponent(origen)}&destino=${encodeURIComponent(destino)}&fuel=${encodeURIComponent($("route-fuel").value)}&radio=${$("route-radio").value}&pais=${state.pais}`);
      state.route = data;
      switchView("stations");
      drawRoute(data);
    } catch (e) {
      toast(e.message);
    } finally {
      hideLoading();
    }
  }

  function drawRoute(data) {
    state.markers.clearLayers();
    const coords = data.geometry.map((c) => [c[1], c[0]]);
    L.polyline(coords, { color: "#3b82f6", weight: 4, opacity: 0.8 }).addTo(state.markers);
    const bounds = L.latLngBounds(coords);
    data.stations.forEach((s) => {
      const icon = L.divIcon({
        className: "",
        html: `<div style="background:#22c55e;border:2px solid #fff;border-radius:50%;width:18px;height:18px;box-shadow:0 2px 6px rgba(0,0,0,.5)"></div>`,
        iconSize: [18, 18], iconAnchor: [9, 9],
      });
      const m = L.marker([s.lat, s.lon], { icon }).addTo(state.markers);
      m.bindPopup(`<b>${esc(s.rotulo)}</b><br>${fmtPrecio(s.precio)} · desvío ${s.desvio.toFixed(2)} km`);
    });
    state.map.fitBounds(bounds, { padding: [60, 60] });

    // Resultados
    const res = $("route-results");
    res.innerHTML = `<h3>Ruta: ${esc(data.origen.label)} → ${esc(data.destino.label)}</h3>` +
      `<p class="dim">${data.km} km · ${data.stations.length} estaciones</p>` +
      data.stations.map((s) =>
        `<div class="station-row" data-id="${s.ideess}">
           <div class="info"><div class="rotulo">${esc(s.rotulo)}</div>
           <div class="dir">${esc(s.direccion)}, ${esc(s.municipio)}</div></div>
           <div class="dist">${s.desvio.toFixed(1)} km</div>
           <div class="price">${fmtPrecio(s.precio)}</div>
         </div>`).join("");
    res.querySelectorAll(".station-row").forEach((row) => {
      row.onclick = () => openDetail(row.dataset.id, null);
    });
  }

  /* ---------------- Vehículo ---------------- */
  function applyVehicleForm() {
    $("cfg-tank").value = state.vehicle.tank;
    $("cfg-cons").value = state.vehicle.cons;
    $("cfg-dist").value = state.vehicle.dist;
  }

  function saveVehicle() {
    state.vehicle.tank = parseFloat($("cfg-tank").value) || 50;
    state.vehicle.cons = parseFloat($("cfg-cons").value) || 0;
    state.vehicle.dist = parseFloat($("cfg-dist").value) || 0;
    save("vehicle", state.vehicle);
    toast("Vehículo guardado");
  }

  /* ---------------- Datos ---------------- */
  async function refreshData() {
    showLoading();
    try {
      const d = await fetch("/api/refresh?pais=" + state.pais, { method: "POST" }).then((r) => r.json());
      if (d.ok) { toast(`Datos actualizados: ${d.estaciones} estaciones (${d.fecha})`); }
      else toast(d.error || "Error");
      updateDataInfo();
    } catch (e) {
      toast(e.message);
    } finally {
      hideLoading();
    }
  }

  async function updateDataInfo() {
    try {
      const data = await getJSON("/api/stations?lat=40.4168&lon=-3.7038&top=1&fuel=" + FUEL_DEFAULT + "&pais=" + state.pais);
      $("data-fecha").textContent = "Última actualización: " + data.fecha;
    } catch (e) {}
  }

  document.addEventListener("DOMContentLoaded", () => {
    init();
    handleHash();
  });
  window.addEventListener("hashchange", handleHash);
  function handleHash() {
    const m = location.hash.match(/#\/estacion\/([^\/]+)/);
    if (m) openDetail(m[1], null);
  }
})();
