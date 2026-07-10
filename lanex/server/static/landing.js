(function () {
  'use strict';
  var d = document;
  var w = window;

  /* ------------------------------------------------------------------ */
  /*  Safe helpers                                                      */
  /* ------------------------------------------------------------------ */
  function $(id) { return d.getElementById(id); }
  function qq(s, p) { return Array.from((p || d).querySelectorAll(s)); }
  function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }
  var REDUCED = false;
  try { REDUCED = w.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) {}
  function setMetaTheme() {
    try {
      var m = d.querySelector('meta[name="theme-color"]');
      if (m) m.setAttribute('content', d.body.classList.contains('theme-light') ? '#f4f7fc' : '#05070d');
    } catch (e) {}
  }

  /* ------------------------------------------------------------------ */
  /*  Loader                                                             */
  /* ------------------------------------------------------------------ */
  try {
    var loader = $('loader');
    if (loader) {
      if (REDUCED) { loader.style.display = 'none'; }
      else {
        setTimeout(function () { loader.classList.add('hidden'); }, 350);
        w.addEventListener('load', function () { loader.classList.add('hidden'); });
      }
    }
  } catch (e) {}

  /* ------------------------------------------------------------------ */
  /*  Theme                                                              */
  /* ------------------------------------------------------------------ */
  try {
    var themeBtn = $('themeBtn');
    if (themeBtn) {
      try { if (localStorage.getItem('ll.theme') === 'light') { d.body.classList.remove('theme-dark'); d.body.classList.add('theme-light'); } } catch (e) {}
      setMetaTheme();
      themeBtn.addEventListener('click', function () {
        var dark = d.body.classList.contains('theme-dark');
        d.body.classList.toggle('theme-dark', !dark);
        d.body.classList.toggle('theme-light', dark);
        setMetaTheme();
        try { localStorage.setItem('ll.theme', dark ? 'light' : 'dark'); } catch (e) {}
      });
    }
  } catch (e) {}

  /* ------------------------------------------------------------------ */
  /*  Nav scroll                                                         */
  /* ------------------------------------------------------------------ */
  try {
    var topnav = $('topnav');
    var tick = false;
    w.addEventListener('scroll', function () {
      if (!tick) {
        w.requestAnimationFrame(function () { if (topnav) topnav.classList.toggle('scrolled', w.scrollY > 40); tick = false; });
        tick = true;
      }
    }, { passive: true });
    if (w.scrollY > 40 && topnav) topnav.classList.add('scrolled');
  } catch (e) {}

  /* ------------------------------------------------------------------ */
  /*  Mobile menu                                                        */
  /* ------------------------------------------------------------------ */
  try {
    var menuBtn = $('menuBtn');
    var navLinks = $('navLinks');
    if (menuBtn && navLinks) {
      menuBtn.setAttribute('aria-expanded', 'false');
      menuBtn.setAttribute('aria-controls', 'navLinks');
      menuBtn.setAttribute('aria-label', 'Toggle navigation menu');
      menuBtn.addEventListener('click', function () {
        var open = navLinks.classList.toggle('open');
        menuBtn.classList.toggle('open', open);
        menuBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
        // Lock body scroll when menu open on mobile
        document.body.style.overflow = open ? 'hidden' : '';
      });
      navLinks.querySelectorAll('a').forEach(function (a) {
        a.addEventListener('click', function () {
          navLinks.classList.remove('open');
          menuBtn.classList.remove('open');
          menuBtn.setAttribute('aria-expanded', 'false');
          document.body.style.overflow = '';
        });
      });
      // Close on Escape (touch keyboards, accessibility)
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && navLinks.classList.contains('open')) {
          navLinks.classList.remove('open');
          menuBtn.classList.remove('open');
          menuBtn.setAttribute('aria-expanded', 'false');
          document.body.style.overflow = '';
          menuBtn.focus();
        }
      });
    }
  } catch (e) {}

  /* ------------------------------------------------------------------ */
  /*  Reveal on scroll                                                   */
  /* ------------------------------------------------------------------ */
  try {
    var reveals = qq('.reveal');
    var reduced = REDUCED;
    if (reduced || !w.IntersectionObserver) {
      reveals.forEach(function (el) { el.classList.add('in'); });
    } else {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) { 
          if (e.isIntersecting) { 
            e.target.classList.add('in'); 
            io.unobserve(e.target); 
          } 
        });
      }, { threshold: 0.01, rootMargin: '0px 0px -10px 0px' });
      reveals.forEach(function (el) { io.observe(el); });
    }
  } catch (e) {}

  /* ------------------------------------------------------------------ */
  /*  Copy buttons                                                       */
  /* ------------------------------------------------------------------ */
  try {
    qq('.copy-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var text = btn.getAttribute('data-copy') || '';
        function ok() { btn.classList.add('ok'); btn.textContent = 'Copied!'; setTimeout(function () { btn.classList.remove('ok'); btn.textContent = 'Copy'; }, 1400); }
        function fb() {
          var ta = d.createElement('textarea');
          ta.value = text; ta.style.cssText = 'position:fixed;opacity:0';
          d.body.appendChild(ta); ta.select();
          try { d.execCommand('copy'); ok(); } catch (e) {}
          d.body.removeChild(ta);
        }
        if (navigator.clipboard && navigator.clipboard.writeText) { navigator.clipboard.writeText(text).then(ok, function () { fb(); }); } else { fb(); }
      });
    });
  } catch (e) {}

  /* ------------------------------------------------------------------ */
  /*  Pointer-tracking glow on cards (fine pointers only)                */
  /* ------------------------------------------------------------------ */
  try {
    if (!REDUCED && w.matchMedia && w.matchMedia('(hover: hover) and (pointer: fine)').matches) {
      qq('.feat-card, .install-card, .step, .fe-card-glass').forEach(function (card) {
        card.addEventListener('mousemove', function (e) {
          var r = card.getBoundingClientRect();
          if (r.width < 1 || r.height < 1) return;
          card.style.setProperty('--mx', ((e.clientX - r.left) / r.width * 100).toFixed(2) + '%');
          card.style.setProperty('--my', ((e.clientY - r.top) / r.height * 100).toFixed(2) + '%');
        });
      });
    }
  } catch (e) {}

  /* ================================================================ */
  /*  3D CHIP ANIMATION - canvas                                        */
  /* ================================================================ */
  try {
    (function () { // isolated: an early return here must not skip the sections below
    var scene = $('scene3d');
    var heroStage = $('heroStage');
    if (!scene) return;

    var cv = d.createElement('canvas');
    cv.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;display:block;z-index:1;pointer-events:auto;';

    // Transparent canvas — the CSS scene layers (grid, glows, dots, floating dies)
    // show through behind the chip animation instead of being painted over.
    var ctx = cv.getContext('2d');
    if (!ctx) return;

    function gv(n, f) { try { return getComputedStyle(d.body).getPropertyValue(n).trim() || f; } catch(e) { return f; } }

    var W, H, cx0, cy0, sc, DPR = 1;
    var isMobile = false;
    var isPortrait = false;
    function resize() {
      DPR = Math.min(w.devicePixelRatio || 1, 2);
      W = w.innerWidth;
      H = w.innerHeight;
      cv.width = Math.floor(W * DPR);
      cv.height = Math.floor(H * DPR);
      cv.style.width = W + 'px';
      cv.style.height = H + 'px';
      ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
      isMobile = W <= 600; // must match the CSS phone breakpoint (.hero-stage flows only ≤600px)
      isPortrait = H >= W;

      // --- Mobile: fit the FULL iso chip inside the visible canvas, not just center it.
      // The chip is 2*SZ wide in iso space but projects to ~2*SZ*cos(30°) ~ 1.732*SZ wide
      // on screen (because isoX = (x-y)*cos30). masterScale can hit 1.6 during litho.
      // We back-compute a `sc` that keeps the chip's max horizontal footprint inside W.
      if (isMobile) {
        var roomW = W * 0.88;
        var stageH = (heroStage && heroStage.clientHeight > 0) ? heroStage.clientHeight : 180;
        var roomH = stageH;
        var maxFootprintScale = 2.6;
        var scFromW = roomW / (360 * maxFootprintScale);
        var scFromH = roomH / (360 * maxFootprintScale * 0.62);
        // Multiply by 1.953125 (3 zoom button clicks of 1.25x)
        sc = Math.min(scFromW, scFromH, 0.55) * 1.953125;
        if (sc < 0.28) sc = 0.28;
        cx0 = 0.50 * W;
        cy0 = 0.76 * H;
      } else {
        cx0 = 0.60 * W;
        cy0 = 0.40 * H;
        // Multiply by 1.5625 (2 zoom button clicks of 1.25x)
        sc = Math.min(W / 1400, H / 900, 1.0) * 1.5625;
      }
      w._bgGrad = null;

      if (cv.parentNode !== scene) {
        scene.appendChild(cv);
      }
      scene.style.display = '';
      if (heroStage) {
        heroStage.style.display = isMobile ? 'block' : 'none';
      }
      // On mobile, allow the full zoom range now that we've set a closer default scale
      if (isMobile) {
        if (userZoom > 3.0) userZoom = 3.0;
        if (userZoom < 0.4) userZoom = 0.4;
      }
      // Re-render immediately if paused so canvas doesn't show stale frame
      if (paused && ctx) { try { render(performance.now() / 1000); } catch(e) {} }
    }
    resize();
    w.addEventListener('resize', resize);
    w.addEventListener('orientationchange', function() { setTimeout(resize, 250); });
    if (w.matchMedia) {
      try {
        w.matchMedia('(resolution: 1dppx)').addEventListener('change', resize);
      } catch (e) {}
    }

    // Safe Polyfill for roundRect
    if (!ctx.roundRect) {
      ctx.roundRect = function (x, y, w, h, r) {
        if (typeof r === 'number') { r = [r, r, r, r]; }
        else if (Array.isArray(r)) {
          if (r.length === 1) r = [r[0], r[0], r[0], r[0]];
          else if (r.length === 2) r = [r[0], r[1], r[0], r[1]];
          else if (r.length === 3) r = [r[0], r[1], r[2], r[1]];
        } else { r = [0, 0, 0, 0]; }
        this.moveTo(x + r[0], y);
        this.lineTo(x + w - r[1], y);
        this.quadraticCurveTo(x + w, y, x + w, y + r[1]);
        this.lineTo(x + w, y + h - r[2]);
        this.quadraticCurveTo(x + w, y + h, x + w - r[2], y + h);
        this.lineTo(x + r[3], y + h);
        this.quadraticCurveTo(x, y + h, x, y + h - r[3]);
        this.lineTo(x, y + r[0]);
        this.quadraticCurveTo(x, y, x + r[0], y);
      };
    }

    /* --- user controls state --- */
    var paused = false;
    var userZoom = 1.0;
    var scrubbing = false;
    var scrubValue = 0;
    var animOffset = 0; // time offset for pause/resume

    var ppBtn = $('animPlayPause');
    var progressBg = $('deckProgressBg');
    var progressFill = $('deckProgressFill');
    var timeLabel = $('animTime');
    var zInBtn = $('animZoomIn');
    var zOutBtn = $('animZoomOut');
    var stageBtns = qq('.deck-stage');
    var cursorEl = $('fakeCursor');

    if (ppBtn) ppBtn.addEventListener('click', function() {
      paused = !paused;
      var icPlay = d.getElementById('ic-play');
      var icPause = d.getElementById('ic-pause');
      if (icPlay && icPause) {
        icPlay.style.display = paused ? 'block' : 'none';
        icPause.style.display = paused ? 'none' : 'block';
      }
      if (paused) {
        running = false;
      } else {
        animOffset = scrubValue - performance.now() / 1000;
        running = true; lastRafTime = performance.now(); raf();
      }
    });
    if (zInBtn) zInBtn.addEventListener('click', function() {
      userZoom = Math.min(userZoom * 1.25, 3.0);
      if (paused) {
        try { render(performance.now() / 1000); } catch(e) {}
      }
    });
    if (zOutBtn) zOutBtn.addEventListener('click', function() {
      userZoom = Math.max(userZoom / 1.25, 0.4);
      if (paused) {
        try { render(performance.now() / 1000); } catch(e) {}
      }
    });
    if (progressBg) {
      function scrubFromEvt(e) {
        var rect = progressBg.getBoundingClientRect();
        var frac = rect.width > 0 ? clamp01((e.clientX - rect.left) / rect.width) : 0;
        scrubValue = frac * TOTAL;
        animOffset = scrubValue - performance.now() / 1000;
      }
      var downAt = 0;
      progressBg.addEventListener('pointerdown', function(e) {
        downAt = performance.now();
        if (progressBg.setPointerCapture && e.pointerId !== undefined) {
          try { progressBg.setPointerCapture(e.pointerId); } catch (err) {}
        }
        scrubFromEvt(e);
        render(performance.now() / 1000);
        e.preventDefault();
      });
      progressBg.addEventListener('pointermove', function(e) {
        if (e.buttons === 0) return;
        scrubFromEvt(e);
        render(performance.now() / 1000);
      });
      progressBg.addEventListener('pointerup', function() { downAt = 0; });
      progressBg.addEventListener('pointercancel', function() { downAt = 0; });
    }
    stageBtns.forEach(function(btn) {
      btn.addEventListener('click', function() {
        var tVal = parseFloat(btn.getAttribute('data-time'));
        scrubValue = tVal;
        animOffset = scrubValue - performance.now() / 1000;
        if (paused) {
          try { render(performance.now() / 1000); } catch(e) {}
        }
      });
    });

    // Scroll-wheel zoom (Ctrl/Cmd held; plain wheel scrolls the page).
    // The hero section overlays the fixed canvas, so bind there too or the
    // canvas handler never fires above the fold.
    function wheelZoom(e) {
      if (!(e.ctrlKey || e.metaKey)) return; // let the page scroll
      e.preventDefault();
      if (e.deltaY < 0) userZoom = Math.min(userZoom * 1.08, 3.0);
      else userZoom = Math.max(userZoom / 1.08, 0.4);
      if (paused) {
        try { render(performance.now() / 1000); } catch(err) {}
      }
    }
    cv.addEventListener('wheel', wheelZoom, { passive: false });
    var heroForZoom = $('hero');
    if (heroForZoom) heroForZoom.addEventListener('wheel', wheelZoom, { passive: false });

    /* --- mouse + touch parallax --- */
    var mx = 0, my = 0, tx = 0, ty = 0;
    w.addEventListener('mousemove', function(e) {
      if (isMobile) return; // mobile uses touch + deviceorientation below
      tx = (e.clientX / W - 0.5) * 2;
      ty = (e.clientY / H - 0.5) * 2;
    });
    // Touch parallax — mobile devices get parallax from finger position
    w.addEventListener('touchmove', function(e) {
      if (!isMobile) return;
      if (e.touches.length > 0) {
        tx = (e.touches[0].clientX / W - 0.5) * 2;
        ty = (e.touches[0].clientY / H - 0.5) * 2;
      }
    }, { passive: true });
    w.addEventListener('touchend', function() {
      // Slowly drift back to center when finger lifts
      tx *= 0.3; ty *= 0.3;
    });
    // Device orientation — subtle tilt parallax (only on mobile, gentle)
    if (w.DeviceOrientationEvent && isMobile) {
      try {
        w.addEventListener('deviceorientation', function(e) {
          if (e.gamma === null || e.beta === null) return; // not supported
          // gamma: left-right tilt (-90..90), beta: front-back tilt (-180..180)
          // Map gently to parallax offsets — clamp to ±0.4 range (subtler than touch)
          var gx = clamp(e.gamma / 45, -1, 1) * 0.4;
          var gy = clamp((e.beta - 30) / 45, -1, 1) * 0.4; // beta~30 is phone held upright
          // Smoothly TOWARD the orientation target (independent of touch fading)
          tx += (gx - tx) * 0.06;
          ty += (gy - ty) * 0.06;
        }, true);
      } catch(e) {}
    }

    /* --- isometric helpers --- */
    var ISO = Math.PI / 6;
    var cosA = Math.cos(ISO), sinA = Math.sin(ISO);
    function isoX(x, y)    { return (x - y) * cosA; }
    function isoY(x, y, z) { return (x + y) * sinA - z; }

    /* --- easing helpers --- */
    function clamp01(v) { return v < 0 ? 0 : v > 1 ? 1 : v; }
    function smooth(lo, hi, v) { var t = clamp01((v - lo) / (hi - lo)); return t * t * (3 - 2 * t); }
    function window_(v, a, b, ri, ro) { return smooth(a, a + ri, v) * (1 - smooth(b - ro, b, v)); }
    function lerp(a, b, t) { return a + (b - a) * t; }
    function easeOut(t) { return 1 - (1 - t) * (1 - t); }

    /* --- timeline --- */
    var TOTAL = 52;

    /* ================================================================ */
    /*  PRE-GENERATE ALL DATA                                            */
    /* ================================================================ */

    // Verilog code lines (One Dark syntax highlighting)
    var codeLines = [
      [["module ", "#c678dd"], ["lanex_core ", "#e5c07b"], ["(", "#abb2bf"]],
      [["  input  ", "#c678dd"], ["clk", "#61afef"], [", ", "#abb2bf"], ["rst_n", "#61afef"], [",", "#abb2bf"]],
      [["  input  ", "#c678dd"], ["[7:0] ", "#d19a66"], ["data_in", "#e06c75"], [",", "#abb2bf"]],
      [["  output ", "#c678dd"], ["reg ", "#c678dd"], ["[7:0] ", "#d19a66"], ["gds_out", "#e06c75"]],
      [[");", "#abb2bf"]],
      [["", ""]],
      [["  always ", "#c678dd"], ["@(", "#abb2bf"], ["posedge ", "#c678dd"], ["clk", "#61afef"], [") ", "#abb2bf"], ["begin", "#c678dd"]],
      [["    if ", "#c678dd"], ["(!rst_n)", "#abb2bf"]],
      [["      gds_out ", "#e06c75"], ["<= ", "#56b6c2"], ["8'h00", "#d19a66"], [";", "#abb2bf"]],
      [["    else", "#c678dd"]],
      [["      gds_out ", "#e06c75"], ["<= ", "#56b6c2"], ["data_in ", "#e06c75"], ["+ ", "#56b6c2"], ["1", "#d19a66"], [";", "#abb2bf"]],
      [["  end", "#c678dd"]],
      [["endmodule", "#c678dd"]]
    ];

    var NUM_GATES = 14;
    var gateData = [];
    var gateTypes = ['AND', 'OR', 'NOT', 'NAND', 'XOR'];
    for (var i = 0; i < NUM_GATES; i++) {
      var seed = i * 7.31 + 0.5;
      gateData.push({
        homeX: Math.sin(seed * 1.1) * 180,
        homeY: Math.sin(seed * 2.3) * 180,
        homeZ: 90 + Math.sin(seed * 3.7) * 50,
        type: gateTypes[i % 5],
        phase: seed,
        cellIdx: i
      });
    }

    var netlist = [];
    for (var i = 0; i < NUM_GATES - 1; i++) netlist.push([i, i + 1]);
    netlist.push([0, 5], [2, 8], [4, 11], [7, 13]);

    var cells = [];
    var CELL_ROWS = 5, CELL_COLS = 7;
    var cellW = 22, cellH = 14, cellGapX = 3, cellGapY = 6;
    var gridW = CELL_COLS * (cellW + cellGapX) - cellGapX;
    var gridH = CELL_ROWS * (cellH + cellGapY) - cellGapY;
    for (var r = 0; r < CELL_ROWS; r++) {
      for (var c = 0; c < CELL_COLS; c++) {
        cells.push({
          x: -gridW / 2 + c * (cellW + cellGapX) + cellW / 2,
          y: -gridH / 2 + r * (cellH + cellGapY) + cellH / 2,
          w: cellW, h: cellH,
          hue: 170 + (r * CELL_COLS + c) * 5,
          delay: (r + c) * 0.06
        });
      }
    }

    var routeLayers = [];
    for (var layer = 0; layer < 4; layer++) {
      var segs = [];
      var isH = (layer % 2 === 0);
      for (var j = 0; j < 14; j++) {
        var seed = layer * 100 + j * 13.7 + 0.3;
        var a1 = Math.sin(seed) * 70;
        var track = Math.sin(seed * 1.7) * 70;
        var a2 = a1 + (20 + Math.abs(Math.sin(seed * 2.9)) * 50) * (Math.sin(seed * 0.3) > 0 ? 1 : -1);
        if (a2 > 78) a2 = 78; if (a2 < -78) a2 = -78;
        if (a1 > a2) { var tmp = a1; a1 = a2; a2 = tmp; }
        segs.push({ a1: a1, a2: a2, track: track, isH: isH });
      }
      routeLayers.push(segs);
    }

    // GDSII polygons per layer
    var gdsLayers = [];
    var gdsCols = [
      ['rgba(34,197,94,0.5)', '#22c55e'],
      ['rgba(239,68,68,0.5)', '#ef4444'],
      ['rgba(59,130,246,0.5)', '#3b82f6'],
      ['rgba(168,85,247,0.5)', '#a855f7'],
      ['rgba(234,179,8,0.45)', '#eab308']
    ];
    for (var li = 0; li < 5; li++) {
      var shapes = [];
      for (var j = 0; j < 12; j++) {
        var seed = li * 50 + j * 5.13 + 1.7;
        shapes.push({
          x: Math.sin(seed * 1.1) * 68,
          y: Math.sin(seed * 2.3) * 68,
          w: 8 + Math.abs(Math.sin(seed * 3.1)) * 18,
          h: 6 + Math.abs(Math.sin(seed * 4.7)) * 14,
          fill: gdsCols[li][0], stroke: gdsCols[li][1]
        });
      }
      gdsLayers.push(shapes);
    }

    /* ================================================================ */
    /*  DRAWING HELPERS                                                  */
    /* ================================================================ */

    function drawQuad(pts, fill, stroke, alpha) {
      if (alpha < 0.008) return;
      ctx.globalAlpha = alpha;
      ctx.beginPath();
      ctx.moveTo(pts[0][0], pts[0][1]);
      for (var i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
      ctx.closePath();
      if (fill) { ctx.fillStyle = fill; ctx.fill(); }
      if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = 1; ctx.stroke(); }
    }

    function drawBox3D(x1, y1, x2, y2, zTop, zBot, topFill, sideA, sideB, border, alpha) {
      if (alpha < 0.008) return;
      drawQuad([
        [isoX(x1, y2), isoY(x1, y2, zTop)], [isoX(x2, y2), isoY(x2, y2, zTop)],
        [isoX(x2, y2), isoY(x2, y2, zBot)], [isoX(x1, y2), isoY(x1, y2, zBot)]
      ], sideA, border, alpha);
      drawQuad([
        [isoX(x2, y1), isoY(x2, y1, zTop)], [isoX(x2, y2), isoY(x2, y2, zTop)],
        [isoX(x2, y2), isoY(x2, y2, zBot)], [isoX(x2, y1), isoY(x2, y1, zBot)]
      ], sideB, border, alpha);
      drawQuad([
        [isoX(x1, y1), isoY(x1, y1, zTop)], [isoX(x2, y1), isoY(x2, y1, zTop)],
        [isoX(x2, y2), isoY(x2, y2, zTop)], [isoX(x1, y2), isoY(x1, y2, zTop)]
      ], topFill, border, alpha);
    }

    function drawGateSymbol(sx, sy, type, size, color, alpha) {
      if (alpha < 0.01) return;
      ctx.globalAlpha = alpha;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5 * sc;
      ctx.beginPath();
      var s = size;
      if (type === 'AND' || type === 'NAND') {
        ctx.moveTo(sx - s, sy - s * 0.5); ctx.lineTo(sx, sy - s * 0.5);
        ctx.arc(sx, sy, s * 0.5, -Math.PI / 2, Math.PI / 2);
        ctx.lineTo(sx - s, sy + s * 0.5); ctx.closePath();
        ctx.moveTo(sx - s * 1.4, sy - s * 0.3); ctx.lineTo(sx - s, sy - s * 0.3);
        ctx.moveTo(sx - s * 1.4, sy + s * 0.3); ctx.lineTo(sx - s, sy + s * 0.3);
        ctx.moveTo(sx + s * 0.5, sy); ctx.lineTo(sx + s * 1.2, sy);
      } else if (type === 'OR' || type === 'XOR') {
        ctx.moveTo(sx - s * 0.7, sy - s * 0.5);
        ctx.quadraticCurveTo(sx + s * 0.3, sy - s * 0.5, sx + s * 0.5, sy);
        ctx.quadraticCurveTo(sx + s * 0.3, sy + s * 0.5, sx - s * 0.7, sy + s * 0.5);
        ctx.quadraticCurveTo(sx - s * 0.3, sy, sx - s * 0.7, sy - s * 0.5);
        ctx.moveTo(sx - s * 1.4, sy - s * 0.3); ctx.lineTo(sx - s * 0.55, sy - s * 0.3);
        ctx.moveTo(sx - s * 1.4, sy + s * 0.3); ctx.lineTo(sx - s * 0.55, sy + s * 0.3);
        ctx.moveTo(sx + s * 0.5, sy); ctx.lineTo(sx + s * 1.2, sy);
      } else {
        ctx.moveTo(sx - s * 0.6, sy - s * 0.45); ctx.lineTo(sx + s * 0.3, sy);
        ctx.lineTo(sx - s * 0.6, sy + s * 0.45); ctx.closePath();
        ctx.moveTo(sx - s * 1.2, sy); ctx.lineTo(sx - s * 0.6, sy);
        ctx.moveTo(sx + s * 0.3, sy); ctx.lineTo(sx + s * 1.2, sy);
      }
      ctx.stroke();
    }

    /* ================================================================ */
    /*  MAIN RENDER                                                      */
    /* ================================================================ */

    /* Cached theme colors — refreshed by refreshTheme() on theme toggle. */
    var THEME = { light: false, bg: '#05070d', m1: '#22d3ee', m2: '#60a5fa', m3: '#2dd4bf',
      route: ['#22d3ee','#60a5fa','#2dd4bf','#fbbf24'],
      waferFillDark: 'rgba(20,25,40,0.9)', waferFillLight: 'rgba(220,230,245,0.9)',
      waferStrokeDark: 'rgba(100,120,180,0.3)', waferStrokeLight: 'rgba(140,160,190,0.5)',
      pkgTopDark: 'rgba(30,41,59,0.97)', pkgTopLight: 'rgba(226,234,244,0.97)',
      pkgSide1Dark: 'rgba(15,23,42,0.95)', pkgSide1Light: 'rgba(200,212,228,0.95)',
      pkgSide2Dark: 'rgba(23,37,66,0.95)', pkgSide2Light: 'rgba(190,202,220,0.95)',
      pkgStrokeDark: '#475569', pkgStrokeLight: '#a9bad2',
      edBgDark: '#1e1e2e', edBgLight: '#f8f9fc',
      edBarDark: '#181825', edBarLight: '#eef1f6',
      edShadowDark: 'rgba(0,0,0,0.5)', edShadowLight: 'rgba(0,0,0,0.08)',
      edBorderDark: 'rgba(99,102,241,0.3)', edBorderLight: 'rgba(99,102,241,0.2)',
      edSepDark: 'rgba(255,255,255,0.06)', edSepLight: 'rgba(0,0,0,0.06)',
      edTitleDark: 'rgba(205,214,244,0.6)', edTitleLight: 'rgba(50,60,80,0.7)',
      edLineNumDark: '#585b70', edLineNumLight: '#a0a8b8' };
    function pick(dk, lt) { return THEME.light ? lt : dk; }
    function refreshTheme() {
      var l = d.body.classList.contains('theme-light');
      if (l === THEME.light) return;
      THEME.light = l;
      THEME.bg = gv('--bg', '#05070d');
      THEME.m1 = gv('--c-m1', '#22d3ee');
      THEME.m2 = gv('--c-m2', '#60a5fa');
      THEME.m3 = gv('--c-m3', '#2dd4bf');
      THEME.route = [THEME.m1, THEME.m2, THEME.m3, l ? '#b7791f' : '#fbbf24'];
    }
    refreshTheme();
    /* On theme toggle, also re-cache the derivatives used by the canvas. */
    try {
      var tb = $('themeBtn');
      if (tb) tb.addEventListener('click', function () {
        setTimeout(function () { refreshTheme(); try { render(performance.now() / 1000); } catch(e){} }, 0);
      });
    } catch (e) {}

    function render(tRaw) {
      var t;
      if (paused || scrubbing) {
        t = scrubValue % TOTAL;
      } else {
        t = (tRaw + animOffset) % TOTAL;
        if (t < 0) t += TOTAL;
        scrubValue = t;
      }

      // Update UI elements (transform avoids layout; label only when the second flips)
      if (progressFill) progressFill.style.transform = 'scaleX(' + (t / TOTAL) + ')';
      var tSec = Math.floor(t);
      if (timeLabel && w._lastTimeSec !== tSec) { w._lastTimeSec = tSec; timeLabel.textContent = tSec + 's'; }

      var steps = ['RTL', 'SYNTH', 'FLOOR', 'PLACE', 'CTS', 'ROUTE', 'GDS', 'LITHO', 'PKG'];
      var stepBounds = [0, 3, 6, 10, 16, 21, 27, 32, 42];
      var numS = steps.length;
      var activeIdx = 0;
      for (var i = numS - 1; i >= 0; i--) { if (t >= stepBounds[i]) { activeIdx = i; break; } }
      stageBtns.forEach(function(btn, idx) {
        btn.classList.toggle('active', idx === activeIdx);
      });

      // Fake Cursor Logic (Simulate driving the flow) — skip on mobile (CSS hides it anyway)
      var cursor = cursorEl;
      if (cursor && !cursor.classList.contains('user-disabled') && !isMobile) {
        if (!paused && !scrubbing) {
          var targetIdx = activeIdx + 1;

          // 1) Initial click on RTL (index 0) — animated approach, then click
          if (t < 0.5 && w._cursorTarget !== 0) {
            w._cursorTarget = 0;
            w._cursorClicked = 0;
            cursor.classList.add('visible');
            var btn0 = stageBtns[0];
            if (btn0) {
              var r0 = btn0.getBoundingClientRect();
              w._cursorTX = r0.left + r0.width / 2;
              w._cursorTY = r0.top + r0.height / 2;
              setTimeout(function() {
                cursor.classList.add('clicking');
                setTimeout(function() { cursor.classList.remove('clicking'); }, 160);
              }, 220);
            }
          }

          // 2) Move to next step (up to GDS = index 6)
          if (targetIdx <= 6 && targetIdx < numS) {
            var nextTime = stepBounds[targetIdx];
            var timeToNext = nextTime - t;

            // Start moving 0.8s before the step
            if (timeToNext <= 0.8 && timeToNext > 0 && w._cursorTarget !== targetIdx) {
              w._cursorTarget = targetIdx;
              cursor.classList.add('visible');
              var targetBtn = stageBtns[targetIdx];
              if (targetBtn) {
                var tbRect = targetBtn.getBoundingClientRect();
                w._cursorTX = tbRect.left + tbRect.width / 2;
                w._cursorTY = tbRect.top + tbRect.height / 2;
              }
            }

            // Click 0.15s before the step starts
            if (timeToNext <= 0.15 && timeToNext > 0 && w._cursorClicked !== targetIdx) {
              w._cursorClicked = targetIdx;
              cursor.classList.add('clicking');
              setTimeout(function() { cursor.classList.remove('clicking'); }, 160);
            }
          }

          // Hide after GDS step is clicked/started
          if (activeIdx >= 6 && t > stepBounds[6] + 0.5) {
            cursor.classList.remove('visible');
          }
        } else {
          cursor.classList.remove('visible');
        }
        // Smoothly lerp toward target every frame for cinematic motion
        if (w._cursorTX !== undefined && w._cursorTY !== undefined) {
          if (w._cursorPX === undefined) {
            w._cursorPX = w._cursorTX; w._cursorPY = w._cursorTY;
          }
          w._cursorPX += (w._cursorTX - w._cursorPX) * 0.12;
          w._cursorPY += (w._cursorTY - w._cursorPY) * 0.12;
          cursor.style.left = w._cursorPX + 'px';
          cursor.style.top  = w._cursorPY + 'px';
        }
      }

      // Reset cursor state when animation loops back to start
      if (t < 1 && w._cursorTarget > 0) {
        w._cursorTarget = -1;
        w._cursorClicked = -1;
      }

      mx += (tx - mx) * 0.06;
      my += (ty - my) * 0.06;
      // Desktop: 22px of parallax swing (subtle backdrop feel).
      // Mobile: 36px so the gentle device-tilt parallax is actually perceivable.
      var parallaxAmt = (isMobile ? 36 : 22) * sc;
      var shiftX = mx * parallaxAmt;
      var shiftY = my * parallaxAmt;
      var ox = cx0 + shiftX;
      var oy = cy0 + shiftY;

      var routeColors = THEME.route;

      var waferFill  = pick(THEME.waferFillDark,  THEME.waferFillLight);
      var waferStroke= pick(THEME.waferStrokeDark,THEME.waferStrokeLight);
      var pkgTop     = pick(THEME.pkgTopDark,     THEME.pkgTopLight);
      var pkgSide1   = pick(THEME.pkgSide1Dark,   THEME.pkgSide1Light);
      var pkgSide2   = pick(THEME.pkgSide2Dark,   THEME.pkgSide2Light);
      var pkgStroke  = pick(THEME.pkgStrokeDark,  THEME.pkgStrokeLight);

      var edBg       = pick(THEME.edBgDark,      THEME.edBgLight);
      var edBar      = pick(THEME.edBarDark,     THEME.edBarLight);
      var edShadow   = pick(THEME.edShadowDark,  THEME.edShadowLight);
      var edBorder   = pick(THEME.edBorderDark,  THEME.edBorderLight);
      var edSep      = pick(THEME.edSepDark,     THEME.edSepLight);
      var edTitle    = pick(THEME.edTitleDark,   THEME.edTitleLight);
      var edLineNum  = pick(THEME.edLineNumDark, THEME.edLineNumLight);

      ctx.globalCompositeOperation = 'source-over';
      ctx.globalAlpha = 1;
      ctx.clearRect(0, 0, W, H); // transparent — the CSS scene behind stays visible

      // Snap gradient center to a coarse grid so the parallax-induced
      // micro-jitter doesn't invalidate the cache every frame.
      var gx = Math.round(ox / 16) * 16;
      var gy = Math.round(oy / 16) * 16;
      if (!w._bgGrad || w._bgGradX !== gx || w._bgGradY !== gy || w._bgGradSc !== sc) {
        w._bgGrad = ctx.createRadialGradient(gx, gy, 0, gx, gy, 400 * sc);
        w._bgGrad.addColorStop(0, 'rgba(34,211,238,0.06)');
        w._bgGrad.addColorStop(0.5, 'rgba(96,165,250,0.025)');
        w._bgGrad.addColorStop(1, 'transparent');
        w._bgGradX = gx; w._bgGradY = gy; w._bgGradSc = sc;
      }
      ctx.fillStyle = w._bgGrad;
      ctx.fillRect(0, 0, W, H);

      var SZ = 180 * sc;
      var hw = SZ / 2;

      // Lithography now ZOOMS IN (scale > 1) instead of zooming out
      var lithoZoom = smooth(32, 33.5, t) - smooth(41.5, 42.5, t);
      var masterScale = lerp(1, 1.6, lithoZoom); // Zoom IN for litho closeup
      masterScale *= userZoom; // Apply user zoom

      var chipSZ = SZ * masterScale;
      var chipHW = chipSZ / 2;

      ctx.save();
      ctx.translate(ox, oy);

      /* ============================================================ */
      /*  ACT 1: RTL CODE EDITOR (0s - 5s)                            */
      /* ============================================================ */
      var codeAlpha = window_(t, 0, 5.5, 0.8, 1.0);
      if (codeAlpha > 0.01) {
        ctx.save();
        // Mobile: shrink the editor and park it BELOW the chip (code drives the chip,
        // so we read top→bottom: badge · title · chip · editor). Desktop: editor floats
        // beside the chip on the left.
        var edScale = isMobile ? 0.74 : 1.0;
        var edSc = sc * edScale;
        var edW = 320 * edSc; var edH = 240 * edSc;
        var edX = isMobile ? (-edW / 2) : (-edW / 2 - 40 * sc);
        // Position it at the same vertical level as the chip die for both mobile and desktop
        var edY = -edH / 2 + Math.sin(t * 1.5) * 4 * sc;

        ctx.globalAlpha = codeAlpha * 0.3;
        ctx.fillStyle = edShadow;
        ctx.beginPath(); ctx.roundRect(edX + 4, edY + 6, edW, edH, 10 * edSc); ctx.fill();

        ctx.globalAlpha = codeAlpha * 0.95;
        ctx.fillStyle = edBg;
        ctx.beginPath(); ctx.roundRect(edX, edY, edW, edH, 10 * edSc); ctx.fill();
        ctx.strokeStyle = edBorder; ctx.lineWidth = 1.5; ctx.stroke();

        var barH = 30 * edSc;
        ctx.globalAlpha = codeAlpha;
        ctx.fillStyle = edBar;
        ctx.beginPath(); ctx.roundRect(edX, edY, edW, barH, [10 * edSc, 10 * edSc, 0, 0]); ctx.fill();
        ctx.strokeStyle = edSep; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(edX, edY + barH); ctx.lineTo(edX + edW, edY + barH); ctx.stroke();

        var dotR = 5 * edSc; var dotY = edY + barH / 2; var dotX0 = edX + 16 * edSc;
        ctx.fillStyle = '#ff5f57'; ctx.beginPath(); ctx.arc(dotX0, dotY, dotR, 0, 6.28); ctx.fill();
        ctx.fillStyle = '#febc2e'; ctx.beginPath(); ctx.arc(dotX0 + 18 * edSc, dotY, dotR, 0, 6.28); ctx.fill();
        ctx.fillStyle = '#28c840'; ctx.beginPath(); ctx.arc(dotX0 + 36 * edSc, dotY, dotR, 0, 6.28); ctx.fill();

        ctx.font = Math.floor(10 * edSc) + 'px "SF Mono","Fira Code",Consolas,monospace';
        ctx.fillStyle = edTitle; ctx.textAlign = 'center';
        ctx.fillText('rtl_synthesis.v', edX + edW / 2, dotY + 3.5 * edSc);

        var lineH = 14.5 * edSc; var codeY0 = edY + barH + 14 * edSc; var codeX0 = edX + 18 * edSc;
        ctx.textAlign = 'left';
        ctx.font = Math.floor(10.5 * edSc) + 'px "SF Mono","Fira Code",Consolas,monospace';
        var totalChars = 0;
        for (var li = 0; li < codeLines.length; li++)
          for (var si = 0; si < codeLines[li].length; si++) totalChars += codeLines[li][si][0].length;
        var revealP = smooth(0.3, 3.0, t);
        var charsToShow = Math.floor(revealP * totalChars);
        var charCount = 0;

        for (var li = 0; li < codeLines.length; li++) {
          ctx.globalAlpha = codeAlpha * 0.25; ctx.fillStyle = edLineNum;
          ctx.fillText((li + 1 < 10 ? ' ' : '') + (li + 1), codeX0 - 4 * edSc, codeY0 + li * lineH);
          var cursorX = codeX0 + 18 * edSc;
          for (var si = 0; si < codeLines[li].length; si++) {
            var tok = codeLines[li][si]; var txt = tok[0]; var col = tok[1];
            if (!txt) continue;
            var vLen = Math.min(txt.length, Math.max(0, charsToShow - charCount));
            charCount += txt.length;
            if (vLen > 0) {
              ctx.globalAlpha = codeAlpha * 0.95; ctx.fillStyle = col;
              ctx.fillText(txt.substring(0, vLen), cursorX, codeY0 + li * lineH);
            }
            cursorX += ctx.measureText(txt).width;
          }
        }
        if (revealP < 1 || (t % 1.0 < 0.5)) {
          ctx.globalAlpha = codeAlpha * 0.8; ctx.fillStyle = '#cdd6f4';
          var curLine = Math.min(Math.floor(charsToShow / 35), codeLines.length - 1);
          ctx.fillRect(codeX0 + 18 * edSc + (charsToShow % 35) * 6.2 * edSc, codeY0 + curLine * lineH - 9 * edSc, 1.5 * edSc, 12 * edSc);
        }
        ctx.restore();
      }

      /* ============================================================ */
      /*  ACT 2: LOGIC GATES (3s - 16s)                                */
      /* ============================================================ */
      var gateAlpha = window_(t, 3.0, 16.0, 1.0, 1.0);
      var morphT = smooth(10.5, 15.0, t);
      if (gateAlpha > 0.01) {
        ctx.globalAlpha = gateAlpha * 0.15 * (1 - morphT);
        ctx.strokeStyle = '#2dd4bf'; ctx.lineWidth = 1 * sc;
        ctx.beginPath();
        for (var ni = 0; ni < netlist.length; ni++) {
          var gA = gateData[netlist[ni][0]], gB = gateData[netlist[ni][1]];
          var aX = gA.homeX + Math.sin(t * 0.7 + gA.phase) * 15;
          var aY = gA.homeY + Math.cos(t * 0.5 + gA.phase * 1.3) * 15;
          var aZ = gA.homeZ + Math.sin(t * 0.9 + gA.phase * 0.7) * 10;
          var bX = gB.homeX + Math.sin(t * 0.7 + gB.phase) * 15;
          var bY = gB.homeY + Math.cos(t * 0.5 + gB.phase * 1.3) * 15;
          var bZ = gB.homeZ + Math.sin(t * 0.9 + gB.phase * 0.7) * 10;
          var cA = cells[Math.min(netlist[ni][0], cells.length - 1)];
          var cB = cells[Math.min(netlist[ni][1], cells.length - 1)];
          aX = lerp(aX, cA.x, morphT); aY = lerp(aY, cA.y, morphT); aZ = lerp(aZ, 5, morphT);
          bX = lerp(bX, cB.x, morphT); bY = lerp(bY, cB.y, morphT); bZ = lerp(bZ, 5, morphT);
          ctx.moveTo(isoX(aX * sc, aY * sc), isoY(aX * sc, aY * sc, aZ * sc));
          ctx.lineTo(isoX(bX * sc, bY * sc), isoY(bX * sc, bY * sc, bZ * sc));
        }
        ctx.stroke();
        for (var gi = 0; gi < NUM_GATES; gi++) {
          var g = gateData[gi];
          var gx = lerp(g.homeX + Math.sin(t * 0.7 + g.phase) * 15, cells[Math.min(gi, cells.length - 1)].x, morphT);
          var gy = lerp(g.homeY + Math.cos(t * 0.5 + g.phase * 1.3) * 15, cells[Math.min(gi, cells.length - 1)].y, morphT);
          var gz = lerp(g.homeZ + Math.sin(t * 0.9 + g.phase * 0.7) * 10, 5, morphT);
          drawGateSymbol(isoX(gx * sc, gy * sc), isoY(gx * sc, gy * sc, gz * sc), g.type, 10 * sc, '#2dd4bf', gateAlpha * (1 - morphT * 0.95));
        }
      }

      /* ============================================================ */
      /*  ACT 3: FLOORPLAN (6s - 48s)                                  */
      /* ============================================================ */
      var subAlpha = smooth(6.0, 7.5, t) * (1 - smooth(47, 48, t));
      if (subAlpha > 0.01) {
        var subZ = lerp(-80, 0, smooth(6.0, 7.8, t));
        ctx.globalCompositeOperation = 'source-over';

        // Soft ground shadow beneath the die — grounds the chip in space
        ctx.save();
        ctx.translate(0, isoY(0, 0, subZ - 12 * sc));
        ctx.scale(1, 0.42);
        var shR = chipHW * 2.0;
        var shGrad = ctx.createRadialGradient(0, 0, 0, 0, 0, shR);
        shGrad.addColorStop(0, THEME.light ? 'rgba(35,55,85,0.22)' : 'rgba(0,0,0,0.5)');
        shGrad.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.globalAlpha = subAlpha;
        ctx.fillStyle = shGrad;
        ctx.beginPath(); ctx.arc(0, 0, shR, 0, 6.28); ctx.fill();
        ctx.restore();

        drawQuad([
          [isoX(-chipHW, -chipHW), isoY(-chipHW, -chipHW, subZ)],
          [isoX(chipHW, -chipHW), isoY(chipHW, -chipHW, subZ)],
          [isoX(chipHW, chipHW), isoY(chipHW, chipHW, subZ)],
          [isoX(-chipHW, chipHW), isoY(-chipHW, chipHW, subZ)]
        ], pick('rgba(10,15,28,0.94)', 'rgba(216,227,240,0.97)'), pick('rgba(34,211,238,0.2)', 'rgba(12,138,184,0.45)'), subAlpha);

        // Act-transition pulse — a ring sweeps out from the die edge as a stage begins
        var actAge = t - stepBounds[activeIdx];
        if (activeIdx >= 2 && actAge >= 0 && actAge < 1.1) {
          var rp = actAge / 1.1;
          var ringR = chipHW * lerp(1.02, 1.55, easeOut(rp));
          ctx.globalAlpha = (1 - rp) * 0.5 * subAlpha;
          ctx.strokeStyle = THEME.m1;
          ctx.lineWidth = 2 * sc;
          ctx.beginPath();
          ctx.moveTo(isoX(-ringR, -ringR), isoY(-ringR, -ringR, subZ));
          ctx.lineTo(isoX(ringR, -ringR), isoY(ringR, -ringR, subZ));
          ctx.lineTo(isoX(ringR, ringR), isoY(ringR, ringR, subZ));
          ctx.lineTo(isoX(-ringR, ringR), isoY(-ringR, ringR, subZ));
          ctx.closePath();
          ctx.stroke();
        }
        ctx.globalCompositeOperation = 'lighter';

        // IO Pads
        var padAlpha = smooth(7.5, 9.0, t) * subAlpha;
        if (padAlpha > 0.01) {
          var padW = 7 * sc * masterScale; ctx.globalAlpha = padAlpha * 0.85;
          ctx.fillStyle = '#d97706';
          for (var p = 0; p < 10; p++) {
            var pos = lerp(-chipHW + padW, chipHW - padW, (p + 0.5) / 10);
            var pw = padW * 0.3;
            ctx.fillRect(isoX(pos, -chipHW) - pw, isoY(pos, -chipHW, subZ) - pw * 0.5, pw * 2, pw);
            ctx.fillRect(isoX(pos, chipHW) - pw, isoY(pos, chipHW, subZ) - pw * 0.5, pw * 2, pw);
            ctx.fillRect(isoX(-chipHW, pos) - pw, isoY(-chipHW, pos, subZ) - pw * 0.5, pw * 2, pw);
            ctx.fillRect(isoX(chipHW, pos) - pw, isoY(chipHW, pos, subZ) - pw * 0.5, pw * 2, pw);
          }
        }

        // PDN
        var pdnAlpha = smooth(8.5, 10.0, t) * subAlpha;
        if (pdnAlpha > 0.01) {
          ctx.globalAlpha = pdnAlpha * 0.55; ctx.strokeStyle = '#f97316';
          ctx.lineWidth = 2.5 * sc * masterScale;
          var pI = chipHW * 0.92;
          ctx.beginPath();
          ctx.moveTo(isoX(-pI, -pI), isoY(-pI, -pI, subZ)); ctx.lineTo(isoX(pI, -pI), isoY(pI, -pI, subZ));
          ctx.lineTo(isoX(pI, pI), isoY(pI, pI, subZ)); ctx.lineTo(isoX(-pI, pI), isoY(-pI, pI, subZ));
          ctx.closePath(); ctx.stroke();
          ctx.lineWidth = 1.5 * sc * masterScale; ctx.globalAlpha = pdnAlpha * 0.3;
          ctx.beginPath();
          for (var si = -2; si <= 2; si++) {
            var sP = si * chipHW * 0.3;
            ctx.moveTo(isoX(-pI, sP), isoY(-pI, sP, subZ)); ctx.lineTo(isoX(pI, sP), isoY(pI, sP, subZ));
            ctx.moveTo(isoX(sP, -pI), isoY(sP, -pI, subZ)); ctx.lineTo(isoX(sP, pI), isoY(sP, pI, subZ));
          }
          ctx.stroke();
        }
      }

      /* ============================================================ */
      /*  ACT 4: CELLS (10s - 48s)                                     */
      /* ============================================================ */
      var cellAlpha = smooth(10.5, 12.0, t) * (1 - smooth(27, 28.5, t) * 0.8) * (1 - smooth(47, 48, t));
      if (cellAlpha > 0.01) {
        var placeP = smooth(10.5, 15.0, t);
        ctx.globalCompositeOperation = 'source-over';
        for (var ci = 0; ci < cells.length; ci++) {
          var cell = cells[ci];
          var cellP = clamp01((placeP - cell.delay) / (1 - cell.delay));
          if (cellP < 0.01) continue;
          var dropZ = lerp(120 * sc * masterScale, 0, easeOut(cellP));
          var cw = cell.w * sc * masterScale / 2;
          var ch = cell.h * sc * masterScale / 2;
          var ccx = cell.x * sc * masterScale; var ccy = cell.y * sc * masterScale;
          drawQuad([
            [isoX(ccx - cw, ccy - ch), isoY(ccx - cw, ccy - ch, dropZ)],
            [isoX(ccx + cw, ccy - ch), isoY(ccx + cw, ccy - ch, dropZ)],
            [isoX(ccx + cw, ccy + ch), isoY(ccx + cw, ccy + ch, dropZ)],
            [isoX(ccx - cw, ccy + ch), isoY(ccx - cw, ccy + ch, dropZ)]
          ], 'hsla(' + cell.hue + ',60%,55%,0.3)', 'hsla(' + cell.hue + ',65%,60%,0.7)', cellAlpha * cellP);
        }
        ctx.globalCompositeOperation = 'lighter';
      }

      /* ============================================================ */
      /*  ACT 5: CTS (16s - 48s)                                       */
      /* ============================================================ */
      var ctsAlpha = smooth(16.0, 17.5, t) * (1 - smooth(27, 28.5, t) * 0.85) * (1 - smooth(47, 48, t));
      if (ctsAlpha > 0.01) {
        var treeGrowth = clamp01((t - 16.0) / 5.0);
        ctx.globalCompositeOperation = 'source-over';
        ctx.strokeStyle = '#ec4899'; ctx.lineWidth = 2 * sc * masterScale;
        var treeSegs = [];
        function buildTree(x, y, size, depth, axis) {
          if (depth === 0) return;
          var h = size / 2;
          var layerP = clamp01((treeGrowth - (4 - depth) * 0.25) / 0.25);
          if (layerP <= 0) return;
          var ext = h * layerP;
          if (axis === 'x') {
            treeSegs.push([x - ext, y, x + ext, y]);
            if (layerP >= 1) { buildTree(x - h, y, size / 2, depth - 1, 'y'); buildTree(x + h, y, size / 2, depth - 1, 'y'); }
          } else {
            treeSegs.push([x, y - ext, x, y + ext]);
            if (layerP >= 1) { buildTree(x, y - h, size, depth - 1, 'x'); buildTree(x, y + h, size, depth - 1, 'x'); }
          }
        }
        buildTree(0, 0, chipSZ * 0.55, 4, 'x');
        ctx.globalAlpha = ctsAlpha; ctx.beginPath();
        var ctsZ = 4 * sc * masterScale;
        for (var si = 0; si < treeSegs.length; si++) {
          var seg = treeSegs[si];
          ctx.moveTo(isoX(seg[0], seg[1]), isoY(seg[0], seg[1], ctsZ));
          ctx.lineTo(isoX(seg[2], seg[3]), isoY(seg[2], seg[3], ctsZ));
        }
        ctx.stroke();
      }

      /* ============================================================ */
      /*  ACT 6: ROUTING (21s - 48s)                                    */
      /* ============================================================ */
      var routeAlpha = smooth(21, 22.5, t) * (1 - smooth(27, 28.5, t) * 0.85) * (1 - smooth(47, 48, t));
      if (routeAlpha > 0.01) {
        ctx.globalCompositeOperation = 'source-over';
        for (var layer = 0; layer < 4; layer++) {
          var layerT = 21.0 + layer * 1.4;
          var layerP = smooth(layerT, layerT + 1.2, t);
          if (layerP < 0.01) continue;
          var lz = (layer + 1) * 12 * sc * masterScale;
          ctx.globalAlpha = routeAlpha * layerP * 0.8;
          ctx.strokeStyle = routeColors[layer];
          ctx.lineWidth = (1.2 + layer * 0.2) * sc * masterScale;
          ctx.beginPath();
          var segs = routeLayers[layer];
          for (var si = 0; si < segs.length; si++) {
            var seg = segs[si]; var s1 = seg.a1 * sc * masterScale; var s2 = (seg.a1 + (seg.a2 - seg.a1) * layerP) * sc * masterScale;
            var trk = seg.track * sc * masterScale;
            if (seg.isH) { ctx.moveTo(isoX(s1, trk), isoY(s1, trk, lz)); ctx.lineTo(isoX(s2, trk), isoY(s2, trk, lz)); }
            else { ctx.moveTo(isoX(trk, s1), isoY(trk, s1, lz)); ctx.lineTo(isoX(trk, s2), isoY(trk, s2, lz)); }
          }
          ctx.stroke();
          // Packets
          if (layerP > 0.3) {
            ctx.fillStyle = pick('#fff', '#155e75'); ctx.globalAlpha = routeAlpha * 0.7;
            for (var si = 0; si < segs.length; si += 3) {
              var seg = segs[si]; var pktPos = ((t * (0.8 + layer * 0.3) + si * 1.7) % 1.0);
              var pos = lerp(seg.a1, seg.a1 + (seg.a2 - seg.a1) * layerP, pktPos) * sc * masterScale;
              var trk = seg.track * sc * masterScale;
              var px = seg.isH ? isoX(pos, trk) : isoX(trk, pos);
              var py = seg.isH ? isoY(pos, trk, lz) : isoY(trk, pos, lz);
              ctx.beginPath(); ctx.arc(px, py, 1.8 * sc * masterScale, 0, 6.28); ctx.fill();
            }
          }
        }
      }

      /* ============================================================ */
      /*  ACT 7: GDSII (27s - 48s)                                     */
      /* ============================================================ */
      var gdsAlpha = smooth(27, 28.5, t) * (1 - smooth(47, 48, t));
      if (gdsAlpha > 0.01) {
        ctx.globalCompositeOperation = 'source-over';
        // Draw GDS layers one by one (each layer at a different z)
        for (var li = 0; li < 5; li++) {
          var layerReveal = smooth(27.5 + li * 0.8, 28.3 + li * 0.8, t);
          if (layerReveal < 0.01) continue;
          var lz = li * 6 * sc * masterScale;
          var shapes = gdsLayers[li];
          for (var gi = 0; gi < shapes.length; gi++) {
            var p = shapes[gi];
            var px = p.x * sc * masterScale; var py = p.y * sc * masterScale;
            var pw = p.w * sc * masterScale / 2; var ph = p.h * sc * masterScale / 2;
            drawQuad([
              [isoX(px - pw, py - ph), isoY(px - pw, py - ph, lz)],
              [isoX(px + pw, py - ph), isoY(px + pw, py - ph, lz)],
              [isoX(px + pw, py + ph), isoY(px + pw, py + ph, lz)],
              [isoX(px - pw, py + ph), isoY(px - pw, py + ph, lz)]
            ], p.fill, p.stroke, gdsAlpha * layerReveal * 0.7);
          }
        }
        ctx.globalCompositeOperation = 'lighter';
      }

      /* ============================================================ */
      /*  ACT 8: LITHOGRAPHY - ZOOM IN (32s - 42s)                     */
      /* ============================================================ */
      if (lithoZoom > 0.01) {
        // Draw the receiving wafer die below the GDS mask
        var waferZ = -40 * sc * masterScale;
        var waferAlpha = lithoZoom * 0.8;
        ctx.globalCompositeOperation = 'source-over';
        drawQuad([
          [isoX(-chipHW, -chipHW), isoY(-chipHW, -chipHW, waferZ)],
          [isoX(chipHW, -chipHW), isoY(chipHW, -chipHW, waferZ)],
          [isoX(chipHW, chipHW), isoY(chipHW, chipHW, waferZ)],
          [isoX(-chipHW, chipHW), isoY(-chipHW, chipHW, waferZ)]
        ], waferFill, waferStroke, waferAlpha);

        // UV exposure sweep printing each GDS layer onto the wafer
        var uvProgress = smooth(33, 40, t);
        if (uvProgress > 0.01) {
          // Printed patterns appearing on wafer (below GDS)
          for (var li = 0; li < 5; li++) {
            var layerPrintT = smooth(33 + li * 1.4, 34 + li * 1.4, t);
            if (layerPrintT < 0.01) continue;
            var shapes = gdsLayers[li];
            for (var gi = 0; gi < shapes.length; gi++) {
              var p = shapes[gi];
              var px = p.x * sc * masterScale; var py = p.y * sc * masterScale;
              var pw = p.w * sc * masterScale / 2; var ph = p.h * sc * masterScale / 2;
              drawQuad([
                [isoX(px - pw, py - ph), isoY(px - pw, py - ph, waferZ + 1)],
                [isoX(px + pw, py - ph), isoY(px + pw, py - ph, waferZ + 1)],
                [isoX(px + pw, py + ph), isoY(px + pw, py + ph, waferZ + 1)],
                [isoX(px - pw, py + ph), isoY(px - pw, py + ph, waferZ + 1)]
              ], p.fill, p.stroke, layerPrintT * waferAlpha * 0.6);
            }
          }

          // UV beam sweeping across
          var beamX = lerp(-chipHW, chipHW, (t * 0.4) % 1.0);
          ctx.globalCompositeOperation = 'lighter';
          ctx.globalAlpha = lithoZoom * 0.12;
          ctx.fillStyle = 'rgba(147,51,234,0.5)';
          var bw = 20 * sc * masterScale;
          ctx.fillRect(isoX(beamX - bw, -chipHW) - 5, isoY(beamX, -chipHW, 30 * sc * masterScale) - 100, bw * 1.5, 250 * sc);
        }

        // Dicing lines (39-41s)
        var laserAlpha = window_(t, 39, 41.5, 0.3, 0.3);
        if (laserAlpha > 0.01) {
          ctx.globalAlpha = laserAlpha * 0.6; ctx.strokeStyle = '#f97316'; ctx.lineWidth = 1.5 * sc;
          ctx.beginPath();
          ctx.moveTo(isoX(-chipHW * 1.2, 0), isoY(-chipHW * 1.2, 0, waferZ)); ctx.lineTo(isoX(chipHW * 1.2, 0), isoY(chipHW * 1.2, 0, waferZ));
          ctx.moveTo(isoX(0, -chipHW * 1.2), isoY(0, -chipHW * 1.2, waferZ)); ctx.lineTo(isoX(0, chipHW * 1.2), isoY(0, chipHW * 1.2, waferZ));
          ctx.stroke();
        }

        // Ambient expensive chip halo (GDS→LITHO transition, deep purple aurora)
        var haloA = window_(t, 28, 33, 0.5, 0.6);
        if (haloA > 0.01) {
          ctx.globalCompositeOperation = 'lighter';
          ctx.globalAlpha = haloA * 0.45;
          var halo = ctx.createRadialGradient(0, isoY(0, 0, 30 * sc), 0, 0, isoY(0, 0, 30 * sc), (chipHW * 1.4));
          halo.addColorStop(0, 'rgba(147,51,234,0.6)');
          halo.addColorStop(0.4, 'rgba(99,102,241,0.35)');
          halo.addColorStop(1, 'rgba(147,51,234,0)');
          ctx.fillStyle = halo;
          // Cover the whole visible canvas in translated space (origin is at ox,oy)
          ctx.fillRect(-ox - 20, -oy - 20, W + 40, H + 40);
        }
        ctx.globalCompositeOperation = 'lighter';
      }

      /* ============================================================ */
      /*  ACT 9: PACKAGING (42s - 52s)                                  */
      /* ============================================================ */
      var pkgAlpha = window_(t, 42.0, 52.0, 1.0, 0.5);
      if (pkgAlpha > 0.01) {
        ctx.globalCompositeOperation = 'source-over';
        var phw = chipHW * 1.15;
        var baseTh = 18 * sc;
        var baseZ = lerp(-100, -20, smooth(42, 43.5, t));

        // QFP gull-wing leads on all four edges — a real IC has visible pins.
        // Back-edge leads draw BEFORE the body (so it occludes them), front after.
        var leadA = smooth(43.5, 44.5, t) * pkgAlpha;
        function drawLeads(front) {
          if (leadA < 0.01) return;
          var lw = 1.7 * sc;                    // half-width of a lead
          var zSh = baseZ - baseTh * 0.55;      // shoulder exit height on the package wall
          var zFt = baseZ - baseTh - 2.5 * sc;  // foot height
          var fillC = pick('rgba(154,168,186,0.96)', 'rgba(128,142,160,0.96)');
          var edgeC = pick('#66788e', '#57677c');
          var sgn = front ? 1 : -1;
          // gull-wing profile: shoulder out, bend down, flat foot
          var prof = [
            [0, zSh, 5 * sc, zSh],
            [5 * sc, zSh, 10 * sc, zFt],
            [10 * sc, zFt, 14 * sc, zFt]
          ];
          for (var pi2 = -3; pi2 <= 3; pi2++) {
            var bp = pi2 * phw * 0.25;
            for (var s2 = 0; s2 < 3; s2++) {
              var o1 = sgn * (phw + prof[s2][0]), z1 = prof[s2][1];
              var o2 = sgn * (phw + prof[s2][2]), z2 = prof[s2][3];
              drawQuad([ // east/west edge lead
                [isoX(o1, bp - lw), isoY(o1, bp - lw, z1)],
                [isoX(o2, bp - lw), isoY(o2, bp - lw, z2)],
                [isoX(o2, bp + lw), isoY(o2, bp + lw, z2)],
                [isoX(o1, bp + lw), isoY(o1, bp + lw, z1)]
              ], fillC, edgeC, leadA * 0.95);
              drawQuad([ // north/south edge lead
                [isoX(bp - lw, o1), isoY(bp - lw, o1, z1)],
                [isoX(bp - lw, o2), isoY(bp - lw, o2, z2)],
                [isoX(bp + lw, o2), isoY(bp + lw, o2, z2)],
                [isoX(bp + lw, o1), isoY(bp + lw, o1, z1)]
              ], fillC, edgeC, leadA * 0.95);
            }
          }
        }
        drawLeads(false);

        drawBox3D(-phw, -phw, phw, phw, baseZ, baseZ - baseTh,
          pkgTop, pkgSide1, pkgSide2, pkgStroke, pkgAlpha);

        drawLeads(true);

        // Wirebonds — fade out as the lid encloses them (they live inside the package)
        var wbA = smooth(44, 45.5, t) * (1 - smooth(46.2, 47.2, t)) * pkgAlpha;
        if (wbA > 0.01) {
          ctx.strokeStyle = '#fbbf24'; ctx.lineWidth = 1.2 * sc; ctx.globalAlpha = wbA * 0.75;
          ctx.beginPath();
          var bondStep = phw * 0.28;
          for (var bx = -phw * 0.8; bx <= phw * 0.8; bx += bondStep) {
            var chipEdge = chipHW * 0.85;
            ctx.moveTo(isoX(bx, -chipEdge), isoY(bx, -chipEdge, 30 * sc));
            ctx.quadraticCurveTo(isoX(bx, -chipEdge - 10 * sc), isoY(bx, -chipEdge - 10 * sc, 45 * sc), isoX(bx, -phw * 0.9), isoY(bx, -phw * 0.9, baseZ));
            ctx.moveTo(isoX(bx, chipEdge), isoY(bx, chipEdge, 30 * sc));
            ctx.quadraticCurveTo(isoX(bx, chipEdge + 10 * sc), isoY(bx, chipEdge + 10 * sc, 45 * sc), isoX(bx, phw * 0.9), isoY(bx, phw * 0.9, baseZ));
          }
          ctx.stroke();
        }

        // Lid — brushed-metal heat spreader that fully ENCLOSES the die
        // (the old version was a thin slab floating 55px above the substrate with
        // glowing text — sides now reach the package top like a real IHS/can)
        var lidA = smooth(45.5, 47, t) * pkgAlpha;
        if (lidA > 0.01) {
          var lsc = sc * masterScale;
          var lidTopZ = 42 * lsc;
          var lidZ = lerp(300, lidTopZ, easeOut(lidA));
          var fw = phw * 0.94;
          var mTop   = pick('rgba(168,180,196,0.98)', 'rgba(206,215,227,0.98)');
          var mTopHi = pick('rgba(199,209,222,0.98)', 'rgba(228,235,244,0.98)');
          var mSideA = pick('rgba(104,116,134,0.97)', 'rgba(156,168,184,0.97)');
          var mSideB = pick('rgba(126,138,156,0.97)', 'rgba(175,186,201,0.97)');
          var mEdge  = pick('#7d8b9d', '#98a6b8');
          // Body: sides drop all the way to the package substrate (encloses the die)
          drawBox3D(-fw, -fw, fw, fw, lidZ, lidZ - (lidTopZ - baseZ), mTop, mSideA, mSideB, mEdge, lidA * pkgAlpha);
          // Raised polished cap in the center
          var cw2 = phw * 0.62, cTh = 8 * lsc;
          drawBox3D(-cw2, -cw2, cw2, cw2, lidZ + cTh, lidZ, mTopHi, mSideA, mSideB, mEdge, lidA * pkgAlpha);
          // Brushed sheen sweeping the cap as it settles
          var shW = cw2 * 0.5, shOff = cw2 * lerp(-0.9, 0.35, easeOut(lidA));
          drawQuad([
            [isoX(shOff - shW, -cw2), isoY(shOff - shW, -cw2, lidZ + cTh)],
            [isoX(shOff + shW * 0.4, -cw2), isoY(shOff + shW * 0.4, -cw2, lidZ + cTh)],
            [isoX(shOff + shW, cw2), isoY(shOff + shW, cw2, lidZ + cTh)],
            [isoX(shOff - shW * 0.4, cw2), isoY(shOff - shW * 0.4, cw2, lidZ + cTh)]
          ], 'rgba(255,255,255,0.55)', null, lidA * pkgAlpha * 0.14);

          // Laser-etched markings — matte dark grey, like real lid engraving
          ctx.save();
          ctx.setTransform(DPR * cosA, DPR * sinA, -DPR * cosA, DPR * sinA, DPR * ox, DPR * (oy - (lidZ + cTh)));
          var etch = pick('rgba(52,62,78,0.92)', 'rgba(60,72,90,0.92)');
          ctx.globalAlpha = lidA * pkgAlpha;
          ctx.strokeStyle = etch; ctx.lineWidth = 1 * lsc;
          var badgeW = 46 * lsc, badgeH = 19 * lsc;
          var badgePerim = 2 * (badgeW * 2 + badgeH * 2);
          ctx.setLineDash([badgePerim]);
          ctx.lineDashOffset = badgePerim * (1 - easeOut(lidA));
          ctx.strokeRect(-badgeW, -badgeH, badgeW * 2, badgeH * 2);
          ctx.setLineDash([]);
          ctx.fillStyle = etch;
          ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          ctx.font = '600 ' + Math.floor(15 * lsc) + 'px "Inter","Segoe UI",sans-serif';
          ctx.fillText('LanEx', 0, -4.5 * lsc);
          ctx.globalAlpha = lidA * pkgAlpha * 0.8;
          ctx.font = Math.floor(7 * lsc) + 'px "JetBrains Mono",Consolas,monospace';
          ctx.fillText('RTL → GDSII', 0, 9.5 * lsc);
          // Pin-1 index dot etched near the corner
          ctx.beginPath(); ctx.arc(-cw2 * 0.74, cw2 * 0.74, 2.6 * lsc, 0, 6.28); ctx.fill();
          ctx.restore();
        }
        ctx.globalCompositeOperation = 'lighter';
      }

      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = 'source-over';
      ctx.restore();
    }

    /* --- Animation loop --- */
    var running = true;
    var lastRafTime = performance.now();
    var frameDrops = 0;
    var isLowPerf = false;

    d.addEventListener('visibilitychange', function() {
      if (d.hidden) { running = false; }
      else if (!running && !paused) {
        // Re-anchor the clock so the movie resumes where it left off
        // instead of jumping ahead by however long the tab was hidden.
        animOffset = scrubValue - performance.now() / 1000;
        running = true; lastRafTime = performance.now(); raf();
      }
    });

    function raf() {
      if (!running) return;
      // When paused, don't burn cycles — wait for resume (play button).
      if (paused) { running = false; return; }
      var now = performance.now();
      var dt = now - lastRafTime;
      lastRafTime = now;

      if (dt > 45) { // < ~22 FPS
        frameDrops++;
      } else {
        frameDrops = Math.max(0, frameDrops - 1);
      }

      if (frameDrops > 20 && !isLowPerf) {
        isLowPerf = true;
        d.body.classList.add('low-perf');
        // Cap DPR and re-fit so the raster stays crisp without tanking fill rate.
        if (DPR > 1) { DPR = 1; resize(); }
        console.warn('Low performance detected, disabling heavy CSS effects.');
      }

      try { render(now / 1000); } catch(e) { console.error('Render:', e); }
      w.requestAnimationFrame(raf);
    }
    raf();

    /* Keyboard: 'C' toggles the autoplay fake cursor */
    var fakeCursorEl = $('fakeCursor');
    w.addEventListener('keydown', function (e) {
      if (e.defaultPrevented) return;
      if (e.key === 'c' || e.key === 'C') {
        if (!fakeCursorEl) return;
        fakeCursorEl.classList.toggle('user-disabled');
        if (fakeCursorEl.classList.contains('user-disabled')) fakeCursorEl.classList.remove('visible');
      }
    });

    })(); // end isolated canvas init
  } catch (e) { console.error('Init err:', e); }

  /* ------------------------------------------------------------------ */
  /*  Milestone Scroll Spy                                                */
  /* ------------------------------------------------------------------ */
  try {
    var sections = d.querySelectorAll('section');
    var mileDots = d.querySelectorAll('.milestone-dot');
    if (sections.length > 0 && mileDots.length > 0 && w.IntersectionObserver) {
      var mo = new IntersectionObserver(function(entries) {
        entries.forEach(function(entry) {
          if (entry.isIntersecting) {
            mileDots.forEach(function(dot) { dot.classList.remove('active'); });
            var activeDot = d.querySelector('.milestone-dot[href="#' + entry.target.id + '"]');
            if (activeDot) activeDot.classList.add('active');
          }
        });
      }, { threshold: 0.2, rootMargin: "-10% 0px -40% 0px" });
      sections.forEach(function(sec) { mo.observe(sec); });
    }
  } catch (e) { console.error('Milestone err:', e); }

  /* ------------------------------------------------------------------ */
  /*  Scroll-to-top button                                               */
  /* ------------------------------------------------------------------ */
  try {
    var sTop = $('scrollTop');
    if (sTop) {
      var stTicking = false;
      w.addEventListener('scroll', function() {
        if (!stTicking) {
          w.requestAnimationFrame(function() {
            sTop.classList.toggle('visible', w.scrollY > 500);
            stTicking = false;
          });
          stTicking = true;
        }
      }, { passive: true });
      sTop.addEventListener('click', function() {
        w.scrollTo({ top: 0, behavior: REDUCED ? 'auto' : 'smooth' });
      });
    }
  } catch (e) {}

})();

