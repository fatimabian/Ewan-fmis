// Review screen: map pin coloured by status, suggestion marker, one-click fixes.
(() => {
  const dataNode = document.getElementById("scan-map-data");
  const form = document.getElementById("scanForm");
  if (!dataNode || !form) return;
  const data = JSON.parse(dataNode.textContent);

  // The site disables a submit button while posting, which drops its value, so the
  // chosen action also travels in a hidden field set at click time.
  const action = document.getElementById("scanAction");
  form.querySelectorAll('button[name="action"]').forEach((button) => {
    button.addEventListener("click", () => { if (action) action.value = button.value; });
  });

  // Staff pick a suggestion explicitly; nothing is ever applied silently.
  form.querySelectorAll(".sg-apply").forEach((button) => {
    button.addEventListener("click", () => {
      const fix = JSON.parse(button.dataset.fix || "{}");
      Object.entries(fix).forEach(([name, value]) => {
        const input = form.elements[name];
        if (input) input.value = value;
      });
      if (action) action.value = "check";
      form.requestSubmit();
    });
  });

  const search = document.getElementById("farmerSearch");
  const go = document.getElementById("farmerSearchGo");
  if (search && go) {
    go.addEventListener("click", () => {
      go.href = `?q=${encodeURIComponent(search.value)}`;
    });
  }

  const mapNode = document.getElementById("scanMap");
  if (!mapNode || typeof L === "undefined") return;
  const colors = {GREEN: "#2f7d5c", YELLOW: "#d8a62b", RED: "#b42318"};
  const map = L.map(mapNode, {scrollWheelZoom: false});
  L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    {maxNativeZoom: 18, maxZoom: 19, noWrap: true, attribution: "Satellite imagery &copy; Esri"}
  ).addTo(map);
  const outline = L.polygon(data.boundary, {color: "#2f7d5c", weight: 3, fill: false}).addTo(map);

  const bounds = [];
  if (data.point) {
    L.circleMarker(data.point, {radius: 11, color: "#fff", weight: 3, fillColor: colors[data.status], fillOpacity: 1})
      .bindTooltip("Location on the form").addTo(map);
    bounds.push(data.point);
  }
  if (data.suggested && !(data.point && data.point[0] === data.suggested[0] && data.point[1] === data.suggested[1])) {
    L.circleMarker(data.suggested, {radius: 13, color: "#111c2b", weight: 3, dashArray: "4 4", fillColor: "#fff", fillOpacity: 0.4})
      .bindTooltip("Suggested correction", {permanent: true, direction: "top"}).addTo(map);
    bounds.push(data.suggested);
  }
  if (bounds.length) {
    map.fitBounds(L.latLngBounds(bounds).pad(0.6), {maxZoom: 16});
  } else {
    map.fitBounds(outline.getBounds());
    const note = L.control({position: "topright"});
    note.onAdd = () => {
      const div = L.DomUtil.create("div", "sg-map-note");
      div.textContent = "No usable location on the form. Rosario boundary shown.";
      return div;
    };
    note.addTo(map);
  }
})();
