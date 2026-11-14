// 3D 안구 미리보기 — the program's 3D eye (fundusview/ui/eye3d.py) in the browser.
//
// The shaders, the eye model and the textures come from the program (web3d/build.py puts them in
// the page); this file is the rest of eye3d.py — the drawing order, the camera, the motion — with
// projection.py, placement.py, the slit-scan timeline of slit_scan.py, the 3D tab's controls of
// main_window.py and the photo analysis of imaging.py, written again in JavaScript. Kept close to
// the Python, name for name, so what is tried here goes into the program unchanged.
'use strict';
(() => {
const DATA = JSON.parse(document.getElementById('eye-data').textContent);
const MD = DATA.model;
const K = MD.consts;
const PI = Math.PI;
const rad = (d) => d * PI / 180;
const deg = (r) => r * 180 / PI;
const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
const now = () => performance.now() / 1000;

// ---------------------------------------------------------------------------------------------
// vectors (arrays of 3) and matrices (row-major arrays, as numpy)
// ---------------------------------------------------------------------------------------------
const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const mul = (a, s) => [a[0] * s, a[1] * s, a[2] * s];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const len = (a) => Math.hypot(a[0], a[1], a[2]);
const unit = (a) => { const n = len(a); return n > 0 ? mul(a, 1 / n) : a.slice(); };
const lerp = (a, b, t) => a + (b - a) * t;
const m3v = (m, v) => [m[0] * v[0] + m[1] * v[1] + m[2] * v[2], m[3] * v[0] + m[4] * v[1] + m[5] * v[2],
  m[6] * v[0] + m[7] * v[1] + m[8] * v[2]];
const m3T = (m) => [m[0], m[3], m[6], m[1], m[4], m[7], m[2], m[5], m[8]];
const I3 = () => [1, 0, 0, 0, 1, 0, 0, 0, 1];

function axisAngle(axis, angle) {
  const k = unit(axis), c = Math.cos(angle), s = Math.sin(angle), t = 1 - c;
  const [x, y, z] = k;
  return [c + x * x * t, x * y * t - z * s, x * z * t + y * s,
    y * x * t + z * s, c + y * y * t, y * z * t - x * s,
    z * x * t - y * s, z * y * t + x * s, c + z * z * t];
}

function perspective(fovy, aspect, near, far) {
  const f = 1 / Math.tan(rad(fovy) / 2);
  return [f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) / (near - far), 2 * far * near / (near - far), 0, 0, -1, 0];
}

function lookAt(eye, target, up) {
  const f = unit(sub(target, eye)), s = unit(cross(f, up)), u = cross(s, f);
  return [s[0], s[1], s[2], -dot(s, eye), u[0], u[1], u[2], -dot(u, eye), -f[0], -f[1], -f[2], dot(f, eye), 0, 0, 0, 1];
}

function mul4(a, b) {
  const o = new Array(16).fill(0);
  for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) {
    let s = 0;
    for (let k = 0; k < 4; k++) s += a[i * 4 + k] * b[k * 4 + j];
    o[i * 4 + j] = s;
  }
  return o;
}
const m4v = (m, v) => [0, 1, 2, 3].map((i) => m[i * 4] * v[0] + m[i * 4 + 1] * v[1] + m[i * 4 + 2] * v[2] + m[i * 4 + 3] * v[3]);

// ---------------------------------------------------------------------------------------------
// projection.py
// ---------------------------------------------------------------------------------------------
const PROJECTIONS = DATA.projections;
function internalFromExternal(fovExt, d = K.DEFAULT_VIEWPOINT) {
  const a = rad(clamp(fovExt, 0.1, 179) / 2);
  return deg(2 * (a + Math.asin(clamp(d * Math.sin(a), -1, 1))));
}
function externalFromInternal(fovInt, d = K.DEFAULT_VIEWPOINT) {
  const t = rad(fovInt / 2);
  return deg(2 * Math.atan2(Math.sin(t), Math.cos(t) + d));
}
function thetaMax(fov, type = 'external', d = K.DEFAULT_VIEWPOINT) {
  const internal = type === 'internal' ? fov : internalFromExternal(fov, d);
  return rad(clamp(internal, 1, 300) / 2);
}
function radialRho(s, c) {
  if (c <= 1e-9) return s;
  const p = (1 - c) / c, q = -s / c;
  const disc = Math.sqrt((q / 2) ** 2 + (p / 3) ** 3);
  return Math.cbrt(-q / 2 + disc) + Math.cbrt(-q / 2 - disc);
}
function gfun(theta, projection, d = K.DEFAULT_VIEWPOINT, tmax = PI / 2, c = K.DEFAULT_RADIAL_C) {
  if (projection === 'stereographic') return Math.tan(theta / 2);
  if (projection === 'equidistant') return theta;
  if (projection === 'orthographic') return Math.sin(theta);
  if (projection === 'radial') return radialRho(theta / tmax, c);
  const den = Math.cos(theta) + d;
  return den <= 1e-6 ? Infinity : Math.sin(theta) / den;
}
function rhoOf(theta, tmax, projection, d, c) {
  const gm = gfun(tmax, projection, d, tmax, c);
  return gm > 0 ? gfun(theta, projection, d, tmax, c) / gm : 0;
}
function thetaOfRho(r, tmax, projection, d, c) {
  if (projection === 'radial') return tmax * ((1 - c) * r + c * r ** 3);
  let lo = 0, hi = tmax;
  const target = r * gfun(tmax, projection, d);
  for (let i = 0; i < 60; i++) {
    const mid = 0.5 * (lo + hi);
    if (gfun(mid, projection, d) < target) lo = mid; else hi = mid;
  }
  return 0.5 * (lo + hi);
}
const spherePoint = (theta, phi) => [Math.sin(theta) * Math.cos(phi), Math.sin(theta) * Math.sin(phi), -Math.cos(theta)];

// ---------------------------------------------------------------------------------------------
// placement.py: where a photo lies on the eye
// ---------------------------------------------------------------------------------------------
const POLE = [0, 0, -1];
function angleBetween(a, b) {
  a = unit(a); b = unit(b);
  return deg(Math.atan2(len(cross(a, b)), dot(a, b)));
}
function tilt(c) {
  c = unit(c);
  const axis = cross(POLE, c), s = len(axis);
  if (s < 1e-12) return c[2] < 0 ? I3() : axisAngle([0, 1, 0], PI);
  return axisAngle(mul(axis, 1 / s), Math.atan2(s, dot(POLE, c)));
}
function centreFor(q, target = POLE) {
  q = unit(q); const t = unit(target);
  const dx = t[0] - q[0], dy = t[1] - q[1], n2 = Math.hypot(dx, dy);
  if (n2 < 1e-12) return POLE.slice();
  const n = [-dy / n2, dx / n2, 0];
  const qp = sub(q, mul(n, dot(n, q))), tp = sub(t, mul(n, dot(n, t)));
  const ang = Math.atan2(dot(n, cross(qp, tp)), dot(qp, tp));
  return m3v(axisAngle(n, ang), POLE);
}
function anatomicalDisc(lat) {
  let phi = rad(K.DISC_TILT_DEG);
  if (lat === 'OS') phi = PI - phi;
  return spherePoint(rad(K.DISC_FOVEA_DEG), phi);
}

class Camera {
  constructor(cx, cy, r, fov, fovType, projection, viewpoint = K.DEFAULT_VIEWPOINT, radialC = K.DEFAULT_RADIAL_C, roll = 0) {
    Object.assign(this, { cx, cy, r, fov, fovType, projection, viewpoint, radialC, roll });
  }
  get tmax() { return thetaMax(this.fov, this.fovType, this.viewpoint); }
  direction(x, y) {
    const dx = (x - this.cx) / this.r, dy = (this.cy - y) / this.r, r = Math.hypot(dx, dy);
    if (r > 1) return null;
    const phi = Math.atan2(dy, dx) - rad(this.roll);
    return spherePoint(thetaOfRho(r, this.tmax, this.projection, this.viewpoint, this.radialC), phi);
  }
  pixel(q) {
    const theta = Math.acos(clamp(-q[2], -1, 1)), tmax = this.tmax;
    if (theta > tmax) return null;
    const r = rhoOf(theta, tmax, this.projection, this.viewpoint, this.radialC);
    const phi = Math.atan2(q[1], q[0]) + rad(this.roll);
    return [this.cx + r * this.r * Math.cos(phi), this.cy - r * this.r * Math.sin(phi)];
  }
  withFov(fov) {
    return new Camera(this.cx, this.cy, this.r, fov, this.fovType, this.projection, this.viewpoint, this.radialC, this.roll);
  }
  thetaLut(n = 256) {   // theta of rho on a table, for many pixels at once
    const tmax = this.tmax, lut = new Float64Array(n + 1);
    for (let k = 0; k <= n; k++) lut[k] = thetaOfRho(k / n, tmax, this.projection, this.viewpoint, this.radialC);
    return lut;
  }
}

function sideOf(disc, cam, lat) {
  if (lat === 'OD' || lat === 'OS') return lat;
  if (!disc) return null;
  const dx = (disc[0] - cam.cx) / Math.max(cam.r, 1);
  return Math.abs(dx) < 0.1 ? null : (dx > 0 ? 'OD' : 'OS');
}

function place(cam, { fovea = null, disc = null, lat = null, align = true } = {}) {
  const qf = fovea ? cam.direction(fovea[0], fovea[1]) : null;
  const qd = disc ? cam.direction(disc[0], disc[1]) : null;
  const out = { by: align ? 'centre' : 'off', centre: POLE.slice(), matrix: I3(), fovea: null, disc: null, distanceDeg: null };
  if (qf && qd) out.distanceDeg = angleBetween(qf, qd);
  if (align) {
    if (qf) { out.by = 'fovea'; out.centre = centreFor(qf, POLE); }
    else if (qd && sideOf(disc, cam, lat)) { out.by = 'disc'; out.centre = centreFor(qd, anatomicalDisc(sideOf(disc, cam, lat))); }
  }
  out.matrix = tilt(out.centre);
  out.fovea = qf ? m3v(out.matrix, qf) : null;
  out.disc = qd ? m3v(out.matrix, qd) : null;
  out.offsetDeg = angleBetween(out.centre, POLE);
  out.distanceMm = out.distanceDeg == null ? null : rad(out.distanceDeg) * 12;
  return out;
}

function expectedFovea(cam, disc, lat) {
  const side = sideOf(disc, cam, lat);
  const qd = disc ? cam.direction(disc[0], disc[1]) : null;
  if (!side || !qd) return null;
  const m = tilt(centreFor(qd, anatomicalDisc(side)));
  return cam.pixel(m3v(m3T(m), POLE));
}

function fitFov(cam, fovea, disc, targetDeg = K.DISC_FOVEA_DEG) {
  const dist = (fov) => {
    const c = cam.withFov(fov), a = c.direction(...fovea), b = c.direction(...disc);
    return a && b ? angleBetween(a, b) : null;
  };
  let lo = 5, hi = cam.fovType === 'internal' ? 300 : 170;
  const dlo = dist(lo), dhi = dist(hi);
  if (dlo == null || dhi == null || !(dlo <= targetDeg && targetDeg <= dhi)) return null;
  for (let i = 0; i < 50; i++) {
    const mid = 0.5 * (lo + hi);
    if (dist(mid) < targetDeg) lo = mid; else hi = mid;
  }
  return 0.5 * (lo + hi);
}

// ---------------------------------------------------------------------------------------------
// eye_model.py: meshes
// ---------------------------------------------------------------------------------------------
function mesh(pos, nrm, idx, uv = null, lines = false) {
  return { pos: Float32Array.from(pos), nrm: Float32Array.from(nrm), idx: Uint32Array.from(idx), uv: uv ? Float32Array.from(uv) : null, lines };
}
function gridIndices(rows, cols) {
  const w = cols + 1, out = new Uint32Array(rows * cols * 6);
  let o = 0;
  for (let i = 0; i < rows; i++) for (let j = 0; j < cols; j++) {
    const a = i * w + j, b = (i + 1) * w + j, c = (i + 1) * w + j + 1, d = i * w + j + 1;
    out[o++] = a; out[o++] = b; out[o++] = c; out[o++] = a; out[o++] = c; out[o++] = d;
  }
  return out;
}
function merge(...meshes) {
  meshes = meshes.filter(Boolean);
  let nv = 0, ni = 0;
  for (const m of meshes) { nv += m.pos.length / 3; ni += m.idx.length; }
  const anyUv = meshes.some((m) => m.uv);
  const pos = new Float32Array(nv * 3), nrm = new Float32Array(nv * 3), idx = new Uint32Array(ni);
  const uv = anyUv ? new Float32Array(nv * 2) : null;
  let v = 0, i = 0;
  for (const m of meshes) {
    pos.set(m.pos, v * 3); nrm.set(m.nrm, v * 3);
    if (uv && m.uv) uv.set(m.uv, v * 2);
    for (let k = 0; k < m.idx.length; k++) idx[i + k] = m.idx[k] + v;
    v += m.pos.length / 3; i += m.idx.length;
  }
  return { pos, nrm, idx, uv, lines: meshes[0].lines };
}
function sphereMesh(nLat, nLon, aMax = PI, center = [0, 0, 0], radius = 1) {
  const n = (nLat + 1) * (nLon + 1), pos = new Float32Array(n * 3), nrm = new Float32Array(n * 3);
  let o = 0;
  for (let i = 0; i <= nLat; i++) {
    const a = aMax * i / nLat;
    for (let j = 0; j <= nLon; j++) {
      const b = 2 * PI * j / nLon, x = Math.sin(a) * Math.cos(b), y = Math.sin(a) * Math.sin(b), z = Math.cos(a);
      nrm[o] = x; nrm[o + 1] = y; nrm[o + 2] = z;
      pos[o] = x * radius + center[0]; pos[o + 1] = y * radius + center[1]; pos[o + 2] = z * radius + center[2];
      o += 3;
    }
  }
  return { pos, nrm, idx: gridIndices(nLat, nLon), uv: null, lines: false };
}
// revolve(r, z, n_seg, normals, relief): a surface of revolution; with relief the normals come from
// the displaced grid (numpy.gradient along both directions, the seam periodic)
function revolve(prof, nSeg, relief = null) {
  const { r, z, nr, nz } = prof, rows = r.length, cols = nSeg + 1;
  const P = new Float64Array(rows * cols * 3), N0 = new Float64Array(rows * cols * 3);
  for (let i = 0; i < rows; i++) for (let j = 0; j < cols; j++) {
    const phi = 2 * PI * j / nSeg, c = Math.cos(phi), s = Math.sin(phi);
    const R = relief ? r[i] - relief(z[i], phi) : r[i], o = (i * cols + j) * 3;
    P[o] = R * c; P[o + 1] = R * s; P[o + 2] = z[i];
    N0[o] = nr[i] * c; N0[o + 1] = nr[i] * s; N0[o + 2] = nz[i];
  }
  let N = N0;
  if (relief) {
    N = new Float64Array(rows * cols * 3);
    const at = (i, j) => (i * cols + j) * 3;
    for (let i = 0; i < rows; i++) for (let j = 0; j < cols; j++) {
      const di = [0, 0, 0], dj = [0, 0, 0];
      const i0 = i === 0 ? 0 : i - 1, i1 = i === rows - 1 ? rows - 1 : i + 1, fi = (i === 0 || i === rows - 1) ? 1 : 0.5;
      let j0 = j - 1, j1 = j + 1, fj = 0.5;
      if (j === 0 || j === cols - 1) { j0 = cols - 2; j1 = 1; fj = 1; }   // dPj[:, 0] = dPj[:, -1] = P[:, 1] - P[:, -2]
      for (let k = 0; k < 3; k++) {
        di[k] = (P[at(i1, j) + k] - P[at(i0, j) + k]) * fi;
        dj[k] = (P[at(i, j1) + k] - P[at(i, j0) + k]) * fj;
      }
      let n = cross(di, dj);
      const ln = len(n), o = at(i, j), n0 = [N0[o], N0[o + 1], N0[o + 2]];
      n = ln > 1e-12 ? mul(n, 1 / ln) : n0;
      if (dot(n, n0) + 1e-12 < 0) n = mul(n, -1);
      N[o] = n[0]; N[o + 1] = n[1]; N[o + 2] = n[2];
    }
  }
  return { pos: Float32Array.from(P), nrm: Float32Array.from(N), idx: gridIndices(rows - 1, nSeg), uv: null, lines: false };
}
function mirroredX(m) {
  const pos = m.pos.slice(), nrm = m.nrm.slice();
  for (let i = 0; i < pos.length; i += 3) { pos[i] = -pos[i]; nrm[i] = -nrm[i]; }
  return { pos, nrm, idx: m.idx, uv: m.uv, lines: m.lines };
}
function annulus(rIn, rOut, z, nSeg) {
  const pos = [], uv = [], nrm = [];
  const val = (r, j) => (typeof r === 'number' ? r : r[j]);
  for (const [rr, v] of [[rIn, 0], [rOut, 1]]) for (let j = 0; j <= nSeg; j++) {
    const phi = 2 * PI * j / nSeg, r = val(rr, j);
    pos.push(r * Math.cos(phi), r * Math.sin(phi), z); uv.push(v, phi / (2 * PI)); nrm.push(0, 0, 1);
  }
  return mesh(pos, nrm, gridIndices(1, nSeg), uv);
}
const cutPlaneZ = (cut) => Math.min(cut, K.LIMBUS_Z);
function wallBaseRadius(z) {
  if (z <= K.Z_ORA) return Math.sqrt(Math.max(K.R_RET ** 2 - z * z, 0));
  const zs = MD.wall_base.z, rs = MD.wall_base.r;
  if (z >= zs[zs.length - 1]) return rs[rs.length - 1];
  const t = (z - zs[0]) / (zs[zs.length - 1] - zs[0]) * (zs.length - 1), i = Math.floor(t);
  return lerp(rs[i], rs[i + 1], t - i);
}
function ciliaryRelief(z, phi) {
  const u = clamp((z - K.PLICATA_Z0) / (K.PLICATA_Z1 - K.PLICATA_Z0), 0, 1);
  const env = Math.sin(PI * u) ** 1.5, ridge = (0.5 + 0.5 * Math.cos(K.CILIARY_PROCESSES * phi)) ** 2;
  return K.PROCESS_HEIGHT * env * ridge;
}
const wallRadius = (z, phi) => wallBaseRadius(z) - ciliaryRelief(z, phi);
function lensRadius(z) {
  const h = z >= K.LENS_EQ_Z ? K.LENS_FRONT_H : K.LENS_BACK_H, u = (z - K.LENS_EQ_Z) / h;
  return K.LENS_R * Math.sqrt(Math.max(0, 1 - u * u));
}
function rimMeshes(cut, nSeg = 432) {
  const zc = cutPlaneZ(cut), out = {};
  if (zc <= -1) return out;
  const rOut = Math.sqrt(Math.max(0, 1 - zc * zc));
  let rIn;
  if (zc <= -K.R_RET) rIn = new Array(nSeg + 1).fill(0);
  else if (zc <= K.IRIS_BACK_Z) rIn = Array.from({ length: nSeg + 1 }, (_, j) => wallRadius(zc, 2 * PI * j / nSeg));
  else if (zc <= K.IRIS_Z) {
    rIn = new Array(nSeg + 1).fill(K.IRIS_ROOT_R);
    out.iris = annulus(K.PUPIL_R - 0.002, K.IRIS_ROOT_R, zc, 192);
  } else {
    const t = (zc - K.IRIS_Z) / (K.LIMBUS_Z - K.IRIS_Z);
    rIn = new Array(nSeg + 1).fill(K.IRIS_ROOT_R + (K.LIMBUS_INNER_R - K.IRIS_ROOT_R) * t ** (1 / 0.8));
  }
  out.wall = annulus(rIn.map((r) => Math.max(r - 0.003, 0)), rOut + 0.003, zc, nSeg);
  if (K.LENS_BACK_Z < zc && zc < K.LENS_FRONT_Z) out.lens = annulus(0, lensRadius(zc) + 0.002, zc, 128);
  return out;
}
function perp(v) {
  const h = Math.abs(v[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0];
  return unit(cross(v, h));
}
function capMesh(center, T, U, V, rx, ry, n, uvOffset, sign = 1) {
  const pos = [], nrm = [], uv = [], idx = [];
  for (let i = -1; i <= n; i++) {
    const a = 2 * PI * i / n, x = i < 0 ? 0 : Math.cos(a), y = i < 0 ? 0 : Math.sin(a);
    pos.push(...add(center, add(mul(U, x * rx), mul(V, y * ry)))); nrm.push(...mul(T, sign)); uv.push(uvOffset + x, y);
  }
  for (let j = 0; j < n; j++) idx.push(0, 1 + j, 2 + j);
  return mesh(pos, nrm, idx, uv);
}
function nerveMesh(p, lat, nSeg = 64, nLen = 48) {
  p = unit(p);
  const nasal = [lat === 'OS' ? -1 : 1, 0, 0];
  const P0 = mul(p, 0.965), P1 = mul(p, 1.30);
  const P2 = add(P1, mul(unit(add(add(p, [0, -0.22, 0]), mul(nasal, 0.10))), 0.30));
  const P3 = add(P2, mul(unit(add(add(p, [0, 0.05, 0]), mul(nasal, 0.25))), 0.30));
  const c = [];
  for (let i = 0; i < nLen; i++) {
    const t = i / (nLen - 1), a = (1 - t) ** 3, b = 3 * (1 - t) ** 2 * t, d = 3 * (1 - t) * t * t, e = t ** 3;
    c.push(add(add(mul(P0, a), mul(P1, b)), add(mul(P2, d), mul(P3, e))));
  }
  const s = [0];
  for (let i = 1; i < nLen; i++) s.push(s[i - 1] + len(sub(c[i], c[i - 1])));
  const sEnd = s[nLen - 1];
  const rr = s.map((si) => K.NERVE_R * (1 + 0.32 * Math.exp(-((si / 0.05) ** 2))) * (1 - 0.05 * si / sEnd));
  const T = c.map((_, i) => unit(i === 0 ? sub(c[1], c[0]) : i === nLen - 1 ? sub(c[i], c[i - 1]) : mul(sub(c[i + 1], c[i - 1]), 0.5)));
  const U = [], V = [];
  let u = perp(p);
  u = sub(u, mul(T[0], dot(u, T[0])));
  for (let i = 0; i < nLen; i++) {
    u = unit(sub(u, mul(T[i], dot(u, T[i]))));
    U.push(u); V.push(cross(T[i], u));
  }
  const pos = [], nrm = [], uv = [];
  for (let i = 0; i < nLen; i++) for (let j = 0; j <= nSeg; j++) {
    const a = 2 * PI * j / nSeg, d = add(mul(U[i], Math.cos(a)), mul(V[i], Math.sin(a)));
    pos.push(...add(c[i], mul(d, rr[i]))); nrm.push(...d); uv.push(s[i] / sEnd, j / nSeg);
  }
  const tube = mesh(pos, nrm, gridIndices(nLen - 1, nSeg), uv);
  const L = nLen - 1;
  return merge(tube, capMesh(c[L], T[L], U[L], V[L], rr[L], rr[L], nSeg, 4.0));
}
function sectionQuad(k, off, size = 1.16) {
  k = unit(k);
  const e1 = unit(sub([0, 0, 1], mul(k, k[2]))), e2 = cross(k, e1), c = mul(k, -off);
  const pos = [];
  for (const [a, b] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) pos.push(...add(c, mul(add(mul(e1, a), mul(e2, b)), size)));
  const n = mul(k, -1);
  return mesh(pos, [...n, ...n, ...n, ...n], [0, 1, 2, 0, 2, 3]);
}
const b64 = (s, Type) => { const bin = atob(s), u8 = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i); return new Type(u8.buffer); };

