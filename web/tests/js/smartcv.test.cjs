/* smartcv.js 단위 테스트 — `node --test tests/js/` (pytest 의 test_smartcv_js.py 가 함께 실행) */
const test = require('node:test');
const assert = require('node:assert/strict');
const CV = require('../../static/js/smartcv.js');

// ---------- 합성 영상 도구 ----------
function rng(seed) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); }
function img(w, h, fill = [0, 0, 0]) {
  const d = new Uint8ClampedArray(w * h * 4);
  for (let i = 0; i < w * h; i++) { d[i * 4] = fill[0]; d[i * 4 + 1] = fill[1]; d[i * 4 + 2] = fill[2]; d[i * 4 + 3] = 255; }
  return { data: d, width: w, height: h };
}
function rect(im, x0, y0, x1, y1, c) {
  for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) { const j = (y * im.width + x) * 4; im.data[j] = c[0]; im.data[j + 1] = c[1]; im.data[j + 2] = c[2]; }
}
function disc(im, cx, cy, r, c, ry = r) {
  for (let y = 0; y < im.height; y++) for (let x = 0; x < im.width; x++) {
    if (((x - cx) / r) ** 2 + ((y - cy) / ry) ** 2 <= 1) { const j = (y * im.width + x) * 4; im.data[j] = c[0]; im.data[j + 1] = c[1]; im.data[j + 2] = c[2]; }
  }
}
function blur(im, sigma) {                             // 분리형 가우시안
  if (sigma < 0.4) return im;
  const r = Math.ceil(sigma * 3), k = [];
  let s = 0;
  for (let i = -r; i <= r; i++) { const v = Math.exp(-(i * i) / (2 * sigma * sigma)); k.push(v); s += v; }
  for (let i = 0; i < k.length; i++) k[i] /= s;
  const { width: w, height: h } = im, src = im.data, t = new Float32Array(w * h * 4), o = img(w, h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) for (let c = 0; c < 3; c++) {
    let a = 0; for (let i = -r; i <= r; i++) a += k[i + r] * src[(y * w + Math.min(w - 1, Math.max(0, x + i))) * 4 + c];
    t[(y * w + x) * 4 + c] = a;
  }
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) for (let c = 0; c < 3; c++) {
    let a = 0; for (let i = -r; i <= r; i++) a += k[i + r] * t[(Math.min(h - 1, Math.max(0, y + i)) * w + x) * 4 + c];
    o.data[(y * w + x) * 4 + c] = a;
  }
  return o;
}
function texture(w = 240, h = 160, seed = 1) {        // 흐린 잡음 → 30~220 범위
  const R = rng(seed), n = img(w, h);
  for (let i = 0; i < w * h * 4; i++) if (i % 4 !== 3) n.data[i] = R() * 255;
  const b = blur(n, 2.2);
  let lo = 255, hi = 0;
  for (let i = 0; i < b.data.length; i++) if (i % 4 !== 3) { lo = Math.min(lo, b.data[i]); hi = Math.max(hi, b.data[i]); }
  for (let i = 0; i < b.data.length; i++) if (i % 4 !== 3) b.data[i] = 30 + (b.data[i] - lo) * 190 / (hi - lo);
  return b;
}
const scaleImg = (im, f) => { const o = img(im.width, im.height); for (let i = 0; i < o.data.length; i++) o.data[i] = i % 4 === 3 ? 255 : im.data[i] * f; return o; };
const linspace = (a, b, n) => Array.from({ length: n }, (_, i) => a + (b - a) * i / (n - 1));

// ---------- 선명도 · 피킹 · 화질 ----------
test('focus prefers sharp and ignores glare edges', () => {
  const sharp = texture();
  const f = (im) => CV.measure(im).focus;
  assert.ok(f(sharp) > f(blur(sharp, 1.5)) && f(blur(sharp, 1.5)) > f(blur(sharp, 4)));
  const glare = blur(sharp, 4);
  rect(glare, 60, 40, 180, 100, [255, 255, 255]);     // 포화 반사광 — 경계는 매우 날카롭다
  assert.ok(f(glare) < f(blur(sharp, 1.5)));
  assert.equal(f(img(50, 50)), 0);
  assert.deepEqual(CV.roiRect(1000, 500, 0.5), { x: 250, y: 125, w: 500, h: 250 });
});

test('peaking marks sharp side, not glare', () => {
  const im = texture(300, 200, 3), bl = blur(im, 4);
  for (let y = 0; y < 200; y++) for (let x = 0; x < 150; x++) for (let c = 0; c < 3; c++) im.data[(y * 300 + x) * 4 + c] = bl.data[(y * 300 + x) * 4 + c];
  rect(im, 200, 20, 260, 60, [255, 255, 255]);
  const m = CV.peakingMask(im, 2);
  let left = 0, right = 0, glare = 0;
  for (let y = 0; y < 200; y++) for (let x = 0; x < 300; x++) {
    const v = m[y * 300 + x];
    if (x < 140) left += v; else if (x > 160) right += v;
    if (x >= 197 && x < 263 && y >= 17 && y < 63) glare += v;
  }
  assert.ok(right > 5 * Math.max(1, left), `${right} vs ${left}`);
  assert.equal(glare, 0);
});

