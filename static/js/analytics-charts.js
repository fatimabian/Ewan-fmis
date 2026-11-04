(() => {
  const ns = "http://www.w3.org/2000/svg";
  const palette = ["#2f7d5c", "#347ec0", "#d1843e", "#bd555b"];
  const fmt = value => Number(value).toLocaleString(undefined, {maximumFractionDigits: 2});
  const svgNode = (tag, attrs = {}, content) => {
    const node = document.createElementNS(ns, tag);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    if (content !== undefined) node.textContent = content;
    return node;
  };
  const initialize = () => document.querySelectorAll("[data-trend-chart]").forEach(chart => {
    if (chart.dataset.trendInitialized) return;
    chart.dataset.trendInitialized = "true";
    const source = JSON.parse(document.getElementById(chart.dataset.trendSource).textContent);
    const dual = source.first_polyline !== undefined;
    const datasets = source.statuses ? source.statuses.map(s => ({name:s.label, color:s.color})) :
      dual ? [{name:chart.dataset.firstLabel,color:palette[0]}, {name:chart.dataset.secondLabel,color:palette[1]}] : [{name:chart.dataset.firstLabel,color:palette[0]}];
    const number = value => Number.isFinite(Number(value)) ? Math.max(0, Number(value)) : 0;
    const points = (source.points || []).map(point => ({label:point.label, values: source.statuses ? point.statuses.map(s => number(s.value)) : dual ? [number(point.first),number(point.second)] : [number(point.value)]}));
    const view = chart.querySelector("[data-trend-view]");
    const windowSelect = chart.querySelector("[data-trend-window]");
    const plot = chart.querySelector("[data-trend-plot]");
    const reading = chart.querySelector("[data-trend-reading]");
    view.value = chart.dataset.defaultView;
    const legend = chart.querySelector("[data-trend-legend]");
    datasets.forEach(dataset => { const item = document.createElement("li"), color = document.createElement("i"); color.style.background = dataset.color; color.setAttribute("aria-hidden","true"); item.append(color, document.createTextNode(dataset.name)); legend.append(item); });
    function render() {
      const shown = windowSelect.value === "all" ? points : points.slice(-Number(windowSelect.value));
      plot.replaceChildren();
      reading.textContent = "Hover or focus a point to see its values.";
      const summary = chart.querySelector("[data-trend-summary]"); summary.replaceChildren();
      datasets.forEach((dataset,index) => { const item = document.createElement("div"), label = document.createElement("small"), total = document.createElement("b"); item.style.borderLeftColor = dataset.color; label.textContent = dataset.name + " · shown months"; total.textContent = fmt(shown.reduce((sum,point) => sum + point.values[index],0)); item.append(label,total); summary.append(item); });
      const insights = chart.querySelector("[data-trend-insights]"); insights.replaceChildren();
      if (shown.length) {
        const last = shown[shown.length-1], previous = shown[shown.length-2];
        const peakPoint = shown.reduce((best,point)=>point.values[0]>best.values[0]?point:best,shown[0]);
        const change = previous ? last.values[0]-previous.values[0] : null;
        const changeText = change === null ? "—" : `${change>0?"+":""}${fmt(change)}${previous.values[0] ? ` (${change>0?"+":""}${fmt(change/previous.values[0]*100)}%)` : " from zero"}`;
        [[`${datasets[0].name} · ${last.label}`,fmt(last.values[0])],[`Monthly change · ${datasets[0].name}`,changeText],[`Peak ${datasets[0].name} · ${peakPoint.label}`,fmt(peakPoint.values[0])]].forEach(([label,value])=>{const item=document.createElement("div"),small=document.createElement("small"),strong=document.createElement("b");small.textContent=label;strong.textContent=value;item.append(small,strong);insights.append(item);});
      }
      const period = chart.querySelector("[data-trend-period]");
      period.textContent = shown.length ? `${shown[0].label} – ${shown[shown.length-1].label} · ${chart.dataset.unit}` : "No records match the selected filters.";
      const table = document.createElement("table"); table.className = "analytics-type-table";
      const header = table.createTHead().insertRow(); ["Month",...datasets.map(s=>s.name)].forEach(label => { const cell = document.createElement("th"); cell.scope = "col"; cell.textContent=label; header.append(cell); });
      const tbody = table.createTBody(); shown.forEach(point => { const row=tbody.insertRow(); const month=document.createElement("th"); month.scope="row";month.textContent=point.label;row.append(month);point.values.forEach(value=>{row.insertCell().textContent=fmt(value);}); });
      chart.querySelector("[data-trend-table]").replaceChildren(table);
      if (!shown.length) return;
      const width = Math.max(660, shown.length * (datasets.length > 2 ? 145 : 85)), height = 325;
      const left=60, right=24, top=30, bottom=265, inner=width-left-right;
      const peak = Math.max(1,...shown.flatMap(point=>point.values));
      const rough = peak/4, power = 10**Math.floor(Math.log10(rough));
      const step = Math.max(chart.dataset.unit === "Hectares" ? 0 : 1, [1,2,2.5,5,10].map(n=>n*power).find(n=>n>=rough));
      const max = Math.ceil(peak/step)*step;
      const y = value => bottom - value/max*(bottom-top);
      const slot = inner/shown.length;
      const x = index => left + slot*(index+.5);
      const svg = svgNode("svg",{viewBox:`0 0 ${width} ${height}`,width,height,role:"img","aria-label":`${view.value === "line" ? "Line" : "Bar"} chart. ${period.textContent}`});
      svg.style.minWidth=`${width}px`;
      const title=svgNode("title",{},chart.getAttribute("aria-label"));svg.append(title);
      for (let tick=0; tick<=max+step*.01;tick+=step) {
        svg.append(svgNode("line",{x1:left,y1:y(tick),x2:width-right,y2:y(tick),class:"trend-grid"}));
        svg.append(svgNode("text",{x:left-10,y:y(tick)+4,"text-anchor":"end",class:"trend-axis"},fmt(tick)));
      }
      shown.forEach((point,index) => {
        const parts=point.label.match(/^([A-Za-z]+) (\d{4})$/);
        const text=svgNode("text",{x:x(index),y:bottom+24,"text-anchor":"middle",class:"trend-axis"},parts ? parts[1] : point.label);
        if (parts) text.append(svgNode("tspan",{x:x(index),dy:18,class:"trend-year"},parts[2]));svg.append(text);
      });
      const announce = (point,index) => { reading.textContent = `${point.label} · ${datasets.map((s,i)=>`${s.name}: ${fmt(point.values[i])}`).join(" · ")}`; svg.querySelectorAll(".trend-active").forEach(node=>node.classList.remove("trend-active")); svg.querySelectorAll(`[data-point="${index}"]`).forEach(node=>node.classList.add("trend-active")); };
      datasets.forEach((dataset,seriesIndex) => {
        if (view.value === "line") svg.append(svgNode("polyline",{points:shown.map((point,i)=>`${x(i)},${y(point.values[seriesIndex])}`).join(" "),fill:"none",stroke:dataset.color,"stroke-width":2.5,"vector-effect":"non-scaling-stroke","stroke-linejoin":"round"}));
        shown.forEach((point,index) => {
          const value=point.values[seriesIndex], label=`${point.label} · ${dataset.name}: ${fmt(value)}`;
          let mark;
          if (view.value === "line") mark=svgNode("circle",{cx:x(index),cy:y(value),r:4,fill:dataset.color,stroke:"var(--ui-surface,white)","stroke-width":1.5});
          else { const barWidth=Math.min(38,slot*.72/datasets.length); mark=svgNode("rect",{x:x(index)+(seriesIndex-datasets.length/2)*barWidth,y:y(value),width:Math.max(1,barWidth-3),height:Math.max(1,bottom-y(value)),fill:dataset.color});
            svg.append(svgNode("text",{x:x(index)+(seriesIndex-datasets.length/2+.5)*barWidth-1,y:y(value)-7,"text-anchor":"middle",class:"trend-value"},fmt(value)));
          }
          mark.setAttribute("tabindex","0");mark.setAttribute("role","img");mark.setAttribute("aria-label",label);mark.dataset.point=index;mark.classList.add("trend-mark");mark.append(svgNode("title",{},label));
          mark.addEventListener("mouseenter",()=>announce(point,index));mark.addEventListener("focus",()=>announce(point,index));svg.append(mark);
        });
      });
      plot.append(svg);
      chart.setAttribute("aria-label",`${chart.querySelector("h3").textContent} ${view.value} chart`);
    }
    view.addEventListener("change",render);windowSelect.addEventListener("change",render);render();
  });
  document.addEventListener("fmis:results-updated", initialize);
  initialize();
})();
