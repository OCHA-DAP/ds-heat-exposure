/* Extreme heat and people in need — dashboard. Data: window.HEAT, window.HEAT_GEO (inlined). */
(function () {
  "use strict";
  var D = window.HEAT, GEO = window.HEAT_GEO;
  var M = D.meta;
  var LATEST = String(M.latest_complete_year);
  var RECENT = String(M.recent_period).replace("-", "–");

  var GROUPS = {
    hnrp_pin: "People in need in the HNRPs",
    gho_pin: "People in need in all GHO country plans",
    gho_countries: "Everyone in countries with a GHO plan",
    world: "Everyone, worldwide"
  };
  var GROUP_SHORT = { hnrp_pin: "people in need (HNRPs)", gho_pin: "people in need (GHO plans)",
    gho_countries: "people in GHO countries", world: "people worldwide" };
  var AGES = { total: "All ages", age65: "Aged 65 and over", under1: "Under 1 year old" };
  var AGE_SHORT = { total: "", age65: "aged 65+", under1: "under 1" };
  var METRICS = {
    wbgt32: { name: "Dangerous humid heat", noun: "days of dangerous humid heat",
      def: "Days when the wet-bulb globe temperature in the shade reaches 32 °C or more: heat and humidity at which heavy outdoor work and sport are unsafe even for people used to the heat. This stands in for the report's “deadly heat days” (Mora et al. 2017), which use a different threshold that has not been published in reusable form." },
    wbt31: { name: "Heat near the limit of human tolerance", noun: "days near the limit of human tolerance",
      def: "Days when the wet-bulb temperature reaches 31 °C or more. Laboratory studies (Vecellio et al. 2022) found that young, healthy adults at rest can no longer keep their body temperature steady at around this level. The report cites 35 °C as the theoretical limit; real-world limits are lower. Reanalysis grids smooth out local peaks, so these days are undercounted." },
    tx35: { name: "Very hot days (over 35 °C)", noun: "days over 35 °C",
      def: "Days with a maximum temperature above 35 °C." },
    tx40: { name: "Extremely hot days (over 40 °C)", noun: "days over 40 °C",
      def: "Days with a maximum temperature above 40 °C." },
    hw: { name: "Heatwave days", noun: "heatwave days",
      def: "Days in a heatwave: two or more days in a row when both the daytime high and the night-time low are hotter than 95% of days at that place in 1986–2005. This is the Lancet Countdown definition the report cites; it is relative to local climate, so it counts unusual heat everywhere, not only in hot places." },
    mat: { name: "Unprecedented average heat (29 °C)", noun: "a yearly average of 29 °C or more",
      def: "Places where the yearly average temperature is 29 °C or more. Until recently such conditions were found on less than 1% of land, mostly in the Sahara (Xu et al. 2020, cited in the report)." },
    wbgt30: { name: "Humid heat (WBGT 30 °C)", noun: "days of humid heat (WBGT 30 °C+)",
      def: "Days when the wet-bulb globe temperature in the shade reaches 30 °C or more: a lower threshold than the dangerous-humid-heat measure." },
    wbt29: { name: "Humid heat (wet-bulb 29 °C)", noun: "days with a wet-bulb temperature of 29 °C+",
      def: "Days when the wet-bulb temperature reaches 29 °C or more: a lower threshold than the tolerance-limit measure." }
  };
  var THRESHOLDS = [1, 10, 20, 30];
  var SCEN = [
    { key: "ref", label: "1995–2014", kind: "observed" },
    { key: "observed_mean", label: RECENT, kind: "observed" },
    { key: "gwl_1.5", label: "1.5 °C", kind: "projected" },
    { key: "gwl_2.0", label: "2 °C", kind: "projected" },
    { key: "gwl_3.0", label: "3 °C", kind: "projected" }
  ];
  var MAP_PERIODS = [
    { key: "latest", label: LATEST + " (observed)" },
    { key: "observed_mean", label: RECENT + " average (observed)" },
    { key: "ref", label: "1995–2014 average (observed)" },
    { key: "gwl_1.5", label: "At 1.5 °C of warming" },
    { key: "gwl_2.0", label: "At 2 °C of warming" },
    { key: "gwl_3.0", label: "At 3 °C of warming" }
  ];
  var RAMP = ["#fde3d4", "#f9c3a3", "#f39c6f", "#eb6834", "#c94f1f", "#9c3a14", "#6e2810"];
  var BINS = {
    tx35: [1, 10, 30, 60, 100, 150], tx40: [1, 5, 15, 30, 60, 100],
    wbgt32: [1, 3, 7, 15, 30, 60], wbt31: [1, 3, 7, 15, 30, 60],
    wbgt30: [1, 5, 15, 30, 60, 100], wbt29: [1, 5, 15, 30, 60, 100],
    hw: [1, 5, 10, 20, 30, 50], mat: [24, 26, 27, 28, 29, 30]
  };

  var state = { group: "hnrp_pin", age: "total", metric: "hw", thr: 10, period: "latest" };

  // ---------- helpers ----------
  function el(tag, attrs, text) {
    var e = document.createElement(tag);
    if (attrs) for (var k in attrs) { if (k === "class") e.className = attrs[k]; else e.setAttribute(k, attrs[k]); }
    if (text != null) e.textContent = text;
    return e;
  }
  function svgEl(tag, attrs) {
    var e = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }
  function fmtPeople(n) {
    if (n == null || isNaN(n)) return "–";
    var a = Math.abs(n);
    if (a >= 1e9) return (n / 1e9).toFixed(a >= 1e10 ? 1 : 2) + " billion";
    if (a >= 1e6) return (n / 1e6).toFixed(a >= 1e8 ? 0 : 1) + " million";
    if (a >= 1e3) return Math.round(n / 1e3).toLocaleString("en") + " thousand";
    return Math.round(n).toLocaleString("en");
  }
  function fmtAxis(n) {
    var a = Math.abs(n);
    if (a >= 1e9) return (n / 1e9).toFixed(1).replace(/\.0$/, "") + "bn";
    if (a >= 1e6) return (n / 1e6).toFixed(a >= 1e7 ? 0 : 1).replace(/\.0$/, "") + "M";
    if (a >= 1e3) return (n / 1e3).toFixed(0) + "k";
    return String(Math.round(n));
  }
  function pct(a, b) { return (a == null || !b) ? "–" : (100 * a / b < 1 && a > 0 ? "<1%" : Math.round(100 * a / b) + "%"); }
  function measureKey() { return state.metric === "mat" ? "people_mat29" : "people_ge" + state.thr; }
  function node(gkey, age) {
    var g = D.scen[gkey]; if (!g) return null; g = g[age || state.age]; if (!g) return null; return g[state.metric] || null;
  }
  function seriesNode(gkey) {
    var g = D.series[gkey]; return g && g[state.age] ? g[state.age][state.metric] : null;
  }
  function phrase(short) {
    var m = METRICS[state.metric];
    var who = (short ? GROUP_SHORT[state.group] : GROUPS[state.group]);
    var age = AGE_SHORT[state.age] ? " " + AGE_SHORT[state.age] : "";
    if (state.metric === "mat") return who + age + " living where the yearly average was 29 °C or more";
    return who + age + " with " + state.thr + "+ " + m.noun + " in the year";
  }

  // ---------- tooltip ----------
  var tip = document.getElementById("tip");
  function showTip(evt, value, label, extra) {
    tip.textContent = "";
    tip.appendChild(el("div", { class: "v" }, value));
    tip.appendChild(el("div", { class: "k" }, label));
    if (extra) extra.forEach(function (t) { tip.appendChild(el("div", { class: "k" }, t)); });
    tip.hidden = false;
    var x = evt.clientX + 14, y = evt.clientY + 14;
    var w = tip.offsetWidth, h = tip.offsetHeight;
    if (x + w > window.innerWidth - 8) x = evt.clientX - w - 14;
    if (y + h > window.innerHeight - 8) y = evt.clientY - h - 14;
    tip.style.left = x + "px"; tip.style.top = y + "px";
  }
  function hideTip() { tip.hidden = true; }

  // ---------- filters ----------
  function fillSelect(id, opts, value) {
    var s = document.getElementById(id); s.textContent = "";
    opts.forEach(function (o) { var op = el("option", { value: o[0] }, o[1]); if (String(o[0]) === String(value)) op.selected = true; s.appendChild(op); });
  }
  function initFilters() {
    fillSelect("f-group", Object.keys(GROUPS).map(function (k) { return [k, GROUPS[k]]; }), state.group);
    fillSelect("f-age", Object.keys(AGES).map(function (k) { return [k, AGES[k]]; }), state.age);
    fillSelect("f-metric", Object.keys(METRICS).map(function (k) { return [k, METRICS[k].name]; }), state.metric);
    fillSelect("f-thr", THRESHOLDS.map(function (t) { return [t, t + (t === 1 ? " day a year" : " days a year")]; }), state.thr);
    fillSelect("f-period", MAP_PERIODS.map(function (p) { return [p.key, p.label]; }), state.period);
    [["f-group", "group"], ["f-age", "age"], ["f-metric", "metric"], ["f-thr", "thr"], ["f-period", "period"]].forEach(function (p) {
      document.getElementById(p[0]).addEventListener("change", function (e) {
        state[p[1]] = p[1] === "thr" ? +e.target.value : e.target.value; render();
      });
    });
    document.querySelectorAll(".tbl-toggle").forEach(function (b) {
      b.addEventListener("click", function () {
        var t = document.getElementById(b.dataset.target + "-table");
        t.hidden = !t.hidden; b.textContent = t.hidden ? "Show as table" : "Hide table";
      });
    });
  }

  // ---------- KPI tiles ----------
  function kpi(label, value, note) {
    var d = el("div", { class: "kpi" });
    d.appendChild(el("p", { class: "label" }, label));
    d.appendChild(el("p", { class: "value" }, value));
    if (note) d.appendChild(el("p", { class: "note" }, note));
    return d;
  }
  function renderKpis() {
    var box = document.getElementById("kpis"); box.textContent = "";
    var n = node(state.group), mk = measureKey();
    var v = n && n[mk] ? n[mk] : {}, ppl = n && n.people ? n.people : {};
    if (state.metric === "mat") {
      // single years swing widely for this measure, so lead with the 10-year average
      var r = seriesRange(state.group, state.age, "mat", "people_mat29", RECENT);
      box.appendChild(kpi("On average, " + RECENT + ": " + phrase(true), fmtPeople(v.observed_mean),
        pct(v.observed_mean, ppl.observed_mean) + " of " + fmtPeople(ppl.observed_mean) +
        (r ? ". Single years ranged from " + fmtPeople(r[0]) + " to " + fmtPeople(r[1]) : "")));
      box.appendChild(kpi("On average, 1995–2014", fmtPeople(v.ref),
        "Today's people, in the earlier climate"));
    } else {
      box.appendChild(kpi("In " + LATEST + ": " + phrase(true), fmtPeople(v.latest),
        pct(v.latest, ppl.latest) + " of " + fmtPeople(ppl.latest)));
      box.appendChild(kpi("Average a year, " + RECENT, fmtPeople(v.observed_mean),
        "1995–2014 average: " + fmtPeople(v.ref)));
    }
    var d2 = (v["gwl_2.0"] != null && v.ref != null) ? v["gwl_2.0"] - v.ref : null;
    box.appendChild(kpi("At 2 °C of global warming (people held at today's numbers)", fmtPeople(v["gwl_2.0"]),
      (d2 != null ? (d2 >= 0 ? "+" : "−") + fmtPeople(Math.abs(d2)) + " compared with 1995–2014" : "")));
    var ip = M.ipcc_50yr_now, w = M.warming;
    box.appendChild(kpi("A heat extreme that used to happen once in 50 years now happens about",
      ip.median.toFixed(1) + " times in 50 years",
      "At " + w.p50.toFixed(2) + " °C of human-caused warming (" + w.year + "). The report quoted 4.8 times at about 1 °C and 13.9 at 2 °C (IPCC)."));
  }

  // ---------- time series ----------
  function renderSeries() {
    var mk = measureKey();
    var sn = seriesNode(state.group);
    var vals = sn && sn[mk] ? sn[mk] : [];
    var years = D.years;
    document.getElementById("ts-title").textContent = "Each year since " + years[0] + ": " + phrase(false);
    var lastY = String(years[years.length - 1]), lastMeta = M.years[lastY] || {};
    document.getElementById("ts-sub").textContent = "Observed (ERA5 reanalysis). People counted at today's population and plan figures, so the line shows the change in heat, not in population." +
      (!lastMeta.complete ? " " + lastY + " runs to " + lastMeta.last_date + " and is not yet complete (open marker)." : "");
    var box = document.getElementById("ts-chart"); box.textContent = "";
    var W = 1040, H = 300, m = { l: 56, r: 16, t: 14, b: 30 };
    var svg = svgEl("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": document.getElementById("ts-title").textContent });
    var ymax = Math.max.apply(null, vals.filter(function (x) { return x != null; }).concat([1]));
    var ticks = niceTicks(0, ymax, 5); ymax = ticks[ticks.length - 1];
    var x = function (i) { return m.l + (W - m.l - m.r) * (i / Math.max(1, years.length - 1)); };
    var y = function (v) { return H - m.b - (H - m.t - m.b) * (v / ymax); };
    ticks.forEach(function (t) {
      var g = svgEl("g", { class: "tick" });
      g.appendChild(svgEl("line", { x1: m.l, x2: W - m.r, y1: y(t), y2: y(t) }));
      var tx = svgEl("text", { x: m.l - 8, y: y(t) + 4, "text-anchor": "end" }); tx.textContent = fmtAxis(t); g.appendChild(tx);
      svg.appendChild(g);
    });
    svg.appendChild(svgEl("line", { class: "axis", x1: m.l, x2: W - m.r, y1: y(0), y2: y(0) }));
    years.forEach(function (yr, i) {
      if (yr % 5 === 0 || i === years.length - 1) {
        var tx = svgEl("text", { x: x(i), y: H - 8, "text-anchor": "middle" }); tx.textContent = yr; svg.appendChild(tx);
      }
    });
    var d = "", started = false;
    vals.forEach(function (v, i) {
      var complete = (M.years[String(years[i])] || {}).complete;
      if (v == null || !complete) return;
      d += (started ? "L" : "M") + x(i).toFixed(1) + "," + y(v).toFixed(1); started = true;
    });
    svg.appendChild(svgEl("path", { d: d, fill: "none", stroke: "var(--series)", "stroke-width": 2, "stroke-linejoin": "round" }));
    vals.forEach(function (v, i) {
      if (v == null) return;
      var complete = (M.years[String(years[i])] || {}).complete;
      if (!complete) svg.appendChild(svgEl("circle", { cx: x(i), cy: y(v), r: 4, fill: "#fff", stroke: "var(--series)", "stroke-width": 2 }));
    });
    // direct label at the last complete year
    var li = -1; vals.forEach(function (v, i) { if (v != null && (M.years[String(years[i])] || {}).complete) li = i; });
    if (li >= 0) {
      svg.appendChild(svgEl("circle", { cx: x(li), cy: y(vals[li]), r: 4, fill: "var(--series)", stroke: "#fff", "stroke-width": 2 }));
      var lab = svgEl("text", { class: "lbl", x: x(li) - 8, y: y(vals[li]) - 10, "text-anchor": "end" }); lab.textContent = fmtAxis(vals[li]); svg.appendChild(lab);
    }
    // crosshair
    var hair = svgEl("line", { x1: 0, x2: 0, y1: m.t, y2: H - m.b, stroke: "var(--axis)", "stroke-width": 1, visibility: "hidden" });
    svg.appendChild(hair);
    var hit = svgEl("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent" });
    hit.addEventListener("pointermove", function (evt) {
      var r = svg.getBoundingClientRect(), px = (evt.clientX - r.left) * W / r.width;
      var i = Math.round((px - m.l) / (W - m.l - m.r) * (years.length - 1)); i = Math.max(0, Math.min(years.length - 1, i));
      hair.setAttribute("x1", x(i)); hair.setAttribute("x2", x(i)); hair.setAttribute("visibility", "visible");
      var meta = M.years[String(years[i])] || {};
      showTip(evt, fmtPeople(vals[i]), String(years[i]) + (meta.complete ? "" : " (to " + meta.last_date + ")"));
    });
    hit.addEventListener("pointerleave", function () { hair.setAttribute("visibility", "hidden"); hideTip(); });
    svg.appendChild(hit);
    box.appendChild(svg);
    // table view
    var tb = document.getElementById("ts-table"); tb.textContent = "";
    var t = el("table", { class: "data" }), hr = el("tr");
    hr.appendChild(el("th", null, "Year")); hr.appendChild(el("th", { class: "num" }, "People"));
    t.appendChild(hr);
    years.forEach(function (yr, i) {
      var tr = el("tr"); tr.appendChild(el("td", null, String(yr) + ((M.years[String(yr)] || {}).complete ? "" : " (incomplete)")));
      tr.appendChild(el("td", { class: "num" }, vals[i] == null ? "–" : Math.round(vals[i]).toLocaleString("en"))); t.appendChild(tr);
    });
    tb.appendChild(t);
  }
  function niceTicks(lo, hi, n) {
    var span = hi - lo || 1, step = Math.pow(10, Math.floor(Math.log10(span / n)));
    var err = span / n / step; if (err >= 7.5) step *= 10; else if (err >= 3.5) step *= 5; else if (err >= 1.5) step *= 2;
    var out = []; for (var v = 0; v <= hi + step * 0.999; v += step) out.push(v); if (out.length < 2) out.push(step); return out;
  }

  // ---------- warming-level bars ----------
  function renderGwl() {
    var mk = measureKey(), n = node(state.group), v = n && n[mk] ? n[mk] : {};
    document.getElementById("gwl-title").textContent = "Now and at higher levels of global warming: " + phrase(true);
    document.getElementById("gwl-sub").textContent = "Average year. Observed periods from ERA5; warming levels from ERA5 1995–2014 shifted by the median change across CMIP6 climate models. People are held at today's numbers. Today's human-caused warming is about " + M.warming.p50.toFixed(1) + " °C.";
    var box = document.getElementById("gwl-chart"); box.textContent = "";
    var W = 1040, H = 280, m = { l: 56, r: 16, t: 26, b: 44 };
    var svg = svgEl("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": document.getElementById("gwl-title").textContent });
    var values = SCEN.map(function (s) { return v[s.key]; });
    var ymax = Math.max.apply(null, values.filter(function (a) { return a != null; }).concat([1]));
    var ticks = niceTicks(0, ymax, 4); ymax = ticks[ticks.length - 1];
    var y = function (a) { return H - m.b - (H - m.t - m.b) * (a / ymax); };
    ticks.forEach(function (t) {
      var g = svgEl("g", { class: "tick" });
      g.appendChild(svgEl("line", { x1: m.l, x2: W - m.r, y1: y(t), y2: y(t) }));
      var tx = svgEl("text", { x: m.l - 8, y: y(t) + 4, "text-anchor": "end" }); tx.textContent = fmtAxis(t); g.appendChild(tx);
      svg.appendChild(g);
    });
    var slot = (W - m.l - m.r) / SCEN.length, bw = Math.min(90, slot * 0.5);
    SCEN.forEach(function (s, i) {
      var a = values[i]; if (a == null) return;
      var cx = m.l + slot * (i + 0.5), top = y(a), h = Math.max(0, y(0) - top);
      var r = Math.min(4, h);
      var path = "M" + (cx - bw / 2) + "," + y(0) + "V" + (top + r) + "Q" + (cx - bw / 2) + "," + top + " " + (cx - bw / 2 + r) + "," + top +
        "H" + (cx + bw / 2 - r) + "Q" + (cx + bw / 2) + "," + top + " " + (cx + bw / 2) + "," + (top + r) + "V" + y(0) + "Z";
      var bar = svgEl("path", { d: path, fill: s.kind === "observed" ? "var(--series)" : "var(--series-soft)", tabindex: 0 });
      bar.addEventListener("pointermove", function (evt) { showTip(evt, fmtPeople(a), s.label + (s.kind === "observed" ? " (observed)" : " of global warming (projected)")); });
      bar.addEventListener("pointerleave", hideTip);
      svg.appendChild(bar);
      var lab = svgEl("text", { class: "lbl", x: cx, y: top - 6, "text-anchor": "middle" }); lab.textContent = fmtAxis(a); svg.appendChild(lab);
      var cat = svgEl("text", { x: cx, y: H - 24, "text-anchor": "middle" }); cat.textContent = s.label; svg.appendChild(cat);
      var kind = svgEl("text", { x: cx, y: H - 8, "text-anchor": "middle" }); kind.textContent = s.kind === "observed" ? "observed" : "warming level"; svg.appendChild(kind);
    });
    svg.appendChild(svgEl("line", { class: "axis", x1: m.l, x2: W - m.r, y1: y(0), y2: y(0) }));
    box.appendChild(svg);
    var tb = document.getElementById("gwl-table"); tb.textContent = "";
    var t = el("table", { class: "data" }), hr = el("tr");
    ["Period", "Kind", "People"].forEach(function (h, i) { hr.appendChild(el("th", i === 2 ? { class: "num" } : null, h)); });
    t.appendChild(hr);
    SCEN.forEach(function (s, i) {
      var tr = el("tr"); tr.appendChild(el("td", null, s.label)); tr.appendChild(el("td", null, s.kind));
      tr.appendChild(el("td", { class: "num" }, values[i] == null ? "–" : Math.round(values[i]).toLocaleString("en"))); t.appendChild(tr);
    });
    tb.appendChild(t);
  }

  // ---------- map ----------
  var map, layer;
  function colorFor(val) {
    if (val == null) return "#eeeeee";
    var b = BINS[state.metric], i = 0; while (i < b.length && val >= b[i]) i++; return RAMP[i];
  }
  function unitVal(f) { var v = f.properties.v[state.metric]; return v ? v[state.period] : null; }
  function renderMap() {
    var isMat = state.metric === "mat";
    document.getElementById("map-title").textContent = "Where people in need face it: " + (isMat ? "yearly average temperature" : METRICS[state.metric].noun + " a year");
    document.getElementById("map-sub").textContent = "Each area is an admin unit of a current GHO country plan, coloured by the " +
      (isMat ? "average temperature where its people live" : "average number of days for the people who live there") +
      ". Plans with only a national figure are shown as one area. Hover for details.";
    if (!map) {
      map = L.map("map", { preferCanvas: true, worldCopyJump: true, scrollWheelZoom: false });
      L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}", {
        attribution: "Tiles © Esri — Esri, HERE, Garmin, OpenStreetMap contributors", maxZoom: 10 }).addTo(map);
      layer = L.geoJSON(GEO, {
        style: styleFor,
        onEachFeature: function (f, l) {
          l.on("mousemove", function (e) {
            var p = f.properties, val = unitVal(f);
            showTip(e.originalEvent, val == null ? "no data" : (isMatNow() ? val.toFixed(1) + " °C" : val.toFixed(1) + " days a year"),
              p.name + " (" + p.iso3 + ")", ["People in need: " + fmtPeople(p.pin)]);
          });
          l.on("mouseout", hideTip);
        }
      }).addTo(map);
      map.fitBounds(layer.getBounds(), { padding: [10, 10] });
    } else {
      layer.setStyle(styleFor);
    }
    var lg = document.getElementById("map-legend"); lg.textContent = "";
    var b = BINS[state.metric], unit = isMat ? " °C" : " days";
    var labels = [];
    labels.push("under " + b[0] + unit);
    for (var i = 1; i < b.length; i++) labels.push(b[i - 1] + "–" + b[i] + unit);
    labels.push(b[b.length - 1] + unit + " or more");
    labels.forEach(function (t, i) {
      var s = el("span"); var sw = el("span", { class: "sw" }); sw.style.background = RAMP[i]; s.appendChild(sw); s.appendChild(document.createTextNode(t)); lg.appendChild(s);
    });
  }
  function isMatNow() { return state.metric === "mat"; }
  function styleFor(f) {
    return { fillColor: colorFor(unitVal(f)), fillOpacity: 0.85, color: "#ffffff", weight: 0.6 };
  }

  // ---------- country table ----------
  var sortKey = "pin", sortDir = -1;
  function renderCountries() {
    var mk = measureKey();
    var ageTxt = AGE_SHORT[state.age] ? " " + AGE_SHORT[state.age] : "";
    document.getElementById("ctry-title").textContent = "By country plan: share of people in need" + ageTxt +
      (state.metric === "mat" ? " living where the yearly average is 29 °C or more" : " with " + state.thr + "+ " + METRICS[state.metric].noun + " a year");
    document.getElementById("ctry-sub").textContent = "People in need are the plan's official national figure, spread over admin areas using the plan's own admin breakdown and, within each area, like the population. Click a column to sort.";
    var rows = D.countries.map(function (c) {
      var n = node("country_pin:" + c.iso3), v = n && n[mk] ? n[mk] : {}, ppl = n && n.people ? n.people.latest : null;
      var share = function (k) { return (v[k] != null && ppl) ? v[k] / ppl : null; };
      return { c: c, name: (c.short_name || c.iso3), pin: c.in_need, latest: share("latest"), recent: share("observed_mean"),
        g2: share("gwl_2.0"), g3: share("gwl_3.0") };
    });
    rows.sort(function (a, b) {
      var x = a[sortKey], y = b[sortKey];
      if (typeof x === "string") return sortDir * x.localeCompare(y);
      return sortDir * ((x == null ? -1 : x) - (y == null ? -1 : y));
    });
    var t = document.getElementById("ctry-table"); t.textContent = "";
    var cols = [["name", "Country", false], ["plan", "Plan", false], ["pin", "People in need", true], ["latest", LATEST, true],
      ["recent", RECENT + " average", true], ["g2", "At 2 °C", true], ["g3", "At 3 °C", true], ["src", "How people in need were placed", false]];
    var hr = el("tr");
    cols.forEach(function (c) {
      var sortable = ["name", "pin", "latest", "recent", "g2", "g3"].indexOf(c[0]) >= 0;
      var th = el("th", { class: (c[2] ? "num " : "") + (sortable ? "sortable" : "") }, c[1] + (sortKey === c[0] ? (sortDir < 0 ? " ↓" : " ↑") : ""));
      if (sortable) th.addEventListener("click", function () { if (sortKey === c[0]) sortDir = -sortDir; else { sortKey = c[0]; sortDir = c[0] === "name" ? 1 : -1; } renderCountries(); });
      hr.appendChild(th);
    });
    t.appendChild(hr);
    rows.forEach(function (r) {
      var tr = el("tr");
      tr.appendChild(el("td", null, r.name));
      tr.appendChild(el("td", { class: "muted" }, r.c.is_hnrp ? "HNRP" : (r.c.plan_type || "")));
      tr.appendChild(el("td", { class: "num" }, fmtPeople(r.pin)));
      ["latest", "recent", "g2", "g3"].forEach(function (k) {
        var td = el("td", { class: "num" }, r[k] == null ? "–" : (r[k] > 0 && r[k] < 0.01 ? "<1%" : Math.round(100 * r[k]) + "%"));
        if (r[k] != null) { var bar = el("span", { class: "bar-in-cell" }); bar.style.width = Math.round(40 * r[k]) + "px"; td.appendChild(bar); }
        tr.appendChild(td);
      });
      tr.appendChild(el("td", { class: "muted" }, placement(r.c)));
      t.appendChild(tr);
    });
  }
  function placement(c) {
    if (c.pin_source === "national") return "National figure only: spread over the whole country.";
    var lvl = c.pin_admin_level ? "admin " + c.pin_admin_level : "admin";
    var src = String(c.pin_source || "");
    var s = (src.indexOf("jiaf") === 0 ? "Plan's needs analysis" : "HDX humanitarian needs data") + ", " + lvl;
    if (src.indexOf("prev year") >= 0) s += " (" + c.pin_source_year + " shares, scaled to the " + c.year + " total)";
    if (c.matched_share != null && c.matched_share < 0.995) s += "; " + Math.round(100 * c.matched_share) + "% matched to boundaries, the rest pooled to larger areas";
    return s + ".";
  }

  // ---------- report comparison ----------
  function getScen(gkey, age, metric, measure, scen) {
    var g = D.scen[gkey]; if (!g || !g[age] || !g[age][metric] || !g[age][metric][measure]) return null;
    return g[age][metric][measure][scen];
  }
  function seriesMean(gkey, age, metric, measure, y0, y1) {
    var s = D.series[gkey]; if (!s || !s[age] || !s[age][metric] || !s[age][metric][measure]) return null;
    var arr = s[age][metric][measure], tot = 0, n = 0;
    D.years.forEach(function (y, i) { if (y >= y0 && y <= y1 && arr[i] != null) { tot += arr[i]; n++; } });
    return n ? tot / n : null;
  }
  function seriesRange(gkey, age, metric, measure, period) {
    var yy = String(period).split(/[-–]/).map(Number), lo = null, hi = null;
    for (var y = yy[0]; y <= yy[1]; y++) {
      var v = seriesAt(gkey, age, metric, measure, y);
      if (v != null) { lo = lo == null ? v : Math.min(lo, v); hi = hi == null ? v : Math.max(hi, v); }
    }
    return lo == null ? null : [lo, hi];
  }
  function seriesAt(gkey, age, metric, measure, year) {
    var s = D.series[gkey]; if (!s || !s[age] || !s[age][metric] || !s[age][metric][measure]) return null;
    var i = D.years.indexOf(+year); return i >= 0 ? s[age][metric][measure][i] : null;
  }
  function renderReport() {
    var t = document.getElementById("report-table"); t.textContent = "";
    var hr = el("tr"); ["Finding in the 2022 report", "Source the report cites", "Now (this page)"].forEach(function (h) { hr.appendChild(el("th", null, h)); }); t.appendChild(hr);
    var ip = M.ipcc_50yr_now, w = M.warming;
    // Lancet: extra heatwave person-days for 65+ and infants vs 1986-2005
    var extra = function (g) {
      var a = ["age65", "under1"].map(function (age) {
        var now = seriesAt(g, age, "hw", "person_days", LATEST), base = seriesMean(g, age, "hw", "person_days", 1986, 2005);
        return (now != null && base != null) ? now - base : null;
      });
      return (a[0] == null || a[1] == null) ? null : a[0] + a[1];
    };
    var shareMora = function (g) {
      var a = getScen(g, "total", "wbgt32", "people_ge20", "latest"), b = getScen(g, "total", "wbgt32", "people", "latest");
      return pct(a, b);
    };
    var mat = function (g, s) { return getScen(g, "total", "mat", "people_mat29", s); };
    var dosio = function (g) {
      var a = getScen(g, "total", "hw", "people_ge10", "gwl_2.0"), b = getScen(g, "total", "hw", "people_ge10", "gwl_1.5");
      return (a != null && b != null) ? a - b : null;
    };
    var rows = [
      ["A heat extreme that happened once in 50 years without climate change now happens 4.8 times as often; at 2 °C nearly 14 times.",
        "IPCC AR6 (2021)",
        "At " + w.p50.toFixed(2) + " °C of human-caused warming in " + w.year + ", about " + ip.median.toFixed(1) + " times (likely range " + ip.low.toFixed(1) + "–" + ip.high.toFixed(1) + "), read from the same IPCC figure."],
      ["Children under 1 and adults over 65 faced 3.7 billion more heatwave person-days in 2020 than the 1986–2005 average.",
        "Lancet Countdown 2021",
        LATEST + ": " + fmtPeople(extra("world")) + " more person-days worldwide than 1986–2005 (today's population held fixed, so this is the change in heat alone); for people in need in the GHO plans, " + fmtPeople(extra("gho_pin")) + "."],
      ["About 30% of the world's population is exposed to deadly heat on at least 20 days a year.",
        "Mora et al. 2017",
        LATEST + ": " + shareMora("world") + " of people worldwide and " + shareMora("hnrp_pin") + " of people in need in the HNRPs had 20+ days of dangerous humid heat (WBGT 32 °C). A stricter threshold than Mora's, so lower shares are expected."],
      ["Up to a third of the world's population could live with yearly average temperatures now found on 0.8% of land, mostly the Sahara.",
        "Xu et al. 2020",
        "Living where the yearly average is 29 °C or more: " + fmtPeople(mat("world", "observed_mean")) + " people worldwide on average in " + RECENT + " (single years vary widely), " + fmtPeople(mat("world", "gwl_2.0")) + " at 2 °C and " + fmtPeople(mat("world", "gwl_3.0")) + " at 3 °C. People in need in the HNRPs: " + fmtPeople(mat("hnrp_pin", "observed_mean")) + " on average in " + RECENT + ", " + fmtPeople(mat("hnrp_pin", "gwl_2.0")) + " at 2 °C. The count depends strongly on the exact threshold: half a degree either way roughly halves or doubles it."],
      ["Limiting warming to 1.5 °C rather than 2 °C would spare up to 420 million people frequent exposure to extreme heatwaves.",
        "Dosio et al. 2018",
        "People with 10+ heatwave days a year: " + fmtPeople(dosio("world")) + " more at 2 °C than at 1.5 °C worldwide; " + fmtPeople(dosio("hnrp_pin")) + " more among people in need in the HNRPs. Different heatwave index from Dosio's."]
    ];
    rows.forEach(function (r) {
      var tr = el("tr"); r.forEach(function (c, i) { tr.appendChild(el("td", i === 1 ? { class: "muted" } : null, c)); }); t.appendChild(tr);
    });
  }

  // ---------- methods ----------
  function renderMethods() {
    var box = document.getElementById("methods"); box.textContent = "";
    box.appendChild(el("h2", null, "How these numbers are made"));
    var paras = [
      ["Weather", "Daily maximum and minimum temperature and humidity from ERA5 (ECMWF, Copernicus Climate Change Service), 0.25° grid, 1986 to " + (M.years[String(D.years[D.years.length - 1])] || {}).last_date + ". Updated monthly, about a week behind real time. Wet-bulb temperature is calculated from the daily maximum temperature and the daily mean humidity and surface pressure; the wet-bulb globe temperature is the shade version (no sun or wind), as in the Copernicus heat-stress indicators."],
      ["Warming levels", "Each level (1.5, 2, 3 °C above 1850–1900) uses the 20 years when each CMIP6 climate model reaches it (IPCC AR6 Atlas, SSP5-8.5 runs). The median model change in each month’s temperature and humidity is added to ERA5’s observed days for 1995–2014, and the days are recounted. This keeps local detail from the weather data but leaves day-to-day variability as it was in 1995–2014, so the hottest extremes are probably understated. The model changes come from the Copernicus Interactive Climate Atlas. As a check, we compared the projected change in hot days with the climate models' own counts, corrected for model bias (ISIMIP, from the same Atlas): for days over 40 °C the two agree to within about 10%; for days over 35 °C ours come out 10–25% lower at 2 and 3 °C, so those projections are probably on the low side."],
      ["People", "Population: WorldPop 2026, 1 km, with age groups. People in need: the official national figure of each current GHO country plan (" + (D.countries[0] || {}).year + "), spread over admin areas using the plan's own breakdown (needs analysis workbooks or HDX humanitarian needs data), and within each area like the population. People in need by age use the population's age mix in each area. All counts are held at today's figures, so changes over time and between warming levels show the change in heat only."],
      ["Current warming", "Human-caused warming of " + M.warming.p50.toFixed(2) + " °C in " + M.warming.year + " (likely " + M.warming.p05 + "–" + M.warming.p95 + " °C), from the Indicators of Global Climate Change, updated yearly."],
      ["What is not here", "This page does not project how many people will be in need. It measures how much dangerous heat today's people in need face, now and with more warming. Reanalysis grids are about 25 km wide, so they miss the hottest spots inside cities and camps; real exposure is likely higher."]
    ];
    paras.forEach(function (p) { box.appendChild(el("h3", null, p[0])); box.appendChild(el("p", null, p[1])); });
  }

  function render() {
    document.getElementById("f-thr-wrap").hidden = state.metric === "mat";
    document.getElementById("metric-def").textContent = METRICS[state.metric].def;
    renderKpis(); renderSeries(); renderGwl(); renderMap(); renderCountries(); renderReport();
  }

  var lastY = String(D.years[D.years.length - 1]);
  document.getElementById("asof").textContent = "Weather data to " + (M.years[lastY] || {}).last_date +
    ". People in need: " + (D.countries[0] || {}).year + " GHO country plans. Warming: " + M.warming.p50.toFixed(2) + " °C (" + M.warming.year + ").";
  initFilters(); renderMethods(); render();
})();
