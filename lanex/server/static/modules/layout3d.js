// layout3d.js — the Layout tab's 3D view (WebGL, no library).
//
// The server sends each layer's merged shapes as flat triangles plus their
// outline edges (controller/layoutview.mesh); here every layer becomes a slab
// between its real bottom and top height (from the PDK's GDS3D process file),
// with the walls extruded from the edges. Heights can be exaggerated (a real
// metal stack is ~6 µm tall on a chip ~100 µm wide, so true scale reads flat)
// and the stack can be spread open, as GDS3D and the Tiny Tapeout viewer do.
// Both are visual scales only: the order and the relative heights stay real.
//
// Looks: a studio set rather than a CAD void. A graded backdrop, a ground grid
// in µm under a thin silicon base with a soft contact shadow, a hemisphere
// ambient with a key and a fill light, a gentle specular on the metals, shaded
// wall bases (cheap ambient occlusion), crisp outlines on the top faces when
// they are big enough to read, and a touch of depth fog. Everything is drawn on
// demand; the only loops are the intro move and the opt-in turntable, and both
// stop the moment the view is hidden.

// ------------------------------------------------------------------ shaders
const VS = `
attribute vec3 aPos;      // x, y (µm from origin), t (0 = bottom, 1 = top)
attribute vec2 aNrm;      // wall normal (x, y); (0, 0) marks a top face
uniform mat4 uMvp;
uniform float uZ0, uZ1;
varying vec3 vNrm;
varying vec3 vPos;
varying float vT;
void main() {
  vec3 p = vec3(aPos.xy, mix(uZ0, uZ1, aPos.z));
  vNrm = dot(aNrm, aNrm) > 0.0 ? vec3(aNrm, 0.0) : vec3(0.0, 0.0, 1.0);
  vPos = p;
  vT = aPos.z;
  gl_Position = uMvp * vec4(p, 1.0);
}`;

const FS = `
precision mediump float;
uniform vec3 uColor;
uniform vec3 uEye;
uniform float uMetal;
uniform vec3 uSky, uGnd;
uniform vec3 uKeyDir, uKeyCol, uFillDir, uFillCol;
uniform vec3 uFog;
uniform vec2 uFogRange;
varying vec3 vNrm;
varying vec3 vPos;
varying float vT;
void main() {
  vec3 v = normalize(uEye - vPos);
  vec3 n = normalize(vNrm);
  if (dot(n, v) < 0.0) n = -n;                     // double-sided walls
  vec3 base = pow(uColor, vec3(2.2));
  vec3 hemi = mix(uGnd, uSky, n.z * 0.5 + 0.5);
  float k = max(dot(n, uKeyDir), 0.0);
  float f = max(dot(n, uFillDir), 0.0);
  float wall = 1.0 - abs(n.z);
  float ao = mix(1.0, mix(0.42, 1.0, vT), wall);   // wall feet sit in shade
  vec3 c = base * (hemi + uKeyCol * k + uFillCol * f) * ao;
  vec3 h = normalize(uKeyDir + v);
  float sp = pow(max(dot(n, h), 0.0), mix(18.0, 72.0, uMetal));
  float fr = pow(1.0 - max(dot(n, v), 0.0), 4.0);
  c += uKeyCol * sp * (0.03 + 0.42 * uMetal) + uSky * fr * (0.05 + 0.10 * uMetal);
  c = pow(c, vec3(1.0 / 2.2));
  float fog = smoothstep(uFogRange.x, uFogRange.y, length(uEye - vPos));
  gl_FragColor = vec4(mix(c, uFog, fog * 0.6), 1.0);
}`;

const LINE_VS = `
attribute vec3 aPos;
uniform mat4 uMvp;
uniform float uZ0, uZ1;
varying vec3 vPos;
void main() {
  vec3 p = vec3(aPos.xy, mix(uZ0, uZ1, aPos.z));
  vPos = p;
  gl_Position = uMvp * vec4(p, 1.0);
}`;

const LINE_FS = `
precision mediump float;
uniform vec4 uColor;
uniform vec3 uEye;
uniform vec2 uFogRange;
varying vec3 vPos;
void main() {
  float fog = smoothstep(uFogRange.x, uFogRange.y, length(uEye - vPos));
  gl_FragColor = vec4(uColor.rgb, uColor.a * (1.0 - fog * 0.8));
}`;

// The backdrop: a vertical grade with a soft vignette, in clip space.
const BG_VS = `
attribute vec2 aPos;
varying vec2 vUv;
void main() { vUv = aPos * 0.5 + 0.5; gl_Position = vec4(aPos, 0.999, 1.0); }`;
const BG_FS = `
precision mediump float;
uniform vec3 uTop, uBot;
uniform float uVig;
varying vec2 vUv;
void main() {
  vec3 c = mix(uBot, uTop, smoothstep(0.0, 1.0, vUv.y));
  vec2 d = vUv - vec2(0.5, 0.56);
  c *= 1.0 - uVig * smoothstep(0.25, 0.95, length(d * vec2(1.25, 1.0)));
  gl_FragColor = vec4(c, 1.0);
}`;

