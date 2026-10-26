(() => {
  const mapNode = document.getElementById("farmerMap");
  if (!mapNode || typeof L === "undefined") return;
  window.FMIS_PROGRESSIVE_MAP = true;

  const byId = (id) => document.getElementById(id);
  const mapDataUrl = mapNode.dataset.mapUrl;
  const parcelListUrl = mapNode.dataset.parcelsUrl;
  const pinUrl = mapNode.dataset.pinUrl;
  const rosarioBoundary = JSON.parse(byId("rosario-map-boundary").textContent);
  const rosarioBounds = L.latLngBounds(rosarioBoundary);
  const rosarioPanBounds = rosarioBounds.pad(0.18);
  const csrfToken = document.querySelector("#pinForm [name=csrfmiddlewaretoken]")?.value || "";

  const barangayFilter = byId("mapBarangayFilter");
  const commodityFilter = byId("mapCommodityFilter");
  const clearFilters = byId("clearMapFilters");
  const backToOverview = byId("backToOverview");
  const mapFilterSummary = byId("mapFilterSummary");
  const visibleMappedCount = byId("visibleMappedCount");
  const unmappedParcelCount = byId("unmappedParcelCount");
  const verificationParcelCount = byId("verificationParcelCount");
  const mapLoadingStatus = byId("mapLoadingStatus");
  const mapEmpty = byId("mapEmpty");
  const mapBreadcrumb = byId("mapBreadcrumb")?.querySelector("span");
  const explorer = byId("mapExplorer");
  const sidePanel = byId("parcelSidePanel");
  const panelTitle = byId("parcelPanelTitle");
  const panelScope = byId("parcelPanelScope");
  const panelSearch = byId("parcelPanelSearch");
  const panelStatus = byId("parcelPanelStatus");
  const panelList = byId("parcelPanelList");
  const panelPageStatus = byId("parcelPageStatus");
  const pagePrevious = byId("parcelPagePrevious");
  const pageNext = byId("parcelPageNext");
  const backToBarangay = byId("backToBarangay");
  const closePanel = byId("closeParcelPanel");
  const farmerSelect = byId("pinFarmer");
  const startPin = byId("startPin");
  const pinHelp = byId("pinHelp");
  const pinEditPanel = byId("pinEditPanel");
  const pinEditFarmer = byId("pinEditFarmer");
  const cancelPinMove = byId("cancelPinMove");
  const savePinMove = byId("savePinMove");

  const state = {
    barangay: "",
    cluster: "",
    page: 1,
    totalPages: 1,
    dataRequest: null,
    listRequest: null,
    detailRequest: null,
    pinning: false,
    moving: null,
    selectedParcel: null,
  };

  const map = L.map(mapNode, {
    scrollWheelZoom: false,
    preferCanvas: true,
    maxBounds: rosarioPanBounds,
    maxBoundsViscosity: 0.72,
    minZoom: 10,
  });
  L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    {maxNativeZoom: 18, maxZoom: 19, noWrap: true, keepBuffer: 1, updateWhenIdle: true,
      attribution: "Satellite imagery &copy; Esri and imagery providers"}
  ).addTo(map);
  L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
    {maxNativeZoom: 18, maxZoom: 19, noWrap: true, keepBuffer: 1, updateWhenIdle: true,
      pane: "overlayPane", attribution: "Place labels &copy; Esri"}
  ).addTo(map);
  L.polygon(rosarioBoundary, {
    renderer: L.svg({padding: 0.25}), color: "#087a3d", weight: 5, opacity: 1,
    fill: true, fillColor: "#51b878", fillOpacity: 0.1, interactive: false,
  }).addTo(map);
  map.fitBounds(rosarioBounds, {padding: [10, 10]});

  const barangayLayer = L.layerGroup().addTo(map);
  const clusterLayer = L.layerGroup().addTo(map);
  const parcelLayer = L.layerGroup().addTo(map);
  const markerByParcel = new Map();
  const farmerIcon = L.divIcon({
    className: "farmer-pin-shell",
    html: '<span class="farmer-pin" aria-hidden="true"><i class="bi bi-geo-alt-fill"></i></span>',
    iconSize: [30, 34], iconAnchor: [15, 32], popupAnchor: [0, -31], tooltipAnchor: [0, -28],
  });
  const movingIcon = L.divIcon({
    className: "farmer-pin-shell is-moving",
    html: '<span class="farmer-pin" aria-hidden="true"><i class="bi bi-geo-alt-fill"></i></span>',
    iconSize: [30, 34], iconAnchor: [15, 32], popupAnchor: [0, -31],
  });

  const setLoading = (message = "", isError = false) => {
    mapLoadingStatus.hidden = !message;
    mapLoadingStatus.classList.toggle("is-error", isError);
    mapLoadingStatus.querySelector("span").textContent = message;
    mapLoadingStatus.querySelector("i").className = isError ? "bi bi-exclamation-triangle" : "bi bi-arrow-repeat";
  };
  const feedback = (message, type = "success") => {
    if (window.fmisFeedback) window.fmisFeedback(message, type);
    else if (type === "error") window.alert(message);
  };
  const requestJson = async (url, options = {}) => {
    const response = await fetch(url, {credentials: "same-origin", ...options});
    let payload = {};
    try { payload = await response.json(); } catch (_) { /* handled below */ }
    if (!response.ok) throw new Error(payload.message || "The map request could not be completed.");
    return payload;
  };
  const postPin = (data) => requestJson(pinUrl, {
    method: "POST",
    headers: {"X-CSRFToken": csrfToken, "X-Requested-With": "XMLHttpRequest"},
    body: new URLSearchParams(data),
  });
  const statusClass = (value) => String(value || "unpinned").toLowerCase().replaceAll("_", "-");
  const escapeText = (value) => String(value ?? "");

  const clearMapLayers = () => {
    barangayLayer.clearLayers();
    clusterLayer.clearLayers();
    parcelLayer.clearLayers();
    markerByParcel.clear();
    map.closePopup();
  };
  const showPanel = (show = true) => {
    sidePanel.hidden = !show;
    explorer.classList.toggle("has-panel", show);
    window.setTimeout(() => map.invalidateSize(), 0);
  };
  const updateCounts = (payload) => {
    visibleMappedCount.textContent = payload.count ?? 0;
    unmappedParcelCount.textContent = payload.unmapped_count ?? 0;
    verificationParcelCount.textContent = payload.verification_count ?? 0;
  };
  const fillSelectOnce = (select, values, label) => {
    const current = select.value;
    select.replaceChildren(new Option(label, ""));
    values.forEach((value) => select.add(new Option(value, value)));
    if ([...select.options].some((option) => option.value === current)) select.value = current;
  };
  const boundsFor = (items) => {
    const points = items.flatMap((item) => item.bounds || (item.lat != null ? [[item.lat, item.lng]] : []));
    return points.length ? L.latLngBounds(points) : null;
  };

  const summaryIcon = (item) => L.divIcon({
    className: "map-summary-marker",
    html: `<span class="barangay-marker"><strong>${escapeText(item.name)}</strong><small>${item.mapped} mapped parcel${item.mapped === 1 ? "" : "s"}</small></span>`,
    iconSize: [124, 48], iconAnchor: [62, 24],
  });
  const clusterIcon = (count) => L.divIcon({
    className: "map-spatial-cluster",
    html: `<span class="spatial-cluster-marker" aria-label="${count} parcels">${count}</span>`,
    iconSize: [46, 46], iconAnchor: [23, 23],
  });

  const loadOverview = async () => {
    state.dataRequest?.abort();
    state.listRequest?.abort();
    state.dataRequest = new AbortController();
    state.barangay = "";
    state.cluster = "";
    state.page = 1;
    barangayFilter.value = "";
    backToOverview.hidden = true;
    backToBarangay.hidden = true;
    panelSearch.value = "";
    panelStatus.value = "";
    showPanel(false);
    clearMapLayers();
    setLoading("Loading Rosario barangay summaries…");
    try {
      const url = new URL(mapDataUrl, window.location.origin);
      if (commodityFilter.value) url.searchParams.set("commodity", commodityFilter.value);
      const payload = await requestJson(url, {signal: state.dataRequest.signal});
      updateCounts(payload);
      fillSelectOnce(barangayFilter, (payload.barangays || []).map((item) => item.name), "All barangays");
      fillSelectOnce(commodityFilter, payload.commodities || [], "All commodities");
      (payload.barangays || []).forEach((item) => {
        L.marker([item.lat, item.lng], {icon: summaryIcon(item), keyboard: true, riseOnHover: true})
          .addTo(barangayLayer)
          .bindTooltip(`${item.name}: ${item.mapped} mapped, ${item.unmapped} not pinned`)
          .on("click", () => selectBarangay(item.name, item.bounds));
      });
      map.fitBounds(rosarioBounds, {padding: [14, 14]});
      mapEmpty.style.display = payload.count ? "none" : "grid";
      mapFilterSummary.textContent = commodityFilter.value
        ? `Barangay overview for ${commodityFilter.value}. Select a barangay to see its map groups.`
        : "Barangay overview. Select a barangay marker to review its farm parcels.";
      mapBreadcrumb.textContent = "Rosario Municipality · Barangay overview";
      setLoading("");
    } catch (error) {
      if (error.name !== "AbortError") setLoading(error.message, true);
    }
  };

  const selectBarangay = async (barangay, preferredBounds = null) => {
    state.dataRequest?.abort();
    state.listRequest?.abort();
    state.dataRequest = new AbortController();
    state.barangay = barangay;
    state.cluster = "";
    state.page = 1;
    barangayFilter.value = barangay;
    backToOverview.hidden = false;
    backToBarangay.hidden = true;
    showPanel(true);
    clearMapLayers();
    panelTitle.textContent = `${barangay} Farm Parcels`;
    panelScope.textContent = "Select a numbered map group or search all parcels in this barangay.";
    mapBreadcrumb.textContent = `Rosario Municipality · ${barangay}`;
    setLoading(`Loading ${barangay} parcel groups…`);
    try {
      const url = new URL(mapDataUrl, window.location.origin);
      url.searchParams.set("barangay", barangay);
      if (commodityFilter.value) url.searchParams.set("commodity", commodityFilter.value);
      const payload = await requestJson(url, {signal: state.dataRequest.signal});
      updateCounts(payload);
      (payload.clusters || []).forEach((item) => {
        L.marker([item.lat, item.lng], {icon: clusterIcon(item.count), keyboard: true, riseOnHover: true})
          .addTo(clusterLayer)
          .bindTooltip(`${item.count} mapped parcel${item.count === 1 ? "" : "s"}. Click to inspect.`)
          .on("click", () => selectCluster(item));
      });
      const groupBounds = boundsFor(payload.clusters || []) || (preferredBounds ? L.latLngBounds(preferredBounds) : null);
      if (groupBounds?.isValid()) map.fitBounds(groupBounds.pad(0.12), {padding: [35, 35], maxZoom: 15});
      mapEmpty.style.display = payload.count ? "none" : "grid";
      mapFilterSummary.textContent = `Showing ${payload.count} mapped parcel${payload.count === 1 ? "" : "s"} in ${barangay}, grouped by location.`;
      await loadParcelPage(1, false);
      setLoading("");
    } catch (error) {
      if (error.name !== "AbortError") setLoading(error.message, true);
    }
  };

  const selectCluster = async (cluster) => {
    state.cluster = cluster.id;
    state.page = 1;
    parcelLayer.clearLayers();
    markerByParcel.clear();
    backToBarangay.hidden = false;
    panelScope.textContent = `${cluster.count} parcel${cluster.count === 1 ? "" : "s"} in this map group`;
    mapBreadcrumb.textContent = `Rosario Municipality · ${state.barangay} · ${cluster.count}-parcel map group`;
    const clusterBounds = L.latLngBounds(cluster.bounds);
    if (clusterBounds.isValid()) map.fitBounds(clusterBounds.pad(0.25), {padding: [45, 45], maxZoom: 18});
    await loadParcelPage(1, true);
  };

  const createParcelMarker = (item, open = false) => {
    if (item.lat == null || item.lng == null) return null;
    const key = String(item.id);
    let marker = markerByParcel.get(key);
    if (!marker) {
      marker = L.marker([item.lat, item.lng], {icon: farmerIcon, keyboard: true, riseOnHover: true})
        .addTo(parcelLayer)
        .bindTooltip(`${item.parcel} · ${item.farmer}`)
        .on("click", () => openParcel(item.id, marker))
        .on("contextmenu", () => beginMove(item, marker));
      markerByParcel.set(key, marker);
    }
    if (open) openParcel(item.id, marker);
    return marker;
  };

  const loadParcelPage = async (page = 1, renderMarkers = Boolean(state.cluster)) => {
    if (!state.barangay) return;
    state.listRequest?.abort();
    state.listRequest = new AbortController();
    panelList.innerHTML = '<p class="parcel-panel-empty">Loading parcels…</p>';
    try {
      const url = new URL(parcelListUrl, window.location.origin);
      url.searchParams.set("barangay", state.barangay);
      url.searchParams.set("page", page);
      if (state.cluster) url.searchParams.set("cluster", state.cluster);
      if (panelSearch.value.trim()) url.searchParams.set("q", panelSearch.value.trim());
      if (panelStatus.value) url.searchParams.set("pin_status", panelStatus.value);
      if (commodityFilter.value) url.searchParams.set("commodity", commodityFilter.value);
      const payload = await requestJson(url, {signal: state.listRequest.signal});
      state.page = payload.pagination.page;
      state.totalPages = payload.pagination.total_pages;
      panelPageStatus.textContent = `Page ${state.page} of ${state.totalPages} · ${payload.pagination.total} records`;
      pagePrevious.disabled = !payload.pagination.has_previous;
      pageNext.disabled = !payload.pagination.has_next;
      panelList.replaceChildren();
      if (renderMarkers) {
        parcelLayer.clearLayers();
        markerByParcel.clear();
      }
      (payload.results || []).forEach((item) => {
        const row = document.createElement("article");
        row.className = "parcel-panel-item";
        const title = document.createElement("strong");
        title.textContent = `${item.parcel} · ${item.farmer}`;
        const identity = document.createElement("small");
        identity.textContent = `${item.farmer_id} · ${item.barangay}`;
        const meta = document.createElement("div");
        meta.className = "parcel-panel-meta";
        const status = document.createElement("span");
        status.className = `parcel-status status-${statusClass(item.pin_status)}`;
        status.textContent = item.pin_status_label;
        const view = document.createElement("button");
        view.type = "button";
        view.className = "btn btn-outline-success";
        view.textContent = item.lat == null ? "Select to pin" : "View on map";
        view.addEventListener("click", () => focusPanelParcel(item));
        meta.append(status, view);
        row.append(title, identity, meta);
        panelList.append(row);
        if (renderMarkers && item.lat != null) createParcelMarker(item, false);
      });
      if (!(payload.results || []).length) {
        const empty = document.createElement("p");
        empty.className = "parcel-panel-empty";
        empty.textContent = "No farm parcels match these filters.";
        panelList.append(empty);
      }
    } catch (error) {
      if (error.name !== "AbortError") {
        panelList.replaceChildren();
        const message = document.createElement("p");
        message.className = "parcel-panel-empty";
        message.textContent = error.message;
        panelList.append(message);
      }
    }
  };

  const popupNode = (item) => {
    const popup = document.createElement("div");
    popup.className = "farmer-popup";
    if (item.photo_url) {
      const photoLink = document.createElement("a");
      photoLink.className = "parcel-popup-photo-link";
      photoLink.href = item.photo_url;
      photoLink.target = "_blank";
      photoLink.rel = "noopener";
      const photo = document.createElement("img");
      photo.className = "parcel-popup-photo";
      photo.src = item.photo_url;
      photo.alt = `Field photo for ${item.parcel}`;
      photo.loading = "lazy";
      photoLink.append(photo);
      popup.append(photoLink);
    } else {
      const empty = document.createElement("div");
      empty.className = "parcel-popup-photo-empty";
      empty.textContent = "No field photo available";
      popup.append(empty);
    }
    const head = document.createElement("div");
    head.className = "farmer-popup-head";
    const avatar = document.createElement("div");
    avatar.className = "farmer-avatar";
    avatar.innerHTML = '<i class="bi bi-person"></i>';
    const identity = document.createElement("div");
    const heading = document.createElement("h3");
    heading.textContent = item.farmer;
    const id = document.createElement("small");
    id.textContent = `${item.farmer_id} · ${item.parcel}`;
    identity.append(heading, id);
    head.append(avatar, identity);
    popup.append(head);
    const facts = document.createElement("div");
    facts.className = "parcel-popup-facts";
    [["Barangay", item.barangay], ["Area", item.area], ["Coordinates", item.coordinates], ["Pin status", item.pin_status_label]].forEach(([label, value]) => {
      const fact = document.createElement("div");
      fact.className = "parcel-popup-fact";
      const strong = document.createElement("strong");
      strong.textContent = label;
      const span = document.createElement("span");
      span.textContent = value || "Not recorded";
      fact.append(strong, span);
      facts.append(fact);
    });
    popup.append(facts);
    const crops = document.createElement("div");
    crops.className = "parcel-popup-crops";
    crops.innerHTML = "<strong>Commodities</strong>";
    const cropList = document.createElement("div");
    cropList.className = "parcel-popup-crop-list";
    (item.crops?.length ? item.crops : [{name: "No commodities recorded", symbol: ""}]).forEach((crop) => {
      const chip = document.createElement("span");
      chip.textContent = `${crop.symbol || ""} ${crop.name}`.trim();
      cropList.append(chip);
    });
    crops.append(cropList);
    popup.append(crops);
    const actions = document.createElement("div");
    actions.className = "farmer-popup-actions";
    const open = document.createElement("a");
    open.href = item.edit_url;
    open.textContent = "Open farm parcel";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Remove pin";
    remove.addEventListener("click", () => confirmRemove(item));
    actions.append(open, remove);
    popup.append(actions);
    return popup;
  };

  const openParcel = async (parcelId, marker = null) => {
    state.detailRequest?.abort();
    state.detailRequest = new AbortController();
    try {
      const item = await requestJson(`${mapDataUrl}${parcelId}/`, {signal: state.detailRequest.signal});
      state.selectedParcel = item;
      let exactMarker = marker || markerByParcel.get(String(parcelId));
      if (!exactMarker && item.lat != null) exactMarker = createParcelMarker(item, false);
      if (!exactMarker) return;
      map.panTo(exactMarker.getLatLng(), {animate: true, duration: 0.2});
      exactMarker.bindPopup(popupNode(item), {
        maxWidth: 330, minWidth: 250, maxHeight: 450, autoPan: true, keepInView: true,
        autoPanPaddingTopLeft: [20, 90], autoPanPaddingBottomRight: [20, 30],
      }).openPopup();
    } catch (error) {
      if (error.name !== "AbortError") feedback(error.message, "error");
    }
  };

  const focusPanelParcel = async (item) => {
    if (item.lat == null || item.lng == null) {
      farmerSelect.value = String(item.id);
      startPin.disabled = false;
      startPin.click();
      return;
    }
    const marker = createParcelMarker(item, false);
    map.setView([item.lat, item.lng], Math.max(map.getZoom(), 17), {animate: true});
    await openParcel(item.id, marker);
  };

  const confirmRemove = (item) => {
    const perform = async () => {
      try {
        const payload = await postPin({parcel_id: item.id, operation: "remove"});
        map.closePopup();
        if (state.barangay) await selectBarangay(state.barangay);
        else await loadOverview();
        feedback(payload.message, "success");
      } catch (error) { feedback(error.message, "error"); }
    };
    if (window.fmisFeedback) {
      window.fmisFeedback(`Remove the saved map pin for ${item.parcel}? The parcel record will be kept.`, "confirm", perform);
    } else if (window.confirm(`Remove the saved map pin for ${item.parcel}?`)) perform();
  };

  const beginMove = (item, marker) => {
    state.pinning = false;
    document.body.classList.remove("map-pin-active");
    if (state.moving?.marker) state.moving.marker.remove();
    marker.removeFrom(parcelLayer);
    const movingMarker = L.marker(marker.getLatLng(), {icon: movingIcon, draggable: true, zIndexOffset: 1200}).addTo(parcelLayer);
    state.moving = {item, originalMarker: marker, marker: movingMarker};
    pinEditFarmer.textContent = `Moving ${item.parcel} · ${item.farmer}`;
    pinEditPanel.classList.add("is-visible");
    movingMarker.dragging.enable();
  };
  const endMove = (restore = true) => {
    if (!state.moving) return;
    const {marker, originalMarker} = state.moving;
    marker.remove();
    if (restore) originalMarker.addTo(parcelLayer);
    state.moving = null;
    pinEditPanel.classList.remove("is-visible");
  };
  cancelPinMove.addEventListener("click", () => endMove(true));
  savePinMove.addEventListener("click", async () => {
    if (!state.moving) return;
    const {item, marker} = state.moving;
    const point = marker.getLatLng();
    if (!rosarioBounds.contains(point)) return feedback("Choose a point inside the Rosario boundary.", "error");
    savePinMove.disabled = true;
    try {
      const payload = await postPin({parcel_id: item.id, operation: "move", latitude: point.lat, longitude: point.lng});
      endMove(false);
      await selectBarangay(item.barangay || state.barangay);
      feedback(payload.message, "success");
    } catch (error) { feedback(error.message, "error"); }
    finally { savePinMove.disabled = false; }
  });

  startPin.addEventListener("click", () => {
    if (!farmerSelect.value) return feedback("Select a farm parcel first.", "error");
    const option = farmerSelect.selectedOptions[0];
    if (option?.dataset.pinStatus && option.dataset.pinStatus !== "UNPINNED") {
      openSelectedPickerParcel();
      return;
    }
    state.pinning = !state.pinning;
    document.body.classList.toggle("map-pin-active", state.pinning);
    pinHelp.hidden = !state.pinning;
    startPin.innerHTML = state.pinning ? '<i class="bi bi-x-lg"></i> Cancel Pinning' : '<i class="bi bi-pin-map"></i> Pin Farm Parcel';
  });
  map.on("click", async (event) => {
    if (!state.pinning || !farmerSelect.value) return;
    if (!rosarioBounds.contains(event.latlng)) return feedback("Choose a point inside the Rosario boundary.", "error");
    startPin.disabled = true;
    try {
      const option = farmerSelect.selectedOptions[0];
      const payload = await postPin({parcel_id: farmerSelect.value, operation: "create", latitude: event.latlng.lat, longitude: event.latlng.lng});
      state.pinning = false;
      document.body.classList.remove("map-pin-active");
      pinHelp.hidden = true;
      startPin.innerHTML = '<i class="bi bi-pin-map"></i> Pin Farm Parcel';
      if (option?.dataset.barangay) await selectBarangay(option.dataset.barangay);
      else await loadOverview();
      feedback(payload.message, "success");
    } catch (error) { feedback(error.message, "error"); }
    finally { startPin.disabled = false; }
  });

  const openSelectedPickerParcel = async () => {
    if (!farmerSelect.value) return;
    const option = farmerSelect.selectedOptions[0];
    if (option?.dataset.barangay && state.barangay !== option.dataset.barangay) await selectBarangay(option.dataset.barangay);
    await openParcel(farmerSelect.value);
  };
  farmerSelect.addEventListener("change", () => {
    const option = farmerSelect.selectedOptions[0];
    startPin.disabled = !farmerSelect.value;
    startPin.innerHTML = option?.dataset.pinStatus && option.dataset.pinStatus !== "UNPINNED"
      ? '<i class="bi bi-geo-alt"></i> View Farm Parcel'
      : '<i class="bi bi-pin-map"></i> Pin Farm Parcel';
  });
  farmerSelect.addEventListener("farmer-picker:selected", openSelectedPickerParcel);

  barangayFilter.addEventListener("change", () => barangayFilter.value ? selectBarangay(barangayFilter.value) : loadOverview());
  commodityFilter.addEventListener("change", () => state.barangay ? selectBarangay(state.barangay) : loadOverview());
  clearFilters.addEventListener("click", () => { commodityFilter.value = ""; loadOverview(); });
  backToOverview.addEventListener("click", loadOverview);
  backToBarangay.addEventListener("click", () => selectBarangay(state.barangay));
  closePanel.addEventListener("click", () => showPanel(false));
  pagePrevious.addEventListener("click", () => loadParcelPage(state.page - 1, Boolean(state.cluster)));
  pageNext.addEventListener("click", () => loadParcelPage(state.page + 1, Boolean(state.cluster)));
  panelStatus.addEventListener("change", () => loadParcelPage(1, Boolean(state.cluster)));
  let searchTimer = null;
  panelSearch.addEventListener("input", () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => loadParcelPage(1, Boolean(state.cluster)), 250);
  });
  window.addEventListener("resize", () => map.invalidateSize());
  startPin.disabled = true;
  loadOverview();
})();