function staticMeshes() {
  const corneaAmax = Math.acos((K.LIMBUS_Z - 0.012 - K.CORNEA_CENTER_Z) / K.CORNEA_R);
  const zon = b64(MD.zonules, Float32Array);
  const mus = MD.muscles;
  const musIdx = b64(mus.idx, mus.idx32 ? Uint32Array : Uint16Array);
  const muscles = { pos: b64(mus.pos, Float32Array), nrm: b64(mus.nrm, Float32Array), uv: b64(mus.uv, Float32Array), idx: Uint32Array.from(musIdx), lines: false };
  return {
    bg: mesh([-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, 1, 0], new Array(12).fill(0), [0, 1, 2, 0, 2, 3]),
    sclera: sphereMesh(80, 160),
    cornea: sphereMesh(48, 192, corneaAmax, [0, 0, K.CORNEA_CENTER_Z], K.CORNEA_R),
    wall: merge(revolve(MD.wall.post, MD.wall.seg_post), revolve(MD.wall.ant, MD.wall.seg_ant, ciliaryRelief)),
    iris: merge(...MD.iris.map((p) => revolve(p, 192))),
    angle: revolve(MD.angle, 192),
    lens: revolve(MD.lens, 160),
    zonules: { pos: zon, nrm: new Float32Array(zon.length), idx: Uint32Array.from({ length: zon.length / 3 }, (_, i) => i), uv: null, lines: true },
    muscles_OD: muscles,
    muscles_OS: mirroredX(muscles),
  };
}

