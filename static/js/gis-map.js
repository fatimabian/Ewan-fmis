// GIS map: one layer at a time, three levels (heat map, points, record card), three colours.
(() => {
  const configNode = document.getElementById("gis-config");
  const mapNode = document.getElementById("gisMap");
  if (!configNode || !mapNode || typeof L === "undefined") return;
  const config = JSON.parse(configNode.textContent);
  const byId = (id) => document.getElementById(id);
  const layers = Object.fromEntries(config.layers.map((layer) => [layer.key, layer]));
  const els = {
    barangay: byId("gisBarangay"), commodity: byId("gisCommodity"), commodityWrap: byId("gisCommodityWrap"),
    status: byId("gisStatus"), reset: byId("gisReset"), shown: byId("gisShown"), unmapped: byId("gisUnmapped"),
    attention: byId("gisAttention"), empty: byId("gisEmpty"), loading: byId("gisLoading"), level: byId("gisLevel"),
    legend: byId("gisLegend"), legendBox: byId("gisLegendBox"), detail: byId("gisDetail"),
    detailTitle: byId("gisDetailTitle"), detailRows: byId("gisDetailRows"), detailLink: byId("gisDetailLink"),
    detailClose: byId("gisDetailClose"),
  };
  const STATUS_LABEL = {good: "green", attention: "gold", neutral: "navy"};
  const defaults = {layer: "parcels", barangay: "", commodity: "", status: ""};
  const params = new URLSearchParams(window.location.search);
  const state = {...defaults};
  Object.keys(defaults).forEach((key) => { if (params.has(key)) state[key] = params.get(key); });
  if (!layers[state.layer]) state.layer = defaults.layer;

  const map = L.map(mapNode, {scrollWheelZoom: false, zoomControl: true});
  L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    {maxNativeZoom: 18, maxZoom: 19, noWrap: true, attribution: "Satellite imagery &copy; Esri"}).addTo(map);
  const outline = L.polygon(config.boundary, {color: "#2f7d5c", weight: 3, fill: false, interactive: false}).addTo(map);
  map.fitBounds(outline.getBounds());
  const markers = L.layerGroup().addTo(map);
  // A small canvas heat layer (no external script is allowed): each point adds a soft blob,
  // and the accumulated opacity is turned into the green to gold ramp.
  const HEAT_STOPS = [[0, "rgba(47,125,92,0)"], [0.25, "rgba(47,125,92,0.75)"], [0.6, "rgba(216,166,43,0.9)"], [1, "rgba(255,244,204,1)"]];
  const heatPalette = (() => {
    const canvas = document.createElement("canvas");
    canvas.width = 1; canvas.height = 256;
    const ctx = canvas.getContext("2d");
    const gradient = ctx.createLinearGradient(0, 0, 0, 256);
    HEAT_STOPS.forEach(([stop, color]) => gradient.addColorStop(stop, color));
    ctx.fillStyle = gradient; ctx.fillRect(0, 0, 1, 256);
    return ctx.getImageData(0, 0, 1, 256).data;
  })();
  const HeatLayer = L.Layer.extend({
    initialize(points) { this._points = points; },
    onAdd(leafletMap) {
      this._map = leafletMap;
      this._canvas = L.DomUtil.create("canvas", "gis-heat");
      leafletMap.getPane("heatPane").appendChild(this._canvas);
      leafletMap.on("moveend zoomend resize", this._redraw, this);
      this._redraw();
    },
    onRemove(leafletMap) {
      leafletMap.off("moveend zoomend resize", this._redraw, this);
      this._canvas.remove();
    },
    _redraw() {
      const size = this._map.getSize();
      const canvas = this._canvas;
      L.DomUtil.setPosition(canvas, this._map.containerPointToLayerPoint([0, 0]));
      canvas.width = size.x; canvas.height = size.y;
      const ctx = canvas.getContext("2d");
      const radius = Math.max(14, Math.min(46, (this._map.getZoom() - 7) * 5));
      const brush = document.createElement("canvas");
      brush.width = brush.height = radius * 2;
      const bctx = brush.getContext("2d");
      const blob = bctx.createRadialGradient(radius, radius, 0, radius, radius, radius);
      blob.addColorStop(0, "rgba(0,0,0,1)"); blob.addColorStop(1, "rgba(0,0,0,0)");
      bctx.fillStyle = blob; bctx.fillRect(0, 0, radius * 2, radius * 2);
      // Fewer points need a stronger blob; many points are softened so the map does not saturate.
      ctx.globalAlpha = Math.max(0.04, Math.min(0.35, 60 / Math.max(this._points.length, 1)));
      this._points.forEach(([lat, lng]) => {
        const p = this._map.latLngToContainerPoint([lat, lng]);
        if (p.x < -radius || p.y < -radius || p.x > size.x + radius || p.y > size.y + radius) return;
        ctx.drawImage(brush, p.x - radius, p.y - radius);
      });
      const image = ctx.getImageData(0, 0, size.x, size.y);
      const pixels = image.data;
      // Colours are relative to the busiest spot in view, so the ramp always has contrast.
      let peak = 1;
      for (let i = 3; i < pixels.length; i += 4) if (pixels[i] > peak) peak = pixels[i];
      const scale = 235 / peak;
      for (let i = 3; i < pixels.length; i += 4) {
        const alpha = pixels[i];
        if (!alpha) continue;
        const k = Math.min(255, Math.round(alpha * scale)) * 4;
        pixels[i - 3] = heatPalette[k]; pixels[i - 2] = heatPalette[k + 1];
        pixels[i - 1] = heatPalette[k + 2]; pixels[i] = heatPalette[k + 3];
      }
      ctx.globalAlpha = 1;
      ctx.putImageData(image, 0, 0);
    },
  });
  map.createPane("heatPane").style.zIndex = 350;
  let heatLayer = null;

  let barangayShape = null;
  let selected = null;
  let request = null;

  config.barangays.forEach((name) => els.barangay.add(new Option(name, name)));
  config.commodities.forEach((name) => els.commodity.add(new Option(name, name)));

  // Each layer has its own icon inside a map pin; the pin colour is the status.
  // The pin is SVG because the system's global shape rule squares every CSS box.
  const PIN_PATH = "M12 1C6 1 1.5 5.600 1.500 11.400c0 7.400 10.500 18.600 10.500 18.600s10.500-11.200 10.500-18.600C22.500 5.600 18 1 12 1z";
  const pinHtml = (icon, status, width = 30) =>
    `<span class="gis-marker gis-${status}" style="--w:${width}px"><svg viewBox="0 0 24 32" aria-hidden="true" focusable="false"><path d="${PIN_PATH}"/></svg><i class="bi ${icon}" aria-hidden="true"></i></span>`;

  function syncControls() {
    const layer = layers[state.layer];
    document.querySelectorAll(".gis-layer-btn").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.layer === state.layer));
    });
    els.commodityWrap.hidden = !layer.uses_commodity;
    els.status.replaceChildren(...layer.status_options.map(([value, label]) => new Option(label, value)));
    if (!layer.status_options.some(([value]) => value === state.status)) state.status = layer.status_options[0][0];
    els.status.value = state.status;
    els.barangay.value = state.barangay;
    els.commodity.value = state.commodity;
    els.legend.replaceChildren(...layer.legend.map(([status, label]) => {
      const item = document.createElement("li");
      const swatch = document.createElement("span");
      swatch.className = "gis-swatch";
      swatch.innerHTML = pinHtml(layer.icon, status, 22);
      item.append(swatch, label);
      return item;
    }));
    const query = new URLSearchParams();
    Object.entries(state).forEach(([key, value]) => { if (value && value !== defaults[key]) query.set(key, value); });
    history.replaceState(null, "", query.toString() ? `?${query}` : window.location.pathname);
  }

  function showLevel(level) {
    els.level.textContent = [
      "",
      "Level 1 of 3: where records are. Pick a busy barangay to see each record.",
      "Level 2 of 3: each record. Select one for its details.",
    ][level] || "";
  }

  function selectBarangay(name) {
    state.barangay = name;
    closeDetail();
    load();
  }

  function renderHeat(data) {
    if (heatLayer) { map.removeLayer(heatLayer); heatLayer = null; }
    heatLayer = new HeatLayer(data.heat).addTo(map);
    // Invisible targets give each barangay a hover total and a way in; keyboard users use the list.
    data.bubbles.forEach((bubble) => {
      const target = L.circleMarker([bubble.lat, bubble.lng], {radius: 16, stroke: false, fillOpacity: 0, interactive: true});
      const note = bubble.attention ? `, ${bubble.attention} need attention` : "";
      target.bindTooltip(`${bubble.barangay}: ${bubble.count}${note}`);
      target.on("click", () => selectBarangay(bubble.barangay));
      markers.addLayer(target);
    });
    const topList = document.getElementById("gisTop");
    topList.replaceChildren(...data.top.map((item) => {
      const row = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "gis-top-btn";
      const name = document.createElement("span"); name.textContent = item.barangay;
      const count = document.createElement("strong"); count.textContent = item.count.toLocaleString();
      button.append(name, count);
      button.addEventListener("click", () => selectBarangay(item.barangay));
      row.append(button);
      return row;
    }));
    map.invalidateSize();
    if (data.bubbles.length) map.fitBounds(L.latLngBounds(data.bubbles.map((b) => [b.lat, b.lng])).pad(0.25));
    else map.fitBounds(outline.getBounds());
  }

  function renderPoints(points, geometry) {
    const layer = layers[state.layer];
    points.forEach((point) => {
      const marker = L.marker([point.lat, point.lng], {
        title: layer.label,
        icon: L.divIcon({className: "", iconSize: [30, 40], iconAnchor: [15, 38], html: pinHtml(layer.icon, point.status)}),
      });
      marker.on("click", () => openDetail(point.id, marker));
      markers.addLayer(marker);
    });
    if (barangayShape) { map.removeLayer(barangayShape); barangayShape = null; }
    if (geometry) {
      barangayShape = L.geoJSON(geometry, {style: {color: "#111c2b", weight: 2, fill: false}, interactive: false}).addTo(map);
    }
    const bounds = points.length ? L.latLngBounds(points.map((p) => [p.lat, p.lng])).pad(0.3)
      : barangayShape ? barangayShape.getBounds() : null;
    map.invalidateSize();
    if (bounds) map.fitBounds(bounds, {maxZoom: 17});
    else if (config.centers[state.barangay]) map.setView(config.centers[state.barangay], 15);
  }

  function setSummary(data) {
    els.shown.textContent = data.mapped.toLocaleString();
    els.unmapped.textContent = data.unmapped.toLocaleString();
    els.attention.textContent = data.attention.toLocaleString();
  }

  async function load() {
    syncControls();
    if (request) request.abort();
    request = new AbortController();
    els.loading.hidden = false;
    els.empty.hidden = true;
    const query = new URLSearchParams({layer: state.layer, barangay: state.barangay, commodity: state.commodity, status: state.status});
    try {
      const response = await fetch(`${config.dataUrl}?${query}`, {signal: request.signal, headers: {Accept: "application/json"}});
      if (!response.ok) throw new Error("bad response");
      const data = await response.json();
      markers.clearLayers();
      if (heatLayer) { map.removeLayer(heatLayer); heatLayer = null; }
      if (barangayShape && !state.barangay) { map.removeLayer(barangayShape); barangayShape = null; }
      setSummary(data);
      showLevel(data.level);
      const overview = data.level === 1;
      byId("gisHeatKey").hidden = !overview;
      els.legend.hidden = overview;
      byId("gisTopBox").hidden = !overview || !data.top.length;
      if (overview) renderHeat(data); else renderPoints(data.points, data.barangay_geometry);
      const none = data.mapped === 0;
      els.empty.hidden = !none;
      if (none) els.empty.textContent = data.total
        ? `${data.total} record${data.total === 1 ? "" : "s"} match, but none has a map location yet.`
        : "Nothing matches these filters.";
      els.loading.hidden = true;
    } catch (error) {
      if (error.name === "AbortError") return;
      els.loading.hidden = true;
      els.empty.hidden = false;
      els.empty.textContent = "The map data could not be loaded. Try again.";
    }
  }

  async function openDetail(id, marker) {
    try {
      const response = await fetch(`${config.detailUrl}?${new URLSearchParams({layer: state.layer, id})}`);
      if (!response.ok) throw new Error("missing");
      const card = await response.json();
      els.detailTitle.textContent = card.title;
      els.detailRows.replaceChildren(...card.rows.flatMap(([label, value]) => {
        const term = document.createElement("dt"); term.textContent = label;
        const description = document.createElement("dd"); description.textContent = value;
        return [term, description];
      }));
      els.detailLink.href = card.url;
      els.detail.hidden = false;
      els.legendBox.hidden = true;
      showLevel(3);
      els.level.textContent = "Level 3 of 3: record details.";
      if (selected) selected.getElement()?.classList.remove("is-selected");
      selected = marker;
      marker.getElement()?.classList.add("is-selected");
    } catch (error) {
      els.level.textContent = "That record could not be opened. It may have been changed.";
    }
  }

  function closeDetail() {
    els.detail.hidden = true;
    els.legendBox.hidden = false;
    if (selected) selected.getElement()?.classList.remove("is-selected");
    selected = null;
  }

  document.querySelectorAll(".gis-layer-btn").forEach((button) => {
    button.addEventListener("click", () => {
      if (state.layer === button.dataset.layer) return;
      state.layer = button.dataset.layer;
      state.status = "";
      closeDetail();
      load();
    });
  });
  [["barangay", els.barangay], ["commodity", els.commodity], ["status", els.status]].forEach(([key, select]) => {
    select.addEventListener("change", () => { state[key] = select.value; closeDetail(); load(); });
  });
  els.reset.addEventListener("click", () => { Object.assign(state, defaults); closeDetail(); load(); });
  els.detailClose.addEventListener("click", () => { closeDetail(); showLevel(state.barangay ? 2 : 1); });
  window.addEventListener("load", () => map.invalidateSize());
  setTimeout(() => map.invalidateSize(), 300);
  load();
})();
