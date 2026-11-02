// GIS map: one layer at a time, three levels (density grid, clustered pins, record card), three colours.
(() => {
  const configNode = document.getElementById("gis-config");
  const mapNode = document.getElementById("gisMap");
  if (!configNode || !mapNode || typeof L === "undefined") return;
  const config = JSON.parse(configNode.textContent);
  const byId = (id) => document.getElementById(id);
  const layers = Object.fromEntries(config.layers.map((layer) => [layer.key, layer]));
  const els = {
    barangay: byId("gisBarangay"), commodity: byId("gisCommodity"), commodityWrap: byId("gisCommodityWrap"),
    status: byId("gisStatus"), reset: byId("gisReset"), more: byId("gisMore"), morePanel: byId("gisMorePanel"),
    moreGrid: byId("gisMoreGrid"), moreCount: byId("gisMoreCount"), shown: byId("gisShown"),
    unmapped: byId("gisUnmapped"), attention: byId("gisAttention"), empty: byId("gisEmpty"),
    loading: byId("gisLoading"), level: byId("gisLevel"), legend: byId("gisLegend"), legendTitle: byId("gisLegendTitle"),
    legendBox: byId("gisLegendBox"), detail: byId("gisDetail"), detailTitle: byId("gisDetailTitle"),
    detailRows: byId("gisDetailRows"), detailLink: byId("gisDetailLink"), detailClose: byId("gisDetailClose"),
    insights: byId("gisInsights"), tabs: byId("gisTabs"), top: byId("gisTop"),
  };

  // State: the layer, the three main filters, and the extra filters of the current layer.
  const defaults = {layer: "parcels", barangay: "", commodity: "", status: ""};
  const params = new URLSearchParams(window.location.search);
  const state = {...defaults, extra: {}};
  Object.keys(defaults).forEach((key) => { if (params.has(key)) state[key] = params.get(key); });
  if (!layers[state.layer]) state.layer = defaults.layer;
  layers[state.layer].filters.forEach((key) => { if (params.get(key)) state.extra[key] = params.get(key); });
  let insightTab = "busiest";
  let lastData = null;

  const map = L.map(mapNode, {scrollWheelZoom: false, zoomControl: true});
  L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    {maxNativeZoom: 18, maxZoom: 19, noWrap: true, attribution: "Satellite imagery &copy; Esri"}).addTo(map);
  const outline = L.polygon(config.boundary, {color: "#2f7d5c", weight: 3, fill: false, interactive: false}).addTo(map);
  map.fitBounds(outline.getBounds());

  // Pins are SVG because the system's global shape rule squares every CSS box.
  const PIN_PATH = "M12 1C6 1 1.5 5.6 1.5 11.4c0 7.4 10.5 18.6 10.5 18.6s10.5-11.2 10.5-18.6C22.5 5.6 18 1 12 1z";
  const pinHtml = (icon, status, width = 30) =>
    `<span class="gis-marker gis-${status}" style="--w:${width}px"><svg viewBox="0 0 24 32" aria-hidden="true" focusable="false"><path d="${PIN_PATH}"/></svg><i class="bi ${icon}" aria-hidden="true"></i></span>`;
  const clusterIcon = (cluster) => {
    const count = cluster.getChildCount();
    const size = count > 50 ? 46 : count > 10 ? 38 : 32;
    return L.divIcon({className: "", iconSize: [size, size],
      html: `<svg class="gis-svg gis-neutral" width="${size}" height="${size}" viewBox="0 0 48 48" aria-hidden="true"><circle cx="24" cy="24" r="21"/><text x="24" y="30" text-anchor="middle">${count}</text></svg>`});
  };
  const pins = L.markerClusterGroup({showCoverageOnHover: false, maxClusterRadius: 60, spiderfyOnMaxZoom: true, iconCreateFunction: clusterIcon});
  const cells = L.layerGroup();
  map.addLayer(pins); map.addLayer(cells);
  let barangayShape = null;
  let selected = null;
  let request = null;

  config.barangays.forEach((name) => els.barangay.add(new Option(name, name)));
  config.commodities.forEach((name) => els.commodity.add(new Option(name, name)));

  const TIER_STYLE = {
    1: {fillColor: "#2f7d5c"}, 2: {fillColor: "#d8a62b"}, 3: {fillColor: "#ffffff"},
  };

  function renderMoreFilters() {
    const layer = layers[state.layer];
    els.moreGrid.replaceChildren(...layer.filters.map((key) => {
      const spec = config.filterSpecs[key];
      const label = document.createElement("label");
      label.textContent = spec.label;
      let input;
      if (spec.kind === "select") {
        input = document.createElement("select");
        input.add(new Option("Any", ""));
        spec.options.forEach(([value, text]) => input.add(new Option(text, value)));
      } else {
        input = document.createElement("input");
        input.type = spec.kind === "date" ? "date" : "number";
        if (spec.kind === "number") { input.min = "0"; input.step = key.startsWith("farmer") ? "1" : "0.01"; input.inputMode = "decimal"; }
        if (spec.hint) input.placeholder = spec.hint;
      }
      input.value = state.extra[key] || "";
      input.addEventListener("change", () => {
        if (input.value) state.extra[key] = input.value; else delete state.extra[key];
        closeDetail(); load();
      });
      label.append(input);
      return label;
    }));
    const active = Object.keys(state.extra).length;
    els.moreCount.hidden = !active;
    els.moreCount.textContent = active;
  }

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
    renderMoreFilters();
    const query = new URLSearchParams();
    Object.entries({...state, ...state.extra}).forEach(([key, value]) => {
      if (key !== "extra" && value && value !== defaults[key]) query.set(key, value);
    });
    history.replaceState(null, "", query.toString() ? `?${query}` : window.location.pathname);
  }

  function renderLegend(data) {
    const layer = layers[state.layer];
    els.legend.replaceChildren();
    if (data.level === 1) {
      els.legendTitle.textContent = "Records per square (about 1 km)";
      data.tiers.forEach((tier) => {
        const item = document.createElement("li");
        const swatch = document.createElement("span");
        swatch.className = `gis-tier gis-tier-${tier.tier}`;
        item.append(swatch, `${tier.label} record${tier.label === "1" ? "" : "s"}`);
        els.legend.append(item);
      });
      return;
    }
    els.legendTitle.textContent = "Legend";
    layer.legend.forEach(([status, label]) => {
      const item = document.createElement("li");
      const swatch = document.createElement("span");
      swatch.className = "gis-swatch";
      swatch.innerHTML = pinHtml(layer.icon, status, 22);
      item.append(swatch, label);
      els.legend.append(item);
    });
  }

  function showLevel(level) {
    els.level.textContent = [
      "",
      "Level 1 of 3: where records are. Select a square, or pick from the insights.",
      "Level 2 of 3: each record. Select one for its details.",
      "Level 3 of 3: record details.",
    ][level] || "";
  }

  function selectBarangay(name) {
    state.barangay = name;
    closeDetail();
    load();
  }

  function renderInsights(data) {
    const insights = data.insights;
    const tabs = [];
    if (data.level === 1) {
      tabs.push(["busiest", "Busiest"]);
      if (insights.attention.length) tabs.push(["attention", "Needs attention"]);
    }
    if (insights.facet.items.length) tabs.push(["facet", insights.facet.title]);
    els.insights.hidden = !tabs.length;
    if (!tabs.some(([key]) => key === insightTab)) insightTab = tabs.length ? tabs[0][0] : "busiest";
    els.tabs.replaceChildren(...tabs.map(([key, label]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "gis-tab";
      button.setAttribute("role", "tab");
      button.setAttribute("aria-selected", String(key === insightTab));
      button.textContent = label;
      button.addEventListener("click", () => { insightTab = key; renderInsights(data); });
      return button;
    }));
    const rows = insightTab === "facet"
      ? insights.facet.items.map((item) => ({label: item.label, count: item.count, action: () => applyFacet(insights.facet.filter, item.value)}))
      : insights[insightTab].map((item) => ({label: item.barangay, count: item.count, action: () => selectBarangay(item.barangay)}));
    els.top.replaceChildren(...rows.map((row) => {
      const li = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "gis-top-btn";
      const name = document.createElement("span"); name.textContent = row.label;
      const count = document.createElement("strong"); count.textContent = row.count.toLocaleString();
      button.append(name, count);
      button.addEventListener("click", row.action);
      li.append(button);
      return li;
    }));
  }

  // A click on a breakdown row sets (or clears) the matching filter.
  function applyFacet(filter, value) {
    if (filter === "commodity") state.commodity = state.commodity === value ? "" : value;
    else if (state.extra[filter] === value) delete state.extra[filter];
    else state.extra[filter] = value;
    closeDetail();
    load();
  }

  function renderCells(data) {
    data.cells.forEach((cell) => {
      const bounds = [[cell.lat, cell.lng], [cell.lat + data.size, cell.lng + data.size]];
      const rect = L.rectangle(bounds, {
        ...TIER_STYLE[cell.tier], color: cell.tier === 3 ? "#111c2b" : "#ffffff", weight: 1.5, opacity: 0.9, fillOpacity: 0.85,
      });
      const note = cell.attention ? `, ${cell.attention} need attention` : "";
      rect.bindTooltip(`${cell.count} record${cell.count === 1 ? "" : "s"}${note}. Mostly ${cell.barangay}`);
      rect.on("click", () => selectBarangay(cell.barangay));
      cells.addLayer(rect);
    });
    map.invalidateSize();
    if (data.cells.length) {
      const lats = data.cells.map((c) => c.lat), lngs = data.cells.map((c) => c.lng);
      map.fitBounds([[Math.min(...lats), Math.min(...lngs)], [Math.max(...lats) + data.size, Math.max(...lngs) + data.size]], {padding: [20, 20]});
    } else map.fitBounds(outline.getBounds());
  }

  function renderPoints(points, geometry) {
    const layer = layers[state.layer];
    points.forEach((point) => {
      const marker = L.marker([point.lat, point.lng], {
        title: layer.label,
        icon: L.divIcon({className: "", iconSize: [30, 40], iconAnchor: [15, 38], html: pinHtml(layer.icon, point.status)}),
      });
      marker.on("click", () => openDetail(point.id, marker));
      pins.addLayer(marker);
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
    const query = new URLSearchParams({layer: state.layer, barangay: state.barangay, commodity: state.commodity, status: state.status, ...state.extra});
    try {
      const response = await fetch(`${config.dataUrl}?${query}`, {signal: request.signal, headers: {Accept: "application/json"}});
      const data = await response.json();
      if (!response.ok) { throw new Error(data.message || "bad response"); }
      lastData = data;
      pins.clearLayers(); cells.clearLayers();
      if (barangayShape && !state.barangay) { map.removeLayer(barangayShape); barangayShape = null; }
      setSummary(data);
      showLevel(data.level);
      renderLegend(data);
      renderInsights(data);
      if (data.level === 1) renderCells(data); else renderPoints(data.points, data.barangay_geometry);
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
      els.empty.textContent = error.message && error.message !== "bad response" ? error.message : "The map data could not be loaded. Try again.";
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
      els.insights.hidden = true;
      showLevel(3);
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
    if (lastData) els.insights.hidden = !els.top.children.length;
    if (selected) selected.getElement()?.classList.remove("is-selected");
    selected = null;
  }

  document.querySelectorAll(".gis-layer-btn").forEach((button) => {
    button.addEventListener("click", () => {
      if (state.layer === button.dataset.layer) return;
      state.layer = button.dataset.layer;
      state.status = "";
      // Keep only the extra filters the new layer understands (the farmer range is shared).
      const allowed = new Set(layers[state.layer].filters);
      Object.keys(state.extra).forEach((key) => { if (!allowed.has(key)) delete state.extra[key]; });
      insightTab = "busiest";
      closeDetail();
      load();
    });
  });
  [["barangay", els.barangay], ["commodity", els.commodity], ["status", els.status]].forEach(([key, select]) => {
    select.addEventListener("change", () => { state[key] = select.value; closeDetail(); load(); });
  });
  els.more.addEventListener("click", () => {
    const open = els.morePanel.hidden;
    els.morePanel.hidden = !open;
    els.more.setAttribute("aria-expanded", String(open));
  });
  els.reset.addEventListener("click", () => { Object.assign(state, defaults, {extra: {}}); closeDetail(); load(); });
  els.detailClose.addEventListener("click", () => { closeDetail(); showLevel(state.barangay ? 2 : 1); });
  if (Object.keys(state.extra).length) { els.morePanel.hidden = false; els.more.setAttribute("aria-expanded", "true"); }
  window.addEventListener("load", () => map.invalidateSize());
  setTimeout(() => map.invalidateSize(), 300);
  load();
})();
