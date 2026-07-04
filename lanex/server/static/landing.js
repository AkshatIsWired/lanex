/* landing.js — time-driven engine for the LanEx home screen ("The Build" v2).
 * ------------------------------------------------------------------
 * A ~48 s looping timeline plays the full chip journey on its own —
 * no scrolling required:
 *
 *   act 0 SYN    0.0– 5.0  RTL code plane + green netlist draws in mid-air
 *   act 1 FP     5.0–10.0  substrate rises, I/O ring + core outline appear
 *   act 2 PLC   10.0–16.0  cell rows drop in and fill; rats-nest descends
 *                          and fades as placement legalizes
 *   act 3 CTS   16.0–20.5  H-tree strokes itself in
 *   act 4 RTE   20.5–26.0  four metal plates land, alternating directions
 *   act 5 GDS   26.0–30.0  passivation + KLayout-purple wash, camera tips
 *                          to a top-down layout view, purple flash
 *   act 6 LITHO 30.0–35.0  mask reticle overhead, UV beam sweeps, exposure
 *                          flash
 *   act 7 DICE  35.0–42.0  crossfade to a wafer; laser scribes a 4×4 grid,
 *                          tiles separate, camera dives into the centre die,
 *                          crossfade back to the assembled die
 *   act 8 PKG   42.0–48.0  substrate with gold pins slides under, lid with
 *                          the mark descends, beauty beat, smooth loop reset
 *
 * Scrolling never drives the die — it only dims the stage and reveals the
 * content sections. The bottom glass tracker mirrors the acts; its chips
 * jump the timeline. `?p=<seconds>` pins the timeline for QA screenshots;
 * `?stay` shows the page even when "skip this screen" is set (that logic
 * lives inline in landing.html so it runs before paint).
 *
 * Classic script, zero dependencies. prefers-reduced-motion = one static
 * finished frame (chips still step the scene by hand).
 */