// The ground: a µm grid fading out round the chip, and the chip's soft
// contact shadow. Without derivatives (rare) only the shadow is drawn.
const GROUND_VS = `
attribute vec2 aPos;
uniform mat4 uMvp;
uniform float uZ;
varying vec2 vXY;
void main() { vXY = aPos; gl_Position = uMvp * vec4(aPos, uZ, 1.0); }`;
const groundFs = (deriv) => `${deriv ? "#extension GL_OES_standard_derivatives : enable\n" : ""}
precision mediump float;
uniform vec2 uCenter, uHalf;
uniform float uStep, uFade, uBlur, uShadow;
uniform vec4 uGrid;
varying vec2 vXY;
float line(vec2 p, float s) {
${deriv ? `  vec2 q = p / s;
  vec2 g = abs(fract(q - 0.5) - 0.5) / max(fwidth(q), vec2(1e-6));
  return 1.0 - min(min(g.x, g.y), 1.0);` : "  return 0.0;"}
}
void main() {
  vec2 p = vXY - uCenter;
  float r = length(p / max(uHalf.x, uHalf.y));
  float fade = 1.0 - smoothstep(1.1, uFade, r);
  float gl = max(line(p, uStep) * 0.55, line(p, uStep * 5.0));
  float ga = uGrid.a * gl * fade;
  vec2 q = abs(p) - uHalf;
  float d = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0);
  float sa = uShadow * (1.0 - smoothstep(-uBlur * 0.6, uBlur, d));
  float a = ga + sa - ga * sa;
  vec3 c = a > 0.0 ? uGrid.rgb * ga * (1.0 - sa) / a : vec3(0.0);
  gl_FragColor = vec4(c, a);
}`;

// ------------------------------------------------------------------ colour schemes
// The layer's job decides its colour, so every PDK reads the same way: metals
// take the app's own layer hues (met1 blue ... met5 orange, as on every LanEx
// page), vias a light tint of the metal under them, contacts tungsten grey.
// "Metallic" is copper-to-gold metals over grey silicon; "PDK" is the process
// file's own colours (what GDS3D shows, close to the 2D layer colours).
export const SCHEMES = {
  lanex: {
    label: "LanEx",
    metals: ["#4da3ff", "#e879c9", "#36d399", "#f2c14e", "#ff7a45", "#a98bff", "#dbe4ef"],
    via: (m) => mixHex(m, "#ffffff", 0.42),
    contact: "#aab4c3", li: "#8ea6c4", poly: "#d6446f", diff: "#4f9e83", tap: "#9aa35e",
    well: "#2c3f57", implant: "#3a3550", mim: "#c9b27a", other: "#7d8ca3",
    base: "#121a26",
  },
  metallic: {
    label: "Metallic",
    metals: ["#c3774a", "#cc8650", "#d49558", "#dba762", "#e2b86e", "#e8c780", "#eed594"],
    via: () => "#b9bec6",
    contact: "#a3a9b2", li: "#9b9087", poly: "#a24b5c", diff: "#5f7069", tap: "#6e6c58",
    well: "#2a2e35", implant: "#33313a", mim: "#b8a27a", other: "#7b7f86",
    base: "#17191d",
  },
  pdk: { label: "PDK", base: "#141922" },
};
export const SCHEME_ORDER = ["lanex", "metallic", "pdk"];