test('quality scores and advice', () => {
  const good = CV.quality({ brightness: 120, over: 0, under: 0, motion: 0 }, 95);
  assert.ok(good.ok && good.focus === 95 && good.exposure === 100);
  const bad = CV.quality({ brightness: 230, over: 0.1, under: 0, motion: 12 }, 40);
  assert.ok(!bad.ok && bad.reflection < 50 && bad.stability < 20);
  assert.ok(bad.issues.some((s) => s.includes('초점')) && bad.issues.some((s) => s.includes('반사')));
});

// ---------- 엔진 ----------
function sweep(eng, base, sigmas, t0 = 0, fps = 30) {
  const trig = []; let t = t0;
  sigmas.forEach((s, i) => { const im = blur(base, s); if (eng.push(CV.measure(im), t, im).triggered) trig.push(i); t += 1 / fps; });
  return { trig, t };
}
const SWEEP = [...linspace(6, 0.3, 30), ...Array(15).fill(0.3), ...linspace(0.3, 6, 20)];

test('best shot picks the sharpest recent frame; buffer bounded', () => {
  const base = texture(), evicted = [];
  const eng = new CV.Engine({ bestWindow: 1, bufferSeconds: 0.5, bufferMax: 10 }, (f) => evicted.push(f));
  let t = 0;
  for (const s of [5, 3, 1.5, 0, 1.5, 3, 5]) { const im = blur(base, s); eng.push(CV.measure(im), t, im); t += 1 / 30; }
  assert.equal(eng.best().frame, base);
  for (let i = 0; i < 40; i++) eng.push(CV.measure(base), t + i / 30, i);
  assert.ok(eng.buf.length <= 10 && evicted.length >= 37);
});

test('auto trigger fires once at the focus plateau, then cooldown', () => {
  const base = texture(), eng = new CV.Engine({ autoMode: 'freeze', cooldownFreeze: 4 });
  const r1 = sweep(eng, base, SWEEP);
  assert.equal(r1.trig.length, 1);
  assert.ok(r1.trig[0] >= 30 && r1.trig[0] <= 40, String(r1.trig));
  assert.deepEqual(sweep(eng, base, SWEEP.slice(0, 45), r1.t).trig, []);        // 쿨다운 중
  assert.equal(sweep(eng, base, SWEEP.slice(0, 45), r1.t + 4).trig.length, 1);  // 쿨다운 뒤 새 스윕
});

test('auto trigger rejects static scene, off mode and blinks', () => {
  const base = texture();
  assert.deepEqual(sweep(new CV.Engine({ autoMode: 'freeze' }), base, Array(60).fill(0.3)).trig, []);
  assert.deepEqual(sweep(new CV.Engine({ autoMode: 'off' }), base, SWEEP).trig, []);
  const eng = new CV.Engine({ autoMode: 'save' });
  let { t } = sweep(eng, base, linspace(6, 0.3, 30));
  const r = eng.push(CV.measure(scaleImg(base, 0.3)), t); t += 1 / 30;
  assert.ok(r.m.blink);
  const fired = []; for (let i = 0; i < 6; i++) fired.push(eng.push(CV.measure(base), t + i / 30).triggered);
  assert.ok(!fired.some(Boolean));
  assert.ok(!eng.best().m.blink);
});

// ---------- 측정 보조 ----------
test('illumination tag', () => {
  assert.equal(CV.classifyIllumination(texture()), 'diffuse');
  const slit = img(200, 150); rect(slit, 90, 0, 110, 150, [220, 210, 200]);
  assert.equal(CV.classifyIllumination(slit), 'slit');
  assert.equal(CV.classifyIllumination(img(200, 150, [10, 30, 150])), 'cobalt');
  const g = texture(); for (let i = 0; i < g.data.length; i += 4) g.data[i] = g.data[i + 2] = g.data[i + 1];
  assert.equal(CV.classifyIllumination(g), 'ir');
});

