// layout3d.js — the Layout tab's 3D view (WebGL, no library).
//
// The server sends each layer's merged shapes as flat triangles plus their
// outline edges (controller/layoutview.mesh); here every layer becomes a slab
// between its real bottom and top height (from the PDK's GDS3D process file),
// with the walls extruded from the edges. Heights can be exaggerated (a real
// metal stack is ~6 µm tall on a chip ~100 µm wide, so true scale reads flat)
// and the layers can be spread apart to see the stack, as GDS3D and the Tiny
// Tapeout viewer do.

const VS = `
attribute vec3 aPos;      // x, y (µm from origin), t (0 = bottom, 1 = top)
attribute vec3 aNrm;
uniform mat4 uMvp;
uniform float uZ0, uZ1;
varying vec3 vNrm;
varying vec3 vPos;
void main() {
  vec3 p = vec3(aPos.xy, mix(uZ0, uZ1, aPos.z));
  vNrm = aNrm;
  vPos = p;
  gl_Position = uMvp * vec4(p, 1.0);
}`;

const FS = `
precision mediump float;
uniform vec3 uColor;
uniform vec3 uLight;
uniform vec3 uEye;
uniform float uMetal;
uniform float uAlpha;
varying vec3 vNrm;
varying vec3 vPos;
void main() {
  vec3 n = normalize(vNrm);
  vec3 l = normalize(uLight);
  float diff = abs(dot(n, l));
  vec3 v = normalize(uEye - vPos);
  vec3 h = normalize(l + v);
  float spec = pow(abs(dot(n, h)), 40.0) * uMetal;
  vec3 c = uColor * (0.38 + 0.62 * diff) + vec3(spec * 0.55);
  gl_FragColor = vec4(c, uAlpha);
}`;

export class Layout3D {
  constructor(wrap, opts = {}) {
    this.wrap = wrap;
    this.opts = opts;
    this.cv = document.createElement("canvas");
    this.cv.className = "lx-cv lx-cv3d";
    this.cv.tabIndex = 0;
    this.cv.setAttribute("aria-label", "3D layout. Drag to turn, right-drag to move, scroll to zoom.");
    this.cv.hidden = true;
    wrap.prepend(this.cv);
    const gl = this.cv.getContext("webgl", { antialias: true, alpha: false, preserveDrawingBuffer: true });
    this.gl = gl;
    this.ok = !!gl;
    this.layers = [];
    this.visible = null;     // Set of layer ids, or null = all
    this.zScale = 4;
    this.spread = 0;
    this.bg = [0.024, 0.031, 0.051];
    this.cam = { theta: -0.75, phi: 0.95, dist: 100, tx: 0, ty: 0, tz: 0 };
    this.extent = null;
    if (!this.ok) return;
    this._prog();
    this._wire();
    this._ro = new ResizeObserver(() => this._resize());
    this._ro.observe(wrap);
  }

  show(on) {
    this.cv.hidden = !on;
    if (on) { this._resize(); this.draw(); }
  }

  setBg(hex) {
    const n = parseInt(hex.slice(1), 16);
    this.bg = [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
    this.draw();
  }

  setVisible(set) { this.visible = set; this.draw(); }
  setZScale(z) { this.zScale = z; this.draw(); }
  setSpread(s) { this.spread = s; this.draw(); }

  // ------------------------------------------------------------- data
  load(buf) {
    const gl = this.gl;
    for (const L of this.layers) gl.deleteBuffer(L.vbo);
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
    let order = 0;
    const sorted = head.layers.slice().sort((a, b) => a.z0 - b.z0 || a.z1 - b.z1);
    for (const L of sorted) {
      const nv = L.tris * 3 + L.edges * 6;
      const data = new Float32Array(nv * 6);
      let k = 0;
      const put = (x, y, t, nx, ny, nz) => { data[k++] = x; data[k++] = y; data[k++] = t; data[k++] = nx; data[k++] = ny; data[k++] = nz; };
      for (let i = 0; i < L.tris; i++) {
        const o = L.triOff + i * 6;
        put(tri[o], tri[o + 1], 1, 0, 0, 1);
        put(tri[o + 2], tri[o + 3], 1, 0, 0, 1);
        put(tri[o + 4], tri[o + 5], 1, 0, 0, 1);
      }
      for (let i = 0; i < L.edges; i++) {
        const o = L.edgeOff + i * 4;
        const x1 = edg[o], y1 = edg[o + 1], x2 = edg[o + 2], y2 = edg[o + 3];
        let nx = y2 - y1, ny = -(x2 - x1);
        const n = Math.hypot(nx, ny) || 1;
        nx /= n; ny /= n;
        put(x1, y1, 0, nx, ny, 0); put(x2, y2, 0, nx, ny, 0); put(x2, y2, 1, nx, ny, 0);
        put(x1, y1, 0, nx, ny, 0); put(x2, y2, 1, nx, ny, 0); put(x1, y1, 1, nx, ny, 0);
      }
      const vbo = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
      gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
      const c = parseInt(L.color.slice(1), 16);
      this.layers.push({ ...L, vbo, count: nv, order: order++,
        rgb: [((c >> 16) & 255) / 255, ((c >> 8) & 255) / 255, (c & 255) / 255] });
    }
    this.reset(false);
    this.draw();
    return head;
  }

  reset(draw = true) {
    if (!this.extent) return;
    const w = this.extent[2], h = this.extent[3];
    // Frame the footprint and the (exaggerated, spread) stack height alike, so a
    // small zoomed-in region doesn't start with the camera inside the metals.
    const top = this.layers.reduce((m, L) => Math.max(m, this._zOf(L)[1]), 0);
    this.cam.tx = w / 2; this.cam.ty = h / 2; this.cam.tz = top * 0.3;
    this.cam.theta = -0.75; this.cam.phi = 0.95;
    this.cam.dist = Math.max(w, h, top * 1.2) * 1.45;
    if (draw) this.draw();
  }

  // ------------------------------------------------------------- GL
  _prog() {
    const gl = this.gl;
    const sh = (type, src) => {
      const s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
      return s;
    };
    const p = gl.createProgram();
    gl.attachShader(p, sh(gl.VERTEX_SHADER, VS));
    gl.attachShader(p, sh(gl.FRAGMENT_SHADER, FS));
    gl.linkProgram(p);
    this.p = p;
    this.loc = {};
    for (const a of ["aPos", "aNrm"]) this.loc[a] = gl.getAttribLocation(p, a);
    for (const u of ["uMvp", "uZ0", "uZ1", "uColor", "uLight", "uEye", "uMetal", "uAlpha"]) this.loc[u] = gl.getUniformLocation(p, u);
  }

  _resize() {
    const r = this.wrap.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2.5);
    const w = Math.max(1, Math.round(r.width * dpr)), h = Math.max(1, Math.round(r.height * dpr));
    if (this.cv.width !== w || this.cv.height !== h) {
      this.cv.width = w; this.cv.height = h;
      this.cv.style.width = r.width + "px"; this.cv.style.height = r.height + "px";
      this.draw();
    }
  }