// What a layer is, from its process-file name: sky130 (met1, via, licon1, li1),
// gf180 (Metal1, Via1, Contact, COMP, Poly2), IHP (Metal1, TopMetal1, TopVia1,
// Cont, Activ, GatPoly, MIM, Vmim). `n` numbers the metals bottom up, IHP's top
// metals continuing after Metal5; a via's `n` is the metal under it.
export function layerRole(name) {
  const s = String(name || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  let m;
  if ((m = s.match(/^(?:met|metal|m)(\d)$/))) return { kind: "metal", n: +m[1] };
  if ((m = s.match(/^topmetal(\d)$/))) return { kind: "metal", n: 5 + +m[1] };
  if (s === "metaltop") return { kind: "metal", n: 6 };
  if (s === "rdl") return { kind: "metal", n: 7 };
  if (s === "via") return { kind: "via", n: 1 };
  if ((m = s.match(/^via(\d)$/))) return { kind: "via", n: +m[1] };
  if ((m = s.match(/^topvia(\d)$/))) return { kind: "via", n: 4 + +m[1] };
  if (s === "vmim") return { kind: "via", n: 5 };
  if (/^(licon\d?|mcon|cont|contact|co)$/.test(s)) return { kind: "contact", n: 0 };
  if (/^li\d?$/.test(s)) return { kind: "li", n: 0 };
  if (/poly/.test(s)) return { kind: "poly", n: 0 };
  if (/^(tap|ptap|ntap)$/.test(s)) return { kind: "tap", n: 0 };
  if (/^(diff|activ|active|comp|od)$/.test(s)) return { kind: "diff", n: 0 };
  if (/well$/.test(s)) return { kind: "well", n: 0 };
  if (/^(psdm|nsdm|psd|nsd|npc|hvi|implant)/.test(s)) return { kind: "implant", n: 0 };
  if (s === "mim" || s === "capm") return { kind: "mim", n: 0 };
  return { kind: "other", n: 0 };
}

// The colour a layer gets in a scheme ("pdk" or unknown: the file's own).
export function schemeColor(scheme, L) {
  const S = SCHEMES[scheme];
  if (!S || !S.metals) return L.color || "#8ea6c4";
  const r = layerRole(L.name);
  const metal = (n) => S.metals[Math.max(0, Math.min(S.metals.length - 1, n - 1))];
  switch (r.kind) {
    case "metal": return metal(r.n);
    case "via": return S.via(metal(r.n));
    case "contact": return S.contact;
    case "li": return S.li;
    case "poly": return S.poly;
    case "diff": return S.diff;
    case "tap": return S.tap;
    case "well": return S.well;
    case "implant": return S.implant;
    case "mim": return S.mim;
    default: return L.color ? mixHex(L.color, S.other, 0.5) : S.other;
  }
}

// Cut layers (vias, contacts) join the layers above and below them; when the
// stack is spread open they stretch across the gap instead of floating.
export function isCut(name) {
  const k = layerRole(name).kind;
  return k === "via" || k === "contact";
}

// Spread opens a gap at every level where a non-cut layer starts (metal,
// poly, diffusion, well ...). Returns each layer's level at its bottom and top:
// rigid layers move as one, cut layers span from their own level up to the
// level of the layer they reach.
export function stackLevels(layers) {
  const eps = 1e-6;
  const breaks = [...new Set(layers.filter((L) => !isCut(L.name)).map((L) => +L.z0.toFixed(5)))].sort((a, b) => a - b);
  const count = (z, incl) => breaks.filter((b) => (incl ? b <= z + eps : b < z - eps)).length;
  const levels = layers.map((L) => {
    const lo = Math.max(0, count(L.z0, true) - 1);
    const hi = isCut(L.name) ? Math.max(lo, count(L.z1, true) - 1) : Math.max(lo, count(L.z1, false) - 1);
    return [lo, hi];
  });
  return { levels, gaps: Math.max(1, breaks.length - 1) };
}

// Good first values for the two sliders, from the footprint and the real stack
// height (substrate to the top metal): the stack, exaggerated and then opened
// by the spread, stands under a quarter as tall as the chip is wide, so a 60 µm
// blinky (×1.5), a 150 µm IHP counter (×1.5), a 250 µm gf180 FIFO (×5) and a
// 480 µm 12k-cell array (×9.75) all read as a city block rather than a pancake
// or a tower. Picked by eye on those real runs. Never below true scale.
export const SPREAD_DEFAULT = 0.7;
export const STACK_TO_SPAN = 0.23;
export function defaults3d(span, stackH) {
  const spread = SPREAD_DEFAULT;
  if (!(span > 0) || !(stackH > 0)) return { z: 2, spread, zMax: 16 };
  const raw = (STACK_TO_SPAN * span) / (stackH * (1 + spread));
  const z = Math.max(1, Math.round(raw * 4) / 4);
  return { z, spread, zMax: Math.max(16, Math.ceil(z * 2.5)) };
}

// The slider readouts.
export function fmtHeight(z) { return "×" + (+z).toFixed(2).replace(/\.?0+$/, ""); }
export function fmtSpread(s) { return Math.round(s * 100) + "%"; }

// A round grid step (1, 2, 5 × 10^n µm) giving ~8 cells across `span`.
export function gridStep(span) {
  const t = Math.max(span, 1e-3) / 8;
  const p = Math.pow(10, Math.floor(Math.log10(t)));
  const m = t / p;
  return (m >= 5 ? 5 : m >= 2 ? 2 : 1) * p;
}

// ------------------------------------------------------------------ the view
const LOOK = {
  dark: {
    top: "#111b2b", bot: "#05080d", vig: 0.42, fog: "#070b12",
    sky: [0.36, 0.40, 0.48], gnd: [0.10, 0.09, 0.08], key: [0.95, 0.92, 0.86], fill: [0.22, 0.30, 0.44],
    grid: [0.42, 0.58, 0.82, 0.16], shadow: 0.62, edge: 0.55, edgeTo: "#04060a",
  },
  light: {
    top: "#fbfcfe", bot: "#dfe5ee", vig: 0.10, fog: "#e6ebf2",
    sky: [0.50, 0.53, 0.58], gnd: [0.16, 0.15, 0.14], key: [0.88, 0.86, 0.82], fill: [0.22, 0.26, 0.34],
    grid: [0.20, 0.27, 0.37, 0.20], shadow: 0.30, edge: 0.45, edgeTo: "#0b1220",
  },
};
const FOV = 0.70;
const HOME = { theta: -1.02, phi: 0.98 };           // a three-quarter view from the south-east
const TOP = { theta: -Math.PI / 2, phi: 0.02 };      // straight down, as the 2D view
const reduceMotion = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

export class Layout3D {
  constructor(wrap, opts = {}) {
    this.wrap = wrap;
    this.opts = opts;      // { onKey(k), onSpin(on) }
    this.cv = document.createElement("canvas");
    this.cv.className = "lx-cv lx-cv3d";
    this.cv.tabIndex = 0;
    this.cv.setAttribute("aria-label", "3D layout. Drag to turn, right-drag to move, scroll to zoom, arrow keys turn, F frames the chip.");
    this.cv.hidden = true;
    wrap.prepend(this.cv);
    const gl = this.cv.getContext("webgl", { antialias: true, alpha: false, preserveDrawingBuffer: true });
    this.gl = gl;
    this.ok = !!gl;
    this.layers = [];
    this.visible = null;     // Set of layer ids, or null = all
    this.zScale = 2;
    this.spread = SPREAD_DEFAULT;
    this.scheme = "lanex";
    this.look = "dark";
    this.auto = true;        // the sliders follow each chip's defaults until moved
    this.lift = 1;           // 0..1: the intro raises the stack out of the 2D plane
    this.spin = false;
    this.cam = { theta: HOME.theta, phi: HOME.phi, dist: 100, tx: 0, ty: 0, tz: 0 };
    this.extent = null;
    this.stackH = 0;
    if (!this.ok) return;
    this._deriv = !!gl.getExtension("OES_standard_derivatives");
    this._progs();
    this._statics();
    this._wire();
    this._ro = new ResizeObserver(() => this._resize());
    this._ro.observe(wrap);
    this._onZoom = () => this._resize();          // UI size changed: re-sharpen
    window.addEventListener("g:zoom", this._onZoom);
    this._onVis = () => { if (document.hidden) this.setSpin(false); };
    document.addEventListener("visibilitychange", this._onVis);
  }

  show(on) {
    this.cv.hidden = !on;
    if (on) { this._resize(); this.draw(); }
    else { this._stopAnim("jump"); this.setSpin(false); }
  }

  // "dark" or "light": the backdrop, lights and grid (the 2D background choice).
  setBg(hex) {
    this.look = /^#?f/i.test(hex) ? "light" : "dark";
    this._recolor();
    this.draw();
  }

  setScheme(s) { this.scheme = SCHEMES[s] ? s : "lanex"; this._recolor(); this.draw(); }
  setVisible(set) { this.visible = set; this.draw(); }
  setZScale(z) { this.zScale = z; this.draw(); }
  setSpread(s) { this.spread = s; this.draw(); }
  colorOf(id) { const L = this.layers.find((x) => x.id === id); return L ? L.hex : null; }
  defaults() { return defaults3d(this.extent ? Math.max(this.extent[2], this.extent[3]) : 0, this.stackTop || this.stackH); }

  // ------------------------------------------------------------- data
  load(buf, { animate = false } = {}) {
    const gl = this.gl;
    this._stopAnim("jump");
    for (const L of this.layers) { gl.deleteBuffer(L.vbo); gl.deleteBuffer(L.lbo); }
    this.layers = [];
    const dv = new DataView(buf);
    const hlen = dv.getUint32(0, true);
    const head = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, hlen)));
    const base = 4 + hlen;
    const tri = new Float32Array(buf, base, head.triFloats);
    const edg = new Float32Array(buf, base + head.triFloats * 4, head.edgeFloats);
    this.head = head;
    const ex = head.extent;
    this.extent = [0, 0, ex[2] - ex[0], ex[3] - ex[1]];
    // Same footprint as the mesh on screen (another stage of the same chip, or
    // the same region): keep the user's camera. A new chip or region is framed.
    const tol = 0.02 * Math.max(this.extent[2], this.extent[3]);
    const keepCam = !!this._ex && this._ex.every((v, i) => Math.abs(v - ex[i]) <= tol);
    this._ex = ex.slice();
    const sorted = head.layers.slice().sort((a, b) => a.z0 - b.z0 || a.z1 - b.z1);
    const { levels, gaps } = stackLevels(sorted);
    this.gaps = gaps;
    const zs = sorted.map((L) => [L.z0, L.z1]).flat();
    this.zLo = zs.length ? Math.min(...zs) : 0;
    this.stackH = zs.length ? Math.max(...zs) - this.zLo : 0;
    // For the default height: the whole stack from the substrate, even when
    // the lowest layers are hidden or left out.
    this.stackTop = zs.length ? Math.max(...zs) - Math.min(0, this.zLo) : 0;
    sorted.forEach((L, i) => {
      const nv = L.tris * 3 + L.edges * 6;
      const data = new Float32Array(nv * 5);
      let k = 0;
      const put = (x, y, t, nx, ny) => { data[k++] = x; data[k++] = y; data[k++] = t; data[k++] = nx; data[k++] = ny; };
      for (let j = 0; j < L.tris; j++) {
        const o = L.triOff + j * 6;
        put(tri[o], tri[o + 1], 1, 0, 0);
        put(tri[o + 2], tri[o + 3], 1, 0, 0);
        put(tri[o + 4], tri[o + 5], 1, 0, 0);
      }
      // Walls, and the top outline as line pairs.
      const lines = new Float32Array(L.edges * 6);
      let q = 0;
      for (let j = 0; j < L.edges; j++) {
        const o = L.edgeOff + j * 4;
        const x1 = edg[o], y1 = edg[o + 1], x2 = edg[o + 2], y2 = edg[o + 3];
        let nx = y2 - y1, ny = -(x2 - x1);
        const n = Math.hypot(nx, ny) || 1;
        nx /= n; ny /= n;
        put(x1, y1, 0, nx, ny); put(x2, y2, 0, nx, ny); put(x2, y2, 1, nx, ny);
        put(x1, y1, 0, nx, ny); put(x2, y2, 1, nx, ny); put(x1, y1, 1, nx, ny);
        lines[q++] = x1; lines[q++] = y1; lines[q++] = 1;
        lines[q++] = x2; lines[q++] = y2; lines[q++] = 1;
      }
      const vbo = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
      gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
      const lbo = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, lbo);
      gl.bufferData(gl.ARRAY_BUFFER, lines, gl.STATIC_DRAW);
      this.layers.push({ ...L, vbo, lbo, count: nv, lcount: L.edges * 2, lv: levels[i],
        role: layerRole(L.name), cut: isCut(L.name) });
    });
    this._recolor();
    if (!keepCam) {
      // A new chip: the sliders start at its own good values, unless the
      // person has set them (this.auto false).
      if (this.auto) { const d = this.defaults(); this.zScale = d.z; this.spread = d.spread; }
      this.reset(false, { animate });
    }
    this.draw();
    return head;
  }

  _recolor() {
    const look = LOOK[this.look];
    for (const L of this.layers) {
      L.hex = schemeColor(this.scheme, L);
      L.rgb = rgb(L.hex);
      L.edge = rgb(mixHex(L.hex, look.edgeTo, look.edge));
      L.metal = L.role.kind === "metal" ? 1 : L.cut ? 0.7 : L.role.kind === "li" ? 0.35 : 0.08;
    }
    const sb = SCHEMES[this.scheme].base;
    this.baseRgb = rgb(this.look === "light" ? mixHex(sb, "#d5dce6", 0.78) : sb);
  }

  // Frame the chip from the starting angle; with `animate`, rise out of the
  // flat 2D picture into it (skipped when motion is reduced).
  reset(draw = true, { animate = false } = {}) {
    if (!this.extent) return;
    this._stopAnim("jump");
    const end = this._framed(HOME.theta, HOME.phi, 1);
    if (animate && !reduceMotion() && !this.cv.hidden) {
      const start = this._framed(TOP.theta, TOP.phi, 0);
      Object.assign(this.cam, start);
      this.lift = 0;
      this._anim = { t0: performance.now(), dur: 1500, from: start, to: end };
      this._loop();
      return;
    }
    Object.assign(this.cam, end);
    this.lift = 1;
    if (draw) this.draw();
  }

  // The camera that fits the chip's footprint and (exaggerated, spread) stack
  // on screen at this angle.
  _framed(theta, phi, lift) {
    const w = this.extent[2], h = this.extent[3];
    const keep = this.lift;
    this.lift = lift;
    const [zlo, zhi] = this._zRange();
    this.lift = keep;
    const cam = { theta, phi, tx: w / 2, ty: h / 2, tz: (zlo + zhi) / 2 };
    const pts = [];
    for (const x of [0, w]) for (const y of [0, h]) for (const z of [zlo - this._baseT(), zhi]) pts.push([x, y, z]);
    const aspect = Math.max(this.cv.width, 1) / Math.max(this.cv.height, 1);
    const sh = this._shift();
    const AX = 0.88 * (1 - sh), AY = 0.82;
    const ndc = (d) => {
      const m = this._mvp({ ...cam, dist: d }, aspect).m;
      const b = [Infinity, Infinity, -Infinity, -Infinity];
      for (const [x, y, z] of pts) {
        const cw = m[3] * x + m[7] * y + m[11] * z + m[15];
        if (cw <= 0) return null;
        const nx = (m[0] * x + m[4] * y + m[8] * z + m[12]) / cw + sh, ny = (m[1] * x + m[5] * y + m[9] * z + m[13]) / cw;
        b[0] = Math.min(b[0], nx); b[1] = Math.min(b[1], ny); b[2] = Math.max(b[2], nx); b[3] = Math.max(b[3], ny);
      }
      return b;
    };
    const fits = (d) => { const b = ndc(d); return !!b && -b[0] < AX && b[2] < AX && -b[1] < AY && b[3] < AY; };
    const fit = () => {
      let lo = Math.max(w, h) * 0.05, hi = Math.max(w, h, zhi - zlo) * 20;
      for (let i = 0; i < 28; i++) { const mid = (lo + hi) / 2; if (fits(mid)) hi = mid; else lo = mid; }
      return hi;
    };
    // Fit, then slide the target so the chip sits in the middle of the free
    // space (a tilted view puts the far edge high and the near edge low), and
    // fit again.
    let d = fit();
    for (let k = 0; k < 2; k++) {
      const b = ndc(d);
      if (!b) break;
      const mx = (b[0] + b[2]) / 2, my = (b[1] + b[3]) / 2;
      const hh = d * Math.tan(FOV / 2), hw = hh * aspect;
      const cp = Math.cos(phi), sp = Math.sin(phi), ct = Math.cos(theta), st = Math.sin(theta);
      cam.tx += -st * mx * hw - cp * ct * my * hh;
      cam.ty += ct * mx * hw - cp * st * my * hh;
      cam.tz += sp * my * hh;
      d = fit();
    }
    return { ...cam, dist: d };
  }

  // The opt-in turntable: a slow turn for showing the chip off.
  setSpin(on) {
    on = !!on && !reduceMotion() && this.layers.length > 0;
    if (on === this.spin) return;
    this.spin = on;
    if (this.opts.onSpin) this.opts.onSpin(on);
    if (on) { this._lastT = 0; this._loop(); }
  }

  // Ends the intro: "jump" lands on its last frame (new data, hidden view),
  // "here" keeps the camera where the person grabbed it, stack fully raised.
  _stopAnim(how) {
    if (!this._anim) return;
    if (how === "jump") Object.assign(this.cam, this._anim.to);
    if (how) this.lift = 1;
    this._anim = null;
  }

  _loop() {
    if (this._looping) return;
    this._looping = true;
    const step = (now) => {
      if ((!this._anim && !this.spin) || this.cv.hidden || document.hidden) { this._looping = false; return; }
      if (this._anim) {
        const a = this._anim;
        const t = Math.min(1, (now - a.t0) / a.dur);
        const e = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;   // ease in-out cubic
        const lift = 1 - Math.pow(1 - Math.min(1, Math.max(0, (t - 0.12) / 0.88)), 3);
        for (const k of ["theta", "phi", "dist", "tx", "ty", "tz"]) this.cam[k] = a.from[k] + (a.to[k] - a.from[k]) * e;
        this.lift = lift;
        if (t >= 1) { this._anim = null; this.lift = 1; }
      }
      if (this.spin) {
        const dt = this._lastT ? Math.min(0.05, (now - this._lastT) / 1000) : 0;
        this.cam.theta -= dt * 0.16;
        this._lastT = now;
      }
      this._draw();
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  // ------------------------------------------------------------- GL
  _progs() {
    const gl = this.gl;
    const sh = (type, src) => {
      const s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
      return s;
    };
    const prog = (vs, fs, attrs, unis) => {
      const p = gl.createProgram();
      gl.attachShader(p, sh(gl.VERTEX_SHADER, vs));
      gl.attachShader(p, sh(gl.FRAGMENT_SHADER, fs));
      gl.linkProgram(p);
      const loc = { p };
      for (const a of attrs) loc[a] = gl.getAttribLocation(p, a);
      for (const u of unis) loc[u] = gl.getUniformLocation(p, u);
      return loc;
    };
    this.P = prog(VS, FS, ["aPos", "aNrm"], ["uMvp", "uZ0", "uZ1", "uColor", "uEye", "uMetal", "uSky", "uGnd",
      "uKeyDir", "uKeyCol", "uFillDir", "uFillCol", "uFog", "uFogRange"]);
    this.PL = prog(LINE_VS, LINE_FS, ["aPos"], ["uMvp", "uZ0", "uZ1", "uColor", "uEye", "uFogRange"]);
    this.PB = prog(BG_VS, BG_FS, ["aPos"], ["uTop", "uBot", "uVig"]);
    this.PG = prog(GROUND_VS, groundFs(this._deriv), ["aPos"], ["uMvp", "uZ", "uCenter", "uHalf", "uStep", "uFade",
      "uBlur", "uShadow", "uGrid"]);
  }

  // The full-screen quad, and a unit box (the silicon base) in the slab format.
  _statics() {
    const gl = this.gl;
    this.quad = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, 1, 1, -1, -1, 1, 1, -1, 1]), gl.STATIC_DRAW);
    const v = [];
    const put = (x, y, t, nx, ny) => v.push(x, y, t, nx, ny);
    put(0, 0, 1, 0, 0); put(1, 0, 1, 0, 0); put(1, 1, 1, 0, 0);
    put(0, 0, 1, 0, 0); put(1, 1, 1, 0, 0); put(0, 1, 1, 0, 0);
    for (const [x1, y1, x2, y2, nx, ny] of [[0, 0, 1, 0, 0, -1], [1, 0, 1, 1, 1, 0], [1, 1, 0, 1, 0, 1], [0, 1, 0, 0, -1, 0]]) {
      put(x1, y1, 0, nx, ny); put(x2, y2, 0, nx, ny); put(x2, y2, 1, nx, ny);
      put(x1, y1, 0, nx, ny); put(x2, y2, 1, nx, ny); put(x1, y1, 1, nx, ny);
    }
    this.box = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.box);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(v), gl.STATIC_DRAW);
    this.boxLines = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.boxLines);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, 0, 1, 1, 0, 1, 1, 0, 1, 1, 1, 1, 1, 1, 1, 0, 1, 1, 0, 1, 1, 0, 0, 1]), gl.STATIC_DRAW);
    this.groundBuf = gl.createBuffer();
  }

  _resize() {
    // CSS size from clientWidth (the client rect is in zoomed px under the
    // app's UI zoom); the backing store adds that zoom to the screen density.
    // On a 1x screen it renders at 1.5x (with the MSAA on top) so thin wires
    // don't shimmer, within a pixel budget that keeps slow GPUs smooth.
    const cw = this.wrap.clientWidth, ch = this.wrap.clientHeight;
    const r = this.wrap.getBoundingClientRect();
    const z = cw && r.width ? r.width / cw : 1;
    let dpr = Math.min(Math.max((window.devicePixelRatio || 1) * z, 1.5), 2.5);
    const budget = 4.2e6;
    if (cw * ch * dpr * dpr > budget) dpr = Math.max(1, Math.sqrt(budget / Math.max(cw * ch, 1)));
    const w = Math.max(1, Math.round(cw * dpr)), h = Math.max(1, Math.round(ch * dpr));
    if (this.cv.width !== w || this.cv.height !== h) {
      this.cv.width = w; this.cv.height = h;
      this.cv.style.width = cw + "px"; this.cv.style.height = ch + "px";
      this.draw();
    }
  }

  // A layer's slab in world z: real heights × zScale, plus the spread gaps of
  // the levels under it; all × lift (0 = flat, during the intro).
  _zOf(L) {
    const gap = (this.spread * this.zScale * this.stackH) / Math.max(this.gaps || 1, 1);
    const k = this.zScale * this.lift;
    const z0 = (L.z0 - this.zLo) * k + L.lv[0] * gap * this.lift;
    const z1 = (L.z1 - this.zLo) * k + L.lv[1] * gap * this.lift;
    return [z0, Math.max(z1, z0 + 1e-4)];
  }

  _zRange() {
    let lo = 0, hi = 0;
    for (const L of this.layers) { const [a, b] = this._zOf(L); lo = Math.min(lo, a); hi = Math.max(hi, b); }
    return [lo, hi];
  }

  _baseT() { return this.extent ? Math.max(this.extent[2], this.extent[3]) * 0.018 : 0; }

  _mvp(c, aspect) {
    const eye = [c.tx + c.dist * Math.sin(c.phi) * Math.cos(c.theta),
                 c.ty + c.dist * Math.sin(c.phi) * Math.sin(c.theta),
                 c.tz + c.dist * Math.cos(c.phi)];
    const span = this.extent ? Math.max(this.extent[2], this.extent[3]) : 1;
    const proj = perspective(FOV, aspect, Math.max(c.dist * 0.01, span * 1e-4), c.dist * 10 + span * 6);
    // Lens shift: the view's centre moves left of a card over its right side.
    proj[8] = this._shift();
    const view = lookAt(eye, [c.tx, c.ty, c.tz], [0, 0, 1]);
    return { m: mul(proj, view), eye };
  }

  // The share of the clip space (0..1) that the controls card covers on the right.
  _shift() {
    const w = this.cv.clientWidth || this.wrap.clientWidth;
    const px = this.opts.inset ? this.opts.inset() : 0;
    return w > 0 && px > 0 && w > px * 2.2 ? px / w : 0;
  }

  draw() {
    if (!this.ok || this.cv.hidden || this._looping) return;
    if (this._raf) return;
    this._raf = requestAnimationFrame(() => { this._raf = 0; this._draw(); });
  }

  _draw() {
    const gl = this.gl;
    const look = LOOK[this.look];
    gl.viewport(0, 0, this.cv.width, this.cv.height);
    gl.disable(gl.DEPTH_TEST);
    gl.depthMask(true);
    gl.clearColor(0, 0, 0, 1);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    // backdrop
    gl.useProgram(this.PB.p);
    gl.uniform3fv(this.PB.uTop, rgb(look.top));
    gl.uniform3fv(this.PB.uBot, rgb(look.bot));
    gl.uniform1f(this.PB.uVig, look.vig);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
    gl.enableVertexAttribArray(this.PB.aPos);
    gl.vertexAttribPointer(this.PB.aPos, 2, gl.FLOAT, false, 0, 0);
    gl.drawArrays(gl.TRIANGLES, 0, 6);
    gl.disableVertexAttribArray(this.PB.aPos);
    if (!this.layers.length || !this.extent) return;

    const c = this.cam;
    const { m, eye } = this._mvp(c, this.cv.width / this.cv.height);
    const W = this.extent[2], H = this.extent[3], span = Math.max(W, H);
    const [zlo] = this._zRange();
    const bt = this._baseT();
    const zBase0 = zlo - bt, zBase1 = zlo - bt * 0.04;
    const fogR = [c.dist * 0.9, c.dist * 2.6 + span];

    // ground: grid and contact shadow (blended, no depth writes)
    gl.enable(gl.DEPTH_TEST);
    gl.depthFunc(gl.LEQUAL);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.depthMask(false);
    const R = span * 3.2, cx = W / 2, cy = H / 2;
    gl.useProgram(this.PG.p);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.groundBuf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([cx - R, cy - R, cx + R, cy - R, cx + R, cy + R, cx - R, cy - R, cx + R, cy + R, cx - R, cy + R]), gl.DYNAMIC_DRAW);
    gl.enableVertexAttribArray(this.PG.aPos);
    gl.vertexAttribPointer(this.PG.aPos, 2, gl.FLOAT, false, 0, 0);
    gl.uniformMatrix4fv(this.PG.uMvp, false, m);
    gl.uniform1f(this.PG.uZ, zBase0);
    gl.uniform2fv(this.PG.uCenter, [cx, cy]);
    gl.uniform2fv(this.PG.uHalf, [W / 2, H / 2]);
    gl.uniform1f(this.PG.uStep, gridStep(span));
    gl.uniform1f(this.PG.uFade, 2.9);
    gl.uniform1f(this.PG.uBlur, span * 0.07);
    gl.uniform1f(this.PG.uShadow, look.shadow);
    gl.uniform4fv(this.PG.uGrid, look.grid);
    gl.drawArrays(gl.TRIANGLES, 0, 6);
    gl.disableVertexAttribArray(this.PG.aPos);
    gl.depthMask(true);
    gl.disable(gl.BLEND);

    // slabs: the silicon base, then every visible layer
    gl.useProgram(this.P.p);
    gl.uniformMatrix4fv(this.P.uMvp, false, m);
    gl.uniform3fv(this.P.uEye, eye);
    gl.uniform3fv(this.P.uSky, look.sky);
    gl.uniform3fv(this.P.uGnd, look.gnd);
    gl.uniform3fv(this.P.uKeyDir, norm([-0.35, -1.0, 1.55]));
    gl.uniform3fv(this.P.uKeyCol, look.key);
    gl.uniform3fv(this.P.uFillDir, norm([0.9, 0.55, 0.45]));
    gl.uniform3fv(this.P.uFillCol, look.fill);
    gl.uniform3fv(this.P.uFog, rgb(look.fog));
    gl.uniform2fv(this.P.uFogRange, fogR);
    gl.enable(gl.POLYGON_OFFSET_FILL);
    gl.polygonOffset(1, 1);
    gl.enableVertexAttribArray(this.P.aPos);
    gl.enableVertexAttribArray(this.P.aNrm);
    const slab = (buf, count, z0, z1, color, metal) => {
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.vertexAttribPointer(this.P.aPos, 3, gl.FLOAT, false, 20, 0);
      gl.vertexAttribPointer(this.P.aNrm, 2, gl.FLOAT, false, 20, 12);
      gl.uniform1f(this.P.uZ0, z0);
      gl.uniform1f(this.P.uZ1, z1);
      gl.uniform3fv(this.P.uColor, color);
      gl.uniform1f(this.P.uMetal, metal);
      gl.drawArrays(gl.TRIANGLES, 0, count);
    };
    // The base box is a unit square: scale it through the MVP.
    const mb = mul(m, [W, 0, 0, 0, 0, H, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
    gl.uniformMatrix4fv(this.P.uMvp, false, mb);
    slab(this.box, 30, zBase0, zBase1, this.baseRgb, 0.15);
    gl.uniformMatrix4fv(this.P.uMvp, false, m);
    const shown = this.layers.filter((L) => !this.visible || this.visible.has(L.id));
    const zs = new Map(shown.map((L) => [L, this._zOf(L)]));
    for (const L of shown) { const [z0, z1] = zs.get(L); slab(L.vbo, L.count, z0, z1, L.rgb, L.metal); }
    gl.disableVertexAttribArray(this.P.aNrm);
    gl.disableVertexAttribArray(this.P.aPos);
    gl.disable(gl.POLYGON_OFFSET_FILL);

    // outlines on the top faces, faded out when the shapes get too small to
    // carry them (a whole big chip would turn to hatching)
    const pxPerUm = (this.cv.height / 2) / (c.dist * Math.tan(FOV / 2));
    const ea = smooth(1.6, 7, pxPerUm) * 0.9;
    gl.useProgram(this.PL.p);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.uniform3fv(this.PL.uEye, eye);
    gl.uniform2fv(this.PL.uFogRange, fogR);
    gl.enableVertexAttribArray(this.PL.aPos);
    const lines = (buf, count, z0, z1, col, a) => {
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.vertexAttribPointer(this.PL.aPos, 3, gl.FLOAT, false, 12, 0);
      gl.uniform1f(this.PL.uZ0, z0);
      gl.uniform1f(this.PL.uZ1, z1);
      gl.uniform4fv(this.PL.uColor, [col[0], col[1], col[2], a]);
      gl.drawArrays(gl.LINES, 0, count);
    };
    gl.uniformMatrix4fv(this.PL.uMvp, false, mb);
    const rim = this.look === "light" ? [0.55, 0.62, 0.72] : [0.30, 0.42, 0.60];
    lines(this.boxLines, 8, zBase0, zBase1, rim, 0.55);
    gl.uniformMatrix4fv(this.PL.uMvp, false, m);
    if (ea > 0.01) for (const L of shown) { const [z0, z1] = zs.get(L); lines(L.lbo, L.lcount, z0, z1, L.edge, ea); }
    gl.disableVertexAttribArray(this.PL.aPos);
    gl.disable(gl.BLEND);
  }

  // ------------------------------------------------------------- input
  _wire() {
    const cv = this.cv;
    let drag = null;
    const touch = () => { this._stopAnim("here"); this.setSpin(false); };
    cv.addEventListener("contextmenu", (e) => e.preventDefault());
    cv.addEventListener("pointerdown", (e) => {
      touch();
      cv.focus({ preventScroll: true });
      cv.setPointerCapture(e.pointerId);
      drag = { x: e.clientX, y: e.clientY, pan: e.button === 2 || e.button === 1 || e.shiftKey };
    });
    cv.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      drag.x = e.clientX; drag.y = e.clientY;
      const c = this.cam;
      if (drag.pan) {
        const k = c.dist / Math.max(this.cv.clientHeight, 1) * 1.1;
        const cs = Math.cos(c.theta), sn = Math.sin(c.theta);
        // screen right = (-sin, cos); screen up projected on the ground = (-cos, -sin)
        c.tx += (dx * sn + dy * cs) * k;
        c.ty += (-dx * cs + dy * sn) * k;
      } else {
        c.theta -= dx * 0.008;
        c.phi = Math.min(Math.max(c.phi - dy * 0.008, 0.02), Math.PI / 2 - 0.02);
      }
      this.draw();
    });
    const up = () => { drag = null; };
    cv.addEventListener("pointerup", up);
    cv.addEventListener("pointercancel", up);
    cv.addEventListener("wheel", (e) => {
      e.preventDefault();
      touch();
      const dy = e.deltaMode === 1 ? e.deltaY * 33 : e.deltaY;
      this.cam.dist = Math.min(Math.max(this.cam.dist * Math.pow(1.0015, dy), 0.05), 1e6);
      this.draw();
    }, { passive: false });
    cv.addEventListener("dblclick", () => this.reset());
    cv.addEventListener("keydown", (e) => {
      if (e.ctrlKey || e.metaKey) return;
      const c = this.cam;
      let hit = true;
      if (e.key === "ArrowLeft") c.theta += 0.12;
      else if (e.key === "ArrowRight") c.theta -= 0.12;
      else if (e.key === "ArrowUp") c.phi = Math.max(c.phi - 0.08, 0.02);
      else if (e.key === "ArrowDown") c.phi = Math.min(c.phi + 0.08, Math.PI / 2 - 0.02);
      else if (e.key === "+" || e.key === "=") c.dist /= 1.25;
      else if (e.key === "-") c.dist *= 1.25;
      else if (e.key === "f" || e.key === "F" || e.key === "Home") this.reset(false);
      else if (this.opts.onKey && this.opts.onKey(e.key) === true) hit = true;
      else hit = false;
      if (hit) { touch(); e.preventDefault(); e.stopPropagation(); this.draw(); }
    });
  }

  // A picture of the view, at up to twice the screen's pixels (for slides and
  // posts), within what the GPU can hold.
  snapshot(scale = 2) {
    const gl = this.gl;
    const w0 = this.cv.width, h0 = this.cv.height;
    const maxR = gl.getParameter(gl.MAX_RENDERBUFFER_SIZE) || 4096;
    const k = Math.max(1, Math.min(scale, maxR / w0, maxR / h0, Math.sqrt(16e6 / (w0 * h0))));
    if (k > 1.01) { this.cv.width = Math.round(w0 * k); this.cv.height = Math.round(h0 * k); }
    this._draw();
    const url = this.cv.toDataURL("image/png");
    if (k > 1.01) { this.cv.width = w0; this.cv.height = h0; this._draw(); }
    return url;
  }

  destroy() {
    this._stopAnim(false);
    this.spin = false;
    if (this._ro) this._ro.disconnect();
    if (this._onZoom) window.removeEventListener("g:zoom", this._onZoom);
    if (this._onVis) document.removeEventListener("visibilitychange", this._onVis);
    this.cv.remove();
  }
}

