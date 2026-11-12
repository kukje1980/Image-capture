/* 슬릿램프 영상 시스템 — 녹내장 분석 (스테레오 보기 · 디스크 C/D · 광각 RNFL · 경과 비교)
 *  Pro 검토 화면의 '녹내장' 버튼으로 연다. MULTI 에서 고른 2장 = 스테레오·경과, 현재 영상 = 디스크·광각.
 *  환자 영상이 없으면 합성 데모 영상으로 동작한다 (데모는 저장하지 않음).
 */
(() => {
'use strict';
const $ = (id) => document.getElementById(id);
const MAXS = 900;
const mkc = (w, h) => { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; };
const clamp = (v, a, b) => v < a ? a : v > b ? b : v;
const sstep = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
function rng(seed) { return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
const REAL = { stereo: false, disc: false, wide: false, prog: false };
const cpt = (cv, e) => { const r = cv.getBoundingClientRect(); return { x: (e.clientX - r.left) * cv.width / r.width, y: (e.clientY - r.top) * cv.height / r.height }; };

function fileToCanvas(file) {
  return new Promise((res, rej) => {
    const img = new Image(), u = URL.createObjectURL(file);
    img.onload = () => { const s = Math.min(1, MAXS / Math.max(img.width, img.height)); const c = mkc(Math.round(img.width * s), Math.round(img.height * s)); c.getContext('2d').drawImage(img, 0, 0, c.width, c.height); URL.revokeObjectURL(u); res(c); };
    img.onerror = () => { URL.revokeObjectURL(u); rej(new Error('image')); };
    img.src = u;
  });
}
function onFile(id, cb) { $(id).addEventListener('change', async (e) => { const f = e.target.files[0]; if (!f) return; try { cb(await fileToCanvas(f)); } catch (_) { /* 읽을 수 없는 파일은 무시 */ } e.target.value = ''; }); }
function seg(id, cb) { const el = $(id); el.addEventListener('click', (e) => { const b = e.target.closest('button[data-v]'); if (!b) return; el.querySelectorAll('button').forEach((x) => x.setAttribute('aria-pressed', x === b)); cb(b.dataset.v); }); }
function slider(id, fmt, cb) { const el = $(id), o = $(id + '-o'); const up = () => { o.textContent = fmt(+el.value); }; el.addEventListener('input', () => { up(); cb(+el.value); }); up(); return (v) => { el.value = v; up(); }; }
const px = (v) => (v > 0 ? '+' : '') + v.toFixed(1).replace(/\.0$/, '') + ' px';

// ================= 합성 안저 영상 =================
function cupOf(o) { const t = o.fx != null ? (Math.sign(o.fx - o.dx) || -1) : -1; return { cx: o.dx + t * o.r * 0.05, cy: o.dy + o.r * 0.07, rx: o.r * 0.92 * o.cup, ry: o.r * o.cup * 1.02 }; }
function drawFundus(o) {
  const c = mkc(o.W, o.H), g = c.getContext('2d'), R = rng(o.seed || 7);
  const cx = o.W / 2, cy = o.H / 2;
  let gr = g.createRadialGradient(cx, cy, 0, cx, cy, Math.hypot(cx, cy));
  gr.addColorStop(0, '#c9552c'); gr.addColorStop(0.7, '#a53c1e'); gr.addColorStop(1, '#6e2010');
  g.fillStyle = gr; g.fillRect(0, 0, o.W, o.H);
  const t = o.fx != null ? (Math.sign(o.fx - o.dx) || -1) : -1;
  for (let i = 0; i < 500; i++) { g.fillStyle = `rgba(${R() < 0.5 ? '70,15,5' : '235,120,70'},${0.03 + R() * 0.05})`; g.beginPath(); g.arc(R() * o.W, R() * o.H, o.r * (0.05 + R() * 0.25), 0, 7); g.fill(); }
  const angd = (a, b) => Math.abs(Math.atan2(Math.sin(a - b), Math.cos(a - b)));
  g.lineCap = 'round';
  for (let i = 0; i < 700; i++) {
    const a = R() * Math.PI * 2, L = o.r * (2.2 + R() * 6), w = o.r * 0.03 * (0.5 + R()), al = 0.05 + R() * 0.08;
    if (o.defW && angd(a, o.defA) < o.defW) continue;
    g.strokeStyle = `rgba(255,216,172,${al})`; g.lineWidth = w;
    g.beginPath(); g.moveTo(o.dx + Math.cos(a) * o.r * 0.9, o.dy + Math.sin(a) * o.r * 0.9); g.lineTo(o.dx + Math.cos(a) * L, o.dy + Math.sin(a) * L); g.stroke();
  }
  if (o.defW) { g.fillStyle = 'rgba(55,8,4,.3)'; g.beginPath(); g.moveTo(o.dx, o.dy); g.arc(o.dx, o.dy, o.r * 8, o.defA - o.defW, o.defA + o.defW); g.closePath(); g.fill(); }
  if (o.fx != null) { gr = g.createRadialGradient(o.fx, o.fy, 0, o.fx, o.fy, o.r * 1.8); gr.addColorStop(0, 'rgba(60,12,6,.6)'); gr.addColorStop(1, 'rgba(60,12,6,0)'); g.fillStyle = gr; g.fillRect(0, 0, o.W, o.H); }
  // 디스크
  g.save(); g.translate(o.dx, o.dy); g.scale(0.92, 1);
  gr = g.createRadialGradient(0, 0, o.r * 0.2, 0, 0, o.r); gr.addColorStop(0, '#ffe0a8'); gr.addColorStop(0.8, '#f3a763'); gr.addColorStop(1, '#d67a40');
  g.fillStyle = gr; g.beginPath(); g.arc(0, 0, o.r, 0, 7); g.fill(); g.restore();
  // 컵
  const cu = cupOf(o);
  g.save(); g.translate(cu.cx, cu.cy); g.scale(cu.rx / cu.ry, 1);
  gr = g.createRadialGradient(0, 0, 0, 0, 0, cu.ry); gr.addColorStop(0, '#fff8e2'); gr.addColorStop(0.75, '#ffefc6'); gr.addColorStop(1, 'rgba(255,224,168,0)');
  g.fillStyle = gr; g.beginPath(); g.arc(0, 0, cu.ry, 0, 7); g.fill(); g.restore();
  for (let i = 0; i < 70; i++) { const a = R() * 7, d = Math.sqrt(R()) * 0.8; g.fillStyle = `rgba(170,120,90,${0.25 + R() * 0.3})`; g.beginPath(); g.arc(cu.cx + Math.cos(a) * d * cu.rx, cu.cy + Math.sin(a) * d * cu.ry, o.r * 0.018 * (0.6 + R()), 0, 7); g.fill(); }
  // 혈관
  function vessel(x, y, a, len, w, col, bend, depth) {
    const ex = x + Math.cos(a) * len, ey = y + Math.sin(a) * len;
    g.strokeStyle = col; g.lineWidth = w; g.beginPath(); g.moveTo(x, y);
    g.quadraticCurveTo((x + ex) / 2 - Math.sin(a) * bend * len, (y + ey) / 2 + Math.cos(a) * bend * len, ex, ey); g.stroke();
    if (depth > 0) for (const s of [-1, 1]) vessel(ex, ey, a + s * (0.3 + R() * 0.35), len * 0.62, w * 0.68, col, bend * 0.5 * s, depth - 1);
  }
  const vx = o.dx - t * o.r * 0.12, vl = o.r * (o.vl || 3.2), k = 0.28;
  const trunks = [[-Math.PI / 2 + t * 0.5, -t * k], [Math.PI / 2 - t * 0.5, t * k], [-Math.PI / 2 - t * 0.75, t * 0.12], [Math.PI / 2 + t * 0.75, -t * 0.12]];
  for (const [a, b] of trunks) {
    vessel(vx, o.dy, a, vl, o.r * 0.1, '#5c1014', b, 3);
    vessel(vx + t * o.r * 0.06, o.dy, a + t * 0.12 * Math.sign(Math.sin(a)), vl * 0.95, o.r * 0.065, '#a8281d', b * 0.9, 3);
  }
  if (o.hem) { const a = o.defA + 0.12; g.strokeStyle = '#7d0a10'; g.lineWidth = o.r * 0.1; g.beginPath(); g.moveTo(o.dx + Math.cos(a) * o.r * 0.9, o.dy + Math.sin(a) * o.r * 0.9); g.lineTo(o.dx + Math.cos(a + 0.05) * o.r * 1.32, o.dy + Math.sin(a + 0.05) * o.r * 1.32); g.stroke(); }
  if (o.round) { g.globalCompositeOperation = 'destination-in'; g.beginPath(); g.ellipse(cx, cy, o.W * 0.495, o.H * 0.495, 0, 0, 7); g.fill(); g.globalCompositeOperation = 'destination-over'; g.fillStyle = '#000'; g.fillRect(0, 0, o.W, o.H); g.globalCompositeOperation = 'source-over'; }
  return c;
}
/** 깊이에 따라 수평으로 밀어 스테레오 한쪽 영상을 만든다 (gx, gy = 전체 어긋남, gain = 밝기) */
function warp(base, depth, s, gx, gy, gain) {
  const w = base.width, h = base.height, src = base.getContext('2d').getImageData(0, 0, w, h).data;
  const out = mkc(w, h), og = out.getContext('2d'), id = og.createImageData(w, h), d = id.data;
  for (let y = 0; y < h; y++) {
    const sy = clamp(y - gy, 0, h - 1);
    for (let x = 0; x < w; x++) {
      const fx = clamp(x - gx + (s ? depth(x - gx, sy) * s : 0), 0, w - 1.001), x0 = fx | 0, f = fx - x0;
      const a = (sy * w + x0) * 4, o = (y * w + x) * 4;
      for (let k = 0; k < 3; k++) d[o + k] = (src[a + k] * (1 - f) + src[a + 4 + k] * f) * gain;
      d[o + 3] = 255;
    }
  }
  og.putImageData(id, 0, 0); return out;
}
const DISC_DEMO = { W: 600, H: 600, dx: 300, dy: 300, r: 170, cup: 0.6, defA: Math.PI / 2 + 0.5, defW: 0.1, seed: 11 };

// ================= 영상 정합 (이동량 탐색) =================
function grayOf(c, w) {
  const h = Math.max(1, Math.round(c.height * w / c.width)), t = mkc(w, h), g = t.getContext('2d');
  g.drawImage(c, 0, 0, w, h); const d = g.getImageData(0, 0, w, h).data, o = new Float32Array(w * h); let m = 0;
  for (let i = 0; i < o.length; i++) { o[i] = 0.3 * d[i * 4] + 0.59 * d[i * 4 + 1] + 0.11 * d[i * 4 + 2]; m += o[i]; }
  m /= o.length; for (let i = 0; i < o.length; i++) o[i] -= m;
  return { g: o, w, h };
}
function searchShift(A, B, w, c0x, c0y, range) {
  const a = grayOf(A, w), b = grayOf(B, w), h = Math.min(a.h, b.h), mg = Math.abs(c0x) + range + 2, mgy = Math.abs(c0y) + range + 2;
  let best = Infinity, bx = c0x, by = c0y;
  if (w - 2 * mg < 8 || h - 2 * mgy < 8) return { dx: c0x, dy: c0y };
  for (let dy = c0y - range; dy <= c0y + range; dy++) for (let dx = c0x - range; dx <= c0x + range; dx++) {
    let s = 0;
    for (let y = mgy; y < h - mgy; y += 2) { const ra = y * w, rb = (y - dy) * w - dx; for (let x = mg; x < w - mg; x += 2) s += Math.abs(a.g[ra + x] - b.g[rb + x]); }
    if (s < best) { best = s; bx = dx; by = dy; }
  }
  return { dx: bx, dy: by };
}
/** B 를 (dx, dy) 만큼 옮기면 A 와 겹친다 */
function findShift(A, B) {
  const c = searchShift(A, B, 120, 0, 0, 14), k = 360 / 120, f = searchShift(A, B, 360, c.dx * k, c.dy * k, 3), s = A.width / 360;
  return { dx: Math.round(f.dx * s * 2) / 2, dy: Math.round(f.dy * s * 2) / 2 };
}
function shifted(src, w, h, dx, dy) { const c = mkc(w, h), g = c.getContext('2d'); g.fillStyle = '#000'; g.fillRect(0, 0, w, h); g.drawImage(src, dx, dy, w, h); return c; }

// ================= 스테레오 =================
const ST = { L: null, R: null, Rs: null, dx: 0, dy: 0, swap: false, mode: 'wiggle', hz: 5, phase: 0, last: 0, profY: null, disp: null };
const setStDx = slider('gst-dx', px, (v) => { ST.dx = v; stRebuild(); });
const setStDy = slider('gst-dy', px, (v) => { ST.dy = v; stRebuild(); });
slider('gst-speed', (v) => v + ' Hz', (v) => { ST.hz = v; });
const ST_HINT = {
  wiggle: '두 장을 번갈아 보여줍니다. 컵 바닥과 림이 서로 다르게 움직이는 정도가 깊이입니다.',
  sbs: '평행법: 왼쪽 눈으로 왼쪽, 오른쪽 눈으로 오른쪽 영상을 봅니다. 간이 입체경이나 VR 화면에 맞는 배치입니다.',
  cross: '교차법: 눈을 모아 왼쪽 눈으로 오른쪽, 오른쪽 눈으로 왼쪽 영상을 봅니다.',
  ana: '적청 안경(왼쪽 빨강, 오른쪽 청록)을 쓰고 봅니다.',
  depth: '파랑은 깊은 곳(컵), 빨강은 솟은 곳입니다. 화면을 누르면 그 높이의 단면이 아래에 그려집니다.',
};
function stSet(L, R) { ST.L = L; ST.R = R; ST.profY = null; setStDx(0); setStDy(0); ST.dx = ST.dy = 0; stRebuild(); }
function stRebuild() { if (!ST.L) return; ST.Rs = shifted(ST.R, ST.L.width, ST.L.height, ST.dx, ST.dy); ST.disp = null; stDraw(); }
function stAuto() { const s = findShift(ST.L, ST.R); ST.dx = clamp(s.dx, -60, 60); ST.dy = clamp(s.dy, -40, 40); setStDx(ST.dx); setStDy(ST.dy); stRebuild(); $('gst-status').textContent = `자동 정렬: 좌우 ${px(ST.dx)}, 상하 ${px(ST.dy)} 보정`; }
function stDemo() {
  const base = drawFundus(DISC_DEMO), cu = cupOf(DISC_DEMO);
  const dep = (x, y) => 1 - sstep(0.5, 1.25, Math.hypot((x - cu.cx) / cu.rx, (y - cu.cy) / cu.ry));
  stSet(warp(base, dep, 7, 0, 0, 1), warp(base, dep, -7, 9, 5, 1.05));
  stAuto(); REAL.stereo = false;
}
function disparity(A, B) {
  const W = 200, a = grayOf(A, W), b = grayOf(B, W), h = Math.min(a.h, b.h), D = 10, r = 4, n = W * h;
  const best = new Float32Array(n).fill(1e9), disp = new Float32Array(n), I = new Float64Array((W + 1) * (h + 1));
  for (let d = -D; d <= D; d++) {
    for (let y = 0; y < h; y++) { let run = 0; for (let x = 0; x < W; x++) { const xb = x + d; run += (xb < 0 || xb >= W) ? 40 : Math.abs(a.g[y * W + x] - b.g[y * W + xb]); I[(y + 1) * (W + 1) + x + 1] = I[y * (W + 1) + x + 1] + run; } }
    for (let y = 0; y < h; y++) { const y0 = Math.max(0, y - r), y1 = Math.min(h, y + r + 1); for (let x = 0; x < W; x++) { const x0 = Math.max(0, x - r), x1 = Math.min(W, x + r + 1); const c = (I[y1 * (W + 1) + x1] - I[y0 * (W + 1) + x1] - I[y1 * (W + 1) + x0] + I[y0 * (W + 1) + x0]) / ((x1 - x0) * (y1 - y0)) + Math.abs(d) * 0.15; if (c < best[y * W + x]) { best[y * W + x] = c; disp[y * W + x] = d; } } }
  }
  const tmp = new Float32Array(n);
  for (let pass = 0; pass < 3; pass++) {
    for (let y = 0; y < h; y++) for (let x = 0; x < W; x++) { let s = 0, c = 0; for (let k = -3; k <= 3; k++) { const xx = x + k; if (xx >= 0 && xx < W) { s += disp[y * W + xx]; c++; } } tmp[y * W + x] = s / c; }
    for (let y = 0; y < h; y++) for (let x = 0; x < W; x++) { let s = 0, c = 0; for (let k = -3; k <= 3; k++) { const yy = y + k; if (yy >= 0 && yy < h) { s += tmp[yy * W + x]; c++; } } disp[y * W + x] = s / c; }
  }
  let mx = 0, mn = 0; const m = 14;
  for (let y = m; y < h - m; y++) for (let x = m; x < W - m; x++) { const v = disp[y * W + x]; if (v > mx) mx = v; if (v < mn) mn = v; }
  return { disp, W, h, mx, mn };
}
function stDraw() {
  if (!ST.L) return;
  const cv = $('gst-cv'), g = cv.getContext('2d'), w = ST.L.width, h = ST.L.height;
  const A = ST.swap ? ST.Rs : ST.L, B = ST.swap ? ST.L : ST.Rs, prof = $('gst-prof');
  prof.hidden = ST.mode !== 'depth'; $('gst-hint').textContent = ST_HINT[ST.mode];
  $('gst-speed-box').hidden = ST.mode !== 'wiggle';
  if (ST.mode === 'sbs' || ST.mode === 'cross') {
    cv.width = 2 * w + 10; cv.height = h; g.fillStyle = '#000'; g.fillRect(0, 0, cv.width, h);
    g.drawImage(ST.mode === 'sbs' ? A : B, 0, 0); g.drawImage(ST.mode === 'sbs' ? B : A, w + 10, 0); return;
  }
  cv.width = w; cv.height = h;
  if (ST.mode === 'wiggle') { g.drawImage(ST.phase ? B : A, 0, 0); return; }
  if (ST.mode === 'ana') {
    const a = A.getContext('2d').getImageData(0, 0, w, h).data, b = B.getContext('2d').getImageData(0, 0, w, h), d = b.data;
    for (let i = 0; i < d.length; i += 4) { const lb = 0.3 * d[i] + 0.59 * d[i + 1] + 0.11 * d[i + 2]; d[i] = 0.3 * a[i] + 0.59 * a[i + 1] + 0.11 * a[i + 2]; d[i + 1] = d[i + 2] = lb; }
    g.putImageData(b, 0, 0); return;
  }
  // 깊이 지도
  if (!ST.disp) ST.disp = disparity(A, B);
  const D = ST.disp, sc = Math.max(2, D.mx, -D.mn), ov = mkc(D.W, D.h), og = ov.getContext('2d'), id = og.createImageData(D.W, D.h);
  for (let i = 0; i < D.disp.length; i++) { const v = D.disp[i] / sc, o = i * 4; if (v > 0) { id.data[o] = 30; id.data[o + 1] = 120; id.data[o + 2] = 255; } else { id.data[o] = 255; id.data[o + 1] = 70; id.data[o + 2] = 40; } id.data[o + 3] = Math.min(1, Math.abs(v)) * 200; }
  og.putImageData(id, 0, 0);
  g.drawImage(A, 0, 0); g.imageSmoothingEnabled = true; g.drawImage(ov, 0, 0, w, h);
  const py = ST.profY == null ? h / 2 : ST.profY;
  g.strokeStyle = 'rgba(255,255,255,.85)'; g.setLineDash([6, 5]); g.lineWidth = 1.5; g.beginPath(); g.moveTo(0, py); g.lineTo(w, py); g.stroke(); g.setLineDash([]);
  prof.width = w; prof.height = 120; const p = prof.getContext('2d'); p.fillStyle = '#0f1215'; p.fillRect(0, 0, w, 120);
  const row = clamp(Math.round(py * D.h / h), 0, D.h - 1), z = 34, amp = 70 / sc;
  p.strokeStyle = '#3a434b'; p.lineWidth = 1; p.beginPath(); p.moveTo(0, z); p.lineTo(w, z); p.stroke();
  p.strokeStyle = '#6cc0ff'; p.lineWidth = 2; p.beginPath();
  for (let x = 0; x < D.W; x++) { const X = (x + 0.5) * w / D.W, Y = z + D.disp[row * D.W + x] * amp; x ? p.lineTo(X, Y) : p.moveTo(X, Y); } p.stroke();
  p.fillStyle = '#aab3bb'; p.font = '12px sans-serif'; p.fillText('단면 (아래로 갈수록 깊음)', 8, 16);
  const cupPx = D.mx * w / D.W;
  $('gst-status').textContent = cupPx < 2 ? `최대 시차 ${cupPx.toFixed(1)} px — 시차가 부족합니다. 두 컷 사이를 더 벌려 다시 찍으세요.` : `컵 최대 시차 ${cupPx.toFixed(1)} px (상대 깊이, 절대 길이 아님)`;
}
seg('gst-mode', (v) => { ST.mode = v; stDraw(); });
$('gst-swap').addEventListener('change', (e) => { ST.swap = e.target.checked; ST.disp = null; stDraw(); });
$('gst-auto').addEventListener('click', stAuto);
$('gst-zero').addEventListener('click', () => { ST.dx = ST.dy = 0; setStDx(0); setStDy(0); stRebuild(); $('gst-status').textContent = '보정을 해제했습니다.'; });
$('gst-demo').addEventListener('click', stDemo);
$('gst-cv').addEventListener('pointerdown', (e) => { if (ST.mode !== 'depth') return; ST.profY = cpt($('gst-cv'), e).y; stDraw(); });
onFile('gst-fl', (c) => { REAL.stereo = true; stSet(c, shifted(ST.R, c.width, c.height, 0, 0)); $('gst-status').textContent = '왼쪽 사진을 불러왔습니다. 오른쪽 사진도 넣은 뒤 자동 정렬을 누르세요.'; });
onFile('gst-fr', (c) => { REAL.stereo = true; ST.R = shifted(c, ST.L.width, ST.L.height, 0, 0); stAuto(); });

// ================= 디스크 C/D =================
const DC = { img: null, disc: null, cup: null, eye: 'OD', drag: null };
function dcSet(img, demo) {
  DC.img = img; const w = img.width, h = img.height;
  if (demo) { const cu = cupOf(DISC_DEMO); DC.disc = { cx: 300, cy: 300, rx: 170 * 0.92, ry: 170 }; DC.cup = { cx: cu.cx, cy: cu.cy, rx: cu.rx * 0.93, ry: cu.ry * 0.93 }; }
  else { const m = Math.min(w, h); DC.disc = { cx: w / 2, cy: h / 2, rx: m * 0.27, ry: m * 0.3 }; DC.cup = { cx: w / 2, cy: h / 2, rx: m * 0.13, ry: m * 0.15 }; }
  dcDraw();
}
const dcHandles = () => { const o = []; for (const k of ['cup', 'disc']) { const e = DC[k]; o.push([k, 'c', e.cx, e.cy], [k, 'e', e.cx + e.rx, e.cy], [k, 'w', e.cx - e.rx, e.cy], [k, 'n', e.cx, e.cy - e.ry], [k, 's', e.cx, e.cy + e.ry]); } return o; };
function dcDraw() {
  if (!DC.img) return;
  const cv = $('gdc-cv'), g = cv.getContext('2d'); cv.width = DC.img.width; cv.height = DC.img.height; g.drawImage(DC.img, 0, 0);
  const u = cv.width / 600;
  for (const [k, col] of [['disc', '#4be08a'], ['cup', '#ffe14a']]) {
    const e = DC[k]; g.strokeStyle = col; g.lineWidth = 2.5 * u; g.beginPath(); g.ellipse(e.cx, e.cy, e.rx, e.ry, 0, 0, 7); g.stroke();
  }
  for (const [k, , x, y] of dcHandles()) { g.fillStyle = k === 'disc' ? '#4be08a' : '#ffe14a'; g.strokeStyle = '#111'; g.lineWidth = 1.5 * u; g.beginPath(); g.arc(x, y, 6 * u, 0, 7); g.fill(); g.stroke(); }
  const d = DC.disc, nasalRight = DC.eye === 'OD';
  g.font = `700 ${15 * u}px sans-serif`; g.textAlign = 'center'; g.textBaseline = 'middle'; g.lineWidth = 3 * u; g.strokeStyle = 'rgba(0,0,0,.7)'; g.fillStyle = '#fff';
  for (const [t, x, y] of [['S', d.cx, d.cy - d.ry - 16 * u], ['I', d.cx, d.cy + d.ry + 16 * u], [nasalRight ? 'N' : 'T', d.cx + d.rx + 16 * u, d.cy], [nasalRight ? 'T' : 'N', d.cx - d.rx - 16 * u, d.cy]]) { g.strokeText(t, x, y); g.fillText(t, x, y); }
  dcReport();
}
function dcReport() {
  const d = DC.disc, c = DC.cup, v = c.ry / d.ry, hz = c.rx / d.rx, ar = (c.rx * c.ry) / (d.rx * d.ry), dd = 2 * d.ry;
  const S = ((c.cy - c.ry) - (d.cy - d.ry)) / dd, I = ((d.cy + d.ry) - (c.cy + c.ry)) / dd, Rr = ((d.cx + d.rx) - (c.cx + c.rx)) / dd, Ll = ((c.cx - c.rx) - (d.cx - d.rx)) / dd;
  const N = DC.eye === 'OD' ? Rr : Ll, T = DC.eye === 'OD' ? Ll : Rr;
  $('gdc-v').textContent = v.toFixed(2);
  $('gdc-vp').innerHTML = v >= 0.7 ? '<span class="g-pill g-bad">0.7 이상</span>' : v >= 0.5 ? '<span class="g-pill g-warn">0.5~0.7</span>' : '<span class="g-pill g-ok">0.5 미만</span>';
  $('gdc-tbl').innerHTML = `<tr><td>수평 C/D</td><td>${hz.toFixed(2)}</td></tr><tr><td>면적 C/D</td><td>${ar.toFixed(2)}</td></tr><tr><td>림 면적 비율</td><td>${((1 - ar) * 100).toFixed(0)}%</td></tr>`;
  const f = (x) => (x < 0 ? '경계 밖' : x.toFixed(3) + ' DD');
  $('gdc-rim').innerHTML = `<tr><td>I 하측</td><td>${f(I)}</td></tr><tr><td>S 상측</td><td>${f(S)}</td></tr><tr><td>N 비측</td><td>${f(N)}</td></tr><tr><td>T 이측</td><td>${f(T)}</td></tr>`;
  const bad = []; if (I < S) bad.push('하측 림이 상측보다 얇음'); if (S < N) bad.push('상측 림이 비측보다 얇음'); if (N < T) bad.push('비측 림이 이측보다 얇음');
  $('gdc-isnt').innerHTML = bad.length ? `<span class="g-pill g-bad">ISNT 어긋남</span><p class="g-note">${bad.join(', ')}</p>` : '<span class="g-pill g-ok">ISNT 순서 유지</span>';
}
(() => {
  const cv = $('gdc-cv');
  cv.addEventListener('pointerdown', (e) => {
    const p = cpt(cv, e), r = 16 * cv.width / 600; let hit = null, bd = r;
    for (const hd of dcHandles()) { const dist = Math.hypot(hd[2] - p.x, hd[3] - p.y); if (dist < bd) { bd = dist; hit = hd; } }
    if (!hit) return; const el = DC[hit[0]]; DC.drag = { k: hit[0], h: hit[1], ox: p.x - el.cx, oy: p.y - el.cy }; cv.setPointerCapture(e.pointerId);
  });
  cv.addEventListener('pointermove', (e) => {
    if (!DC.drag) return; const p = cpt(cv, e), el = DC[DC.drag.k], h = DC.drag.h;
    if (h === 'c') { el.cx = p.x - DC.drag.ox; el.cy = p.y - DC.drag.oy; } else if (h === 'e' || h === 'w') el.rx = Math.max(5, Math.abs(p.x - el.cx)); else el.ry = Math.max(5, Math.abs(p.y - el.cy));
    dcDraw();
  });
  const end = () => { DC.drag = null; }; cv.addEventListener('pointerup', end); cv.addEventListener('pointercancel', end);
})();
seg('gdc-eye', (v) => { DC.eye = v; dcDraw(); });
onFile('gdc-f', (c) => { REAL.disc = true; dcSet(c, false); });
function dcDemo() { REAL.disc = false; dcSet(drawFundus(DISC_DEMO), true); }
function dcEye(v) { DC.eye = v === 'OS' ? 'OS' : 'OD'; document.querySelectorAll('#gdc-eye button').forEach((x) => x.setAttribute('aria-pressed', x.dataset.v === DC.eye)); }
$('gdc-from').addEventListener('click', () => { if (ST.L) { REAL.disc = REAL.stereo; dcSet(ST.L, false); } });

// ================= 광각 분석 =================
const SECT = [
  ['이측', 311, 400, '중심부 (유두황반다발)', '#e8c547'], ['상이측', 41, 80, '하측 궁상 영역 · 비측 계단', '#e0564f'],
  ['상비측', 81, 120, '하측 주변부', '#b678d6'], ['비측', 121, 230, '이측 시야', '#5cb46e'],
  ['하비측', 231, 270, '상측 주변부', '#4aa3df'], ['하이측', 271, 310, '상측 궁상 영역 · 비측 계단', '#f08a3c'],
];
const WD = { src: null, proc: null, disc: null, fovea: null, marks: [], tool: 'mark', rf: true, k: 1.5, sec: true, vf: true };
$('gwd-leg').innerHTML = SECT.map((s) => `<span><i style="background:${s[4]}"></i>${s[0]}</span>`).join('');
function wdEnhance() {
  const s = WD.src, w = s.width, h = s.height, c = mkc(w, h), g = c.getContext('2d'); g.drawImage(s, 0, 0);
  if (WD.rf || WD.k) {
    const id = g.getImageData(0, 0, w, h), d = id.data, sm = mkc(Math.max(1, w >> 4), Math.max(1, h >> 4)); sm.getContext('2d').drawImage(s, 0, 0, sm.width, sm.height);
    const bl = mkc(w, h), bg = bl.getContext('2d'); bg.imageSmoothingQuality = 'high'; bg.drawImage(sm, 0, 0, w, h); const b = bg.getImageData(0, 0, w, h).data, k = WD.k;
    let m = 0, n = 0; for (let i = 0; i < d.length; i += 16) if (d[i] + d[i + 1] + d[i + 2] > 24) { m += d[i + 1]; n++; } m = n ? m / n : 80;
    for (let i = 0; i < d.length; i += 4) {
      if (d[i] + d[i + 1] + d[i + 2] <= 24) continue;
      if (WD.rf) { const v = 105 + (d[i + 1] - m) * 1.9 + k * 2.2 * (d[i + 1] - b[i + 1]); d[i] = d[i + 1] = d[i + 2] = v; }
      else for (let j = 0; j < 3; j++) d[i + j] = d[i + j] + k * 1.4 * (d[i + j] - b[i + j]);
    }
    g.putImageData(id, 0, 0);
  }
  WD.proc = c; wdDraw();
}
function wdAxes() {
  const d = WD.disc, f = WD.fovea, L = Math.hypot(f.x - d.x, f.y - d.y) || 1, t = { x: (f.x - d.x) / L, y: (f.y - d.y) / L };
  let u = { x: t.y, y: -t.x }; if (u.y > 0) u = { x: -u.x, y: -u.y };
  return { t, u, L, rd: L / 5.2, od: d.x > f.x };
}
function wdInfo(p) {
  const a = wdAxes(), vx = p.x - WD.disc.x, vy = p.y - WD.disc.y;
  const th = (Math.atan2(vx * a.u.x + vy * a.u.y, vx * a.t.x + vy * a.t.y) * 180 / Math.PI + 360) % 360, t2 = th < 40.5 ? th + 360 : th;
  const s = SECT.find((x) => t2 >= x[1] - 0.5 && t2 < x[2] + 0.5) || SECT[0];
  let hr = Math.round(a.od ? 9 + th / 30 : 3 - th / 30); hr = ((hr % 12) + 12) % 12 || 12;
  return { hr, sect: s, dd: Math.hypot(vx, vy) / (2 * a.rd) };
}
function wdDraw() {
  if (!WD.proc) return;
  const cv = $('gwd-cv'), g = cv.getContext('2d'); cv.width = WD.proc.width; cv.height = WD.proc.height; g.drawImage(WD.proc, 0, 0);
  const u = cv.width / 900, ok = WD.disc && WD.fovea;
  $('gwd-hint').textContent = ok ? '화면을 누르면 소견이 표시되고, 시계 방향·구역·대응 시야가 목록에 계산됩니다.' : '먼저 "디스크 지정"과 "황반 지정"으로 두 지점을 눌러 주세요.';
  if (ok) {
    const a = wdAxes(), d = WD.disc, f = WD.fovea, dir = (th) => { const r = th * Math.PI / 180; return { x: a.t.x * Math.cos(r) + a.u.x * Math.sin(r), y: a.t.y * Math.cos(r) + a.u.y * Math.sin(r) }; };
    if (WD.sec) {
      const r1 = a.rd * 1.25, r2 = a.rd * 2.0;
      for (const s of SECT) {
        g.beginPath();
        for (let th = s[1]; th <= s[2]; th += 3) { const v = dir(th); g.lineTo(d.x + v.x * r2, d.y + v.y * r2); }
        for (let th = s[2]; th >= s[1]; th -= 3) { const v = dir(th); g.lineTo(d.x + v.x * r1, d.y + v.y * r1); }
        g.closePath(); g.fillStyle = s[4] + '99'; g.fill(); g.strokeStyle = 'rgba(0,0,0,.6)'; g.lineWidth = 1; g.stroke();
      }
    }
    if (WD.vf) {
      const sc = a.L / 15.5, n = { x: -a.t.x, y: -a.t.y }, dn = { x: -a.u.x, y: -a.u.y };
      const rows = [[21, -9, 9], [15, -15, 15], [9, -21, 21], [3, -27, 21]];
      for (const sg of [1, -1]) for (const [y, x0, x1] of rows) for (let x = x0; x <= x1; x += 6) {
        const X = f.x + n.x * x * sc + dn.x * y * sg * sc, Y = f.y + n.y * x * sc + dn.y * y * sg * sc;
        g.fillStyle = sg > 0 ? '#58d6ff' : '#ffc14a'; g.strokeStyle = 'rgba(0,0,0,.75)'; g.lineWidth = 1; g.beginPath(); g.arc(X, Y, 3.2 * u, 0, 7); g.fill(); g.stroke();
      }
    }
    g.strokeStyle = 'rgba(255,255,255,.8)'; g.lineWidth = 1.2 * u; g.setLineDash([5 * u, 4 * u]); g.beginPath(); g.moveTo(d.x, d.y); g.lineTo(f.x, f.y); g.stroke(); g.setLineDash([]);
  }
  const dot = (p, col, t) => { g.fillStyle = col; g.strokeStyle = '#000'; g.lineWidth = 1.5 * u; g.beginPath(); g.arc(p.x, p.y, 5 * u, 0, 7); g.fill(); g.stroke(); g.font = `700 ${12 * u}px sans-serif`; g.lineWidth = 3 * u; g.strokeText(t, p.x + 8 * u, p.y - 8 * u); g.fillStyle = '#fff'; g.fillText(t, p.x + 8 * u, p.y - 8 * u); };
  if (WD.disc) dot(WD.disc, '#4be08a', '디스크'); if (WD.fovea) dot(WD.fovea, '#ffe14a', '황반');
  WD.marks.forEach((m, i) => { g.strokeStyle = '#fff'; g.lineWidth = 2.5 * u; g.beginPath(); g.arc(m.x, m.y, 11 * u, 0, 7); g.stroke(); g.strokeStyle = '#ff4d6a'; g.lineWidth = 1.5 * u; g.stroke(); g.font = `700 ${13 * u}px sans-serif`; g.lineWidth = 3 * u; g.strokeStyle = '#000'; g.strokeText(i + 1, m.x + 14 * u, m.y + 4 * u); g.fillStyle = '#fff'; g.fillText(i + 1, m.x + 14 * u, m.y + 4 * u); });
  wdReport();
}
function wdReport() {
  const ok = WD.disc && WD.fovea, geo = $('gwd-geo'), list = $('gwd-list');
  if (!ok) { geo.innerHTML = ''; list.innerHTML = '<li><span>디스크와 황반을 지정하면 계산됩니다.</span></li>'; return; }
  const a = wdAxes(), ang = Math.atan2(WD.fovea.y - WD.disc.y, Math.abs(WD.fovea.x - WD.disc.x)) * 180 / Math.PI;
  geo.innerHTML = `<tr><td>눈</td><td>${a.od ? 'OD (우안)' : 'OS (좌안)'}</td></tr><tr><td>디스크–황반 각</td><td>${Math.abs(ang).toFixed(1)}° ${ang >= 0 ? '아래' : '위'}</td></tr><tr><td>배율 (추정)</td><td>${(a.L / 15.5).toFixed(1)} px/°</td></tr>`;
  list.innerHTML = WD.marks.length ? WD.marks.map((m, i) => { const r = wdInfo(m); return `<li><b>${i + 1}. ${m.kind} · ${r.hr}시 방향</b><span>${r.sect[0]} 구역, 디스크에서 ${r.dd.toFixed(1)} DD<br>대응 시야: ${r.sect[3]}</span></li>`; }).join('') : '<li><span>아직 표시한 소견이 없습니다.</span></li>';
}
function wdDemo() {
  const o = { W: 900, H: 620, dx: 610, dy: 300, r: 30, fx: 452, fy: 318, cup: 0.6, defA: Math.PI / 2 + 0.5, defW: 0.12, seed: 5, vl: 6.5, round: true };
  WD.src = drawFundus(o); WD.disc = { x: o.dx, y: o.dy }; WD.fovea = { x: o.fx, y: o.fy };
  REAL.wide = false; wdTool('mark');
  WD.marks = [{ x: o.dx + Math.cos(o.defA) * 125, y: o.dy + Math.sin(o.defA) * 125, kind: 'RNFL 결손' }]; wdEnhance();
}
$('gwd-cv').addEventListener('pointerdown', (e) => {
  const p = cpt($('gwd-cv'), e);
  if (WD.tool === 'disc') { WD.disc = p; wdTool(WD.fovea ? 'mark' : 'fovea'); } else if (WD.tool === 'fovea') { WD.fovea = p; wdTool(WD.disc ? 'mark' : 'disc'); } else if (WD.disc && WD.fovea) WD.marks.push({ x: p.x, y: p.y, kind: $('gwd-kind').value });
  wdDraw();
});
seg('gwd-tool', (v) => { WD.tool = v; });
function wdTool(v) { WD.tool = v; document.querySelectorAll('#gwd-tool button').forEach((x) => x.setAttribute('aria-pressed', x.dataset.v === v)); }
$('gwd-clear').addEventListener('click', () => { WD.marks = []; wdDraw(); });
$('gwd-rf').addEventListener('change', (e) => { WD.rf = e.target.checked; wdEnhance(); });
$('gwd-sec').addEventListener('change', (e) => { WD.sec = e.target.checked; wdDraw(); });
$('gwd-vf').addEventListener('change', (e) => { WD.vf = e.target.checked; wdDraw(); });
slider('gwd-k', (v) => v.toFixed(1), (v) => { WD.k = v; wdEnhance(); });
$('gwd-demo').addEventListener('click', wdDemo);
function wdSet(c) { WD.src = c; WD.disc = WD.fovea = null; WD.marks = []; wdTool('disc'); wdEnhance(); }
onFile('gwd-f', (c) => { REAL.wide = true; wdSet(c); });

// ================= 경과 비교 =================
const PG = { A: null, B: null, Bs: null, dx: 0, dy: 0, mode: 'flick', hz: 2, mix: 0.5, phase: 0, last: 0 };
const setPgDx = slider('gpg-dx', px, (v) => { PG.dx = v; pgRebuild(); });
const setPgDy = slider('gpg-dy', px, (v) => { PG.dy = v; pgRebuild(); });
slider('gpg-speed', (v) => v + ' Hz', (v) => { PG.hz = v; });
slider('gpg-mix', (v) => v + '%', (v) => { PG.mix = v / 100; pgDraw(); });
const PG_HINT = { flick: '정합한 두 사진을 번갈아 보여줍니다. 움직이거나 나타나는 부분이 변화입니다.', blend: '슬라이더로 기준과 추적 사진을 섞어 봅니다.', diff: '밝기 차이가 큰 곳을 분홍색으로 표시합니다. 조명 차이도 함께 잡히므로 깜빡임으로 확인하세요.' };
function pgRebuild() { if (!PG.A) return; PG.Bs = shifted(PG.B, PG.A.width, PG.A.height, PG.dx, PG.dy); pgDraw(); }
function pgAuto() { const s = findShift(PG.A, PG.B); PG.dx = clamp(s.dx, -60, 60); PG.dy = clamp(s.dy, -60, 60); setPgDx(PG.dx); setPgDy(PG.dy); pgRebuild(); $('gpg-status').textContent = `자동 정합: 좌우 ${px(PG.dx)}, 상하 ${px(PG.dy)} 보정`; }
function pgDemo() {
  const o = { W: 600, H: 600, dx: 330, dy: 300, r: 105, cup: 0.6, defA: Math.PI / 2 + 0.5, defW: 0.07, seed: 23 };
  PG.A = drawFundus(o); PG.B = warp(drawFundus({ ...o, defW: 0.15, hem: true }), null, 0, 7, -5, 1.06); pgAuto(); REAL.prog = false;
}
function pgDraw() {
  if (!PG.A) return;
  const cv = $('gpg-cv'), g = cv.getContext('2d'), w = PG.A.width, h = PG.A.height; cv.width = w; cv.height = h;
  $('gpg-hint').textContent = PG_HINT[PG.mode]; $('gpg-speed-box').hidden = PG.mode !== 'flick'; $('gpg-mix-box').hidden = PG.mode !== 'blend';
  let tag = '';
  if (PG.mode === 'flick') { g.drawImage(PG.phase ? PG.Bs : PG.A, 0, 0); tag = PG.phase ? '추적' : '기준'; }
  else if (PG.mode === 'blend') { g.drawImage(PG.A, 0, 0); g.globalAlpha = PG.mix; g.drawImage(PG.Bs, 0, 0); g.globalAlpha = 1; }
  else {
    const a = PG.A.getContext('2d').getImageData(0, 0, w, h), b = PG.Bs.getContext('2d').getImageData(0, 0, w, h).data, d = a.data;
    let ma = 0, mb = 0; for (let i = 0; i < d.length; i += 16) { ma += d[i] + d[i + 1] + d[i + 2]; mb += b[i] + b[i + 1] + b[i + 2]; } const gn = mb ? ma / mb : 1;
    for (let i = 0; i < d.length; i += 4) { const la = (d[i] + d[i + 1] + d[i + 2]) / 3, df = Math.abs(la - (b[i] + b[i + 1] + b[i + 2]) / 3 * gn), k = b[i] + b[i + 1] + b[i + 2] ? clamp((df - 14) / 30, 0, 1) : 0; d[i] = la * (1 - k) + 255 * k; d[i + 1] = la * (1 - k) + 40 * k; d[i + 2] = la * (1 - k) + 150 * k; }
    g.putImageData(a, 0, 0);
  }
  if (tag) { g.font = '700 15px sans-serif'; g.fillStyle = 'rgba(0,0,0,.65)'; g.fillRect(10, 10, 54, 26); g.fillStyle = PG.phase ? '#ffc14a' : '#58d6ff'; g.fillText(tag, 20, 29); }
}
seg('gpg-mode', (v) => { PG.mode = v; pgDraw(); });
$('gpg-auto').addEventListener('click', pgAuto);
$('gpg-zero').addEventListener('click', () => { PG.dx = PG.dy = 0; setPgDx(0); setPgDy(0); pgRebuild(); $('gpg-status').textContent = '보정을 해제했습니다.'; });
$('gpg-demo').addEventListener('click', pgDemo);
onFile('gpg-fa', (c) => { REAL.prog = true; PG.A = c; PG.B = shifted(PG.B, c.width, c.height, 0, 0); PG.dx = PG.dy = 0; setPgDx(0); setPgDy(0); pgRebuild(); $('gpg-status').textContent = '기준 사진을 불러왔습니다. 추적 사진도 넣어 주세요.'; });
onFile('gpg-fb', (c) => { REAL.prog = true; PG.B = shifted(c, PG.A.width, PG.A.height, 0, 0); pgAuto(); });

// ================= 탭 · 애니메이션 =================
let tab = 'stereo';
const REDRAW = { stereo: stDraw, disc: dcDraw, wide: wdDraw, prog: pgDraw };
$('glc-tabs').addEventListener('click', (e) => {
  const b = e.target.closest('button[data-tab]'); if (!b) return; tab = b.dataset.tab;
  document.querySelectorAll('#glc-tabs button').forEach((x) => x.setAttribute('aria-selected', x === b));
  for (const k of Object.keys(REDRAW)) $('glc-p-' + k).hidden = k !== tab;
  REDRAW[tab]();
});
setInterval(() => {
  if (!dlg.open) return;
  const now = performance.now();
  if (tab === 'stereo' && ST.mode === 'wiggle' && now - ST.last > 500 / ST.hz) { ST.last = now; ST.phase ^= 1; stDraw(); }
  if (tab === 'prog' && PG.mode === 'flick' && now - PG.last > 500 / PG.hz) { PG.last = now; PG.phase ^= 1; pgDraw(); }
}, 30);

if (window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches) {
  ST.mode = 'sbs'; document.querySelectorAll('#gst-mode button').forEach((x) => x.setAttribute('aria-pressed', x.dataset.v === 'sbs'));
  PG.mode = 'blend'; document.querySelectorAll('#gpg-mode button').forEach((x) => x.setAttribute('aria-pressed', x.dataset.v === 'blend'));
}

// ================= 앱 연동: 열기 · 저장 =================
const dlg = $('glc'), msg = (t) => { $('glc-msg').textContent = t; };
let eye = 'NA';
function capToCanvas(c) {
  return new Promise((res, rej) => {
    const im = new Image();
    im.onload = () => { const s = Math.min(1, MAXS / Math.max(im.width, im.height)); const cv = mkc(Math.round(im.width * s), Math.round(im.height * s)); cv.getContext('2d').drawImage(im, 0, 0, cv.width, cv.height); res(cv); };
    im.onerror = () => rej(new Error('영상을 불러오지 못했습니다.'));
    im.src = c.url;
  });
}
/** Pro 화면의 선택 상태에서 분석할 영상을 고른다: [스테레오·경과용 2장 | null, 디스크·광각용 1장 | null] */
function pick(P) {
  let pair = null;
  if (P.sel.length === 2) { const [i, j] = [...P.sel].sort((x, y) => x - y); pair = [P.caps[i], P.caps[j]]; }
  else if (P.idx > 0 && P.caps[P.idx]) pair = [P.caps[P.idx - 1], P.caps[P.idx]];
  return [pair, P.caps[P.idx] || (pair && pair[1]) || null];
}
let openSeq = 0;
async function open() {
  const tok = ++openSeq, [pair, cur] = pick(window.SlitPro.state);
  if (!dlg.open) dlg.showModal();
  msg('');
  eye = (cur && cur.eye) || (pair && pair[0].eye) || 'NA';
  try {
    const cs = await Promise.all([...(pair || []), ...(cur ? [cur] : [])].map(capToCanvas));
    if (tok !== openSeq) return;
    if (pair) {
      REAL.stereo = REAL.prog = true;
      stSet(cs[0], shifted(cs[1], cs[0].width, cs[0].height, 0, 0)); stAuto();
      PG.A = cs[0]; PG.B = shifted(cs[1], cs[0].width, cs[0].height, 0, 0); pgAuto();
    } else { stDemo(); pgDemo(); }
    if (cur) { const c = cs[cs.length - 1]; REAL.disc = REAL.wide = true; dcEye(cur.eye); dcSet(c, false); wdSet(c); }
    else { dcDemo(); wdDemo(); }
    $('glc-src').textContent = (pair ? `스테레오·경과: ${pair[0].captured_at} ↔ ${pair[1].captured_at}` : '스테레오·경과: 데모 영상 (MULTI에서 2장을 고른 뒤 여세요)')
      + '  ·  ' + (cur ? `디스크·광각: ${cur.captured_at}` : '디스크·광각: 데모 영상');
  } catch (e) { if (tok === openSeq) msg(e.message); }
}
const ST_KO = { wiggle: '위글', sbs: '나란히', cross: '교차', ana: '적청', depth: '깊이 지도' };
function noteOf() {
  if (tab === 'stereo') return '스테레오 ' + ST_KO[ST.mode];
  if (tab === 'disc') return 'CDR ' + (DC.cup.ry / DC.disc.ry).toFixed(2);
  return tab === 'wide' ? '광각 RNFL 분석' : '경과 비교';
}
async function save() {
  const App = window.SlitApp, p = App.currentPatient();
  if (!p) { msg('환자를 먼저 선택하세요.'); return false; }
  if (!REAL[tab]) { msg('데모 영상은 저장하지 않습니다.'); return false; }
  const cv = $({ stereo: 'gst-cv', disc: 'gdc-cv', wide: 'gwd-cv', prog: 'gpg-cv' }[tab]);
  const blob = await new Promise((r) => cv.toBlob(r, 'image/png'));
  const ok = blob && await App.persistCapture(p, 'photo', blob, 'png', tab === 'disc' ? DC.eye : eye, null, noteOf(), { silent: true });
  if (!ok) { msg('저장하지 못했습니다.'); return false; }
  msg(`저장했습니다 — ${noteOf()}`);
  const P = window.SlitPro.state, keep = P.idx;      // 새 영상이 추가돼도 보던 영상과 선택은 그대로
  await window.SlitPro.reload(false); P.idx = keep;
  App.renderThumbs();
  return true;
}
$('pro-glc').addEventListener('click', open);
$('glc-save').addEventListener('click', save);
$('glc-close').addEventListener('click', () => dlg.close());

// 자동화 테스트·디버깅용 핸들
window.SlitGlaucoma = { open, save, pick, noteOf, real: REAL, stereo: ST, disc: DC, wide: WD, prog: PG, findShift, disparity,
  setTab: (t) => document.querySelector(`#glc-tabs [data-tab=${t}]`).click() };
})();