// ---------------------------------------------------------------------------------------------
// motion.py: one ticker for every animation, stepped with the real time between frames
// ---------------------------------------------------------------------------------------------
const ease = (x) => { const t = clamp(x, 0, 1); return t * t * (3 - 2 * t); };
const easeOut = (x) => 1 - (1 - clamp(x, 0, 1)) ** 3;
const motionOn = !(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
const ticker = {
  anims: new Set(),
  add(a) { this.anims.add(a); requestFrame(); },
  remove(a) { this.anims.delete(a); },
  step(dt) {
    for (const a of [...this.anims]) {
      if (!this.anims.has(a)) continue;
      if (!a.step(dt)) this.anims.delete(a);
    }
  },
};
class Decay {   // a flick: the speed at release dies away
  constructor(move, tau = 0.3, stop = 6, done = null) { Object.assign(this, { move, tau, stopSpeed: stop, done, vx: 0, vy: 0 }); }
  start(vx, vy) {
    this.stop();
    if (!motionOn || Math.hypot(vx, vy) < this.stopSpeed * 4) return false;
    this.vx = vx; this.vy = vy; ticker.add(this); return true;
  }
  step(dt) {
    const k = Math.exp(-dt / this.tau), d = this.tau * (1 - k);
    this.move(this.vx * d, this.vy * d);
    this.vx *= k; this.vy *= k;
    if (Math.hypot(this.vx, this.vy) < this.stopSpeed) { if (this.done) this.done(); return false; }
    return true;
  }
  running() { return ticker.anims.has(this); }
  stop() { ticker.remove(this); }
}
class Chase {   // an amount handed out smoothly (wheel zoom)
  constructor(apply, halfLife = 0.055, eps = 1e-3) { Object.assign(this, { apply, halfLife, eps, left: 0 }); }
  add(x) { if (!motionOn) { this.apply(x); return; } this.left += x; ticker.add(this); }
  step(dt) {
    let part = this.left * (1 - 0.5 ** (dt / this.halfLife));
    if (Math.abs(this.left - part) < this.eps) part = this.left;
    this.left -= part; this.apply(part);
    return this.left !== 0;
  }
  running() { return ticker.anims.has(this); }
  stop() { this.left = 0; ticker.remove(this); }
}
class Tween {   // update(k), k eased from 0 to 1, then done()
  constructor(update, duration = 0.3, easing = easeOut, done = null) { Object.assign(this, { update, duration, easing, done, t: 0, live: false }); }
  start() {
    this.stop(); this.t = 0; this.live = true;
    if (!motionOn || this.duration <= 0) { this.finish(); return; }
    this.update(0); ticker.add(this);
  }
  step(dt) {
    this.t += dt;
    const t = this.t / this.duration;
    if (t >= 1) { this.finish(); return false; }
    this.update(this.easing(t)); return true;
  }
  running() { return this.live; }
  stop() { this.live = false; ticker.remove(this); }
  finish() { if (!this.live) return; this.live = false; ticker.remove(this); this.update(1); if (this.done) this.done(); }
}
class Velocity {
  constructor() { this.pts = []; }
  reset() { this.pts = []; }
  add(x, y) { const t = now(); this.pts.push([t, x, y]); while (this.pts.length > 2 && t - this.pts[0][0] > 0.09) this.pts.shift(); }
  get() {
    const t = now();
    if (this.pts.length < 2 || t - this.pts[this.pts.length - 1][0] > 0.06) return [0, 0];
    const [t0, x0, y0] = this.pts[0], [t1, x1, y1] = this.pts[this.pts.length - 1];
    return t1 - t0 < 1e-3 ? [0, 0] : [(x1 - x0) / (t1 - t0), (y1 - y0) / (t1 - t0)];
  }
}

// ---------------------------------------------------------------------------------------------
// the eye: EyeView's state, camera and drawing
// ---------------------------------------------------------------------------------------------
const canvas = document.getElementById('eye');
const overlay = document.getElementById('eye-overlay');
const gl = canvas.getContext('webgl2', { antialias: true, alpha: false, depth: true, preserveDrawingBuffer: false });

const E = {
  DIST0: MD.dist0, FOV0: MD.fov0, SPIN_WAIT: 3.0,
  HOME: { yaw: 38, pitch: 18, dist: MD.dist0, target: [0, 0, 0] },
  // photo + mapping
  tex: null, center: [0.5, 0.5], radius: [0.5, 0.5], texel: [0.001, 0.001],
  fov: 135, fovType: 'internal', projection: 'equidistant', viewpoint: K.DEFAULT_VIEWPOINT, radialC: K.DEFAULT_RADIAL_C, roll: 0,
  laterality: null, discDir: null, align: true, placement: place(new Camera(0, 0, 1, 135, 'internal', 'equidistant')), marks: [null, null, null],
  // view
  mode: 'outside', cut: 0.25, showNerve: true, showMuscles: false, showGrid: false,
  half: 0, xray: 0, scan: null, scanDim: 1, scanBeam: 1, fovSweep: 0, fovAlpha: 0, fovRing: 0, black: false,
  slitAxis: 'v', scanSign: -1,  // the slit's way over the photo: along its vertical ('v') or horizontal ('h') axis, from which end
  simple: 0,                    // 단순하게 보기: 0 the detailed look … 1 plain (tweened)
  reliefOn: false, reliefAmount: 0.45 * 0.08, hmap: null, hmapTex: null, hmapVer: 0,   // 망막 높낮이
  relief: 0, glass: 0, dark: 0, autoRotate: 0, outFov: 38,
  yaw: 38, pitch: 18, dist: MD.dist0, target: [0, 0, 0], inYaw: 0, inPitch: 0, inFov: MD.fov0, inZ: 0.35,
  drag: null, dragKind: '', touched: now(), entering: false, enterPlan: [], enterEnd: {}, viewEnds: null,
  rlight: [0, 0.6, 0.8],
};
E.thetaMax = () => thetaMax(E.fov, E.fovType, E.viewpoint);
E.photoCamera = (c) => new Camera(c[0], c[1], c[2], E.fov, E.fovType, E.projection, E.viewpoint, E.radialC, E.roll);

function replace() {
  const [disc, fovea, circle] = E.marks;
  let pl = { by: E.align ? 'centre' : 'off', centre: POLE.slice(), matrix: I3(), fovea: null, disc: null, distanceDeg: null, offsetDeg: 0, distanceMm: null };
  if (circle && circle[2]) pl = place(E.photoCamera(circle), { fovea, disc, lat: E.laterality, align: E.align });
  E.placement = pl;
  E.discDir = pl.disc || anatomicalDisc(E.laterality);
}
function setLandmarks(lat, disc, fovea, circle) { E.laterality = lat; E.marks = [disc, fovea, circle]; replace(); updateRelief(); redraw(); }

// 세로 단면 follows the photo's vertical meridian (up on the photo), turned with the photo's roll; the
// slit moves along the photo's vertical ('v') or horizontal ('h') axis.
const slitAngle = (axis = E.slitAxis) => (axis === 'h' ? 0 : PI / 2);   // on the photo, from its right
const meridian = (axis = 'v') => { const a = slitAngle(axis) - rad(E.roll); return [Math.cos(a), Math.sin(a), 0]; };
function halfPlane() {
  let k = cross(meridian(), [0, 0, 1]);
  if (E.discDir && Math.abs(dot(E.discDir, k)) > 1e-6) k = dot(E.discDir, k) > 0 ? k : mul(k, -1);
  else if (E.laterality === 'OS') k = mul(k, -1);
  return [k, 1.05 * (1 - clamp(E.half, 0, 1))];
}
const halfOn = () => E.mode === 'outside' && E.half > 1e-3;
const pose = () => ({ yaw: E.yaw, pitch: E.pitch, dist: E.dist, target: E.target.slice() });
function viewSize() { return [Math.max(1, canvas.clientWidth), Math.max(1, canvas.clientHeight)]; }
function fit(dist, halfWidth) { const [w, h] = viewSize(); return Math.max(dist, halfWidth / (Math.tan(rad(19)) * (w / h)) + 0.45); }
function poseFrom(d, dist, target = [0, 0, 0]) {
  d = unit(d);
  return { yaw: ((deg(Math.atan2(d[0], d[2])) % 360) + 360) % 360, pitch: deg(Math.asin(clamp(d[1], -1, 1))), dist, target: target.slice() };
}
const sectionPose = () => poseFrom(mul(halfPlane()[0], -1), fit(3.6, 1.3), [0, 0, 0.12]);
const showcasePose = () => poseFrom(add(mul(halfPlane()[0], -0.70), [0, -0.25, 0.65]), fit(3.8, 1.2));
const tilted = () => E.placement.offsetDeg > 1e-6;

function meridianRows(n = 721) {   // along the meridian: angle, place on the photo along that axis (-1…1), inside the field
  const tmax = E.thetaMax(), m = meridian(), M = E.placement.matrix, alpha = slitAngle('v');
  const lut = []; for (let k = 0; k <= 256; k++) lut.push(rhoOf(k / 256 * tmax, tmax, E.projection, E.viewpoint, E.radialC));
  const ts = [], rows = [], inside = [];
  for (let i = 0; i < n; i++) {
    const t = -0.97 * PI + 1.94 * PI * i / (n - 1);
    const d = [Math.sin(t) * m[0], Math.sin(t) * m[1], -Math.cos(t)];
    const q = m3v(m3T(M), d), theta = Math.acos(clamp(-q[2], -1, 1));
    const x = Math.min(theta, tmax) / tmax * 256, j = Math.min(255, Math.floor(x));
    const rho = lerp(lut[j], lut[j + 1], x - j);
    ts.push(t); rows.push(rho * Math.cos(Math.atan2(q[1], q[0]) + rad(E.roll) - alpha)); inside.push(theta <= tmax);
  }
  return [ts, rows, inside];
}
function fieldOnMeridian() {
  if (!tilted()) return [-E.thetaMax(), E.thetaMax()];
  const [t, , inside] = meridianRows(), k = t.filter((_, i) => inside[i]);
  return k.length ? [k[0], k[k.length - 1]] : [-E.thetaMax(), E.thetaMax()];
}
function scanTheta(s) {   // where the slit at s (0…1 of its way) falls on the meridian: angle, side
  const dy = E.scanSign * (2 * clamp(s, 0, 1) - 1), tmax = E.thetaMax();   // (on 세로 단면: the slit moves up or down)
  if (tilted()) {
    const [t, row, inside] = meridianRows(), k = [];
    for (let i = 0; i < t.length; i++) if (inside[i]) k.push(i);
    if (k.length > 1 && row[k[k.length - 1]] > row[k[0]]) {   // np.interp(dy, rows, t)
      let tt = dy <= row[k[0]] ? t[k[0]] : t[k[k.length - 1]];
      if (dy > row[k[0]] && dy < row[k[k.length - 1]]) {
        for (let a = 0; a < k.length - 1; a++) {
          const r0 = row[k[a]], r1 = row[k[a + 1]];
          if (dy >= r0 && dy <= r1 && r1 > r0) { tt = lerp(t[k[a]], t[k[a + 1]], (dy - r0) / (r1 - r0)); break; }
        }
      }
      return [Math.abs(tt), tt >= 0 ? 1 : -1];
    }
  }
  return [thetaOfRho(Math.min(1, Math.abs(dy)), tmax, E.projection, E.viewpoint, E.radialC), dy >= 0 ? 1 : -1];
}
const magnification = () => (E.mode === 'inside' ? Math.tan(rad(E.FOV0) / 2) / Math.tan(rad(E.inFov) / 2) : homeDist() / E.dist);
// the start distance: the program's, or farther on a narrow (portrait) screen so the whole eye shows
const homeDist = () => fit(E.DIST0, 1.25);
const home = () => ({ ...E.HOME, dist: homeDist(), target: [0, 0, 0] });

function viewBasis() {
  let eye, f, up, fovy;
  if (E.mode === 'inside') {
    const cy = Math.cos(rad(E.inYaw)), sy = Math.sin(rad(E.inYaw)), cp = Math.cos(rad(E.inPitch)), sp = Math.sin(rad(E.inPitch));
    eye = [0, 0, E.inZ]; f = [sy * cp, sp, -cy * cp]; up = [0, 1, 0]; fovy = E.inFov;
  } else {
    const cy = Math.cos(rad(E.yaw)), sy = Math.sin(rad(E.yaw)), cp = Math.cos(rad(E.pitch)), sp = Math.sin(rad(E.pitch));
    const d = [sy * cp, sp, cy * cp];
    eye = add(E.target, mul(d, E.dist)); f = mul(d, -1); fovy = E.outFov;
    up = Math.abs(E.pitch) < 89 ? [0, 1, 0] : [0, 0, -1];
  }
  const r = unit(cross(f, up));
  return [eye, f, r, cross(r, f), fovy];
}
function cameraMats(aspect) {
  const [eye, f, , u, fovy] = viewBasis();
  const [near, far] = E.mode === 'inside' ? [0.01, 10] : [Math.max(0.001, Math.min(0.05, 0.02 * E.dist)), E.dist + 6];
  return [mul4(perspective(fovy, aspect, near, far), lookAt(eye, add(eye, f), u)), eye];
}
function studioLights(campos, camUp = [0, 1, 0]) {
  const c = unit(campos);
  let right = cross(mul(c, -1), camUp);
  right = unit(len(right) > 1e-6 ? right : [1, 0, 0]);
  const up = cross(right, mul(c, -1));
  const key = unit(add(sub(c, mul(right, 0.85)), mul(up, 0.75))), fill = unit(sub(add(c, right), mul(up, 0.2)));
  const out = { key, fill };
  for (const [n, d] of [['k', key], ['f', fill]]) { const ax = unit(cross(up, d)); out[n + 'x'] = ax; out[n + 'y'] = cross(d, ax); }
  return out;
}
function ray(px, py) {
  const [eye, f, r, u, fovy] = viewBasis(), [w, h] = viewSize(), t = Math.tan(rad(fovy) / 2);
  const x = (2 * px / w - 1) * t * w / h, y = (1 - 2 * py / h) * t;
  return [eye, unit(add(f, add(mul(r, x), mul(u, y))))];
}
function pick(o, d) {
  const hits = (radius, c = [0, 0, 0]) => {
    const oc = sub(o, c), b = dot(oc, d), disc = b * b - (dot(oc, oc) - radius * radius);
    if (disc < 0) return null;
    const q = Math.sqrt(disc); return [-b - q, -b + q];
  };
  let rIn = K.R_RET;
  if (E.mode === 'inside') { const h = hits(rIn); return h ? add(o, mul(d, h[1])) : null; }
  if (len(o) < 0.999) { const hi = hits(rIn); return hi && hi[1] > 0 ? add(o, mul(d, hi[1])) : null; }
  const h = hits(1);
  if (!h || h[1] <= 0) return null;
  if (halfOn()) {
    const [k, off] = halfPlane(), kept = (p) => dot(p, k) >= -off - 1e-6;
    if (h[0] > 0 && kept(add(o, mul(d, h[0])))) return add(o, mul(d, h[0]));
    const dn = dot(d, k);
    if (Math.abs(dn) > 1e-9) {
      const t = (-off - dot(o, k)) / dn, c = add(o, mul(d, t));
      if (t > 0 && rIn * rIn <= dot(c, c) && dot(c, c) <= 1) return c;
    }
    const hi = hits(rIn);
    return hi && hi[1] > 0 && kept(add(o, mul(d, hi[1]))) ? add(o, mul(d, hi[1])) : null;
  }
  if (E.cut >= 0.999) {
    const p = add(o, mul(d, Math.max(h[0], 0)));
    if (p[2] > K.LIMBUS_Z) { const hc = hits(K.CORNEA_R, [0, 0, K.CORNEA_CENTER_Z]); if (hc && hc[0] > 0) return add(o, mul(d, hc[0])); }
    return p;
  }
  const clip = cutPlaneZ(E.cut);
  if (h[0] > 0) { const p = add(o, mul(d, h[0])); if (p[2] <= clip + 1e-6) return p; }
  if (o[2] > clip && d[2] < 0) { const c = add(o, mul(d, (clip - o[2]) / d[2])); if (rIn * rIn <= dot(c, c) && dot(c, c) <= 1) return c; }
  const hi = hits(rIn);
  return hi && hi[1] > 0 && add(o, mul(d, hi[1]))[2] <= clip ? add(o, mul(d, hi[1])) : null;
}
function zoomAt(steps, pos = null) {
  const [w, h] = viewSize();
  pos = pos || [w / 2, h / 2];
  if (E.mode === 'inside') zoomInside(steps, pos); else zoomOutside(steps, pos);
  viewChanged();
}
function zoomOutside(steps, pos) {
  const [o, d] = ray(...pos), hit = pick(o, d), anchor = hit || add(o, mul(d, E.dist));
  let s = 0.88 ** steps;
  const reach = len(sub(anchor, o));
  if (s < 1) s = Math.max(s, Math.min(1, 0.06 / Math.max(reach, 1e-6)), 0.02 / E.dist);
  s = Math.min(s, 12 / E.dist);
  if (Math.abs(s - 1) < 1e-9) return;
  let target;
  if (s > 1 && E.dist * s >= homeDist()) target = mul(E.target, 0.5);
  else {
    target = add(anchor, mul(sub(E.target, anchor), s));
    if (s > 1) target = mul(target, 1 - 0.5 * clamp((E.dist * s - 1.6) / 1.7, 0, 1));
  }
  E.target = target; E.dist *= s;
}
function zoomInside(steps, pos) {
  const fov = clamp(E.inFov * 0.88 ** steps, 4, 140);
  if (fov === E.inFov) return;
  const [, d0] = ray(...pos);
  E.inFov = fov;
  for (let i = 0; i < 3; i++) {
    const [, d1] = ray(...pos), axis = cross(d1, d0), sa = len(axis);
    if (sa < 1e-9) break;
    const k = mul(axis, 1 / sa), a = Math.atan2(sa, dot(d1, d0));
    let [, f] = viewBasis();
    f = add(add(mul(f, Math.cos(a)), mul(cross(k, f), Math.sin(a))), mul(k, dot(k, f) * (1 - Math.cos(a))));
    E.inPitch = clamp(deg(Math.asin(clamp(f[1], -1, 1))), -85, 85);
    E.inYaw = clamp(deg(Math.atan2(f[0], -f[2])), -150, 150);
  }
}
function pan(dx, dy) {
  if (E.mode === 'inside') { look(dx, dy); return; }
  const [, , r, u, fovy] = viewBasis(), [, h] = viewSize(), k = 2 * E.dist * Math.tan(rad(fovy) / 2) / h;
  const t = add(sub(E.target, mul(r, dx * k)), mul(u, dy * k)), n = len(t);
  E.target = n <= 1.5 ? t : mul(t, 1.5 / n);
  redraw();
}
function look(dx, dy) {
  if (E.mode === 'inside') {
    const [, h] = viewSize(), k = E.inFov / h;
    E.inYaw = clamp(E.inYaw - dx * k, -150, 150); E.inPitch = clamp(E.inPitch + dy * k, -85, 85);
  } else {
    E.yaw = (((E.yaw - dx * 0.4) % 360) + 360) % 360; E.pitch = clamp(E.pitch + dy * 0.4, -89, 89);
  }
  redraw();
}

// motion of the eye
const fling = new Decay((dx, dy) => (E.dragKind === 'pan' ? pan(dx, dy) : look(dx, dy)), 0.42, 4.0);
let zoomPos = null;
const zoomGlide = new Chase((s) => zoomAt(s, zoomPos), 0.05);
const turnX = new Chase((d) => keyTurn(d, 0), 0.045);
const turnY = new Chase((d) => keyTurn(0, d), 0.045);
let viewGlide = new Tween(() => {}, 0.45);
function keyTurn(dx, dy) {
  if (E.mode === 'inside') { E.inYaw = clamp(E.inYaw - dx * 0.5, -150, 150); E.inPitch = clamp(E.inPitch + dy * 0.5, -85, 85); }
  else { E.yaw = (((E.yaw - dx) % 360) + 360) % 360; E.pitch = clamp(E.pitch + dy, -89, 89); }
  redraw();
}
function stopMotion() { fling.stop(); zoomGlide.stop(); turnX.stop(); turnY.stop(); viewGlide.stop(); journey.stop(); }
const moving = () => E.drag != null || fling.running() || zoomGlide.running() || turnX.running() || turnY.running() || viewGlide.running() || journey.running();
function glideTo(goal = null, inside = null, duration = 0.45, extra = null, done = null, easing = ease) {
  fling.stop(); zoomGlide.stop(); viewGlide.stop();
  extra = extra || {};
  const x0 = {}; for (const k of Object.keys(extra)) x0[k] = E[k];
  E.viewEnds = [[pose(), [E.inYaw, E.inPitch, E.inFov], x0], goal, inside, extra];
  viewGlide = new Tween(viewGlideTo, duration, easing, done);
  viewGlide.start();
}
function viewGlideTo(k) {
  if (!E.viewEnds) return;
  const [[p0, i0, x0], p1, i1, x1] = E.viewEnds;
  if (p1) {
    const dy = ((((p1.yaw - p0.yaw + 180) % 360) + 360) % 360) - 180;
    E.yaw = (((p0.yaw + dy * k) % 360) + 360) % 360;
    E.pitch = lerp(p0.pitch, p1.pitch, k);
    E.dist = p0.dist * (p1.dist / p0.dist) ** k;
    E.target = [0, 1, 2].map((i) => lerp(p0.target[i], p1.target[i], k));
    if (k >= 1) { E.yaw = ((p1.yaw % 360) + 360) % 360; E.pitch = p1.pitch; E.dist = p1.dist; }
  }
  if (i1) { E.inYaw = lerp(i0[0], i1[0], k); E.inPitch = lerp(i0[1], i1[1], k); E.inFov = i0[2] * (i1[2] / i0[2]) ** k; }
  for (const [n, g] of Object.entries(x1)) E[n] = lerp(x0[n], g, k);
  viewChanged();
}
function resetView(animate = true) {
  if (animate && motionOn) { journey.stop(); glideTo(home(), [0, 0, E.FOV0], 0.45, { outFov: 38 }); return; }
  stopMotion();
  Object.assign(E, { yaw: 38, pitch: 18, dist: homeDist(), target: [0, 0, 0], inYaw: 0, inPitch: 0, inFov: E.FOV0, outFov: 38 });
  viewChanged();
}
const frontPose = () => ({ yaw: 0, pitch: 0, dist: homeDist(), target: [0, 0, 0] });
function frontView(animate = true) {
  if (animate && motionOn && E.mode === 'outside') { journey.stop(); glideTo(frontPose(), null, 0.45, { outFov: 38 }); return; }
  stopMotion();
  Object.assign(E, { ...frontPose(), outFov: 38 });
  viewChanged();
}
// 들어가며 보기: from the whole eye, in through the cornea, the anterior chamber, the pupil, the lens and
// the vitreous to the retina — nothing goes dark on the way. j: 0 the whole eye … 1 the retina (내부).
const JOURNEY_Z = 0.35;       // where it ends: the inside view's eye point (EyeView.in_z)
const journey = {
  j: 0, from: null, fromCut: 0.25, fromXray: 0, tween: null, playing: false,
  running() { return this.playing; },
  begin() {   // the path starts from the eye as it is now (or the start view)
    if (this.from) return;
    if (E.mode === 'inside') { this.from = { ...home() }; this.j = 1; }
    else { this.from = pose(); this.j = 0; }
    this.fromCut = E.cut < 0.999 ? E.cut : 0.25;
    this.fromXray = E.xray;
    if (vt.active()) vt.finish();
    E.half = 0;
  },
  pose(j) {   // the camera and the eye at j
    const f = this.from, a = 0.32;
    const out = { mode: j >= 1 ? 'inside' : 'outside', cut: lerp(this.fromCut, 1, ease(j / 0.12)), xray: lerp(this.fromXray, 0, ease(j / 0.12)) };
    if (j <= a) {   // to the front of the closed eye, coming nearer
      const k = ease(j / a);
      Object.assign(out, { yaw: ((lerpAngle(f.yaw, 0, k) % 360) + 360) % 360, pitch: lerp(f.pitch, 0, k), dist: f.dist * (1.9 / f.dist) ** k,
        target: f.target.map((x) => x * (1 - k)), outFov: 38 });
    } else {        // along the axis: the cornea, the chamber, the pupil, the lens, the vitreous
      const k = ease((j - a) / (1 - a));
      const knots = [[0, 1.9], [0.2, 1.12], [0.78, 0.45], [1, JOURNEY_Z]];   // most of the time from the cornea to the lens
      let z = JOURNEY_Z;
      for (let i = 0; i < knots.length - 1; i++) {
        const [k0, z0] = knots[i], [k1, z1] = knots[i + 1];
        if (k <= k1) { z = lerp(z0, z1, (k - k0) / (k1 - k0)); break; }
      }
      const fov = 38 + (80 - 38) * ease((1.55 - z) / 0.5) + (E.FOV0 - 80) * ease((0.6 - z) / 0.25);
      Object.assign(out, { yaw: 0, pitch: 0, dist: z, target: [0, 0, 0], outFov: fov });
    }
    return out;
  },
  apply(j) {
    this.j = clamp(j, 0, 1);
    const p = this.pose(this.j);
    Object.assign(E, { cut: p.cut, xray: p.xray, yaw: p.yaw, pitch: p.pitch, dist: p.dist, target: p.target, outFov: p.outFov });
    if (p.mode === 'inside') Object.assign(E, { mode: 'inside', inYaw: 0, inPitch: 0, inFov: E.FOV0, inZ: JOURNEY_Z });
    else E.mode = 'outside';
    ui.onJourney(this.j);
    viewChanged();
  },
  scrub(j) { this.stop(); this.begin(); this.apply(j); },
  play(to, done = null) {   // glide to j = to (1 in, 0 out), slowly enough to see where it passes
    this.stop(); this.begin();
    const j0 = this.j, dur = Math.max(0.4, 7.5 * Math.abs(to - j0));
    this.playing = true;
    this.tween = new Tween((k) => this.apply(lerp(j0, to, k)), dur, (x) => x, () => { this.playing = false; if (done) done(); });
    this.tween.start();
  },
  stop() { if (this.tween) this.tween.stop(); this.playing = false; },
  end() {   // back to the ordinary views: the path is forgotten
    this.stop(); this.from = null;
  },
};
// 자동 회전
const spin = {
  yaw: null,
  step(dt) {
    const t = now();
    const busy = E.drag != null || fling.running() || zoomGlide.running() || viewGlide.running() || journey.running() || E.mode !== 'outside'
      || E.scan != null || show.playing || len(viewBasis()[0]) < 1.1;   // (not inside the eye on the way in)
    if (busy || this.yaw == null || Math.abs(E.yaw - this.yaw) > 1e-9) { E.touched = t; this.yaw = E.yaw; return E.autoRotate !== 0; }
    const k = clamp((t - E.touched - E.SPIN_WAIT) / 1.5, 0, 1);
    if (k > 0) { E.yaw = (E.yaw + E.autoRotate * k * k * (3 - 2 * k) * dt) % 360; this.yaw = E.yaw; redraw(); }
    return E.autoRotate !== 0;
  },
};
function setAutoRotate(degPerS) {
  E.autoRotate = degPerS; E.touched = now();
  if (degPerS && motionOn) ticker.add(spin); else ticker.remove(spin);
}

// the section's view tween (slit_scan.ViewTween): camera, section plane and 망막 투시 glide together
const vt = {
  timer: null, from: null, to: null, t0: 0, dur: 0.8, done: null,
  go(goal, half, xray, duration = 0.8, done = null) {
    this.finish(); stopMotion();
    this.from = [pose(), E.half, E.xray]; this.to = [goal, half, xray];
    this.t0 = now(); this.dur = Math.max(duration, 1e-3); this.done = done;
    if (!motionOn || duration <= 0) { this.live = true; this.finish(true); return; }
    this.live = true; ticker.add(this);
  },
  step() {
    const k = ease((now() - this.t0) / this.dur), [[p0, h0, x0], [p1, h1, x1]] = [this.from, this.to];
    E.half = lerp(h0, h1, k); E.xray = lerp(x0, x1, k);
    if (p1) { const p = lerpPose(p0, p1, k); Object.assign(E, { yaw: p.yaw, pitch: p.pitch, dist: p.dist, target: p.target }); }
    redraw();
    if (k >= 1) { this.finish(); return false; }
    return true;
  },
  active() { return !!this.live; },
  finish(withPose = false) {   // the cut and the coats reach their goal; the camera only for an instant change
    if (!this.live) return;     // (a touch ends the glide where the camera is, as in the program)
    this.live = false; ticker.remove(this);
    E.half = this.to[1]; E.xray = this.to[2];
    const p = this.to[0];
    if (p && withPose) Object.assign(E, { yaw: p.yaw, pitch: p.pitch, dist: p.dist, target: p.target.slice() });
    viewChanged();
    const d = this.done; this.done = null; if (d) d();
  },
};
const lerpAngle = (a, b, t) => a + (((((b - a + 180) % 360) + 360) % 360) - 180) * t;
const lerpPose = (p0, p1, t) => ({ yaw: ((lerpAngle(p0.yaw, p1.yaw, t) % 360) + 360) % 360, pitch: lerp(p0.pitch, p1.pitch, t),
  dist: lerp(p0.dist, p1.dist, t), target: [0, 1, 2].map((i) => lerp(p0.target[i], p1.target[i], t)) });

// ---------------------------------------------------------------------------------------------
// WebGL: programs, meshes, textures
// ---------------------------------------------------------------------------------------------
const R = { prog: {}, info: new Map(), meshes: {}, dyn: {}, keys: {}, mtex: {}, ok: false };   // info: by program object
function compile(src, kind) {
  const s = gl.createShader(kind); gl.shaderSource(s, src); gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
  return s;
}
function program(name, { vs, fs }) {
  const p = gl.createProgram();
  gl.attachShader(p, compile(vs, gl.VERTEX_SHADER)); gl.attachShader(p, compile(fs, gl.FRAGMENT_SHADER));
  ['a_pos', 'a_nrm', 'a_uv'].forEach((n, i) => gl.bindAttribLocation(p, i, n));
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(name + ': ' + gl.getProgramInfoLog(p));
  const info = {};
  for (let i = 0, n = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS); i < n; i++) {
    const a = gl.getActiveUniform(p, i);
    info[a.name.replace(/^u_/, '').replace(/\[0\]$/, '')] = { loc: gl.getUniformLocation(p, a.name), type: a.type };
  }
  gl.useProgram(p);
  for (const [n, unit] of Object.entries(MD.units)) if (info[n]) gl.uniform1i(info[n].loc, unit);
  R.prog[name] = p; R.info.set(p, info);
  return p;
}
function setU(p, values) {
  const info = R.info.get(p);
  for (const [name, v] of Object.entries(values)) {
    const u = info[name];
    if (!u) continue;
    switch (u.type) {
      case gl.FLOAT: gl.uniform1f(u.loc, +v); break;
      case gl.INT: case gl.BOOL: gl.uniform1i(u.loc, v | 0); break;
      case gl.FLOAT_VEC2: gl.uniform2f(u.loc, v[0], v[1]); break;
      case gl.FLOAT_VEC3: gl.uniform3f(u.loc, v[0], v[1], v[2]); break;
      case gl.FLOAT_VEC4: gl.uniform4f(u.loc, v[0], v[1], v[2], v[3]); break;
      case gl.FLOAT_MAT3: gl.uniformMatrix3fv(u.loc, true, new Float32Array(v)); break;
      case gl.FLOAT_MAT4: gl.uniformMatrix4fv(u.loc, true, new Float32Array(v)); break;
      default: break;
    }
  }
}
function upload(m) {
  const vao = gl.createVertexArray();
  gl.bindVertexArray(vao);
  const bufs = [];
  for (const [loc, data, size] of [[0, m.pos, 3], [1, m.nrm, 3], [2, m.uv, 2]]) {
    if (!data) { gl.disableVertexAttribArray(loc); gl.vertexAttrib2f(loc, 0, 0); continue; }
    const b = gl.createBuffer(); bufs.push(b);
    gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 0, 0);
  }
  const ib = gl.createBuffer(); bufs.push(ib);
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, m.idx, gl.STATIC_DRAW);
  gl.bindVertexArray(null);
  return { vao, bufs, n: m.idx.length, mode: m.lines ? gl.LINES : gl.TRIANGLES };
}
function drawMesh(g) {
  if (!g) return;
  gl.bindVertexArray(g.vao);
  if (!g.hasUv) gl.vertexAttrib2f(2, 0, 0);
  gl.drawElements(g.mode, g.n, gl.UNSIGNED_INT, 0);
  gl.bindVertexArray(null);
}
function freeMesh(g) { if (!g) return; gl.deleteVertexArray(g.vao); g.bufs.forEach((b) => gl.deleteBuffer(b)); }
function dynamic(name, key, build) {
  if (R.keys[name] !== key || !(name in R.dyn)) {
    freeMesh(R.dyn[name]);
    R.keys[name] = key;
    const m = build();
    R.dyn[name] = m ? Object.assign(upload(m), { hasUv: !!m.uv }) : null;
  }
  return R.dyn[name];
}
function makeTexture(source, w, h) {
  const t = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, t);
  gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
  gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE);
  gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
  if (source instanceof Uint8Array || source instanceof Uint8ClampedArray) {
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(source.buffer, source.byteOffset, source.byteLength));
  } else gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, source);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
  gl.generateMipmap(gl.TEXTURE_2D);
  const aniso = gl.getExtension('EXT_texture_filter_anisotropic');
  if (aniso) gl.texParameterf(gl.TEXTURE_2D, aniso.TEXTURE_MAX_ANISOTROPY_EXT, 4);
  return t;
}
function loadImage(src) {
  return new Promise((res, rej) => { const im = new Image(); im.onload = () => res(im); im.onerror = rej; im.src = src; });
}
async function initGL() {
  if (!gl) throw new Error('이 브라우저에서는 WebGL 2를 쓸 수 없습니다');
  for (const [name, s] of Object.entries(DATA.shaders)) program(name, s);
  for (const [name, m] of Object.entries(staticMeshes())) R.meshes[name] = Object.assign(upload(m), { hasUv: !!m.uv });
  const names = { iris: 'iris', scl_a: 'scl_a', scl_p: 'scl_p', peri: 'peri' };
  for (const [unitName, key] of Object.entries(names)) {
    const im = await loadImage(DATA.textures[key]);
    R.mtex[unitName] = makeTexture(im);
  }
  R.empty = makeTexture(new Uint8Array(4), 1, 1);
  R.ok = true;
}