// ------------------------------------------------------------- small helpers
function rgb(hex) {
  const n = parseInt(String(hex).replace("#", ""), 16);
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}
export function mixHex(a, b, t) {
  const x = rgb(a), y = rgb(b);
  return "#" + x.map((v, i) => Math.round((v + (y[i] - v) * t) * 255).toString(16).padStart(2, "0")).join("");
}
function norm(v) { const l = Math.hypot(...v) || 1; return v.map((x) => x / l); }
function smooth(a, b, x) { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); }

// ------------------------------------------------------------- tiny mat4 (column-major)
function perspective(fovy, aspect, near, far) {
  const f = 1 / Math.tan(fovy / 2), nf = 1 / (near - far);
  return [f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) * nf, -1, 0, 0, 2 * far * near * nf, 0];
}
function lookAt(e, c, up) {
  let zx = e[0] - c[0], zy = e[1] - c[1], zz = e[2] - c[2];
  let l = Math.hypot(zx, zy, zz) || 1; zx /= l; zy /= l; zz /= l;
  let xx = up[1] * zz - up[2] * zy, xy = up[2] * zx - up[0] * zz, xz = up[0] * zy - up[1] * zx;
  l = Math.hypot(xx, xy, xz) || 1; xx /= l; xy /= l; xz /= l;
  const yx = zy * xz - zz * xy, yy = zz * xx - zx * xz, yz = zx * xy - zy * xx;
  return [xx, yx, zx, 0, xy, yy, zy, 0, xz, yz, zz, 0,
    -(xx * e[0] + xy * e[1] + xz * e[2]), -(yx * e[0] + yy * e[1] + yz * e[2]), -(zx * e[0] + zy * e[1] + zz * e[2]), 1];
}
function mul(a, b) {
  const o = new Array(16);
  for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) {
    let s = 0;
    for (let k = 0; k < 4; k++) s += a[k * 4 + j] * b[i * 4 + k];
    o[i * 4 + j] = s;
  }
  return o;
}
