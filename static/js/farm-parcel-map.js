(() => {
  const mapNode = document.getElementById("farmerMap");
  if (!mapNode || typeof L === "undefined") return;
  window.FMIS_PROGRESSIVE_MAP = true;

  const byId = (id) => document.getElementById(id);
  const mapDataUrl = mapNode.dataset.mapUrl;
  const parcelListUrl = mapNode.dataset.parcelsUrl;
  const parcelSearchUrl = mapNode.dataset.searchUrl;
  const pinUrl = mapNode.dataset.pinUrl;
  const rosarioBoundary = JSON.parse(byId("rosario-map-boundary").textContent);
  const rosarioBounds = L.latLngBounds(rosarioBoundary);
  const rosarioPanBounds = rosarioBounds.pad(0.18);
  const BARANGAY_MAX_ZOOM = 15;
  const FARM_MIN_ZOOM = 17;
  const FARM_MAX_ZOOM = 18;
  const csrfToken = document.querySelector("#pinForm [name=csrfmiddlewaretoken]")?.value || "";

  const barangayFilter = byId("mapBarangayFilter");
  const commodityFilter = byId("mapCommodityFilter");
  const clearFilters = byId("clearMapFilters");
  const mapParcelSearch = byId("mapParcelSearch");
  const mapParcelSearchResults = byId("mapParcelSearchResults");
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
  const mobileSheet = byId("parcelMobileSheet");
  const mobileSheetContent = byId("parcelMobileSheetContent");
  const mobileSheetHandle = byId("parcelMobileSheetHandle");
  const mobileSheetExpand = byId("parcelMobileSheetExpand");
  const mobileSheetClose = byId("parcelMobileSheetClose");
  const mobilePopupQuery = window.matchMedia("(max-width: 768px)");

  const state = {
    barangay: "",
    cluster: "",
    page: 1,
    totalPages: 1,
    dataRequest: null,
    listRequest: null,
    detailRequest: null,
    searchRequest: null,
    pinning: false,
    moving: null,
    selectedParcel: null,
    mapMode: "overview",
    zoomTransition: false,
    programmaticMove: false,
    programmaticMoveToken: 0,
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
  const redPinIcon = (contextClass = "") => L.divIcon({
    className: `farmer-pin-shell ${contextClass}`.trim(),
    html: '<span class="farmer-pin" aria-hidden="true"><i class="bi bi-geo-alt-fill"></i></span>',
    iconSize: [28, 28], iconAnchor: [14, 23], popupAnchor: [0, -22], tooltipAnchor: [0, -20],
  });
  const farmerIcon = redPinIcon("parcel-location-pin");
  const movingIcon = L.divIcon({
    className: "farmer-pin-shell is-moving",
    html: '<span class="farmer-pin" aria-hidden="true"><i class="bi bi-geo-alt-fill"></i></span>',
    iconSize: [28, 28], iconAnchor: [14, 23], popupAnchor: [0, -22],
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
  const confirmAction = (message, onConfirm) => {
    if (window.fmisFeedback) {
      window.fmisFeedback(message, "confirm", onConfirm);
      return;
    }
    if (window.confirm(message)) onConfirm();
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
  const decideReview = async (review, approve) => {
    const url = approve ? review.approve_url : review.reject_url;
    const payload = await requestJson(url, {
      method: "POST",
      headers: {"X-CSRFToken": csrfToken, "X-Requested-With": "XMLHttpRequest"},
      body: new URLSearchParams({decision_notes: approve ? "Verified on the farm parcel map." : "Returned for field verification."}),
    });
    map.closePopup();
    if (state.barangay) await selectBarangay(state.barangay);
    else await loadOverview();
    if (approve && payload.parcel_id) await openParcel(payload.parcel_id);
    feedback(payload.message, "success");
  };
  const statusClass = (value) => String(value || "unpinned").toLowerCase().replaceAll("_", "-");
  const hideMobileSheet = () => {
    if (!mobileSheet) return;
    mobileSheet.hidden = true;
    mobileSheet.classList.remove("is-expanded");
    mobileSheetContent.replaceChildren();
    mobileSheetExpand.setAttribute("aria-expanded", "false");
    mobileSheetExpand.setAttribute("aria-label", "Expand farm parcel details");
    mobileSheetHandle.setAttribute("aria-label", "Expand farm parcel details");
    mobileSheetExpand.querySelector("i").className = "bi bi-chevron-up";
    window.setTimeout(() => map.invalidateSize({pan: false}), 0);
  };

  const clearMapLayers = () => {
    barangayLayer.clearLayers();
    clusterLayer.clearLayers();
    parcelLayer.clearLayers();
    markerByParcel.clear();
    map.closePopup();
    hideMobileSheet();
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
  const flyToBounds = (bounds, options = {}) => {
    const target = bounds instanceof L.LatLngBounds ? bounds : L.latLngBounds(bounds || []);
    if (!target.isValid()) return false;
    state.programmaticMove = true;
    const moveToken = ++state.programmaticMoveToken;
    const finishProgrammaticMove = () => {
      if (state.programmaticMoveToken === moveToken) state.programmaticMove = false;
    };
    map.once("moveend", finishProgrammaticMove);
    map.stop();
    map.flyToBounds(target.pad(options.pad ?? 0.1), {
      paddingTopLeft: options.paddingTopLeft || [38, 38],
      paddingBottomRight: options.paddingBottomRight || [38, 38],
      maxZoom: options.maxZoom,
      animate: true,
      duration: options.duration ?? 0.65,
    });
    window.setTimeout(finishProgrammaticMove, 1200);
    return true;
  };
  const focusOverview = () => flyToBounds(rosarioBounds, {
    pad: 0.02,
    paddingTopLeft: [14, 14],
    paddingBottomRight: [14, 14],
    maxZoom: 13,
    duration: 0.65,
  });
  const focusFarm = (point) => new Promise((resolve) => {
    const latLng = L.latLng(point);
    const targetZoom = Math.min(FARM_MAX_ZOOM, Math.max(FARM_MIN_ZOOM, map.getZoom() + 1));
    const alreadyFocused = map.getCenter().distanceTo(latLng) < 4 && map.getZoom() >= targetZoom;
    if (alreadyFocused) {
      resolve();
      return;
    }
    let settled = false;
    const moveToken = ++state.programmaticMoveToken;
    const finish = () => {
      if (settled) return;
      settled = true;
      if (state.programmaticMoveToken === moveToken) state.programmaticMove = false;
      resolve();
    };
    state.programmaticMove = true;
    map.once("moveend", finish);
    map.stop();
    map.flyTo(latLng, targetZoom, {animate: true, duration: 0.55});
    window.setTimeout(finish, 900);
  });
  const selectPanelParcel = (parcelId) => {
    panelList.querySelectorAll(".parcel-panel-item").forEach((row) => {
      const selected = row.dataset.parcelId === String(parcelId);
      row.classList.toggle("is-selected", selected);
      row.setAttribute("aria-current", selected ? "true" : "false");
    });
  };

  const summaryIcon = () => redPinIcon("barangay-location-pin");
  const clusterIcon = () => redPinIcon("cluster-location-pin");

  const loadOverview = async ({resetBarangay = true, preservePanel = false, focus = true} = {}) => {
    state.dataRequest?.abort();
    state.listRequest?.abort();
    state.dataRequest = new AbortController();
    if (resetBarangay) state.barangay = "";
    state.cluster = "";
    state.mapMode = "overview";
    state.page = 1;
    if (resetBarangay) barangayFilter.value = "";
    backToBarangay.hidden = true;
    if (!preservePanel) {
      panelSearch.value = "";
      panelStatus.value = "";
      showPanel(false);
    }
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
        L.marker([item.lat, item.lng], {icon: summaryIcon(), keyboard: true, riseOnHover: true})
          .addTo(barangayLayer)
          .bindTooltip(`${item.name}: ${item.mapped} mapped, ${item.unmapped} not pinned`)
          .on("click", () => selectBarangay(item.name));
      });
      if (focus) window.requestAnimationFrame(focusOverview);
      mapEmpty.style.display = payload.count ? "none" : "grid";
      mapFilterSummary.hidden = true;
      mapBreadcrumb.textContent = state.barangay && preservePanel
        ? `Rosario Municipality · Barangay overview · ${state.barangay} filter retained`
        : "Rosario Municipality · Barangay overview";
      setLoading("");
    } catch (error) {
      if (error.name !== "AbortError") setLoading(error.message, true);
    }
  };

  const selectBarangay = async (barangay, {focus = true} = {}) => {
    state.dataRequest?.abort();
    state.listRequest?.abort();
    state.dataRequest = new AbortController();
    state.barangay = barangay;
    state.cluster = "";
    state.mapMode = "barangay";
    state.page = 1;
    barangayFilter.value = barangay;
    backToBarangay.hidden = true;
    showPanel(true);
    clearMapLayers();
    panelTitle.textContent = `${barangay} Farm Parcels`;
    panelScope.textContent = "Select a red map group pin or search all parcels in this barangay.";
    mapBreadcrumb.textContent = `Rosario Municipality · ${barangay}`;
    setLoading(`Loading ${barangay} parcel groups…`);
    try {
      const url = new URL(mapDataUrl, window.location.origin);
      url.searchParams.set("barangay", barangay);
      if (commodityFilter.value) url.searchParams.set("commodity", commodityFilter.value);
      const payload = await requestJson(url, {signal: state.dataRequest.signal});
      updateCounts(payload);
      (payload.clusters || []).forEach((item) => {
        L.marker([item.lat, item.lng], {icon: clusterIcon(), keyboard: true, riseOnHover: true})
          .addTo(clusterLayer)
          .bindTooltip(`${item.count} mapped parcel${item.count === 1 ? "" : "s"}. Click to inspect.`)
          .on("click", () => selectCluster(item));
      });
      const focused = focus && payload.focus_bounds
        ? flyToBounds(payload.focus_bounds, {
            pad: 0.12,
            paddingTopLeft: [42, 42],
            paddingBottomRight: [42, 42],
            maxZoom: BARANGAY_MAX_ZOOM,
            duration: 0.7,
          })
        : false;
      mapEmpty.style.display = payload.count ? "none" : "grid";
      const focusNote = focused
        ? " The map is focused on the barangay while keeping its reliable locations visible."
        : ` ${payload.focus_message || "No reliable geographic extent is available, so the previous map view was kept."}`;
      mapFilterSummary.hidden = false;
      mapFilterSummary.textContent = `Showing ${payload.count} mapped parcel${payload.count === 1 ? "" : "s"} in ${barangay}, grouped by location.${focusNote}`;
      await loadParcelPage(1, false);
      setLoading("");
    } catch (error) {
      if (error.name !== "AbortError") setLoading(error.message, true);
    }
  };

  const selectCluster = async (cluster) => {
    state.cluster = cluster.id;
    state.mapMode = "cluster";
    state.page = 1;
    clusterLayer.clearLayers();
    parcelLayer.clearLayers();
    markerByParcel.clear();
    backToBarangay.hidden = false;
    panelScope.textContent = `${cluster.count} parcel${cluster.count === 1 ? "" : "s"} in this map group`;
    mapBreadcrumb.textContent = `Rosario Municipality · ${state.barangay} · ${cluster.count}-parcel map group`;
    flyToBounds(cluster.bounds, {
      pad: 0.25,
      paddingTopLeft: [45, 45],
      paddingBottomRight: [45, 45],
      maxZoom: 16,
      duration: 0.55,
    });
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
        row.dataset.parcelId = String(item.id);
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
        empty.textContent = payload.unlocated_matches
          ? "A matching parcel was found, but it is unpinned or its saved location is invalid."
          : "No parcels found.";
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

  const popupNode = (item, parcelMarker = null) => {
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
    if (item.pending_review) {
      const pending = document.createElement("div");
      pending.className = "parcel-coordinate-review";
      const message = document.createElement("p");
      message.textContent = `Proposed coordinate: ${item.pending_review.proposed_coordinates}`;
      const approve = document.createElement("button");
      approve.type = "button";
      approve.className = "btn btn-success";
      approve.textContent = "Approve correction";
      approve.addEventListener("click", () => decideReview(item.pending_review, true));
      const reject = document.createElement("button");
      reject.type = "button";
      reject.className = "btn btn-outline-secondary";
      reject.textContent = "Reject";
      reject.addEventListener("click", () => decideReview(item.pending_review, false));
      pending.append(message, approve, reject);
      popup.append(pending);
    }
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
    const move = document.createElement("button");
    move.type = "button";
    move.className = "parcel-popup-move";
    move.textContent = "Move pin";
    move.addEventListener("click", () => {
      const marker = parcelMarker || markerByParcel.get(String(item.id));
      if (!marker) return feedback("The selected farm pin is not available on the map.", "error");
      map.closePopup();
      hideMobileSheet();
      beginMove(item, marker);
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "parcel-popup-remove";
    remove.textContent = "Remove pin";
    remove.addEventListener("click", () => confirmRemove(item));
    const pinActions = document.createElement("span");
    pinActions.className = "parcel-popup-pin-actions";
    pinActions.append(move, remove);
    actions.append(open, pinActions);
    popup.append(actions);
    return popup;
  };

  const adjustMapForMobileSheet = (marker) => {
    window.requestAnimationFrame(() => {
      map.invalidateSize({pan: false});
      if (!marker || mobileSheet.hidden) return;
      const point = map.latLngToContainerPoint(marker.getLatLng());
      const visibleBottom = map.getSize().y - mobileSheet.offsetHeight - 18;
      const desiredY = Math.max(72, visibleBottom * 0.48);
      const offset = point.y - desiredY;
      if (offset > 0) map.panBy([0, offset], {animate: true, duration: 0.25});
    });
  };
  const showMobileSheet = (item, marker) => {
    map.closePopup();
    mobileSheetContent.replaceChildren(popupNode(item, marker));
    mobileSheet.hidden = false;
    mobileSheetContent.scrollTop = 0;
    adjustMapForMobileSheet(marker);
  };
  const toggleMobileSheet = () => {
    if (mobileSheet.hidden) return;
    const expanded = mobileSheet.classList.toggle("is-expanded");
    mobileSheetExpand.setAttribute("aria-expanded", String(expanded));
    mobileSheetExpand.setAttribute("aria-label", `${expanded ? "Collapse" : "Expand"} farm parcel details`);
    mobileSheetHandle.setAttribute("aria-label", `${expanded ? "Collapse" : "Expand"} farm parcel details`);
    mobileSheetExpand.querySelector("i").className = expanded
      ? "bi bi-chevron-down"
      : "bi bi-chevron-up";
    adjustMapForMobileSheet(markerByParcel.get(String(state.selectedParcel?.id)));
  };

  const openParcel = async (parcelId, marker = null) => {
    state.detailRequest?.abort();
    state.detailRequest = new AbortController();
    try {
      const item = await requestJson(`${mapDataUrl}${parcelId}/`, {signal: state.detailRequest.signal});
      state.selectedParcel = item;
      state.mapMode = "farm";
      let exactMarker = marker || markerByParcel.get(String(parcelId));
      if (!exactMarker && item.lat != null) exactMarker = createParcelMarker(item, false);
      if (!exactMarker) return;
      selectPanelParcel(parcelId);
      markerByParcel.forEach((candidate) => candidate.getElement()?.classList.remove("is-selected"));
      exactMarker.getElement()?.classList.add("is-selected");
      await focusFarm(exactMarker.getLatLng());
      if (mobilePopupQuery.matches) {
        showMobileSheet(item, exactMarker);
        return;
      }
      hideMobileSheet();
      exactMarker.bindPopup(popupNode(item, exactMarker), {
        maxWidth: 390, minWidth: 290, maxHeight: 450, autoPan: true, keepInView: true,
        autoPanPaddingTopLeft: [20, 90], autoPanPaddingBottomRight: [20, 30],
      }).openPopup();
    } catch (error) {
      if (error.name !== "AbortError") feedback(error.message, "error");
    }
  };

  const focusPanelParcel = async (item) => {
    if (item.lat == null || item.lng == null) {
      const option = new Option(`${item.parcel} · ${item.farmer}`, String(item.id), true, true);
      option.dataset.barangay = item.barangay || state.barangay;
      option.dataset.pinStatus = "UNPINNED";
      farmerSelect.replaceChildren(option);
      startPin.disabled = false;
      startPin.click();
      return;
    }
    const marker = createParcelMarker(item, false);
    await openParcel(item.id, marker);
  };

  const hideMapSearchResults = () => {
    mapParcelSearchResults.hidden = true;
    mapParcelSearchResults.replaceChildren();
    mapParcelSearch.setAttribute("aria-expanded", "false");
  };
  const chooseMapSearchResult = async (item) => {
    mapParcelSearch.value = `${item.parcel} · ${item.farmer_id}`;
    hideMapSearchResults();
    if (item.barangay && state.barangay !== item.barangay) await selectBarangay(item.barangay);
    if (item.is_pinned) {
      await openParcel(item.id);
      return;
    }
    showPanel(true);
    panelStatus.value = "";
    panelSearch.value = item.parcel || item.farmer_id;
    await loadParcelPage(1, false);
    selectPanelParcel(item.id);
    feedback(`${item.parcel} is unpinned. Use Select to pin in the Farm Parcels panel.`, "info");
  };
  const searchMapParcels = async () => {
    const query = mapParcelSearch.value.trim();
    state.searchRequest?.abort();
    if (query.length < 2) {
      hideMapSearchResults();
      return;
    }
    state.searchRequest = new AbortController();
    const url = new URL(parcelSearchUrl, window.location.origin);
    url.searchParams.set("q", query);
    url.searchParams.set("compact", "1");
    url.searchParams.set("pinned_only", "1");
    if (barangayFilter.value) url.searchParams.set("barangay", barangayFilter.value);
    if (commodityFilter.value) url.searchParams.set("commodity", commodityFilter.value);
    try {
      const payload = await requestJson(url, {signal: state.searchRequest.signal});
      mapParcelSearchResults.replaceChildren();
      (payload.results || []).forEach((item) => {
        const option = document.createElement("button");
        option.type = "button";
        option.className = "map-search-result";
        option.setAttribute("role", "option");
        const label = document.createElement("span");
        label.className = "map-search-result-label";
        label.textContent = `${item.parcel} / ${item.farmer_id} - ${item.farmer} (${item.barangay})`;
        option.append(label);
        option.addEventListener("click", () => chooseMapSearchResult(item));
        mapParcelSearchResults.append(option);
      });
      if (!(payload.results || []).length) {
        const empty = document.createElement("p");
        empty.className = "map-search-message";
        empty.textContent = payload.unlocated_matches
          ? "A matching parcel was found, but it is unpinned or its saved location is invalid."
          : "No farm parcels match your search.";
        mapParcelSearchResults.append(empty);
      }
      mapParcelSearchResults.hidden = false;
      mapParcelSearch.setAttribute("aria-expanded", "true");
    } catch (error) {
      if (error.name !== "AbortError") feedback(error.message, "error");
    }
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

  const positionPinEditPanel = () => {
    const marker = state.moving?.marker;
    if (!marker) return;
    const point = map.latLngToContainerPoint(marker.getLatLng());
    const mapRect = mapNode.getBoundingClientRect();
    const shellRect = pinEditPanel.offsetParent.getBoundingClientRect();
    pinEditPanel.style.left = `${mapRect.left - shellRect.left + point.x}px`;
    pinEditPanel.style.top = `${mapRect.top - shellRect.top + point.y}px`;
  };
  map.on("move zoom", positionPinEditPanel);

  const beginMove = (item, marker) => {
    state.pinning = false;
    document.body.classList.remove("map-pin-active");
    if (state.moving?.marker) state.moving.marker.remove();
    marker.removeFrom(parcelLayer);
    const movingMarker = L.marker(marker.getLatLng(), {icon: movingIcon, draggable: true, zIndexOffset: 1200}).addTo(parcelLayer);
    state.moving = {item, originalMarker: marker, marker: movingMarker};
    movingMarker.on("drag", positionPinEditPanel);
    pinEditFarmer.textContent = `Moving ${item.parcel} · ${item.farmer}`;
    pinEditPanel.classList.add("is-visible");
    positionPinEditPanel();
    movingMarker.dragging.enable();
  };
  const endMove = (restore = true) => {
    if (!state.moving) return;
    const {marker, originalMarker} = state.moving;
    marker.remove();
    if (restore) originalMarker.addTo(parcelLayer);
    state.moving = null;
    pinEditPanel.classList.remove("is-visible");
    pinEditPanel.style.left = "";
    pinEditPanel.style.top = "";
  };
  cancelPinMove.addEventListener("click", () => {
    if (!state.moving) return;
    const {item} = state.moving;
    confirmAction(
      `Cancel moving ${item.parcel}? The saved pin will remain at its current location.`,
      () => endMove(true)
    );
  });
  savePinMove.addEventListener("click", () => {
    if (!state.moving) return;
    const {item, marker} = state.moving;
    const point = marker.getLatLng();
    if (!rosarioBounds.contains(point)) return feedback("Choose a point inside the Rosario boundary.", "error");
    confirmAction(
      `Save this new location for ${item.parcel}? It will be submitted for verification, and the saved pin will remain unchanged until approved.`,
      async () => {
        if (!state.moving || state.moving.marker !== marker) return;
        savePinMove.disabled = true;
        cancelPinMove.disabled = true;
        try {
          const currentPoint = marker.getLatLng();
          const payload = await postPin({parcel_id: item.id, operation: "move", latitude: currentPoint.lat, longitude: currentPoint.lng});
          endMove(true);
          await selectBarangay(item.barangay || state.barangay);
          feedback(payload.message, "success");
        } catch (error) { feedback(error.message, "error"); }
        finally {
          savePinMove.disabled = false;
          cancelPinMove.disabled = false;
        }
      }
    );
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
  clearFilters.addEventListener("click", () => {
    state.searchRequest?.abort();
    mapParcelSearch.value = "";
    commodityFilter.value = "";
    panelSearch.value = "";
    panelStatus.value = "";
    hideMapSearchResults();
    loadOverview();
  });
  backToBarangay.addEventListener("click", () => {
    if (state.barangay) selectBarangay(state.barangay);
    else loadOverview();
  });
  closePanel.addEventListener("click", () => showPanel(false));
  mobileSheetClose.addEventListener("click", hideMobileSheet);
  mobileSheetExpand.addEventListener("click", toggleMobileSheet);
  mobileSheetHandle.addEventListener("click", toggleMobileSheet);
  pagePrevious.addEventListener("click", () => loadParcelPage(state.page - 1, Boolean(state.cluster)));
  pageNext.addEventListener("click", () => loadParcelPage(state.page + 1, Boolean(state.cluster)));
  panelStatus.addEventListener("change", () => loadParcelPage(1, Boolean(state.cluster)));
  let searchTimer = null;
  panelSearch.addEventListener("input", () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => loadParcelPage(1, Boolean(state.cluster)), 250);
  });
  let mapSearchTimer = null;
  mapParcelSearch.addEventListener("input", () => {
    window.clearTimeout(mapSearchTimer);
    mapSearchTimer = window.setTimeout(searchMapParcels, 250);
  });
  mapParcelSearch.addEventListener("keydown", (event) => {
    if (event.key === "Escape") hideMapSearchResults();
    if (event.key === "Enter") {
      const firstResult = mapParcelSearchResults.querySelector(".map-search-result");
      if (firstResult && !mapParcelSearchResults.hidden) {
        event.preventDefault();
        firstResult.click();
      }
    }
  });
  document.addEventListener("click", (event) => {
    if (!event.target.closest(".map-search-field")) hideMapSearchResults();
  });
  map.on("zoomend", async () => {
    if (state.zoomTransition || state.programmaticMove || !state.barangay) return;
    if (state.mapMode === "farm" && map.getZoom() <= 16) {
      state.zoomTransition = true;
      try { await selectBarangay(state.barangay, {focus: false}); }
      finally { state.zoomTransition = false; }
    }
  });
  mobilePopupQuery.addEventListener("change", () => {
    map.closePopup();
    hideMobileSheet();
  });
  window.addEventListener("resize", () => map.invalidateSize({pan: false}));
  startPin.disabled = true;
  loadOverview();
})();