  _zOf(L) {
    // Spread lifts each layer by its stacking order, so the gaps open evenly.
    const lift = this.spread * L.order * 0.9;
    return [L.z0 * this.zScale + lift, L.z1 * this.zScale + lift];
  }

  draw() {
    if (!this.ok || this.cv.hidden) return;
    if (this._raf) return;
    this._raf = requestAnimationFrame(() => { this._raf = 0; this._draw(); });
  }

  _draw() {
    const gl = this.gl;
    gl.viewport(0, 0, this.cv.width, this.cv.height);
    gl.clearColor(this.bg[0], this.bg[1], this.bg[2], 1);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    if (!this.layers.length) return;
    gl.enable(gl.DEPTH_TEST);
    gl.disable(gl.CULL_FACE);
    gl.useProgram(this.p);
    const c = this.cam;
    const eye = [c.tx + c.dist * Math.sin(c.phi) * Math.cos(c.theta),
                 c.ty + c.dist * Math.sin(c.phi) * Math.sin(c.theta),
                 c.tz + c.dist * Math.cos(c.phi)];
    const span = Math.max(this.extent[2], this.extent[3]);
    const proj = perspective(0.75, this.cv.width / this.cv.height, Math.max(c.dist * 0.01, span * 1e-4), c.dist * 10 + span * 4);
    const view = lookAt(eye, [c.tx, c.ty, c.tz], [0, 0, 1]);
    gl.uniformMatrix4fv(this.loc.uMvp, false, mul(proj, view));
    gl.uniform3fv(this.loc.uLight, [0.45, -0.6, 1.0]);
    gl.uniform3fv(this.loc.uEye, eye);
    gl.uniform1f(this.loc.uAlpha, 1);
    const stride = 24;
    gl.enableVertexAttribArray(this.loc.aPos);
    gl.enableVertexAttribArray(this.loc.aNrm);
    for (const L of this.layers) {
      if (this.visible && !this.visible.has(L.id)) continue;
      const [z0, z1] = this._zOf(L);
      gl.bindBuffer(gl.ARRAY_BUFFER, L.vbo);
      gl.vertexAttribPointer(this.loc.aPos, 3, gl.FLOAT, false, stride, 0);
      gl.vertexAttribPointer(this.loc.aNrm, 3, gl.FLOAT, false, stride, 12);
      gl.uniform1f(this.loc.uZ0, z0);
      gl.uniform1f(this.loc.uZ1, z1);
      gl.uniform3fv(this.loc.uColor, L.rgb);
      gl.uniform1f(this.loc.uMetal, L.metal ? 1 : 0.15);
      gl.drawArrays(gl.TRIANGLES, 0, L.count);
    }
  }

  // ------------------------------------------------------------- input
  _wire() {
    const cv = this.cv;
    let drag = null;
    cv.addEventListener("contextmenu", (e) => e.preventDefault());
    cv.addEventListener("pointerdown", (e) => {
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
      if (hit) { e.preventDefault(); e.stopPropagation(); this.draw(); }
    });
  }

  snapshot() { return this.cv.toDataURL("image/png"); }

  destroy() {
    if (this._ro) this._ro.disconnect();
    this.cv.remove();
  }
}

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