/* ------------------------------------------------------------------ */
/*  Home-screen contract (LanEx cockpit integration)                   */
/*  - "skip this screen next time" persists to `ll.landing`            */
/*  - [data-launch] links fade the page out, then enter the cockpit    */
/*  Shares the `ll.theme` / `ll.landing` keys with the running app.    */
/* ------------------------------------------------------------------ */
(function () {
  'use strict';
  var d = document;
  var REDUCED = false;
  try { REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) {}

  /* "Skip this screen next time" checkbox. */
  var skipBox = d.getElementById('skip-next');
  if (skipBox) {
    try { skipBox.checked = localStorage.getItem('ll.landing') === 'skip'; } catch (e) {}
    skipBox.addEventListener('change', function () {
      try {
        if (this.checked) localStorage.setItem('ll.landing', 'skip');
        else localStorage.removeItem('ll.landing');
      } catch (e) {}
    });
  }

  /* [data-launch] → into the cockpit, with a quick fade unless reduced-motion. */
  var launchers = d.querySelectorAll('[data-launch]');
  Array.prototype.forEach.call(launchers, function (a) {
    a.addEventListener('click', function (ev) {
      var href = a.getAttribute('href');
      if (!href || REDUCED) return;               // plain navigation
      ev.preventDefault();
      d.body.classList.add('is-launching');
      setTimeout(function () { window.location.href = href; }, 330);
    });
  });
})();