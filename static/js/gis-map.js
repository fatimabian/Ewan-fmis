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
    status: byId("gisStatus"), reset: byId("gisReset"), apply: byId("gisApply"),
    filterToggle: byId("gisFilterToggle"), filterLabel: byId("gisFilterLabel"), filterCount: byId("gisFilterCount"),
    filterTitle: byId("gisFiltersTitle"), filterPanel: byId("gisFilters"), moreGrid: byId("gisMoreGrid"), shown: byId("gisShown"),
    unmapped: byId("gisUnmapped"), attention: byId("gisAttention"), empty: byId("gisEmpty"),
    loading: byId("gisLoading"), level: byId("gisLevel"), legend: byId("gisLegend"), legendTitle: byId("gisLegendTitle"),
    legendBox: byId("gisLegendBox"), detail: byId("gisDetail"), detailTitle: byId("gisDetailTitle"),
    detailRows: byId("gisDetailRows"), detailLink: byId("gisDetailLink"), detailClose: byId("gisDetailClose"),
    detailPhotoWrap: byId("gisDetailPhotoWrap"), detailPhoto: byId("gisDetailPhoto"),
    detailPhotoEmpty: byId("gisDetailPhotoEmpty"), detailKicker: byId("gisDetailKicker"),
    insights: byId("gisInsights"), tabs: byId("gisTabs"), top: byId("gisTop"), chips: byId("gisChips"),
    parcelDirectory: byId("gisParcelDirectory"), parcelDirectoryTitle: byId("gisParcelDirectoryTitle"),
    parcelDirectoryScope: byId("gisParcelDirectoryScope"), parcelSearch: byId("gisParcelSearch"),
    parcelPinStatus: byId("gisParcelPinStatus"), parcelList: byId("gisParcelList"),
    parcelPrevious: byId("gisParcelPrevious"), parcelNext: byId("gisParcelNext"),
    parcelPageStatus: byId("gisParcelPageStatus"),
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
  let parcelListRequest = null;
  let parcelPage = 1;
  let parcelSearchTimer = null;
  const markerByRecord = new Map();

  config.barangays.forEach((name) => els.barangay.add(new Option(name, name)));
  config.commodities.forEach((name) => els.commodity.add(new Option(name, name)));

  const TIER_STATUS = {1: "good", 2: "attention", 3: "neutral"};

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
        updateFilterButton();
      });
      label.className = "fmis-filter-field";
      label.append(input);
      return label;
    }));
  }

  function activeFilterCount() {
    const layer = layers[state.layer];
    const defaultStatus = layer.status_options[0]?.[0] || "";
    return Number(Boolean(state.barangay)) + Number(Boolean(state.commodity && layer.uses_commodity))
      + Number(Boolean(state.status && state.status !== defaultStatus)) + Object.keys(state.extra).length;
  }

  function updateFilterButton() {
    const count = activeFilterCount();
    const name = layers[state.layer].short_label;
    els.filterLabel.textContent = `Filter ${name}`;
    els.filterTitle.textContent = `Filter ${name}`;
    els.filterToggle.classList.toggle("has-active-filters", count > 0);
    els.filterCount.hidden = !count;
    els.filterCount.textContent = count ? String(count) : "";
  }

  function closeFilters() {
    els.filterPanel.hidden = true;
    els.filterToggle.setAttribute("aria-expanded", "false");
    els.filterToggle.focus();
  }

  // One removable chip per applied filter; ranges are shown as a single chip.
  function appliedFilters() {
    const layer = layers[state.layer];
    const specs = config.filterSpecs;
    const text = (key, value) => {
      const options = specs[key].options || [];
      return (options.find(([v]) => v === value) || [value, value])[1];
    };
    const list = [];
    if (state.barangay) list.push({text: `Barangay: ${state.barangay}`, clear: () => { state.barangay = ""; }});
    if (state.commodity && layer.uses_commodity) list.push({text: `Commodity: ${state.commodity}`, clear: () => { state.commodity = ""; }});
    const statusLabel = (layer.status_options.find(([v]) => v === state.status) || [])[1];
    if (state.status && state.status !== layer.status_options[0][0]) list.push({text: statusLabel, clear: () => { state.status = ""; }});
    const done = new Set();
    const range = (low, high, name) => {
      if (!(low in state.extra) && !(high in state.extra)) return;
      done.add(low); done.add(high);
      const from = state.extra[low], to = state.extra[high];
      const label = from && to ? `${name} ${from} to ${to}` : from ? `${name} from ${from}` : `${name} up to ${to}`;
      list.push({text: label, clear: () => { delete state.extra[low]; delete state.extra[high]; }});
    };
    range("farmer_from", "farmer_to", "Farmer no.");
    range("area_min", "area_max", "Area (ha)");
    range("date_from", "date_to", "Date");
    Object.keys(state.extra).filter((key) => !done.has(key)).forEach((key) => {
      list.push({text: `${specs[key].label}: ${text(key, state.extra[key])}`, clear: () => { delete state.extra[key]; }});
    });
    return list;
  }

  function renderChips() {
    const applied = appliedFilters();
    els.chips.hidden = !applied.length;
    els.chips.replaceChildren(...applied.map((item) => {
      const chip = document.createElement("span");
      chip.className = "gis-chip";
      chip.append(item.text);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.setAttribute("aria-label", `Remove filter ${item.text}`);
      remove.textContent = "×";
      remove.addEventListener("click", () => { item.clear(); closeDetail(); load(); });
      chip.append(remove);
      return chip;
    }));
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
    updateFilterButton();
    renderChips();
    const query = new URLSearchParams();
    Object.entries({...state, ...state.extra}).forEach(([key, value]) => {
      if (key === "commodity" && !layer.uses_commodity) return;
      if (key !== "extra" && value && value !== defaults[key]) query.set(key, value);
    });
    history.replaceState(null, "", query.toString() ? `?${query}` : window.location.pathname);
  }

  function renderLegend(data) {
    const layer = layers[state.layer];
    els.legend.replaceChildren();
    if (data.level === 1) {
      els.legendTitle.textContent = "Records by map area (about 1 km)";
      data.tiers.forEach((tier) => {
        const item = document.createElement("li");
        const swatch = document.createElement("span");
        swatch.className = "gis-swatch";
        swatch.innerHTML = pinHtml(layer.icon, TIER_STATUS[tier.tier], 22);
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
      "Level 1 of 3: where records are. Select a density pin, or pick from the insights.",
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
    const layer = layers[state.layer];
    data.cells.forEach((cell) => {
      const center = [cell.lat + (data.size / 2), cell.lng + (data.size / 2)];
      const marker = L.marker(center, {
        title: `${cell.count} records near ${cell.barangay}`,
        icon: L.divIcon({
          className: "",
          iconSize: [32, 43],
          iconAnchor: [16, 41],
          html: pinHtml(layer.icon, TIER_STATUS[cell.tier], 32),
        }),
      });
      const note = cell.attention ? `, ${cell.attention} need attention` : "";
      marker.bindTooltip(`${cell.count} record${cell.count === 1 ? "" : "s"}${note}. Mostly ${cell.barangay}`);
      marker.on("click", () => selectBarangay(cell.barangay));
      cells.addLayer(marker);
    });
    map.invalidateSize();
    if (data.cells.length) {
      const centers = data.cells.map((cell) => [cell.lat + (data.size / 2), cell.lng + (data.size / 2)]);
      map.fitBounds(L.latLngBounds(centers).pad(0.2), {padding: [20, 20], maxZoom: 14});
    } else map.fitBounds(outline.getBounds());
  }

  function renderPoints(points, geometry) {
    const layer = layers[state.layer];
    markerByRecord.clear();
    points.forEach((point) => {
      const marker = L.marker([point.lat, point.lng], {
        title: layer.label,
        icon: L.divIcon({className: "", iconSize: [30, 40], iconAnchor: [15, 38], html: pinHtml(layer.icon, point.status)}),
      });
      marker.on("click", () => openDetail(point.id, marker));
      pins.addLayer(marker);
      markerByRecord.set(String(point.id), marker);
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

  function parcelDetailUrl(id) {
    return config.parcelDetailUrl.replace("{id}", encodeURIComponent(id));
  }

  function normalizeParcelCard(item) {
    const crops = (item.crops || []).map((crop) => crop.name).join(", ") || "None recorded";
    return {
      title: item.parcel,
      kicker: `${item.farmer_id} · ${item.farmer}`,
      image: item.photo_url || "",
      imageAlt: `Field photo for ${item.parcel}`,
      url: item.edit_url,
      rows: [
        ["Farmer", item.farmer], ["Barangay", item.barangay], ["Area", item.area],
        ["Coordinates", item.coordinates], ["Pin status", item.pin_status_label], ["Commodities", crops],
      ],
    };
  }

  function showDetailCard(card) {
    els.detailTitle.textContent = card.title;
    els.detailKicker.textContent = card.kicker || "";
    els.detailKicker.hidden = !card.kicker;
    const showPhoto = state.layer === "parcels";
    els.detailPhotoWrap.hidden = !showPhoto;
    if (showPhoto && card.image) {
      els.detailPhoto.src = card.image;
      els.detailPhoto.alt = card.imageAlt || `Field photo for ${card.title}`;
      els.detailPhoto.hidden = false;
      els.detailPhotoEmpty.hidden = true;
      els.detailPhoto.onerror = () => {
        els.detailPhoto.hidden = true;
        els.detailPhotoEmpty.hidden = false;
      };
    } else if (showPhoto) {
      els.detailPhoto.removeAttribute("src");
      els.detailPhoto.alt = "";
      els.detailPhoto.hidden = true;
      els.detailPhotoEmpty.hidden = false;
    }
    els.detailRows.replaceChildren(...card.rows.flatMap(([label, value]) => {
      const term = document.createElement("dt"); term.textContent = label;
      const description = document.createElement("dd"); description.textContent = value;
      return [term, description];
    }));
    els.detailLink.href = card.url;
    els.detailClose.textContent = state.layer === "parcels" && state.barangay ? "Back to parcel list" : "Back to legend";
    els.detail.hidden = false;
    els.parcelDirectory.hidden = true;
    els.legendBox.hidden = true;
    els.insights.hidden = true;
    showLevel(3);
  }

  function focusParcel(item) {
    const marker = markerByRecord.get(String(item.id));
    if (marker) {
      pins.zoomToShowLayer(marker, () => {
        map.setView(marker.getLatLng(), Math.max(map.getZoom(), 17));
        openDetail(item.id, marker);
      });
    } else {
      openDetail(item.id, null);
    }
  }

  async function loadParcelDirectory(page = 1) {
    const visible = state.layer === "parcels" && Boolean(state.barangay);
    els.parcelDirectory.hidden = !visible;
    if (!visible) return;
    if (parcelListRequest) parcelListRequest.abort();
    parcelListRequest = new AbortController();
    els.parcelDirectoryTitle.textContent = `${state.barangay} Farm Parcels`;
    els.parcelList.innerHTML = '<p class="gis-directory-empty">Loading parcels…</p>';
    const url = new URL(config.parcelListUrl, window.location.origin);
    url.searchParams.set("barangay", state.barangay);
    url.searchParams.set("page", page);
    if (state.commodity) url.searchParams.set("commodity", state.commodity);
    if (els.parcelSearch.value.trim()) url.searchParams.set("q", els.parcelSearch.value.trim());
    if (els.parcelPinStatus.value) url.searchParams.set("pin_status", els.parcelPinStatus.value);
    try {
      const response = await fetch(url, {signal: parcelListRequest.signal, headers: {Accept: "application/json"}});
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || "The parcel list could not be loaded.");
      parcelPage = data.pagination.page;
      els.parcelDirectoryScope.textContent = `${data.pagination.total} matching parcel${data.pagination.total === 1 ? "" : "s"}`;
      els.parcelPageStatus.textContent = `Page ${data.pagination.page} of ${data.pagination.total_pages}`;
      els.parcelPrevious.disabled = !data.pagination.has_previous;
      els.parcelNext.disabled = !data.pagination.has_next;
      els.parcelList.replaceChildren(...data.results.map((item) => {
        const row = document.createElement("article");
        row.className = "gis-directory-item";
        const title = document.createElement("strong");
        title.textContent = `${item.parcel} · ${item.farmer}`;
        const identity = document.createElement("small");
        identity.textContent = `${item.farmer_id} · ${item.barangay}`;
        const footer = document.createElement("div");
        const status = document.createElement("span");
        status.className = `gis-pin-status is-${String(item.pin_status).toLowerCase()}`;
        status.textContent = item.pin_status === "UNPINNED" ? "Not pinned" : item.pin_status_label;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "btn btn-outline-secondary";
        button.textContent = item.lat !== null && item.lng !== null ? "View on map" : "View details";
        button.addEventListener("click", () => focusParcel(item));
        footer.append(status, button);
        row.append(title, identity, footer);
        return row;
      }));
      if (!data.results.length) els.parcelList.innerHTML = '<p class="gis-directory-empty">No parcels match this list filter.</p>';
    } catch (error) {
      if (error.name === "AbortError") return;
      const message = document.createElement("p");
      message.className = "gis-directory-empty";
      message.textContent = error.message || "The parcel list could not be loaded.";
      els.parcelList.replaceChildren(message);
    }
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
      if (state.layer === "parcels" && state.barangay) loadParcelDirectory(1);
      else els.parcelDirectory.hidden = true;
      if (state.layer === "parcels" && state.barangay) els.insights.hidden = true;
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
      const url = state.layer === "parcels"
        ? parcelDetailUrl(id)
        : `${config.detailUrl}?${new URLSearchParams({layer: state.layer, id})}`;
      const response = await fetch(url, {headers: {Accept: "application/json"}});
      if (!response.ok) throw new Error("missing");
      const payload = await response.json();
      showDetailCard(state.layer === "parcels" ? normalizeParcelCard(payload) : payload);
      if (selected) selected.getElement()?.classList.remove("is-selected");
      selected = marker;
      marker?.getElement()?.classList.add("is-selected");
    } catch (error) {
      els.level.textContent = "That record could not be opened. It may have been changed.";
    }
  }

  function closeDetail() {
    els.detail.hidden = true;
    els.legendBox.hidden = false;
    const hasDirectory = state.layer === "parcels" && Boolean(state.barangay);
    els.parcelDirectory.hidden = !hasDirectory;
    if (lastData) els.insights.hidden = hasDirectory || !els.top.children.length;
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
    select.addEventListener("change", () => { state[key] = select.value; updateFilterButton(); });
  });
  els.reset.addEventListener("click", () => {
    Object.assign(state, {barangay: "", commodity: "", status: "", extra: {}});
    closeDetail();
    load();
  });
  els.apply.addEventListener("click", () => { closeFilters(); closeDetail(); load(); });
  els.detailClose.addEventListener("click", () => { closeDetail(); showLevel(state.barangay ? 2 : 1); });
  els.parcelSearch.addEventListener("input", () => {
    clearTimeout(parcelSearchTimer);
    parcelSearchTimer = setTimeout(() => loadParcelDirectory(1), 250);
  });
  els.parcelPinStatus.addEventListener("change", () => loadParcelDirectory(1));
  els.parcelPrevious.addEventListener("click", () => loadParcelDirectory(Math.max(1, parcelPage - 1)));
  els.parcelNext.addEventListener("click", () => loadParcelDirectory(parcelPage + 1));
  window.addEventListener("load", () => map.invalidateSize());
  setTimeout(() => map.invalidateSize(), 300);
  load();
})();