test('fluorescein area and redness', () => {
  const im = img(400, 400, [10, 20, 120]);            // 코발트블루 배경 (RGB)
  rect(im, 100, 100, 200, 150, [90, 220, 40]);        // 녹색 형광 5000px
  const r = CV.fluorescein(im, null, 1, 10);
  assert.ok(Math.abs(r.areaPx - 5000) < 400 && Math.abs(r.areaMm2 - 50) < 4);
  assert.ok(r.mask[120 * 400 + 150] && !r.mask[300 * 400 + 300]);
  assert.ok(CV.fluorescein(im, { x1: 90, y1: 90, x2: 210, y2: 160 }).ratio > r.ratio);
  const half = img(200, 200, [10, 20, 120]); rect(half, 50, 50, 100, 75, [90, 220, 40]);   // 같은 영상을 ½ 로 축소해 계산해도 원본 면적
  assert.ok(Math.abs(CV.fluorescein(half, null, 0.5, 10).areaPx - 5000) < 400);
  const pale = img(300, 300, [190, 180, 180]), red = img(300, 300, [190, 180, 180]);
  for (let y = 0; y < 300; y += 6) rect(red, 0, y, 300, y + 1, [190, 40, 40]);
  const a = CV.redness(pale), b = CV.redness(red);
  assert.ok(b.index > a.index && b.vesselPct > 10 && a.vesselPct < 10);
});

// ---------- 백내장 ----------
function slitPhoto(lens, cornea = 200, w = 800, h = 600) {
  const R = rng(1), im = img(w, h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    let v = 12 + (R() - 0.5) * 12;
    if (x >= 300 && x < 308) v += cornea;
    if (x >= 340 && x < 420) v += lens;
    if (y >= 150 && y < 160 && x >= 302 && x < 312) v = 255;
    v = Math.max(0, Math.min(255, v));
    const j = (y * w + x) * 4; im.data[j] = im.data[j + 1] = im.data[j + 2] = v;
  }
  return im;
}
test('nuclear index: monotone, normalised by cornea, glare-robust', () => {
  const idx = [20, 60, 120, 180].map((lv) => CV.nuclear(slitPhoto(lv)).index);
  assert.deepEqual([...idx].sort((a, b) => a - b), idx);
  assert.ok(idx[0] < 25 && idx[3] > 90, String(idx));
  const r = CV.nuclear(slitPhoto(60));
  assert.ok(r.hasCornea && r.corneaBand[0] >= 296 && r.corneaBand[0] <= 300 && r.lensBand[0] >= 336 && r.lensBand[0] <= 342);
  assert.ok(Math.abs(CV.nuclear(scaleImg(slitPhoto(60), 0.6)).index - r.index) < 8);     // 조명이 어두워도
  const glare = slitPhoto(60); rect(glare, 350, 200, 400, 260, [255, 255, 255]);
  assert.ok(Math.abs(CV.nuclear(glare).index - r.index) < 5);
  assert.ok(!CV.nuclear(slitPhoto(60, 0)).hasCornea);
  const roi = CV.nuclear(slitPhoto(60), { x1: 280, y1: 100, x2: 450, y2: 500 });
  assert.ok(roi.hasCornea && Math.abs(roi.index - r.index) < 5);
});

test('cortical index, pupil diameter and small-pupil flag', () => {
  const retro = (spots) => { const im = img(500, 500); disc(im, 250, 250, 150, [200, 70, 60]);
    if (spots) { disc(im, 200, 220, 25, [60, 20, 20]); disc(im, 300, 300, 40, [70, 25, 25], 15); } return im; };
  const pupil = { x1: 100, y1: 100, x2: 400, y2: 400 };
  const r = CV.cortical(retro(true), pupil, 1, 30);
  assert.ok(r.index > 2 && r.index < 8 && Math.abs(r.pupilMm - 10) < 1e-6 && !r.smallPupil, JSON.stringify({ i: r.index }));
  assert.ok(r.mask[220 * 500 + 200] && !r.mask[250 * 500 + 250]);
  assert.equal(CV.cortical(retro(false), pupil).index, 0);
  assert.ok(CV.cortical(retro(true), pupil, 1, 80).smallPupil);
});

test('alignShift recovers shift and small rotation', () => {
  const base = texture(240, 180, 7), w = 240, h = 180, ang = 3 * Math.PI / 180, moved = img(w, h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {        // 원본을 3° 회전 + 오른쪽 10px
    const u = x - 10 - w / 2, v = y - h / 2;
    const sx = Math.round(Math.cos(ang) * u + Math.sin(ang) * v + w / 2), sy = Math.round(-Math.sin(ang) * u + Math.cos(ang) * v + h / 2);
    if (sx >= 0 && sx < w && sy >= 0 && sy < h) for (let c = 0; c < 3; c++) moved.data[(y * w + x) * 4 + c] = base.data[(sy * w + sx) * 4 + c];
  }
  const r = CV.alignShift(moved, base);
  assert.ok(r.ok);
  assert.ok(Math.abs(r.angle + 3) <= 0.75, `angle ${r.angle}`);          // 되돌리는 방향
  assert.ok(Math.abs(r.dx * w + 10) <= 3, `dx ${r.dx * w}`);
});