// ---------------------------------------------------------------------------------------------
// drawing: EyeView._paint_scene (the detailed look)
// ---------------------------------------------------------------------------------------------
// the way the slit moves over the photo (x to its right, y down)
function scanDir(axis = E.slitAxis, sign = E.scanSign) { const a = slitAngle(axis); return [sign * Math.cos(a), -sign * Math.sin(a)]; }
function mappingUniforms() {
  const tmax = E.thetaMax();
  let scan = [-1, 0];
  if (E.scan != null && E.scanDim > 0) scan = [2 * clamp(E.scan, 0, 1) - 1, Math.min(1, E.scanDim)];
  const tex = !!E.tex;
  return {
    tmax, gmax: gfun(tmax, E.projection, E.viewpoint, tmax, E.radialC), proj: Math.max(0, PROJECTIONS.indexOf(E.projection)),
    d: E.viewpoint, c: E.radialC, center: E.center, radius: E.radius, roll: rad(E.roll), place: m3T(E.placement.matrix),
    grid: E.showGrid ? 1 : 0, has_tex: tex ? 1 : 0, scan, scan_dir: scanDir(), fovring: E.fovRing,
    relief: tex ? E.relief : 0, texel: E.texel, rlight: m3v(m3T(E.placement.matrix), E.rlight),
    hmap_on: reliefSheetOn() ? 1 : 0,
  };
}
function paintScene(w, h) {
  gl.viewport(0, 0, w, h);
  const [, vf, vr, vu] = viewBasis();
  E.rlight = unit(add(add(mul(vr, -0.55), mul(vu, 0.75)), mul(vf, -0.35)));
  if (E.black) gl.clearColor(0, 0, 0, 1); else gl.clearColor(0.105, 0.115, 0.13, 1);
  gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
  gl.disable(gl.CULL_FACE); gl.disable(gl.BLEND);
  const inside = E.mode === 'inside', half = halfOn(), closed = !inside && !half && E.cut >= 0.999;
  const [mvp, campos] = cameraMats(w / h);
  // 들어가며 보기: the camera inside the globe (or the cornea) still in the outside view — the coats are
  // seen from within (their outer faces are not drawn), the inside of the eye is drawn as when opened
  const within = !inside && (len(campos) < 0.999 || len(sub(campos, [0, 0, K.CORNEA_CENTER_Z])) < K.CORNEA_R
    || (journey.from != null && journey.j > 0.27));   // (from the cornea on, it is clear: the inside shows through the pupil)
  // the textures, on the units the shaders were told
  const bind = (unitIdx, t) => { gl.activeTexture(gl.TEXTURE0 + unitIdx); gl.bindTexture(gl.TEXTURE_2D, t); };
  bind(MD.units.tex, E.tex || R.empty);
  for (const n of ['iris', 'scl_a', 'scl_p', 'peri']) bind(MD.units[n], R.mtex[n]);
  bind(MD.units.hmap, E.hmapTex || R.empty);
  gl.activeTexture(gl.TEXTURE0);
  gl.enable(gl.DEPTH_TEST);

  const lights = inside ? { key: unit([0.15, 0.25, 1]), kx: [1, 0, 0], ky: [0, 1, 0], fill: [0, 0, 1], fx: [1, 0, 0], fy: [0, 1, 0] } : studioLights(campos);
  const [k, off] = half ? halfPlane() : [[0, 0, 0], 1];
  const clip = closed || inside || half ? 2 : E.cut;
  const common = { mvp, campos, cut: clip, mirror: E.laterality === 'OS' ? 1 : 0, hk: k, hoff: off, simple: E.simple, ...lights };
  const mapping = mappingUniforms();
  const use = (name, extra = {}) => { const p = R.prog[name]; gl.useProgram(p); setU(p, common); setU(p, extra); return p; };
  const glass = inside || half ? 0 : clamp(E.glass, 0, 1);
  const drawSclera = () => {
    use('sclera', { clip: closed || half ? K.LIMBUS_Z : Math.min(E.cut, K.LIMBUS_Z), disc: E.discDir || [0.37, 0.02, -0.93],
      xray: E.xray, glass, ...mapping });
    drawMesh(R.meshes.sclera);
  };
  if (!inside) {
    if (glass <= 0) drawSclera();
    if (half) {
      use('section', { part: 0 });
      drawMesh(dynamic('half_face', k.map((x) => x.toFixed(6)).join() + ':' + off.toFixed(5), () => sectionQuad(k, off)));
    } else if (!closed) {
      const p = use('tissue', { rim_post: cutPlaneZ(E.cut) < K.Z_ORA ? 1 : 0 });
      const rims = rimFor(E.cut);
      for (const [part, kind] of [['wall', 0], ['iris', 1]]) {
        const g = dynamic('rim_' + part, E.cut.toFixed(4), () => rims[part] || null);
        if (g) { setU(p, { kind }); drawMesh(g); }
      }
    }
    if (E.showNerve && E.discDir) {
      use('tissue', { kind: 4 });
      drawMesh(dynamic('nerve', E.discDir.map((x) => x.toFixed(6)).join() + E.laterality, () => nerveMesh(E.discDir, E.laterality)));
    }
    if (E.showMuscles) { use('tissue', { kind: 5 }); drawMesh(R.meshes[E.laterality === 'OS' ? 'muscles_OS' : 'muscles_OD']); }
    if (closed && !within) { use('cornea'); drawMesh(R.meshes.cornea); }
  }
  if (!closed || glass > 0 || within) {
    if (inside || half || E.cut > K.IRIS_BACK_Z) {
      use('tissue', { kind: 2 }); drawMesh(R.meshes.iris);
      setU(R.prog.tissue, { kind: 3 }); drawMesh(R.meshes.angle);
    }
    const sheet = reliefSheet();   // 망막 높낮이: the photographed field as the relief sheet, the wall open there
    const pw = use('wall', { inside: inside ? 1 : 0, light: inside ? [0, 0, 1] : lights.key, side: glass > 0 ? 1 : 0, glass, hole: sheet ? 0.995 : 0, ...mapping });
    drawMesh(R.meshes.wall);
    if (sheet) { setU(pw, { hole: 0 }); drawMesh(sheet); }
  }
  drawBackdrop(w, h);
  if (inside || half || within || ((!closed || glass > 0) && E.cut > K.LENS_BACK_Z)) {
    gl.enable(gl.BLEND);
    gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA, gl.ZERO, gl.ONE);
    gl.depthMask(false);
    // from within the eye the studio's lights are not mirrored in the lens and the cornea
    const p = use('clear', { kind: 2, within: within || inside ? 1 : 0 });
    if (E.simple < 0.999) drawMesh(R.meshes.zonules);
    setU(p, { kind: 0 });
    gl.enable(gl.CULL_FACE);
    for (const face of [gl.FRONT, gl.BACK]) { gl.cullFace(face); drawMesh(R.meshes.lens); }
    gl.disable(gl.CULL_FACE);
    if (half) {
      use('section', { part: 1 }); drawMesh(R.dyn.half_face);
      use('clear', { kind: 3 }); drawMesh(R.meshes.cornea);
    } else if (within && closed) {
      use('clear', { kind: 3 }); drawMesh(R.meshes.cornea);   // the cornea as a clear shell on the way in
    } else if (!inside) {
      const g = dynamic('rim_lens', E.cut.toFixed(4), () => rimFor(E.cut).lens || null);
      if (g) { setU(p, { kind: 1 }); drawMesh(g); }
    }
    gl.depthMask(true); gl.disable(gl.BLEND);
  }
  if (glass > 0) {
    gl.enable(gl.BLEND);
    gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA, gl.ZERO, gl.ONE);
    gl.depthMask(false);
    const sheet = reliefSheet();
    const pw = use('wall', { inside: 0, light: lights.key, side: 2, glass, hole: sheet ? 0.995 : 0, ...mapping });
    drawMesh(R.meshes.wall);
    if (sheet) { setU(pw, { hole: 0 }); drawMesh(sheet); }
    drawSclera();
    gl.depthMask(true); gl.disable(gl.BLEND);
  }
  drawDark();
  return mvp;
}
let rimCache = [null, {}];
function rimFor(cut) { if (rimCache[0] !== cut) rimCache = [cut, rimMeshes(cut)]; return rimCache[1]; }
function drawBackdrop(w, h) {
  gl.depthMask(false);
  const p = R.prog.bg; gl.useProgram(p); setU(p, { aspect: w / Math.max(1, h), black: E.black ? 1 : 0 });
  drawMesh(R.meshes.bg);
  gl.depthMask(true);
}
function drawDark() {
  if (E.dark <= 0.002) return;
  const p = R.prog.fade; gl.useProgram(p); setU(p, { dark: Math.min(1, E.dark) });
  gl.disable(gl.DEPTH_TEST); gl.enable(gl.BLEND);
  gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA, gl.ZERO, gl.ONE);
  drawMesh(R.meshes.bg);
  gl.disable(gl.BLEND);
}