(function () {
  "use strict";

  var d = document;
  var REDUCED = false;
  try { REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e) {}

  /* ---------- helpers ---------- */
  function clamp01(x) { return x < 0 ? 0 : x > 1 ? 1 : x; }
  function ss(a, b, x) {            // smoothstep
    var t = clamp01((x - a) / (b - a));
    return t * t * (3 - 2 * t);
  }
  function win(x, a, b, ri, ro) {   // rise over [a,a+ri], fall over [b-ro,b]
    return ss(a, a + ri, x) * (1 - ss(b - ro, b, x));
  }
  function bell(x, c, w) {          // cosine bump centred on c, half-width w
    var t = Math.abs(x - c);
    return t >= w ? 0 : 0.5 * (1 + Math.cos(Math.PI * t / w));
  }
  function lerp(a, b, t) { return a + (b - a) * t; }

  /* ---------- theme (shared `ll.theme` key with the cockpit) ---------- */
  var themeBtn = d.getElementById("theme-btn");
  if (themeBtn) themeBtn.addEventListener("click", function () {
    var dark = d.body.classList.contains("theme-dark");
    d.body.classList.toggle("theme-dark", !dark);
    d.body.classList.toggle("theme-light", dark);
    try { localStorage.setItem("ll.theme", dark ? "light" : "dark"); } catch (e) {}
  });

  /* ---------- "skip this screen next time" (home-screen contract) ---------- */
  var skipBox = d.getElementById("skip-next");
  if (skipBox) {
    try { skipBox.checked = localStorage.getItem("ll.landing") === "skip"; } catch (e) {}
    skipBox.addEventListener("change", function () {
      try {
        if (this.checked) localStorage.setItem("ll.landing", "skip");
        else localStorage.removeItem("ll.landing");
      } catch (e) {}
    });
  }

  /* ---------- smooth handoff into the cockpit ---------- */
  var launchers = d.querySelectorAll("[data-launch]");
  for (var li = 0; li < launchers.length; li++) {
    launchers[li].addEventListener("click", function (ev) {
      var href = this.getAttribute("href");
      if (!href || REDUCED) return;               // plain navigation
      ev.preventDefault();
      d.body.classList.add("leaving");
      setTimeout(function () { window.location.href = href; }, 330);
    });
  }

  /* ---------- copy-to-clipboard on install cards ---------- */
  var copies = d.querySelectorAll(".copy-btn");
  for (var ci = 0; ci < copies.length; ci++) {
    copies[ci].addEventListener("click", function () {
      var btn = this, text = btn.getAttribute("data-copy") || "";
      function ok() {
        btn.classList.add("ok"); btn.textContent = "Copied";
        setTimeout(function () { btn.classList.remove("ok"); btn.textContent = "Copy"; }, 1400);
      }
      function fallback() {
        var ta = d.createElement("textarea");
        ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
        d.body.appendChild(ta); ta.select();
        try { d.execCommand("copy"); ok(); } catch (e) {}
        d.body.removeChild(ta);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(ok, function () { fallback(); });
      } else { fallback(); }
    });
  }

  /* ---------- reveal-on-scroll (content sections only) ---------- */
  var reveals = d.querySelectorAll(".reveal");
  if (REDUCED || !("IntersectionObserver" in window)) {
    for (var ri = 0; ri < reveals.length; ri++) reveals[ri].classList.add("in");
  } else {
    var io = new IntersectionObserver(function (entries) {
      for (var i = 0; i < entries.length; i++) {
        if (entries[i].isIntersecting) {
          entries[i].target.classList.add("in");
          io.unobserve(entries[i].target);
        }
      }
    }, { threshold: 0.12, rootMargin: "0px 0px -8% 0px" });
    for (var rj = 0; rj < reveals.length; rj++) io.observe(reveals[rj]);
    // Belt-and-braces: anything already in view reveals immediately, so the
    // above-the-fold copy can never sit invisible waiting on observer timing.
    window.requestAnimationFrame(function () {
      var vh = window.innerHeight;
      for (var k = 0; k < reveals.length; k++) {
        var r = reveals[k].getBoundingClientRect();
        if (r.top < vh * 0.95 && r.bottom > 0) {
          reveals[k].classList.add("in");
          io.unobserve(reveals[k]);
        }
      }
    });
  }

  /* ---------- smooth in-page navigation (clicks only; deep links jump) ---------- */
  var anchors = d.querySelectorAll('a[href^="#"]');
  for (var ai = 0; ai < anchors.length; ai++) {
    anchors[ai].addEventListener("click", function (ev) {
      var target = d.getElementById((this.getAttribute("href") || "").slice(1));
      if (!target) return;
      ev.preventDefault();
      target.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "start" });
    });
  }

  /* ================================================================
     The timeline engine
     ================================================================ */
  var TOTAL = 48;
  var TAU = Math.PI * 2;
  var ACTS = [
    { t0: 0.0,  cap: "Yosys maps the RTL onto standard cells — logic becomes a netlist." },
    { t0: 5.0,  cap: "OpenROAD shapes the die — core area, I/O ring, power plan." },
    { t0: 10.0, cap: "Cells settle into rows — the green rats-nest pulls them together." },
    { t0: 16.0, cap: "A balanced clock tree grows so every flop hears the same tick." },
    { t0: 20.5, cap: "Metal, layer by layer — signals weave through the routing stack." },
    { t0: 26.0, cap: "Tape-out — the layout streams out as GDSII. LanEx hands off here." },
    { t0: 30.0, cap: "At the fab: UV light prints each mask layer onto the wafer." },
    { t0: 35.0, cap: "At the fab: a laser scribes the wafer and the dies separate." },
    { t0: 42.0, cap: "At the fab: die bonded, lid sealed — your design is a chip." }
  ];

  var stage = d.getElementById("stage");
  var die = d.getElementById("die");
  var rig = d.getElementById("rig");
  if (!stage || !die || !rig) return;

  var q = function (sel) { return stage.querySelector(sel); };

  /* plates: rise window [a,b], entry z, resting z (scaled by pkg compression) */
  var plates = [
    { el: q('[data-plate="sub"]'),   z: 0,   from: -140, a: 5.0,  b: 6.4  },
    { el: q('[data-plate="dev"]'),   z: 18,  from: 190,  a: 10.3, b: 11.7 },
    { el: q('[data-plate="htree"]'), z: 42,  from: 110,  a: 16.0, b: 16.9 },
    { el: q('[data-plate="m1"]'),    z: 66,  from: 210,  a: 20.5, b: 21.8 },
    { el: q('[data-plate="m2"]'),    z: 90,  from: 230,  a: 21.7, b: 23.0 },
    { el: q('[data-plate="m3"]'),    z: 114, from: 250,  a: 22.9, b: 24.2 },
    { el: q('[data-plate="mt"]'),    z: 138, from: 270,  a: 24.1, b: 25.5 },
    { el: q('[data-plate="pass"]'),  z: 162, from: 300,  a: 26.0, b: 27.0 }
  ];
  var subPlate = plates[0].el;
  var devRows = die.querySelector(".dev-rows");
  var nestPlate = q('[data-plate="nest"]');
  var gdsPlate = q('[data-plate="gds"]');
  var sheen = q('[data-part="sheen"]');
  var shadow = q('[data-part="shadow"]');
  var codePlane = q('[data-part="code"]');
  var maskPlane = q('[data-part="mask"]');
  var uvBeam = q('[data-part="uv"]');
  var uvPrint = q('[data-part="uvprint"]');
  var wafer = q('[data-part="wafer"]');
  var pkgSub = q('[data-part="pkgsub"]');
  var pkgLid = q('[data-part="pkglid"]');
  var dip = q('[data-part="dip"]');
  var fGds = q('[data-part="fgds"]');
  var fUv = q('[data-part="fuv"]');
  var htreePath = d.getElementById("htree-path");

  var htreeLen = 0;
  if (htreePath && htreePath.getTotalLength) {
    try {
      htreeLen = htreePath.getTotalLength();
      htreePath.style.strokeDasharray = htreeLen + " " + htreeLen;
      htreePath.style.strokeDashoffset = String(htreeLen);
    } catch (e) { htreeLen = 0; }
  }

  /* ---- rats-nest netlist: deterministic green flightlines (seeded LCG) ---- */
  var nestGroups = [];
  (function buildNest() {
    var svg = d.getElementById("nest-svg");
    if (!svg) return;
    var seed = 0x1a2ec4 >>> 0;
    function rnd() { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; }
    var NS = "http://www.w3.org/2000/svg";
    var pts = [], i;
    for (i = 0; i < 24; i++) pts.push([8 + 84 * rnd(), 8 + 84 * rnd()]);
    for (var g = 0; g < 3; g++) {
      var grp = d.createElementNS(NS, "g");
      grp.style.opacity = "0";
      for (var l = 0; l < 10; l++) {
        var pa = pts[(rnd() * pts.length) | 0];
        var pb = pts[(rnd() * pts.length) | 0];
        if (pa === pb) continue;
        var ln = d.createElementNS(NS, "line");
        ln.setAttribute("x1", pa[0].toFixed(1)); ln.setAttribute("y1", pa[1].toFixed(1));
        ln.setAttribute("x2", pb[0].toFixed(1)); ln.setAttribute("y2", pb[1].toFixed(1));
        grp.appendChild(ln);
      }
      svg.appendChild(grp);
      nestGroups.push(grp);
    }
    var dots = d.createElementNS(NS, "g");
    for (i = 0; i < pts.length; i++) {
      var c = d.createElementNS(NS, "circle");
      c.setAttribute("cx", pts[i][0].toFixed(1));
      c.setAttribute("cy", pts[i][1].toFixed(1));
      c.setAttribute("r", "1");
      dots.appendChild(c);
    }
    svg.appendChild(dots);
  })();

  /* ---- wafer: 4×4 tile grid + 3+3 scribe lines + laser dot ---- */
  var GRID = 300, TILE = 75;
  var tiles = [], scribes = [], laser = null;
  (function buildWafer() {
    var grid = d.getElementById("wafer-grid");
    if (!grid) return;
    for (var r = 0; r < 4; r++) {
      for (var c = 0; c < 4; c++) {
        var tl = d.createElement("div");
        tl.className = "wtile" + (r === 1 && c === 1 ? " hero-tile" : "");
        tl.style.left = (c * TILE) + "px";
        tl.style.top = (r * TILE) + "px";
        grid.appendChild(tl);
        tiles.push({ el: tl, r: r, c: c });
      }
    }
    for (var k = 0; k < 3; k++) {
      var v = d.createElement("div");
      v.className = "scribe v";
      v.style.left = ((k + 1) * TILE) + "px";
      grid.appendChild(v);
      var h = d.createElement("div");
      h.className = "scribe h";
      h.style.top = ((k + 1) * TILE) + "px";
      grid.appendChild(h);
      scribes.push(v, h);      // order fixed below: cuts run v0,v1,v2,h0,h1,h2
    }
    scribes = [scribes[0], scribes[2], scribes[4], scribes[1], scribes[3], scribes[5]];
    laser = d.createElement("div");
    laser.className = "laser";
    grid.appendChild(laser);
  })();

  /* laser cut schedule: 3 vertical then 3 horizontal scribes */
  var CUTS = [36.3, 37.0, 37.7, 38.4, 39.1, 39.8];
  var CUT_DUR = 0.62;

  /* ---- one frame of the story at timeline second t ---- */
  function renderScene(t) {
    /* die visibility (crossfade with the wafer during dicing) */
    var hid = ss(35.0, 36.0, t) * (1 - ss(41.15, 41.9, t));
    var dieVis = 1 - hid;
    /* packaging compression: the stack squashes into one slab */
    var zf = 1 - 0.55 * ss(42.2, 43.6, t);

    /* camera */
    var gv = win(t, 26.9, 30.2, 1.1, 1.0);      // top-down layout view (GDS)
    var rotX = 60 - 18 * bell(t, 8.0, 1.9) - 44 * gv;
    var rotZ = lerp(-33 + 9 * Math.sin(TAU * t / TOTAL), -6, gv);
    var camScale = 0.97 + 0.06 * ss(44.6, 46.4, t);   // beauty beat
    rig.style.transform =
      "rotateX(" + rotX.toFixed(2) + "deg) rotateZ(" + rotZ.toFixed(2) + "deg) scale(" + camScale.toFixed(3) + ")";

    /* loop-reset dim (element overlay — opacity on the 3D tree would flatten it) */
    if (dip) dip.style.opacity = (1 - ss(0.0, 0.85, t) * (1 - ss(47.15, 47.9, t))).toFixed(3);

    /* act flashes */
    if (fGds) fGds.style.opacity = (0.45 * bell(t, 27.5, 0.4)).toFixed(3);
    if (fUv) fUv.style.opacity = (0.55 * bell(t, 33.85, 0.32)).toFixed(3);

    /* plates: rise from entry z, then rest (× compression) */
    var subT = 0;
    for (var p = 0; p < plates.length; p++) {
      var pl = plates[p];
      if (!pl.el) continue;
      var riseT = ss(pl.a, pl.b, t);
      if (pl.el === subPlate) subT = riseT;
      pl.el.style.transform = "translate3d(0,0," + lerp(pl.from, pl.z * zf, riseT).toFixed(1) + "px)";
      pl.el.style.opacity = (riseT * dieVis).toFixed(3);
    }
    if (subPlate) {
      subPlate.style.setProperty("--io", ss(6.2, 7.4, t).toFixed(3));
      subPlate.style.setProperty("--core", ss(7.2, 8.6, t).toFixed(3));
    }
    if (devRows) devRows.style.setProperty("--fill", ss(11.4, 15.3, t).toFixed(3));

    /* rats-nest: draws in mid-air (SYN), hovers (FP), descends + fades as
       the rows legalize (PLC) */
    if (nestPlate) {
      var nestOp = ss(1.0, 1.9, t) * (1 - ss(13.2, 15.7, t));
      var nestZ = lerp(150, 26, ss(10.2, 12.2, t));
      nestPlate.style.transform = "translate3d(0,0," + nestZ.toFixed(1) + "px)";
      nestPlate.style.opacity = (nestOp * dieVis).toFixed(3);
      for (var g = 0; g < nestGroups.length; g++) {
        nestGroups[g].style.opacity = ss(1.1 + 0.8 * g, 2.4 + 0.8 * g, t).toFixed(3);
      }
    }

    /* clock H-tree draw-in */
    if (htreePath && htreeLen) {
      htreePath.style.strokeDashoffset = String((htreeLen * (1 - ss(16.3, 19.9, t))).toFixed(1));
    }

    /* tape-out purple wash */
    if (gdsPlate) {
      gdsPlate.style.transform = "translate3d(0,0," + (170 * zf).toFixed(1) + "px)";
      gdsPlate.style.opacity = (0.9 * win(t, 26.5, 30.3, 0.8, 0.9) * dieVis).toFixed(3);
    }

    /* lithography: mask overhead, UV beam sweep, printed stripe on the die */
    if (maskPlane) {
      var mT = ss(30.2, 31.0, t);
      maskPlane.style.transform = "translate3d(0,0," + lerp(330, 235, mT).toFixed(1) + "px)";
      maskPlane.style.opacity = (0.95 * win(t, 30.2, 34.7, 0.7, 0.7)).toFixed(3);
    }
    var beamOp = win(t, 30.7, 33.8, 0.4, 0.35);
    var beamX = lerp(-180, 180, ss(31.0, 33.5, t));
    if (uvBeam) {
      uvBeam.style.transform = "translate3d(" + beamX.toFixed(1) + "px,0,242px)";
      uvBeam.style.opacity = beamOp.toFixed(3);
    }
    if (uvPrint) {
      uvPrint.style.transform = "translate3d(" + beamX.toFixed(1) + "px,0,172px)";
      uvPrint.style.opacity = (0.55 * beamOp).toFixed(3);
    }

    /* dicing: wafer crossfade, laser scribes, separation, dive into a die */
    if (wafer) {
      var sep = ss(40.1, 40.9, t);
      var zm = ss(40.7, 41.75, t);
      var wScale = 1 + 2.1 * zm;
      /* zoom about the hero tile (row 1, col 1) so the camera dives into it */
      var heroOff = -(TILE / 2) - 6.5 * sep;      // tile centre offset from grid centre
      var wTx = -heroOff * (wScale - 1);
      wafer.style.transform =
        "translate3d(" + wTx.toFixed(1) + "px," + wTx.toFixed(1) + "px," +
        lerp(-80, 0, ss(35.0, 36.0, t)).toFixed(1) + "px) scale(" + wScale.toFixed(3) + ")";
      wafer.style.opacity = hid.toFixed(3);
      wafer.style.setProperty("--hero-glow", zm.toFixed(3));

      for (var w = 0; w < tiles.length; w++) {
        var tile = tiles[w];
        var dx = (tile.c - 1.5) * 13 * sep;
        var dy = (tile.r - 1.5) * 13 * sep;
        var hero = tile.r === 1 && tile.c === 1;
        tile.el.style.transform =
          "translate3d(" + dx.toFixed(1) + "px," + dy.toFixed(1) + "px," + (hero ? (8 * zm).toFixed(1) : "0") + "px)";
        tile.el.style.opacity = hero ? "1" : (1 - 0.55 * zm).toFixed(3);
      }
      for (var s = 0; s < scribes.length; s++) {
        scribes[s].style.setProperty("--cut", ss(CUTS[s], CUTS[s] + CUT_DUR, t).toFixed(3));
      }
      if (laser) {
        var lOp = win(t, 36.25, 40.45, 0.15, 0.25);
        if (lOp > 0.001) {
          var seg = 0;
          for (var cI = CUTS.length - 1; cI >= 0; cI--) { if (t >= CUTS[cI]) { seg = cI; break; } }
          var prog = clamp01((t - CUTS[seg]) / CUT_DUR);
          var lx, ly;
          if (seg < 3) { lx = (seg + 1) * TILE; ly = GRID * prog; }
          else { ly = (seg - 2) * TILE; lx = GRID * prog; }
          laser.style.transform = "translate3d(" + lx.toFixed(1) + "px," + ly.toFixed(1) + "px,3px)";
          laser.style.opacity = (lOp * (0.75 + 0.25 * Math.sin(t * 38))).toFixed(3);
        } else {
          laser.style.opacity = "0";
        }
      }
    }

    /* packaging: pin substrate under, lid down, sheen, done */
    if (pkgSub) {
      var pT = ss(42.0, 43.3, t);
      pkgSub.style.transform = "translate3d(0,0," + lerp(-260, -26, pT).toFixed(1) + "px)";
      pkgSub.style.opacity = pT.toFixed(3);
    }
    if (pkgLid) {
      var lT = ss(43.6, 45.0, t);
      pkgLid.style.transform = "translate3d(0,0," + lerp(430, 77, lT).toFixed(1) + "px)";
      pkgLid.style.opacity = ss(43.5, 43.9, t).toFixed(3);
    }
    if (sheen) {
      var shOp = win(t, 45.2, 46.7, 0.5, 0.6);
      sheen.style.opacity = shOp.toFixed(3);
      sheen.style.transform = "translateZ(" + (t >= 43.6 ? 90 : (166 * zf)).toFixed(1) + "px)";
      sheen.style.animationPlayState = shOp > 0.01 ? "running" : "paused";
    }
    if (shadow) {
      shadow.style.transform = "translateZ(-30px)";
      shadow.style.opacity = (0.55 * subT * dieVis).toFixed(3);
    }

    /* floating RTL code plane (synthesis) */
    if (codePlane) {
      var cOp = win(t, 0.35, 6.2, 0.9, 1.2);
      codePlane.style.opacity = cOp.toFixed(3);
      codePlane.style.transform =
        "rotateY(-14deg) rotateX(4deg) translateY(" + ((1 - cOp) * 26).toFixed(1) + "px)";
    }
  }

  /* ---- tracker: chips, progress fill, honest caption ---- */
  var tracker = d.getElementById("tracker");
  var trkFill = d.getElementById("trk-fill");
  var trkCap = d.getElementById("trk-cap");
  var trkChips = tracker ? tracker.querySelectorAll(".trk-chip") : [];
  var lastAct = -1;

  var trkPct = d.getElementById("trk-pct");
  var lastPct = -1;

  function renderTracker(t) {
    if (trkFill) trkFill.style.transform = "scaleX(" + (t / TOTAL).toFixed(4) + ")";
    var pct = Math.round(t / TOTAL * 100);
    if (trkPct && pct !== lastPct) { lastPct = pct; trkPct.textContent = pct + "%"; }
    var act = 0;
    for (var i = ACTS.length - 1; i >= 0; i--) { if (t >= ACTS[i].t0) { act = i; break; } }
    if (act === lastAct) return;
    lastAct = act;
    for (var c = 0; c < trkChips.length; c++) {
      trkChips[c].classList.toggle("on", c === act);
      trkChips[c].classList.toggle("done", c < act);
    }
    if (trkCap) {
      trkCap.textContent = ACTS[act].cap;
      trkCap.classList.remove("swap");
      void trkCap.offsetWidth;                    // restart the fade animation
      trkCap.classList.add("swap");
    }
  }

  /* ---- clock: t loops over [0,TOTAL); chips jump it; hidden tabs pause it ---- */
  var epoch = (window.performance && performance.now) ? performance.now() : Date.now();
  var offset = 0;
  function nowMs() { return (window.performance && performance.now) ? performance.now() : Date.now(); }
  function currentT() {
    var t = ((nowMs() - epoch) / 1000 + offset) % TOTAL;
    return t < 0 ? t + TOTAL : t;
  }

  /* deterministic QA hook: ?p=<seconds> pins the timeline to one frame.
     NOTE: the loop deliberately does NOT stop for prefers-reduced-motion —
     the self-playing build IS this page (VMs and OS "no animations" settings
     force that media query on people who never chose it). The tracker's
     pause button is the motion control instead. */
  var pinned = null;
  var paused = false;
  var pm = window.location.search.match(/[?&]p=([0-9.]+)/);
  if (pm) {
    var pv = parseFloat(pm[1]);
    if (isFinite(pv)) pinned = Math.min(TOTAL - 0.01, Math.max(0, pv));
  }

  function jumpTo(sec) {
    if (pinned !== null) {                        // pinned QA frame: step frame by frame
      pinned = sec;
      renderScene(pinned);
      renderTracker(pinned);
      return;
    }
    offset = sec;
    epoch = nowMs();
    if (paused) {                                 // stay paused, show the new frame
      renderScene(sec);
      renderTracker(sec);
    }
  }
  for (var ch = 0; ch < trkChips.length; ch++) {
    trkChips[ch].addEventListener("click", function () {
      var idx = parseInt(this.getAttribute("data-act"), 10);
      if (idx >= 0 && idx < ACTS.length) jumpTo(ACTS[idx].t0 + 0.05);
    });
  }

  /* ---- scroll: dim the stage behind content, partial return at the finale ---- */
  var topnav = d.getElementById("topnav");
  var cockpitSec = d.getElementById("cockpit");
  var finaleSec = d.getElementById("launch");
  var stageOp = 1;

  function renderScroll() {
    var vh = window.innerHeight;
    if (topnav) topnav.classList.toggle("scrolled", (window.scrollY || 0) > 30);
    var fade = 0, back = 0;
    if (cockpitSec) {
      var cr = cockpitSec.getBoundingClientRect();
      fade = clamp01((vh * 0.8 - cr.top) / (vh * 0.55));
    }
    if (finaleSec) {
      var fr = finaleSec.getBoundingClientRect();
      back = clamp01((vh * 0.85 - fr.top) / (vh * 0.6));
    }
    stageOp = Math.max(1 - 0.92 * fade, 0.5 * back);
    stage.style.opacity = stageOp.toFixed(3);
    /* the tracker leaves for good once the content starts (the stage's partial
       return behind the finale must NOT bring it back over the footer links) */
    if (tracker) tracker.classList.toggle("hide", fade > 0.5);
  }
  var scrollQueued = false;
  function onScroll() {
    if (scrollQueued) return;
    scrollQueued = true;
    window.requestAnimationFrame(function () { scrollQueued = false; renderScroll(); });
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll);

  /* ---- main loop ---- */
  var rafId = 0;
  function frame() {
    var t = currentT();
    if (stageOp > 0.03) {                         // skip scene writes while fully dimmed
      renderScene(t);
      renderTracker(t);
    }
    rafId = window.requestAnimationFrame(frame);
  }

  /* pause/play (also promotes a pinned QA frame into a live loop) */
  var playBtn = d.getElementById("trk-play");
  function setPaused(p) {
    paused = p;
    if (tracker) tracker.classList.toggle("paused", p);
    if (playBtn) {
      playBtn.setAttribute("aria-label", p ? "Play animation" : "Pause animation");
      playBtn.title = p ? "Play" : "Pause";
    }
    window.cancelAnimationFrame(rafId);
    if (p) {
      offset = currentT();                        // freeze the story...
    } else {
      epoch = nowMs();                            // ...or resume exactly there
      rafId = window.requestAnimationFrame(frame);
    }
  }
  if (playBtn) playBtn.addEventListener("click", function () {
    if (pinned !== null) {                        // unpin and play from that frame
      offset = pinned;
      pinned = null;
      setPaused(false);
      return;
    }
    setPaused(!paused);
  });

  d.addEventListener("visibilitychange", function () {
    if (pinned !== null || paused) return;        // nothing is running
    if (d.hidden) {
      offset = currentT();
      window.cancelAnimationFrame(rafId);
    } else {
      epoch = nowMs();
      rafId = window.requestAnimationFrame(frame);
    }
  });

  renderScroll();
  if (pinned !== null) {
    renderScene(pinned);
    renderTracker(pinned);
  } else if (!d.hidden) {
    rafId = window.requestAnimationFrame(frame);
  }
})();