// the field of view and the slit beam over the section (EyeView._paint_overlay), on a 2D canvas
const FOV_COLOR = [56, 200, 255], BEAM_COLOR = [255, 128, 64];
function paintOverlay(mvp) {
  const ctx = overlay.getContext('2d'), [w, h] = viewSize(), dpr = overlay.width / w;
  ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, overlay.width, overlay.height);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const wanted = halfOn() && ((E.fovAlpha > 0.005 && E.fovSweep > 0) || (E.scan != null && E.scanBeam > 0.005));
  if (!wanted) return;
  const [k, off] = halfPlane(), eye = viewBasis()[0];
  const vis = ease((-dot(eye, k) - off) / Math.max(len(eye), 1e-6) / 0.3);
  if (vis <= 0) return;
  const toScreen = (p) => { const v = m4v(mvp, [p[0], p[1], p[2], 1]); return v[3] <= 1e-6 ? null : [(v[0] / v[3] + 1) * 0.5 * w, (1 - v[1] / v[3]) * 0.5 * h]; };
  const m = meridian(), zax = [0, 0, 1], base = mul(k, -off);
  const onPlane = (t, r) => add(base, mul(sub(mul(m, Math.sin(t)), mul(zax, Math.cos(t))), r));
  const centre = toScreen(base), edge = toScreen(onPlane(PI / 2, 1));
  if (!centre || !edge) return;
  const eyePx = Math.hypot(edge[0] - centre[0], edge[1] - centre[1]), lw = Math.max(1.4, eyePx / 95);
  const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${clamp(a, 0, 1)})`;
  const glow = (pts, color, alpha, width) => {
    pts = pts.filter(Boolean);
    if (pts.length < 2 || alpha <= 0) return;
    ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    for (const [wm, a] of [[4.5, 0.12], [2.4, 0.28], [1, 1]]) {
      ctx.strokeStyle = rgba(color, alpha * a); ctx.lineWidth = width * wm;
      ctx.beginPath(); ctx.moveTo(...pts[0]); for (const q of pts.slice(1)) ctx.lineTo(...q); ctx.stroke();
    }
  };
  const spot = (p, color, alpha, r) => {
    for (const [rm, a] of [[2.6, 0.18], [1.6, 0.4], [1, 1]]) { ctx.fillStyle = rgba(color, alpha * a); ctx.beginPath(); ctx.arc(p[0], p[1], r * rm, 0, 2 * PI); ctx.fill(); }
  };
  if (E.scan != null && E.scanBeam > 0.005) {
    const a = E.scanBeam * vis, [th, side] = scanTheta(E.scan), hit = toScreen(onPlane(side * th, K.R_RET));
    glow([toScreen(add(base, mul(zax, 1.9))), toScreen(add(base, mul(zax, K.IRIS_Z + 0.01))), hit], BEAM_COLOR, a, lw * 1.15);
    if (hit) spot(hit, [255, 226, 190], a, lw * 1.6);
  }
  if (E.fovAlpha > 0.005 && E.fovSweep > 0) {
    const a = E.fovAlpha * vis, [t0, t1] = fieldOnMeridian(), mid = 0.5 * (t0 + t1), hs = 0.5 * (t1 - t0) * Math.min(1, E.fovSweep);
    for (const et of [mid + hs, mid - hs]) glow([centre, toScreen(onPlane(et, K.R_RET))], FOV_COLOR, a, lw);
    const arc = []; for (let i = 0; i < 72; i++) arc.push(toScreen(onPlane(mid - hs + 2 * hs * i / 71, 0.2)));
    glow(arc, FOV_COLOR, a * 0.9, lw * 0.8);
    spot(centre, FOV_COLOR, a, lw * 1.2);
    const la = a * ease((E.fovSweep - 0.55) / 0.45), anchor = toScreen(add(base, mul(zax, 0.33)));
    if (la > 0.01 && anchor) {
      const big = Math.max(14, Math.round(eyePx * 0.24)), small = Math.max(10, Math.round(eyePx * 0.075));
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.lineJoin = 'round';
      for (const [text, size, dy, ow] of [[`${Math.round(deg(2 * E.thetaMax()))}°`, big, -small * 0.75, Math.max(2, big / 9)],
        ['안구 중심각', small, big * 0.55, Math.max(1.5, small / 5)]]) {
        ctx.font = `${size === big ? 700 : 500} ${size}px ${getComputedStyle(document.body).fontFamily}`;
        ctx.strokeStyle = `rgba(0,16,28,${la * 0.85})`; ctx.lineWidth = ow * 2; ctx.strokeText(text, anchor[0], anchor[1] + dy);
        ctx.fillStyle = rgba(FOV_COLOR, la); ctx.fillText(text, anchor[0], anchor[1] + dy);
      }
    }
  }
}

// ---------------------------------------------------------------------------------------------
// the frame loop: animations step on real time, the eye is drawn when something changed
// ---------------------------------------------------------------------------------------------
// A computer without a graphics card (the browser draws in software): while the eye moves and the
// frames come slowly, it is drawn smaller and stretched; when it stops, sharp again (as the program).
let dirty = true, rafId = 0, lastT = 0, scale = 1, slowFrames = 0, sharpTimer = 0;
function redraw() { dirty = true; requestFrame(); }
function requestFrame() { if (!rafId) rafId = requestAnimationFrame(frame); }
function frame(t) {
  rafId = 0;
  const gap = lastT ? (t - lastT) / 1000 : 1 / 60, dt = clamp(gap, 1e-4, 0.25);
  lastT = t;
  ticker.step(dt);
  if (show.timerOn) show.tick();
  const busy = ticker.anims.size > 0 || show.timerOn || E.drag != null;
  if (busy && gap > 0.05 && ++slowFrames >= 2) { scale = Math.max(0.45, scale * 0.8); slowFrames = 0; }
  else if (gap < 0.03) { slowFrames = 0; if (busy && scale < 1) scale = Math.min(1, scale * 1.06); }
  if (dirty && R.ok) {
    dirty = false; render(busy ? [1, 0.8, 0.65, 0.5].find((q) => q <= scale + 1e-9) || 0.5 : 1);   // in steps: the canvas is resized seldom
    clearTimeout(sharpTimer);
    if (busy && scale < 1) sharpTimer = setTimeout(() => { if (!(ticker.anims.size || show.timerOn || E.drag)) redraw(); }, 180);
  }
  if (ticker.anims.size || show.timerOn || dirty) requestFrame(); else lastT = 0;
}
function render(s = 1) {
  resize(s);
  const mvp = paintScene(canvas.width, canvas.height);
  paintOverlay(mvp);
}
function resize(s = 1) {
  const [w, h] = viewSize();
  let dpr = Math.min(window.devicePixelRatio || 1, 2);
  if (w * h * dpr * dpr > 4.2e6) dpr = Math.sqrt(4.2e6 / (w * h));
  dpr *= s;
  const W = Math.round(w * dpr), H = Math.round(h * dpr);
  if (canvas.width !== W || canvas.height !== H) { canvas.width = W; canvas.height = H; }
  if (overlay.width !== W || overlay.height !== H) { overlay.width = W; overlay.height = H; }
}
function viewChanged() { ui.zoom && (ui.zoom.textContent = `배율 ×${magnification().toFixed(1)}`); redraw(); }

// ---------------------------------------------------------------------------------------------
// 슬릿 스캔 (slit_scan.SlitScanShow): a pure function of time
// ---------------------------------------------------------------------------------------------
const ramp = (t, t0, t1) => ease((t - t0) / (t1 - t0));
// The slit can cross the photo four ways. Down and up: on 세로 단면 seen from the side, the beam through
// the pupil to the retina. Right and left: on the eye opened at the front, seen from the front, the
// slit sweeping over the retina. 상하좌우: all four, one after another.
const SLIT = {
  down: { axis: 'v', sign: -1, stage: 'section', name: '위에서 아래로' },
  up: { axis: 'v', sign: 1, stage: 'section', name: '아래에서 위로' },
  right: { axis: 'h', sign: 1, stage: 'front', name: '왼쪽에서 오른쪽으로' },
  left: { axis: 'h', sign: -1, stage: 'front', name: '오른쪽에서 왼쪽으로' },
};
const SLIT_ALL = ['down', 'up', 'right', 'left'];
const FRONT_CUT = 0.25;   // the front opening for the right/left passes
const show = {
  T_SIDE: 1.6, T_FOV: [1.6, 3.4], SCAN: 5.2, SCAN_ALL: 4.2, GAP: 0.6, SWITCH: 2.8, DONE: 0.5, TURN: 3.3, END_HALF: 0.62, SPIN_RATE: 14,
  timerOn: false, playing: false, showFov: false, xrayAfter: false, t0: 0, dir: 'down', segs: [],
  passes() { return this.dir === 'all' ? SLIT_ALL : [this.dir]; },
  start() {
    stopMotion();
    journey.end();
    const passes = this.passes(), first = SLIT[passes[0]];
    Object.assign(E, { mode: 'outside', dark: 0, outFov: 38 });
    this.startPose = pose(); this.startHalf = E.half; this.startXray = E.xray; this.startCut = E.cut;
    E.slitAxis = first.axis; E.scanSign = first.sign;
    // the timeline: to the first stage, the field of view, the passes (a pause between two on one
    // stage; between 세로 단면 and the front opening the section closes as the front opens), the turn
    // to the showcase, the spin
    const segs = [], dur = passes.length > 1 ? this.SCAN_ALL : this.SCAN;
    let t = this.T_FOV[1];
    passes.forEach((key, i) => {
      if (i > 0) {
        const prev = SLIT[passes[i - 1]], cur = SLIT[key], same = prev.stage === cur.stage, d = same ? this.GAP : this.SWITCH;
        segs.push({ kind: same ? 'gap' : 'switch', t0: t, t1: t + d, from: prev, to: cur }); t += d;
      }
      segs.push({ kind: 'scan', t0: t, t1: t + dur, pass: SLIT[key], first: i === 0 }); t += dur;
    });
    this.segs = segs; this.last = SLIT[passes[passes.length - 1]];
    this.T_DONE = t + this.DONE; this.T_TURN = [this.T_DONE, this.T_DONE + this.TURN];
    this.at = { section: { pose: sectionPose(), half: 1, cut: 1 }, front: { pose: { ...frontPose(), dist: fit(E.DIST0, 1.15) }, half: 0, cut: FRONT_CUT } };
    this.end = this.last.stage === 'section' ? { pose: showcasePose(), half: this.END_HALF, cut: 1, xray: 1 }
      : { pose: home(), half: 0, cut: FRONT_CUT, xray: 0 };
    this.t0 = now(); this.playing = true; this.timerOn = true;
    this.apply(this.frame(0)); requestFrame();
  },
  stop() {
    if (!this.timerOn) return;
    this.timerOn = false;
    const wasPlaying = this.playing; this.playing = false;
    const t = now() - this.t0;
    E.scan = null; E.scanBeam = 0; views.side.setScan(null);
    if (wasPlaying && t < this.T_DONE) { if (E.half > 0.01) E.half = 1; E.xray = this.xrayAfter ? 1 : 0; }
    else { E.half = this.end.half; E.cut = this.end.cut; E.xray = this.end.xray; }
    const on = this.showFov ? 1 : 0;
    E.fovSweep = E.fovAlpha = E.fovRing = on;
    ui.where('');
    redraw(); ui.onScanStopped();
  },
  frame(t) {
    const ring = this.showFov ? 1 : 0, first = SLIT[this.passes()[0]];
    const F = (p, half, cut, xray, scan, dim, beam, sweep, alpha, fring, phase, slit = first) =>
      ({ pose: p, half, cut, xray, scan, dim, beam, sweep, alpha, fring, phase, axis: slit.axis, sign: slit.sign, name: slit.name, stage: slit.stage });
    const st = this.at[first.stage];
    if (t < this.T_SIDE) {
      const k = ramp(t, 0, this.T_SIDE), kh = ramp(t, 0.2, 1.45);
      return F(lerpPose(this.startPose, st.pose, k), lerp(this.startHalf, st.half, kh), lerp(this.startCut, st.cut, kh),
        lerp(this.startXray, 0, ramp(t, 0, 0.8)), null, 0, 0, 0, 0, lerp(ring, 0, k), 'side');
    }
    if (t < this.T_FOV[1]) {
      const t0 = this.T_FOV[0];
      return F(st.pose, st.half, st.cut, 0, 0, ramp(t, t0 + 0.2, t0 + 1.4), 0, ramp(t, t0, t0 + 1.2), 1, 0, 'fov');
    }
    for (const g of this.segs) {
      if (t >= g.t1) continue;
      if (g.kind === 'scan') {
        const { t0, t1 } = g, s = 0.5 - 0.5 * Math.cos(PI * clamp((t - t0) / (t1 - t0), 0, 1)), at = this.at[g.pass.stage];
        const beam = ramp(t, t0, t0 + 0.25) * (1 - ramp(t, t1, t1 + 0.35));
        const dim = g.first ? 1 : ramp(t, t0, t0 + 0.35);   // a later pass: the photo darkens again as it starts
        return F(at.pose, at.half, at.cut, 0, s, dim, beam, 1, 1, 0, 'scan', g.pass);
      }
      const A = this.at[g.from.stage], B = this.at[g.to.stage];
      if (g.kind === 'gap') return F(B.pose, B.half, B.cut, 0, 1, 1 - ramp(t, g.t0, g.t0 + 0.3), 0, 1, 1, 0, 'gap', g.from);
      // switch: the section closes as the camera turns to the front and the front opens (or back)
      const { t0, t1 } = g, mid = 0.5 * (t0 + t1), on = t < mid ? g.from : g.to;
      const half = A.half > B.half ? 1 - ramp(t, t0, t0 + 1.2) : ramp(t, t1 - 1.2, t1);
      const cut = A.cut > B.cut ? lerp(A.cut, B.cut, ramp(t, t0 + 1.0, t1)) : lerp(A.cut, B.cut, ramp(t, t0, t1 - 1.0));
      const p = lerpPose(A.pose, B.pose, ramp(t, t0 + 0.2, t1 - 0.2));
      const sweep = t < mid ? 1 : ramp(t, t1 - 0.9, t1), alpha = t < mid ? 1 - ramp(t, t0, t0 + 0.6) : ramp(t, t1 - 0.9, t1 - 0.3);
      return F(p, half, cut, 0, null, 0, 0, sweep, alpha, 0, 'switch', on);
    }
    const last = this.last, at = this.at[last.stage], end = this.end;
    if (t < this.T_DONE) return F(at.pose, at.half, at.cut, 0, 1, 1 - ramp(t, this.T_DONE - this.DONE, this.T_DONE), 0, 1, 1, 0, 'done', last);
    const [t0, t1] = this.T_TURN;
    if (t < t1) {
      return F(lerpPose(at.pose, end.pose, ramp(t, t0, t1)), lerp(at.half, end.half, ramp(t, t0 + 0.3, t1 - 0.6)), at.cut,
        end.xray * ramp(t, t0, t0 + 1.8), null, 0, 0, 1, 1 - ramp(t, t0, t0 + 0.5), ramp(t, t0 + 1.2, t0 + 2.2), 'turn', last);
    }
    const ts = t - t1, sp = this.SPIN_RATE * (ts - 1.5 * (1 - Math.exp(-ts / 1.5)));
    return F({ ...end.pose, yaw: (end.pose.yaw + sp) % 360 }, end.half, end.cut, end.xray, null, 0, 0, 1, 0, lerp(1, ring, ramp(ts, 1.5, 3.0)), 'spin', last);
  },
  apply(f) {
    Object.assign(E, { half: f.half, cut: f.cut, xray: f.xray, scan: f.scan, scanDim: f.dim, scanBeam: f.beam, fovSweep: f.sweep, fovAlpha: f.alpha,
      fovRing: f.fring, slitAxis: f.axis, scanSign: f.sign });
    Object.assign(E, { yaw: f.pose.yaw, pitch: f.pose.pitch, dist: f.pose.dist, target: f.pose.target.slice() });
    views.side.setScan(f.scan, f.dim, scanDir(f.axis, f.sign));
    if (this.playing) ui.where(['fov', 'scan', 'gap', 'switch'].includes(f.phase) ? `슬릿 — ${f.name}` + (f.stage === 'section' ? ' · 세로 단면' : ' · 앞에서 본 망막') : '');
    viewChanged();
  },
  tick() {
    const t = now() - this.t0;
    this.apply(this.frame(t));
    if (this.playing && t >= this.T_TURN[1]) { this.playing = false; ui.where(''); ui.onScanFinished(); }
  },
};

// ---------------------------------------------------------------------------------------------
// photos: imaging.py (the circle, the optic disc, the fovea, the alpha mask)
// ---------------------------------------------------------------------------------------------
function pixelsOf(img, maxSide) {   // an image drawn into a canvas no larger than maxSide
  const s = Math.min(1, maxSide / Math.max(img.width, img.height));
  const w = Math.max(1, Math.round(img.width * s)), h = Math.max(1, Math.round(img.height * s));
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  const ctx = c.getContext('2d', { willReadFrequently: true });
  ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(img, 0, 0, w, h);
  return { canvas: c, w, h, data: ctx.getImageData(0, 0, w, h).data, scale: s };
}
function downsample(px, maxSide) {   // every step-th pixel, as imaging._downsample
  const step = Math.max(1, Math.ceil(Math.max(px.w, px.h) / maxSide));
  const w = Math.ceil(px.w / step), h = Math.ceil(px.h / step);
  const lum = new Float32Array(w * h), green = new Float32Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const o = ((y * step) * px.w + x * step) * 4, d = px.data;
    lum[y * w + x] = d[o] * 0.299 + d[o + 1] * 0.587 + d[o + 2] * 0.114; green[y * w + x] = d[o + 1];
  }
  return { w, h, lum, green, step };
}
function percentile(arr, p) { const a = Float32Array.from(arr).sort(); return a[Math.min(a.length - 1, Math.floor(p / 100 * (a.length - 1)))]; }
function blur(src, w, h, sigma) {   // imaging.gaussian_blur: a separable Gaussian, 3 σ each way, mirrored at the edges
  if (sigma < 0.3) return Float32Array.from(src);
  const rad = Math.max(1, Math.floor(3 * sigma)), n = 2 * rad + 1, k = new Float64Array(n);
  let sum = 0;
  for (let i = 0; i < n; i++) { const x = i - rad; k[i] = Math.exp(-x * x / (2 * sigma * sigma)); sum += k[i]; }
  for (let i = 0; i < n; i++) k[i] /= sum;
  const refl = (i, m) => {   // numpy's "reflect": … c b | a b c … (the edge is not repeated)
    if (m === 1) return 0;
    const p = 2 * (m - 1);
    i = ((i % p) + p) % p;
    return i < m ? i : p - i;
  };
  const tmp = new Float64Array(w * h), out = new Float32Array(w * h);
  const ix = new Int32Array(w + 2 * rad); for (let i = 0; i < ix.length; i++) ix[i] = refl(i - rad, w);
  for (let y = 0; y < h; y++) {   // along the rows
    const row = y * w;
    for (let x = 0; x < w; x++) { let acc = 0; for (let i = 0; i < n; i++) acc += k[i] * src[row + ix[x + i]]; tmp[row + x] = acc; }
  }
  const iy = new Int32Array(h + 2 * rad); for (let i = 0; i < iy.length; i++) iy[i] = refl(i - rad, h) * w;
  for (let y = 0; y < h; y++) {   // along the columns
    for (let x = 0; x < w; x++) { let acc = 0; for (let i = 0; i < n; i++) acc += k[i] * tmp[iy[y + i] + x]; out[y * w + x] = acc; }
  }
  return out;
}
function detectCircle(px) {
  const s = downsample(px, 512), { w, h, lum, step } = s;
  const thr = Math.max(10, 0.08 * percentile(lum, 99));
  const ys = [], x0s = [], x1s = [];
  for (let y = 0; y < h; y++) {
    let count = 0, best = 0, bs = 0, start = -1;
    for (let x = 0; x <= w; x++) {
      const on = x < w && lum[y * w + x] > thr;
      if (on) { count++; if (start < 0) start = x; } else if (start >= 0) { if (x - start > best) { best = x - start; bs = start; } start = -1; }
    }
    if (count < 0.15 * w || best < 0.15 * w) continue;
    ys.push(y); x0s.push(bs); x1s.push(bs + best - 1);
  }
  const fallback = [px.w / 2, px.h / 2, Math.min(px.w, px.h) / 2];
  if (ys.length < 8) return fallback;
  const mids = x0s.map((a, i) => (a + x1s[i]) / 2), cx = [...mids].sort((a, b) => a - b)[mids.length >> 1];
  let Y = ys, H = x0s.map((a, i) => (x1s[i] - a + 1) / 2);
  const ok = mids.map((m) => Math.abs(m - cx) < 0.05 * w);
  if (ok.filter(Boolean).length >= 8) { Y = Y.filter((_, i) => ok[i]); H = H.filter((_, i) => ok[i]); }
  let s11 = 0, s12 = 0, s22 = 0, t1 = 0, t2 = 0;   // least squares: half² + y² = c0 + 2·cy·y
  for (let i = 0; i < Y.length; i++) { const a = 1, b = 2 * Y[i], v = H[i] ** 2 + Y[i] ** 2; s11 += a * a; s12 += a * b; s22 += b * b; t1 += a * v; t2 += b * v; }
  const det = s11 * s22 - s12 * s12;
  let c0 = (t1 * s22 - s12 * t2) / det, cy = (s11 * t2 - s12 * t1) / det, r2 = c0 + cy * cy;
  let r = r2 > 0 ? Math.sqrt(r2) : Math.max(...H);
  if (!(0.2 * w < r && r < 1.2 * Math.max(w, h))) { r = Math.max(...H); cy = Y[H.indexOf(r)]; }
  return [(cx + 0.5) * step, (cy + 0.5) * step, r * step];
}
function detectDisc(px, circle, discFrac = 0.11, search = 0.7) {
  const s = downsample(px, 384), { w, h, lum, step } = s;
  const cx = circle[0] / step, cy = circle[1] / step, r = circle[2] / step, dr = Math.max(1.5, r * discFrac);
  const mean = blur(lum, w, h, dr), sq = blur(lum.map((v) => v * v), w, h, dr);
  const sd = new Float32Array(w * h), inside = new Uint8Array(w * h), vals = [], means = [];
  for (let i = 0; i < w * h; i++) {
    sd[i] = Math.sqrt(Math.max(sq[i] - mean[i] * mean[i], 0));
    const x = i % w, y = (i / w) | 0, d2 = (x - cx) ** 2 + (y - cy) ** 2;
    if (d2 <= (search * r) ** 2) { inside[i] = 1; vals.push(sd[i]); means.push(mean[i]); }
  }
  if (vals.length < 50) return null;
  const med = percentile(vals, 50), mu = vals.reduce((a, b) => a + b, 0) / vals.length;
  const std = Math.sqrt(vals.reduce((a, b) => a + (b - mu) ** 2, 0) / vals.length);
  let best = -1, bi = -1;
  for (let i = 0; i < w * h; i++) if (inside[i]) { const z = (sd[i] - med) / (std + 1e-6); if (z > best) { best = z; bi = i; } }
  if (best < 3) return null;
  const ix = bi % w, iy = (bi / w) | 0;
  if ((ix - cx) ** 2 + (iy - cy) ** 2 < (0.08 * r) ** 2) {   // at the centre: a disc only when it is bright too
    const mm = percentile(means, 50), mmu = means.reduce((a, b) => a + b, 0) / means.length;
    const mstd = Math.sqrt(means.reduce((a, b) => a + (b - mmu) ** 2, 0) / means.length);
    if ((mean[bi] - mm) / (mstd + 1e-6) < 1) return null;
  }
  return [(ix + 0.5) * step, (iy + 0.5) * step, best];
}
function lateralityFromDisc(disc, circle) {
  if (!disc || (disc.length > 2 && disc[2] < 4)) return null;
  const dx = (disc[0] - circle[0]) / Math.max(circle[2], 1);
  return Math.abs(dx) < 0.1 ? null : (dx > 0 ? 'OD' : 'OS');
}
function morphOpen(src, w, h, k) {   // the foveal reflex and other small bright spots, opened away
  const r = k >> 1, offs = [];
  for (let dy = -r; dy <= r; dy++) for (let dx = -r; dx <= r; dx++) if (dx * dx + dy * dy <= r * r + r) offs.push([dx, dy]);
  const pass = (a, fn, init) => {
    const o = new Float32Array(w * h);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      let v = init;
      for (const [dx, dy] of offs) { const xx = clamp(x + dx, 0, w - 1), yy = clamp(y + dy, 0, h - 1); v = fn(v, a[yy * w + xx]); }
      o[y * w + x] = v;
    }
    return o;
  };
  return pass(pass(src, Math.min, Infinity), Math.max, -Infinity);
}
function detectFovea(px, cam, disc, lat, windowDeg = 7) {
  // (the eye unknown: both sides are tried and the darker macula wins — a photo turned toward the
  // nose has its disc near the centre, where the side of the disc does not tell the eye)
  if (!disc || !cam || !cam.r) return null;
  const sides = lat === 'OD' || lat === 'OS' ? [lat] : ['OD', 'OS'];
  const s = downsample(px, 384), { w, h, lum, green, step } = s;
  const lut = cam.thetaLut(), tmax = cam.tmax;
  const dirs = new Float32Array(w * h * 3), mask = new Float32Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = y * w + x, dx = ((x + 0.5) * step - cam.cx) / cam.r, dy = (cam.cy - (y + 0.5) * step) / cam.r, rho = Math.hypot(dx, dy);
    const t = Math.min(rho, 1) * 256, j = Math.min(255, Math.floor(t)), th = lerp(lut[j], lut[j + 1], t - j);
    const phi = Math.atan2(dy, dx) - rad(cam.roll), st = Math.sin(th);
    dirs[i * 3] = st * Math.cos(phi); dirs[i * 3 + 1] = st * Math.sin(phi); dirs[i * 3 + 2] = -Math.cos(th);
    mask[i] = rho <= 1 && lum[i] > 8 ? 1 : 0;
  }
  let best = null;
  for (const side of sides) {
    const guess = expectedFovea(cam, disc, side);
    if (!guess) continue;
    const q0 = cam.direction(...guess), q1 = cam.direction(Math.min(guess[0] + step, cam.cx + cam.r), guess[1]);
    const degPx = q1 ? Math.max(angleBetween(q0, q1), 1e-3) : deg(tmax) / (cam.r / step);
    const sSmall = 1.5 / degPx, sBig = 6 / degPx;
    const g = morphOpen(green, w, h, Math.max(3, Math.round(2 / degPx) | 1));
    const gm = g.map((v, i) => v * mask[i]);
    const cover = blur(mask, w, h, sBig), coverS = blur(mask, w, h, sSmall), gb = blur(gm, w, h, sBig), gs = blur(gm, w, h, sSmall);
    const dark = new Float32Array(w * h), valid = new Uint8Array(w * h), vals = [];
    for (let i = 0; i < w * h; i++) {
      const c = Math.max(cover[i], 1e-6);
      dark[i] = gb[i] / c - gs[i] / Math.max(coverS[i], 1e-6);
      if (mask[i] > 0 && cover[i] > 0.85) { valid[i] = 1; vals.push(dark[i]); }
    }
    if (vals.length < 50) continue;
    const mu = vals.reduce((a, b) => a + b, 0) / vals.length;
    const spread = Math.sqrt(vals.reduce((a, b) => a + (b - mu) ** 2, 0) / vals.length) + 0.25;
    let bs = -1e9, bi = -1;
    const dist = new Float32Array(w * h);
    for (let i = 0; i < w * h; i++) {
      if (!valid[i]) continue;
      const d = deg(Math.acos(clamp(dirs[i * 3] * q0[0] + dirs[i * 3 + 1] * q0[1] + dirs[i * 3 + 2] * q0[2], -1, 1)));
      dist[i] = d;
      if (d > windowDeg) continue;
      const sc = dark[i] / spread * (0.55 + 0.45 * Math.exp(-((d / (0.7 * windowDeg)) ** 2)));
      if (sc > bs) { bs = sc; bi = i; }
    }
    if (bi < 0) continue;
    const ix = bi % w, iy = (bi / w) | 0, peak = dark[bi], around = gb[bi] / Math.max(cover[bi], 1e-6);
    if (peak < Math.max(1, 0.012 * around)) continue;
    const conf = peak / spread;
    let sw = 0, sx = 0, sy = 0;
    for (let i = 0; i < w * h; i++) {
      if (!valid[i] || dist[i] > windowDeg) continue;
      const x = i % w, y = (i / w) | 0;
      if (Math.hypot(x - ix, y - iy) > 4 / degPx) continue;
      const wt = Math.max(dark[i] - 0.5 * peak, 0); sw += wt; sx += wt * x; sy += wt * y;
    }
    const fx = peak > 0 && sw > 0 ? sx / sw : ix, fy = peak > 0 && sw > 0 ? sy / sw : iy;
    const cand = [(fx + 0.5) * step, (fy + 0.5) * step, conf, side];
    if (!best || cand[2] > best[2]) best = cand;
  }
  return best && best[2] >= 1.2 ? best : null;
}
function fundusAlpha(px, circle) {   // 255 on the lit retina, 0 on the black surround (soft edge)
  const { w, h, data } = px, n = w * h, lum = new Float32Array(n);
  for (let i = 0; i < n; i++) lum[i] = data[i * 4] * 0.299 + data[i * 4 + 1] * 0.587 + data[i * 4 + 2] * 0.114;
  const hist = new Uint32Array(256); for (let i = 0; i < n; i++) hist[Math.min(255, lum[i] | 0)]++;
  let acc = 0, p99 = 255; for (let v = 0; v < 256; v++) { acc += hist[v]; if (acc >= 0.99 * n) { p99 = v; break; } }
  const thr = Math.max(8, 0.05 * p99), [cx, cy, r] = circle;
  const m = new Float32Array(n);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = y * w + x;
    m[i] = lum[i] > thr && (x - cx) ** 2 + (y - cy) ** 2 <= (r * 1.01) ** 2 ? 255 : 0;
  }
  const t = new Float32Array(n), e = new Float32Array(n);   // erode 3×3 (rows, then columns)
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = y * w + x;
    t[i] = Math.min(m[i], m[y * w + Math.max(0, x - 1)], m[y * w + Math.min(w - 1, x + 1)]);
  }
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = y * w + x;
    e[i] = Math.min(t[i], t[Math.max(0, y - 1) * w + x], t[Math.min(h - 1, y + 1) * w + x]);
  }
  return blur(e, w, h, Math.max(1, Math.min(w, h) / 600));
}

// a photo: its pixels at texture size, its geometry and landmarks in those pixels
const photo = { current: null };
function analysePhoto(img, meta) {
  const maxTex = Math.min(gl ? gl.getParameter(gl.MAX_TEXTURE_SIZE) : 4096, 4096);
  const px = pixelsOf(img, maxTex);
  const k = px.scale;
  const P = { img, px, label: meta.label, key: meta.key || 'own', eye: meta.eye || null, eyeSetting: meta.eyeSetting || 'auto',
    fov: meta.fov, fovType: meta.fov_type, projection: meta.projection, device: meta.device, own: !!meta.own,
    disc: null, fovea: null, hand: { disc: false, fovea: false } };
  P.circle = detectCircle(px);
  if ($('autofind').checked) findLandmarks(P);
  P.alpha = fundusAlpha(px, P.circle);
  return P;
}
// 황반·유두 자동으로 찾기 (the default): the optic disc where vessels gather on a bright cup, then the
// dark macula where that disc says it should be — what the program does when it imports a photo.
// A place set by hand (황반 지정 · 유두 지정) is kept.
function findLandmarks(P) {
  const px = P.px;
  const tmax = deg(thetaMax(P.fov, P.fovType));
  if (!P.hand.disc) {
    const disc = detectDisc(px, P.circle, Math.min(0.25, 3.8 / Math.max(tmax, 5)), P.device === 'camera45' ? 0.7 : 0.5);
    P.disc = disc ? disc.slice(0, 2) : null;
    if (P.eyeSetting === 'auto') P.eye = lateralityFromDisc(disc, P.circle) || P.eye;
  }
  if (!P.hand.fovea) {
    const cam = new Camera(...P.circle, P.fov, P.fovType, P.projection);
    const f = P.disc ? detectFovea(px, cam, P.disc, P.eyeSetting === 'auto' ? null : P.eye) : null;
    P.fovea = f ? f.slice(0, 2) : null;
    if (f && P.eyeSetting === 'auto') P.eye = f[3];   // the fovea lies temporal of the disc: that tells the eye
  }
}
function showPhoto(P) {
  photo.current = P;
  const { px, alpha } = P, rgba = new Uint8ClampedArray(px.data);
  for (let i = 0; i < px.w * px.h; i++) rgba[i * 4 + 3] = alpha[i];
  if (E.tex) gl.deleteTexture(E.tex);
  E.tex = makeTexture(rgba, px.w, px.h);
  E.center = [P.circle[0] / px.w, P.circle[1] / px.h];
  E.radius = [P.circle[2] / px.w, P.circle[2] / px.h];
  E.texel = [1 / px.w, 1 / px.h];
  Object.assign(E, { fov: P.fov, fovType: P.fovType, projection: P.projection, roll: 0 });
  setLandmarks(P.eye, P.disc, P.fovea, P.circle);
  views.preview.set(P); views.side.set(P);
  ui.syncPhoto();
}

// ---------------------------------------------------------------------------------------------
// 망막 높낮이 (relief.py): the shape of the retinal surface under the photo — raised vessels, the
// disc's cup and rim, the foveal pit — and the fine mesh over the photographed field built from it
// ---------------------------------------------------------------------------------------------
const RELIEF = { SIDE: 512, VESSEL_H: 0.55, CUP_H: -1.0, CUP_FRAC: 0.45, DISC_R_DEG: 3.8, DISC_RIM_H: 0.22,
  PIT_H: -0.55, PIT_R_DEG: 3.7, PIT_RIM_H: 0.12, N: 256, MAX: 0.08 };
function rankFilter(a, w, h, r, max) {   // a square max or min filter of half-size r, edges repeated
  let src = a;
  for (const horiz of [true, false]) {
    const out = new Float32Array(w * h);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      let v = max ? -Infinity : Infinity;
      for (let k = -r; k <= r; k++) {
        const xx = horiz ? clamp(x + k, 0, w - 1) : x, yy = horiz ? y : clamp(y + k, 0, h - 1), s = src[yy * w + xx];
        v = max ? (s > v ? s : v) : (s < v ? s : v);
      }
      out[y * w + x] = v;
    }
    src = out;
  }
  return src;
}
function vesselLayer(P, tmaxDeg) {   // relief.vessels: a black top-hat of the green channel, 0…1
  const key = Math.round(tmaxDeg * 10);
  if (P.vessel && P.vessel.key === key) return P.vessel;
  const s = downsample(P.px, RELIEF.SIDE), { w, h, green, step } = s;
  const cx = P.circle[0] / step, cy = P.circle[1] / step, R = P.circle[2] / step, ppd = R / Math.max(tmaxDeg, 1);
  const r = clamp(Math.round(ppd * 0.6), 2, 10);
  const closed = rankFilter(rankFilter(green, w, h, r, true), w, h, r, false);
  const th = new Float32Array(w * h), inner = [];
  for (let i = 0; i < w * h; i++) {
    th[i] = closed[i] - green[i];
    const x = i % w, y = (i / w) | 0;
    if ((x - cx) ** 2 + (y - cy) ** 2 <= (0.97 * R) ** 2) inner.push(th[i]);
  }
  let v = new Float32Array(w * h);
  if (inner.length >= 50) {
    const lo = percentile(inner, 60), hi = percentile(inner, 99.5);
    for (let i = 0; i < w * h; i++) v[i] = clamp((th[i] - lo) / Math.max(hi - lo, 1e-6), 0, 1);
    v = blur(v, w, h, Math.max(0.6, r * 0.35));
  }
  P.vessel = { key, v, w, h, step };
  return P.vessel;
}
const bowl = (x) => 0.5 * (1 + Math.cos(PI * clamp(x, 0, 1)));
function heightMap(P, tmaxDeg, disc, fovea) {   // relief.height_map: -1 (the cup's floor) … +1
  const { v, w, h, step } = vesselLayer(P, tmaxDeg);
  const cx = P.circle[0] / step, cy = P.circle[1] / step, R = P.circle[2] / step, ppd = R / Math.max(tmaxDeg, 1);
  const rd = RELIEF.DISC_R_DEG * ppd, rp = RELIEF.PIT_R_DEG * ppd, H = new Float32Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = y * w + x;
    let z = RELIEF.VESSEL_H * v[i];
    if (disc) {
      const d = Math.hypot(x - disc[0] / step, y - disc[1] / step);
      z += RELIEF.CUP_H * bowl(d / (RELIEF.CUP_FRAC * rd)) + RELIEF.DISC_RIM_H * Math.exp(-(((d - 0.9 * rd) / (0.28 * rd)) ** 2));
    }
    if (fovea) {
      const d = Math.hypot(x - fovea[0] / step, y - fovea[1] / step);
      z += RELIEF.PIT_H * bowl(d / rp) + RELIEF.PIT_RIM_H * Math.exp(-(((d - 1.35 * rp) / (0.45 * rp)) ** 2));
    }
    const tt = clamp((Math.hypot(x - cx, y - cy) / Math.max(R, 1) - 0.88) / 0.12, 0, 1);
    H[i] = clamp(z * (1 - tt * tt * (3 - 2 * tt)), -1, 1);
  }
  return { H, w, h, step };
}
function encode16(H) {   // 16 bits in R (high) and G (low), as the shaders read it
  const out = new Uint8Array(H.length * 4);
  for (let i = 0; i < H.length; i++) {
    const v = Math.round((clamp(H[i], -1, 1) * 0.5 + 0.5) * 65535);
    out[i * 4] = v >> 8; out[i * 4 + 1] = v & 255; out[i * 4 + 3] = 255;
  }
  return out;
}
// The relief's heights for the photo shown, as a texture (the shading) and for the sheet (the shape)
function updateRelief() {
  const P = photo.current;
  E.hmap = null;
  if (P && P.circle) {
    const hm = heightMap(P, deg(E.thetaMax()), E.marks[0], E.marks[1]);
    E.hmap = hm;
    if (E.hmapTex) gl.deleteTexture(E.hmapTex);
    E.hmapTex = makeTexture(encode16(hm.H), hm.w, hm.h);
  }
  E.hmapVer = (E.hmapVer || 0) + 1;
}
function sampleH(hm, x, y) {   // bilinear, 0 outside
  const x0 = Math.floor(x), y0 = Math.floor(y), fx = x - x0, fy = y - y0;
  let s = 0;
  for (const [dy, wy] of [[0, 1 - fy], [1, fy]]) for (const [dx, wx] of [[0, 1 - fx], [1, fx]]) {
    const xi = x0 + dx, yi = y0 + dy;
    if (xi >= 0 && xi < hm.w && yi >= 0 && yi < hm.h) s += hm.H[yi * hm.w + xi] * wx * wy;
  }
  return s;
}
function sheetMesh() {   // relief.sheet_mesh: over the image circle, raised by the heights, normals into the eye
  const hm = E.hmap, P = photo.current, n = RELIEF.N, tmax = E.thetaMax(), M = E.placement.matrix, roll = rad(E.roll);
  const [cx, cy, R] = P.circle, amount = E.reliefAmount, lutT = [];
  for (let k = 0; k <= 256; k++) lutT.push(thetaOfRho(k / 256, tmax, E.projection, E.viewpoint, E.radialC));
  const pos = new Float32Array(n * n * 3), nrm = new Float32Array(n * n * 3), keep = new Uint8Array(n * n), dirs = new Float64Array(n * n * 3);
  for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) {
    const a = -1.03 + 2.06 * i / (n - 1), b = -1.03 + 2.06 * j / (n - 1), rr = Math.hypot(a, b), k = j * n + i;
    keep[k] = rr <= 1.03 ? 1 : 0;
    let th;
    if (rr <= 1) { const x = rr * 256, l = Math.min(255, Math.floor(x)); th = lerp(lutT[l], lutT[l + 1], x - l); } else th = tmax * rr;
    const ph = Math.atan2(b, a) - roll, q = [Math.sin(th) * Math.cos(ph), Math.sin(th) * Math.sin(ph), -Math.cos(th)];
    const d = m3v(M, q), hgt = keep[k] ? sampleH(hm, (cx + a * R) / hm.step, (cy - b * R) / hm.step) : 0;
    const rad_ = K.R_RET - amount * hgt;
    for (let c = 0; c < 3; c++) { pos[k * 3 + c] = d[c] * rad_; dirs[k * 3 + c] = d[c]; }
  }
  const at = (i, j) => { const k = (j * n + i) * 3; return [pos[k], pos[k + 1], pos[k + 2]]; };
  for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) {
    const du = sub(at(Math.min(i + 1, n - 1), j), at(Math.max(i - 1, 0), j)), dv = sub(at(i, Math.min(j + 1, n - 1)), at(i, Math.max(j - 1, 0)));
    let nn = unit(cross(du, dv));
    const k = (j * n + i) * 3;
    if (nn[0] * -dirs[k] + nn[1] * -dirs[k + 1] + nn[2] * -dirs[k + 2] < 0) nn = mul(nn, -1);
    nrm[k] = nn[0]; nrm[k + 1] = nn[1]; nrm[k + 2] = nn[2];
  }
  const idx = [];
  for (let j = 0; j < n - 1; j++) for (let i = 0; i < n - 1; i++) {
    const k = j * n + i;
    if (keep[k] && keep[k + 1] && keep[k + n] && keep[k + n + 1]) idx.push(k, k + n, k + 1, k + 1, k + n, k + n + 1);
  }
  return { pos, nrm, idx: Uint32Array.from(idx), uv: null, lines: false };
}
const reliefSheetOn = () => E.reliefOn && E.reliefAmount > 1e-4 && !!E.hmap && !!E.tex;
function reliefSheet() {
  if (!reliefSheetOn()) return null;
  const M = E.placement.matrix;
  return dynamic('relief', [E.hmapVer, E.reliefAmount.toFixed(4), E.fov, E.fovType, E.projection, E.roll, M.map((x) => x.toFixed(6)).join()].join('|'), sheetMesh);
}

// ---------------------------------------------------------------------------------------------
// the flat photo (inspector preview and 사진 나란히): image circle, disc, fovea, the slit
// ---------------------------------------------------------------------------------------------
class PhotoCanvas {
  constructor(el, { marks = true, crop = false } = {}) { this.el = el; this.marks = marks; this.crop = crop; this.scan = null; this.dim = 1; this.dir = [0, 1]; }
  set(P) { this.P = P; this.draw(); }
  setScan(s, dim = 1, dir = [0, 1]) { this.scan = s; this.dim = dim; this.dir = dir; this.draw(); }
  rect() {
    const P = this.P, cw = this.el.clientWidth, ch = this.el.clientHeight;
    if (!P) return null;
    const [sx, sy, sw, sh] = this.crop ? [P.circle[0] - P.circle[2], Math.max(0, P.circle[1] - P.circle[2]), 2 * P.circle[2],
      Math.min(P.px.h, P.circle[1] + P.circle[2]) - Math.max(0, P.circle[1] - P.circle[2])] : [0, 0, P.px.w, P.px.h];
    const m = this.crop ? 0.04 * Math.min(cw, ch) : 0, s = Math.min((cw - 2 * m) / sw, (ch - 2 * m) / sh);
    return { src: [sx, sy, sw, sh], x: (cw - sw * s) / 2, y: (ch - sh * s) / 2, s };
  }
  toPhoto(ex, ey) { const r = this.rect(); return r ? [r.src[0] + (ex - r.x) / r.s, r.src[1] + (ey - r.y) / r.s] : null; }
  draw() {
    const c = this.el, dpr = Math.min(2, window.devicePixelRatio || 1), cw = c.clientWidth, ch = c.clientHeight;
    if (!cw || !ch) return;
    if (c.width !== Math.round(cw * dpr)) { c.width = Math.round(cw * dpr); c.height = Math.round(ch * dpr); }
    const ctx = c.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = '#000'; ctx.fillRect(0, 0, cw, ch);
    const P = this.P, r = this.rect();
    if (!P || !r) return;
    const [sx, sy, sw, sh] = r.src, X = (x) => r.x + (x - sx) * r.s, Y = (y) => r.y + (y - sy) * r.s;
    ctx.save();
    if (this.crop) { ctx.beginPath(); ctx.arc(X(P.circle[0]), Y(P.circle[1]), P.circle[2] * r.s, 0, 2 * PI); ctx.clip(); }
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(P.px.canvas, sx, sy, sw, sh, r.x, r.y, sw * r.s, sh * r.s);
    ctx.restore();
    if (this.scan != null && this.dim > 0) {   // ahead of the slit: not scanned yet; the slit glows
      // drawn turned so that the slit moves down the page (this.dir: its way on the photo)
      const R0 = P.circle[2] * r.s, big = 2 * Math.hypot(cw, ch), y = (2 * clamp(this.scan, 0, 1) - 1) * R0;
      ctx.save();
      ctx.beginPath(); ctx.rect(r.x, r.y, sw * r.s, sh * r.s); ctx.clip();
      ctx.translate(X(P.circle[0]), Y(P.circle[1])); ctx.rotate(Math.atan2(-this.dir[0], this.dir[1]));
      ctx.fillStyle = `rgba(0,0,0,${0.75 * this.dim})`; ctx.fillRect(-big, y, 2 * big, big);
      const hgt = 2 * R0 * 0.05, gr = ctx.createLinearGradient(0, y - hgt, 0, y);
      gr.addColorStop(0, 'rgba(255,110,50,0)'); gr.addColorStop(1, `rgba(255,110,50,${0.27 * this.dim})`);
      ctx.fillStyle = gr; ctx.fillRect(-big, y - hgt, 2 * big, hgt);
      const lw = Math.max(1.5, 2 * R0 / 260);
      for (const [wm, col] of [[6, [255, 80, 30, 0.18]], [3, [255, 95, 40, 0.43]], [1.4, [255, 120, 60, 0.92]], [0.5, [255, 225, 190, 1]]]) {
        ctx.strokeStyle = `rgba(${col[0]},${col[1]},${col[2]},${col[3] * this.dim})`; ctx.lineWidth = lw * wm;
        ctx.beginPath(); ctx.moveTo(-big, y); ctx.lineTo(big, y); ctx.stroke();
      }
      ctx.restore();
    }
    if (!this.marks) return;
    ctx.setLineDash([5, 4]); ctx.strokeStyle = 'rgba(80,200,255,0.65)'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.arc(X(P.circle[0]), Y(P.circle[1]), P.circle[2] * r.s, 0, 2 * PI); ctx.stroke(); ctx.setLineDash([]);
    const ring = (p, rr, col, label, left = false) => {
      if (!p) return;
      ctx.lineWidth = 2; ctx.strokeStyle = 'rgba(0,0,0,0.6)'; ctx.beginPath(); ctx.arc(X(p[0]), Y(p[1]), rr + 1, 0, 2 * PI); ctx.stroke();
      ctx.strokeStyle = col; ctx.lineWidth = 1.6; ctx.beginPath(); ctx.arc(X(p[0]), Y(p[1]), rr, 0, 2 * PI); ctx.stroke();
      ctx.font = '600 11px ' + getComputedStyle(document.body).fontFamily; ctx.fillStyle = col;
      ctx.textAlign = left ? 'right' : 'left'; ctx.textBaseline = 'middle';
      const tx = left ? X(p[0]) - rr - 4 : X(p[0]) + rr + 4;
      ctx.strokeStyle = 'rgba(0,0,0,0.7)'; ctx.lineWidth = 3; ctx.strokeText(label, tx, Y(p[1]));
      ctx.fillText(label, tx, Y(p[1]));
    };
    ring(P.disc, Math.max(6, P.circle[2] * r.s * 0.07), '#ffd60a', '유두');
    const fLeft = P.disc && P.fovea ? P.fovea[0] < P.disc[0] : false;
    ring(P.fovea, Math.max(4, P.circle[2] * r.s * 0.03), '#64d2ff', '황반', fLeft);
  }
}
const views = { preview: null, side: null };   // the inspector's photo and 사진 나란히

// ---------------------------------------------------------------------------------------------
// the controls (main_window.py, the 3D tab)
// ---------------------------------------------------------------------------------------------
const $ = (id) => document.getElementById(id);
const ui = {
  cutValues: { front: 25, section: 0 },
  view: 'front',
  marking: null,
  init() {
    this.zoom = $('zoom');
    views.preview = new PhotoCanvas($('photo'));
    views.side = new PhotoCanvas($('side-photo'), { marks: false, crop: true });
    // photos
    const sel = $('photo-select');
    DATA.photos.forEach((p, i) => { const o = document.createElement('option'); o.value = i; o.textContent = p.label; sel.appendChild(o); });
    sel.addEventListener('change', () => this.loadDemo(+sel.value));
    $('photo-file').addEventListener('change', (e) => { const f = e.target.files && e.target.files[0]; if (f) this.loadFile(f); e.target.value = ''; });
    const stage = $('stage');
    stage.addEventListener('dragover', (e) => { e.preventDefault(); });
    stage.addEventListener('drop', (e) => { e.preventDefault(); const f = e.dataTransfer.files && e.dataTransfer.files[0]; if (f) this.loadFile(f); });
    for (const [id, what] of [['mark-fovea', 'fovea'], ['mark-disc', 'disc']]) {
      $(id).addEventListener('click', () => this.setMarking(this.marking === what ? null : what));
    }
    $('redetect').addEventListener('click', () => this.redetect());
    $('autofind').addEventListener('change', () => this.onAutofind($('autofind').checked));
    $('photo').addEventListener('click', (e) => this.onPhotoClick(e));
    // the bar
    for (const b of document.querySelectorAll('[name=mode]')) b.addEventListener('change', () => this.on3dMode($('mode-out').checked));
    $('scan').addEventListener('click', () => this.toggleScan());
    $('full').addEventListener('click', () => this.toggleFull());
    $('panel').addEventListener('click', () => { const on = document.body.classList.toggle('no-panel'); $('panel').setAttribute('aria-pressed', String(!on)); setTimeout(() => { redraw(); views.preview.draw(); }, 0); });
    // 시점
    $('front').addEventListener('click', () => { show.stop(); this.leaveJourney(); frontView(true); });
    $('home').addEventListener('click', () => { show.stop(); this.leaveJourney(); resetView(true); });
    // 들어가며 보기
    $('journey-play').addEventListener('click', () => this.playJourney());
    $('journey').addEventListener('input', () => { show.stop(); journey.scrub(+$('journey').value / 100); });
    // 안구 열기
    for (const b of document.querySelectorAll('[name=view]')) b.addEventListener('change', () => this.setView(b.value));
    // 슬릿 스캔
    for (const b of document.querySelectorAll('[name=slitdir]')) b.addEventListener('change', () => this.onSlitDir(b.value));
    $('scan2').addEventListener('click', () => this.toggleScan());
    $('cut').addEventListener('input', () => this.onCut(+$('cut').value));
    $('glass').addEventListener('input', () => { E.glass = +$('glass').value / 100; redraw(); });
    $('xray').addEventListener('change', () => this.onXray($('xray').checked));
    // 효과
    $('relief').addEventListener('change', () => { E.relief = $('relief').checked ? MD.relief : 0; redraw(); });
    $('surface').addEventListener('change', () => { E.reliefOn = $('surface').checked; $('height').disabled = !E.reliefOn; redraw(); });
    $('height').addEventListener('input', () => { E.reliefAmount = +$('height').value / 100 * RELIEF.MAX; redraw(); });
    $('spin').addEventListener('change', () => setAutoRotate($('spin').checked ? MD.spin : 0));
    $('fovmarks').addEventListener('change', () => this.applyFovMarks());
    $('sidephoto').addEventListener('change', () => this.onSidePhoto($('sidephoto').checked));
    // 표시
    $('nerve').addEventListener('change', () => { E.showNerve = $('nerve').checked; redraw(); });
    $('muscles').addEventListener('change', () => { E.showMuscles = $('muscles').checked; redraw(); });
    $('grid').addEventListener('change', () => { E.showGrid = $('grid').checked; redraw(); });
    $('simple').addEventListener('change', () => this.onSimple($('simple').checked));
    // 사진 맞춤
    $('align').addEventListener('change', () => { E.align = $('align').checked; replace(); this.caption(); redraw(); });
    const pj = $('projection');
    for (const k of PROJECTIONS) { const o = document.createElement('option'); o.value = k; o.textContent = DATA.projection_labels[k]; pj.appendChild(o); }
    for (const id of ['fov', 'fovtype', 'projection', 'roll', 'lat']) $(id).addEventListener('change', () => this.onMapping());
    $('fov').addEventListener('input', () => this.onMapping());
    $('roll').addEventListener('input', () => this.onMapping());
    $('fitfov').addEventListener('click', () => this.fitFov());
    $('device').addEventListener('change', () => this.onDevice());
    // the eye: drag, wheel, pinch, keys
    this.bindEye();
    window.addEventListener('resize', () => { redraw(); views.preview.draw(); views.side.draw(); });
    document.addEventListener('fullscreenchange', () => {
      const on = !!document.fullscreenElement; document.body.classList.toggle('full', on); $('full').textContent = on ? '돌아가기' : '크게 보기';
      E.black = on || $('sidephoto').checked; setTimeout(() => { redraw(); views.side.draw(); }, 50);
    });
    if (!document.fullscreenEnabled) $('full').hidden = true;
  },
  status(text) { $('status').textContent = text; },
  loadDemo(i) {
    const meta = DATA.photos[i];
    loadImage(meta.src).then((img) => {
      show.stop();
      const P = analysePhoto(img, { ...meta, eyeSetting: meta.eye });
      showPhoto(P);
      this.status(`${meta.label} — ${$('autofind').checked ? this.foundText(P) : '데모 사진'}`);
    });
  },
  loadFile(file) {
    if (!/^image\//.test(file.type)) { this.status('사진 파일(JPEG·PNG 등)을 골라 주세요'); return; }
    const url = URL.createObjectURL(file);
    this.status('사진을 읽는 중…');
    loadImage(url).then((img) => {
      const devKey = $('device').value, dev = DATA.devices[devKey];
      const eye = $('lat').value;
      const P = analysePhoto(img, { label: file.name, fov: dev.fov, fov_type: dev.fov_type, projection: dev.projection, device: devKey, own: true,
        eye: eye === 'auto' ? null : eye, eyeSetting: eye });
      URL.revokeObjectURL(url);
      show.stop();
      showPhoto(P);
      $('photo-select').value = '';
      this.status(`${file.name} — ${$('autofind').checked ? this.foundText(P) : '자동으로 찾기가 꺼져 있습니다'}`);
    }).catch(() => { URL.revokeObjectURL(url); this.status('이 파일은 열 수 없습니다'); });
  },
  syncPhoto() {
    const P = photo.current;
    if (!P) return;
    $('fov').value = P.fov; $('fovtype').value = P.fovType; $('projection').value = P.projection; $('roll').value = 0;
    $('lat').value = P.eyeSetting === 'auto' ? 'auto' : (P.eye || 'auto');
    $('device').value = P.device || 'camera45';
    const eyeName = P.eye ? (P.eye === 'OD' ? '우안' : '좌안') : '';
    $('photo-name').textContent = P.label + (eyeName && !P.label.includes(eyeName) ? ` · ${eyeName}` : '');
    this.foundLine();
    this.setMarking(null);
    this.caption();
  },
  onMapping() {
    const P = photo.current;
    if (!P) return;
    P.fov = +$('fov').value || P.fov; P.fovType = $('fovtype').value; P.projection = $('projection').value;
    const eye = $('lat').value, eyeChanged = eye !== P.eyeSetting;
    P.eyeSetting = eye; if (eye !== 'auto') P.eye = eye;
    if (eyeChanged && $('autofind').checked) { findLandmarks(P); this.syncPhoto(); }   // the macula is looked for on that eye's side
    Object.assign(E, { fov: P.fov, fovType: P.fovType, projection: P.projection, roll: +$('roll').value || 0 });
    setLandmarks(P.eye, P.disc, P.fovea, P.circle);
    views.preview.draw(); this.caption();
  },
  onDevice() {   // the camera's field of view and projection; the landmarks found again for it
    const P = photo.current, dev = DATA.devices[$('device').value];
    if (!P) return;
    Object.assign(P, { device: $('device').value, fov: dev.fov, fovType: dev.fov_type, projection: dev.projection });
    if ($('autofind').checked) findLandmarks(P);
    Object.assign(E, { fov: P.fov, fovType: P.fovType, projection: P.projection });
    setLandmarks(P.eye, P.disc, P.fovea, P.circle);
    this.syncPhoto();
    this.status(`${dev.label}의 화각·투영으로 바꾸고 황반·유두를 다시 찾았습니다`);
  },
  foundLine() {   // where each landmark came from
    const P = photo.current;
    if (!P) { $('found').textContent = ''; return; }
    const part = (name, has, hand) => `<span class="${has ? (hand ? 'hand' : 'auto') : 'none'}">${name} ${has ? (hand ? '직접 지정' : '자동으로 찾음') : '없음'}</span>`;
    $('found').innerHTML = part('유두', !!P.disc, P.hand.disc) + ' · ' + part('황반', !!P.fovea, P.hand.fovea);
  },
  onAutofind(on) {
    const P = photo.current;
    if (!P) return;
    if (on) findLandmarks(P);
    else { if (!P.hand.disc) P.disc = null; if (!P.hand.fovea) P.fovea = null; }
    setLandmarks(P.eye, P.disc, P.fovea, P.circle);
    views.preview.draw(); this.caption();
    this.status(on ? this.foundText(P) : '자동으로 찾기를 껐습니다 — 황반·유두를 직접 지정하거나 사진 중심을 후극에 둡니다');
  },
  foundText(P) {
    return P.disc && P.fovea ? '유두와 황반을 자동으로 찾아 제자리에 맞췄습니다'
      : P.disc ? '유두를 자동으로 찾았습니다 (황반은 사진에 없거나 찾지 못했습니다 — 유두를 코쪽 제자리에 맞춤)'
        : '유두와 황반을 찾지 못했습니다 — 사진에서 직접 지정할 수 있습니다';
  },
  setMarking(what) {
    this.marking = what;
    $('mark-fovea').setAttribute('aria-pressed', String(what === 'fovea'));
    $('mark-disc').setAttribute('aria-pressed', String(what === 'disc'));
    $('photo').classList.toggle('picking', !!what);
    $('mark-hint').textContent = what === 'fovea' ? '사진에서 황반(중심와)을 누르세요' : what === 'disc' ? '사진에서 시신경 유두를 누르세요' : '';
  },
  onPhotoClick(e) {
    const P = photo.current;
    if (!P || !this.marking) return;
    const b = $('photo').getBoundingClientRect(), p = views.preview.toPhoto(e.clientX - b.left, e.clientY - b.top);
    if (!p) return;
    if (this.marking === 'fovea') { P.fovea = p; P.hand.fovea = true; } else {
      P.disc = p; P.hand.disc = true;
      if (P.fovea && !P.hand.fovea) {   // a fovea far from the new disc: looked for again beside it
        const cam = E.photoCamera(P.circle), a = cam.direction(...P.fovea), d = cam.direction(...p);
        if (!a || !d || angleBetween(a, d) < 12 || angleBetween(a, d) > 32) P.fovea = null;
      }
      if (!P.fovea && $('autofind').checked) { const f = detectFovea(P.px, E.photoCamera(P.circle), P.disc, P.eye); P.fovea = f ? f.slice(0, 2) : null; }
    }
    const what = this.marking;
    this.setMarking(null);
    setLandmarks(P.eye, P.disc, P.fovea, P.circle);
    views.preview.draw(); this.caption(); this.foundLine();
    this.status(what === 'fovea' ? '황반 위치를 정했습니다 — 3D에서 안구 뒤쪽 한가운데에 맞췄습니다' : '시신경 유두 위치를 정했습니다');
  },
  redetect() {
    const P = photo.current;
    if (!P) return;
    P.hand = { disc: false, fovea: false };
    if (!$('autofind').checked) { $('autofind').checked = true; }
    findLandmarks(P);
    setLandmarks(P.eye, P.disc, P.fovea, P.circle);
    views.preview.draw(); this.caption(); this.foundLine();
    this.status('직접 정한 위치를 지우고 다시 찾았습니다 — ' + this.foundText(P));
  },
  caption() {   // MainWindow._placement_text
    const tmax = deg(E.thetaMax()), pl = E.placement;
    const lines = [`망막 범위: 사진 중심에서 ${tmax.toFixed(0)}° (안구 중심각 ${(2 * tmax).toFixed(0)}°)`];
    let where = { fovea: '황반을 안구 뒤쪽 한가운데(후극)에 맞춤', disc: '황반이 사진에 없어 시신경 유두를 코쪽 제자리에 맞춤',
      centre: '황반·시신경 유두를 찾지 못해 사진 중심을 후극에 둠', off: '사진 중심을 후극에 둠 (실제 위치에 맞춤 꺼짐)' }[pl.by];
    if ((pl.by === 'fovea' || pl.by === 'disc') && pl.offsetDeg >= 0.5) where += ` — 사진 중심은 후극에서 ${pl.offsetDeg.toFixed(0)}°`;
    lines.push(where);
    if (pl.distanceDeg != null) {
      const offr = Math.abs(pl.distanceDeg / K.DISC_FOVEA_DEG - 1);
      lines.push(`황반–유두 ${pl.distanceDeg.toFixed(1)}° · ${pl.distanceMm.toFixed(1)} mm (보통 약 4.5 mm)` + (offr > 0.2 ? ' — 화각이 실제와 다를 수 있습니다' : ''));
    }
    $('caption').textContent = lines.join('\n');
    const P = photo.current;
    $('fitfov').disabled = !(P && P.disc && P.fovea);
  },
  fitFov() {
    const P = photo.current;
    if (!P || !P.disc || !P.fovea) return;
    const fov = fitFov(E.photoCamera(P.circle), P.fovea, P.disc);
    if (fov == null) { this.status('황반–유두 거리로 화각을 정할 수 없습니다'); return; }
    $('fov').value = fov.toFixed(1); this.onMapping();
    this.status(`화각을 ${fov.toFixed(1)}°로 맞췄습니다 (황반–유두 4.5 mm 기준)`);
  },
  onCut(v) {
    if (show.timerOn) show.stop();
    this.cutValues[this.view] = v;
    if (this.view !== 'front') { vt.finish(); E.half = 1 - v / 100; } else E.cut = v < 100 ? v / 100 : 1;
    redraw();
  },
  syncView(mode) {
    this.view = mode;
    $('view-' + mode).checked = true;
    const cut = $('cut');
    cut.min = mode === 'front' ? -30 : 0; cut.value = this.cutValues[mode];
  },
  setView(mode, animate = true) {
    show.stop();
    this.leaveJourney();
    this.syncView(mode);
    E.cut = 1;
    let goal, half, done = null;
    if (mode === 'section') { goal = sectionPose(); half = 1 - this.cutValues.section / 100; } else { goal = E.half < 0.5 ? null : home(); half = 0; done = () => this.onCut(+$('cut').value); }
    if (!$('mode-out').checked) goal = null;
    vt.go(goal, half, E.xray, animate ? 0.9 : 0, done);
    this.applyFovMarks();
  },
  onXray(on) {
    if (show.timerOn) show.stop();
    vt.go(null, E.half, on ? 1 : 0, 0.6);
  },
  applyFovMarks() {
    const on = $('fovmarks').checked;
    show.showFov = on;
    if (show.playing) return;
    E.fovSweep = E.fovAlpha = E.fovRing = on ? 1 : 0;
    redraw();
  },
  onSidePhoto(on) {
    document.body.classList.toggle('side', on);
    E.black = on || !!document.fullscreenElement;
    setTimeout(() => { redraw(); views.side.draw(); }, 0);
  },
  onSlitDir(dir) {
    show.dir = dir;
    const p = dir === 'all' ? null : SLIT[dir];
    $('slit-note').textContent = p ? `${p.name} — ${p.stage === 'front' ? '앞을 연 안구의 망막 위로' : '세로 단면을 옆에서'} 봅니다`
      : '위↓ 아래↑ (세로 단면) 다음 왼→ 오른← (앞에서 본 망막) 차례로';
    if (show.playing) { show.stop(); this.toggleScan(); }
  },
  onSimple(on) {   // 단순하게 보기: the coats, the iris and the lens fade to plain shapes; the retina stays as it is
    const from = E.simple, to = on ? 1 : 0;
    if (this.simpleTween) this.simpleTween.stop();
    this.simpleTween = new Tween((k) => { E.simple = lerp(from, to, k); redraw(); }, 0.45);
    this.simpleTween.start();
  },
  where(text) {   // the name chip over the eye
    const tag = $('where');
    clearTimeout(this.whereTimer);
    if (text) { tag.textContent = text; tag.hidden = false; } else if (!journey.from) tag.hidden = true;
  },
  scanButtons(text) { $('scan').textContent = text; $('scan2').textContent = text; },
  toggleScan() {
    if (show.playing) { show.stop(); return; }
    show.xrayAfter = $('xray').checked;
    if (!photo.current) { this.status('사진을 먼저 고르세요'); return; }
    if (!$('mode-out').checked) { $('mode-out').checked = true; }
    if (!$('sidephoto').checked) { $('sidephoto').checked = true; this.onSidePhoto(true); }
    vt.finish();
    show.showFov = $('fovmarks').checked;
    this.leaveJourney();
    E.cut = 1;
    const first = SLIT[show.passes()[0]];
    if (first.stage === 'section') { this.cutValues.section = 0; this.syncView('section'); }
    else { this.cutValues.front = Math.round(FRONT_CUT * 100); this.syncView('front'); }
    setTimeout(() => show.start(), 30);
    this.scanButtons('■ 멈춤');
    this.status('슬릿 스캔 — 안구를 누르거나 돌리면 멈춥니다');
  },
  syncFromEye() {
    if (E.half > 0.01) { this.cutValues.section = Math.round(100 * (1 - E.half)); this.syncView('section'); }
    else { this.cutValues.front = E.cut < 1 ? Math.round(E.cut * 100) : 100; this.syncView('front'); }
    $('xray').checked = E.xray > 0.5;
  },
  onScanFinished() { this.scanButtons('▶ 슬릿 스캔'); this.syncFromEye(); },
  onScanStopped() { this.scanButtons('▶ 슬릿 스캔'); this.syncFromEye(); this.applyFovMarks(); },
  on3dMode(outside) {   // 외부 | 내부: along the way in (or back out), nothing goes dark
    show.stop(); vt.finish();
    $('cut').disabled = !outside;
    for (const b of document.querySelectorAll('[name=view]')) b.disabled = !outside;
    if (this.view !== 'front' && !outside) this.syncView('front');
    journey.play(outside ? 0 : 1, () => { if (outside) this.leaveJourney(true); });
  },
  // 들어가며 보기
  playJourney() {
    if (journey.running()) { journey.stop(); return; }
    show.stop();
    const to = journey.j >= 0.999 ? 0 : 1;
    journey.play(to, () => { if (to === 0) this.leaveJourney(true); });
  },
  leaveJourney(glide = false) {   // back to the ordinary outside view (the front cut as the slider says)
    if (!journey.from) return;
    journey.end();
    if (E.mode === 'inside') return;
    const cut = +$('cut').value;
    if (glide) glideTo(home(), null, 0.6, { cut: cut < 100 ? cut / 100 : 1, outFov: 38 });
    else { E.outFov = 38; E.cut = cut < 100 ? cut / 100 : 1; }
  },
  onJourney(j) {   // the slider, the 외부 | 내부 switch and the name of the place passed
    $('journey').value = Math.round(j * 100);
    $('journey-play').textContent = journey.running() ? '■ 멈춤' : j >= 0.999 ? '◀ 나오기' : '▶ 들어가기';
    $(j >= 0.999 ? 'mode-in' : 'mode-out').checked = true;
    const z = len(viewBasis()[0]);
    const where = j <= 0.001 ? '' : j >= 0.999 ? '망막 — 황반과 시신경 유두 (망막 시점)' : j < 0.32 ? '안구 전체 — 각막 쪽으로'
      : z > 1.09 ? '각막 앞' : z > 0.83 ? '앞방 — 각막과 홍채 사이 (방수)' : z > 0.785 ? '동공 — 홍채 가운데'
      : z > 0.46 ? '수정체' : '유리체 — 앞에 망막이 보입니다';
    const tag = $('where');
    if (where) { tag.textContent = where; tag.hidden = false; clearTimeout(this.whereTimer); }
    if (j >= 0.999 || j <= 0.001) this.whereTimer = setTimeout(() => { tag.hidden = true; }, j >= 0.999 ? 2500 : 0);
  },
  toggleFull() {
    if (document.fullscreenElement) { document.exitFullscreen().catch(() => {}); return; }
    const el = $('stage');
    if (el.requestFullscreen) el.requestFullscreen().catch(() => this.status('이 화면에서는 전체 화면을 쓸 수 없습니다'));
  },
  bindEye() {
    const vel = new Velocity();
    const pointers = new Map();
    let press = null, pinch = null;
    const interacted = () => { if (show.timerOn) show.stop(); if (vt.active()) vt.finish(); if (journey.running()) { journey.stop(); ui.onJourney(journey.j); } };
    canvas.addEventListener('contextmenu', (e) => e.preventDefault());
    canvas.addEventListener('pointerdown', (e) => {
      canvas.setPointerCapture(e.pointerId);
      pointers.set(e.pointerId, [e.offsetX, e.offsetY]);
      stopMotion(); E.touched = now(); interacted();
      if (pointers.size === 2) {   // two fingers: pinch to zoom, move to pan
        const [a, b] = [...pointers.values()];
        pinch = { d: Math.hypot(a[0] - b[0], a[1] - b[1]), c: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] };
        E.drag = null; return;
      }
      E.drag = press = [e.offsetX, e.offsetY];
      vel.reset(); vel.add(e.offsetX, e.offsetY);
      E.dragKind = e.button === 2 ? 'zoom' : (e.button === 1 || e.shiftKey) ? 'pan' : 'rotate';
    });
    canvas.addEventListener('pointermove', (e) => {
      if (!pointers.has(e.pointerId)) return;
      pointers.set(e.pointerId, [e.offsetX, e.offsetY]);
      if (pinch && pointers.size === 2) {
        const [a, b] = [...pointers.values()], d = Math.hypot(a[0] - b[0], a[1] - b[1]), c = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
        if (d > 0 && pinch.d > 0) zoomAt(Math.log(d / pinch.d) / -Math.log(0.88), c);
        E.dragKind = 'pan'; pan(c[0] - pinch.c[0], c[1] - pinch.c[1]);
        pinch = { d, c }; return;
      }
      if (!E.drag) return;
      const dx = e.offsetX - E.drag[0], dy = e.offsetY - E.drag[1];
      E.drag = [e.offsetX, e.offsetY]; vel.add(e.offsetX, e.offsetY);
      if (E.dragKind === 'zoom') zoomAt(-dy / 40, press);
      else if (E.dragKind === 'pan') pan(dx, dy);
      else look(dx, dy);
    });
    const up = (e) => {
      pointers.delete(e.pointerId);
      if (pinch) { if (pointers.size < 2) pinch = null; E.drag = null; return; }
      const was = E.drag; E.drag = null; E.touched = now();
      if (was && (E.dragKind === 'rotate' || E.dragKind === 'pan')) fling.start(...vel.get());
    };
    canvas.addEventListener('pointerup', up);
    canvas.addEventListener('pointercancel', up);
    canvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      fling.stop(); viewGlide.stop(); E.touched = now(); interacted();
      zoomPos = [e.offsetX, e.offsetY];
      const px = e.deltaMode === 1 ? e.deltaY * 40 : e.deltaMode === 2 ? e.deltaY * 800 : e.deltaY;
      zoomGlide.add(clamp(-px / 100, -6, 6));
    }, { passive: false });
    canvas.addEventListener('dblclick', () => { interacted(); E.drag = null; resetView(true); });
    canvas.addEventListener('keydown', (e) => {
      const k = e.key;
      if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', '+', '=', '-', '_', '0', 'Home'].includes(k)) {
        e.preventDefault(); interacted(); E.touched = now(); fling.stop(); viewGlide.stop();
      }
      if (k === 'ArrowLeft') turnX.add(-10); else if (k === 'ArrowRight') turnX.add(10);
      else if (k === 'ArrowUp') turnY.add(-10); else if (k === 'ArrowDown') turnY.add(10);
      else if (k === '+' || k === '=') { zoomPos = null; zoomGlide.add(2); }
      else if (k === '-' || k === '_') { zoomPos = null; zoomGlide.add(-2); }
      else if (k === '0' || k === 'Home') resetView(true);
      else if (k === ' ' && document.fullscreenElement) { e.preventDefault(); this.toggleScan(); }
    });
  },
};

// ---------------------------------------------------------------------------------------------
// start: the first demo photo, the program's defaults (자세히, 유리 공막 80, 자동 회전; 망막 입체 —
// 표면 높낮이 and 입체 조명 — off: the photo as taken)
// ---------------------------------------------------------------------------------------------
async function main() {
  ui.init();
  try {
    await initGL();
  } catch (err) {
    document.body.classList.add('no-gl');
    $('gl-error').textContent = '3D를 그릴 수 없습니다: ' + (err && err.message ? err.message.split('\n')[0] : err);
    return;
  }
  E.glass = +$('glass').value / 100;
  E.relief = $('relief').checked ? MD.relief : 0;
  E.reliefOn = $('surface').checked;
  $('height').disabled = !E.reliefOn;
  E.cut = 0.25;
  E.dist = homeDist();
  ui.syncView('front');
  ui.loadDemo(0);
  setAutoRotate($('spin').checked ? MD.spin : 0);
  viewChanged();
  window.eye3d = { E, ui, show, journey, redraw, setAutoRotate, frontView, resetView, glideTo, motionOn, cameraMats, m4v, R, gl, renderNow: render,
    find: { pixelsOf, detectCircle, detectDisc, detectFovea, blur } };   // for checks from the console
}
main();
})();
