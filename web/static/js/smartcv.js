/* 슬릿램프 영상 시스템 — 스마트 캡처 · 측정 보조 알고리즘 (브라우저 전용 계산, 서버로 보내지 않음)
 *
 * 데스크탑 앱 app/capture/smart_capture.py · analysis.py · cataract.py 와 같은 방법을 JS 로 옮긴 것.
 * DOM 을 쓰지 않는 순수 계산 모듈이라 Node 로도 테스트한다 (tests/js/smartcv.test.mjs).
 * 입력 영상은 ImageData 형태 { data: RGBA Uint8ClampedArray, width, height } — 축소는 호출하는 쪽(canvas)이 한다.
 *
 * 스마트 캡처
 *   measure()   관심 영역 선명도(Tenengrad, 반사광·암부 제외) · 밝기 · 포화/암부 비율 · 흔들림용 축소 영상
 *   Engine      Best Shot 버퍼(최근 1초) + 자동 촬영 판정(초점 스윕 → 최고점 근처 안정 · 깜빡임/반사/흔들림 거부 · 쿨다운)
 *   quality()   초점·노출·안정·반사 0~100 + 재촬영 안내 (진단 아님)
 *   peakingMask()  초점이 맞은 경계 표시용 마스크
 * 측정 보조 (질환 판정 없음 — 같은 조건 영상끼리 비교하는 상대값)
 *   classifyIllumination · fluorescein · redness · nuclear(핵 혼탁, 슬릿) · cortical(피질 혼탁, 역조명) · alignShift(경과 비교 정렬)
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.SmartCV = api;
}(typeof self !== 'undefined' ? self : this, () => {
  'use strict';

  const clamp = (x, lo, hi) => (x < lo ? lo : x > hi ? hi : x);
  const AUTO_MODES = ['off', 'freeze', 'save'];
  // 백내장 지수 조정 상수 — 데스크탑 cataract.py 와 동일 (실사진으로 조정 필요)
  const CAT = { RATIO_CLEAR: 0.12, RATIO_DENSE: 0.95, SAT_LEVEL: 250, DARK_FRAC: 0.72, PUPIL_EDGE_SKIP: 0.08 };
  const ILLUMINATION_LABELS = { diffuse: '디퓨즈', slit: '슬릿', cobalt: '코발트블루(형광)', ir: 'IR·흑백' };

  // ---------- 기본 연산 ----------
  function gray(im) {
    const n = im.width * im.height, d = im.data, g = new Uint8Array(n);
    for (let i = 0, j = 0; i < n; i++, j += 4) g[i] = (d[j] * 77 + d[j + 1] * 150 + d[j + 2] * 29) >> 8;
    return g;
  }
  /** 3×3 가우시안 [1 2 1]/16 (가장자리 복제) */
  function blur3(g, w, h) {
    const t = new Float32Array(w * h), o = new Float32Array(w * h);
    for (let y = 0; y < h; y++) {
      const r = y * w;
      for (let x = 0; x < w; x++) {
        const a = g[r + (x ? x - 1 : 0)], c = g[r + (x < w - 1 ? x + 1 : x)];
        t[r + x] = (a + 2 * g[r + x] + c) * 0.25;
      }
    }
    for (let y = 0; y < h; y++) {
      const ru = (y ? y - 1 : 0) * w, rd = (y < h - 1 ? y + 1 : y) * w, r = y * w;
      for (let x = 0; x < w; x++) o[r + x] = (t[ru + x] + 2 * t[r + x] + t[rd + x]) * 0.25;
    }
    return o;
  }
  /** 이진 마스크 팽창 (정사각 반경 r) — 행·열 누적합 */
  function dilate(m, w, h, r) {
    const tmp = new Uint8Array(w * h), out = new Uint8Array(w * h), row = new Int32Array(w + 1), col = new Int32Array(h + 1);
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) row[x + 1] = row[x] + m[y * w + x];
      for (let x = 0; x < w; x++) tmp[y * w + x] = row[Math.min(w, x + r + 1)] - row[Math.max(0, x - r)] > 0 ? 1 : 0;
    }
    for (let x = 0; x < w; x++) {
      for (let y = 0; y < h; y++) col[y + 1] = col[y] + tmp[y * w + x];
      for (let y = 0; y < h; y++) out[y * w + x] = col[Math.min(h, y + r + 1)] - col[Math.max(0, y - r)] > 0 ? 1 : 0;
    }
    return out;
  }
  const erode = (m, w, h, r) => { const inv = m.map((v) => 1 - v), d = dilate(inv, w, h, r); return d.map((v) => 1 - v); };
  /** Sobel 기울기 → (gx, gy) 콜백 */
  function sobel(b, w, h, fn) {
    for (let y = 1; y < h - 1; y++) {
      for (let x = 1; x < w - 1; x++) {
        const i = y * w + x;
        const tl = b[i - w - 1], t = b[i - w], tr = b[i - w + 1], l = b[i - 1], r = b[i + 1], bl = b[i + w - 1], bo = b[i + w], br = b[i + w + 1];
        fn(i, (tr + 2 * r + br) - (tl + 2 * l + bl), (bl + 2 * bo + br) - (tl + 2 * t + tr));
      }
    }
  }
  /** 영역 평균 축소 (흔들림 비교용) */
  function shrinkGray(g, w, h, nw) {
    nw = Math.max(1, Math.min(w, nw));
    const nh = Math.max(1, Math.round(h * nw / w)), out = new Float32Array(nw * nh);
    for (let y = 0; y < nh; y++) {
      const y0 = Math.floor(y * h / nh), y1 = Math.max(y0 + 1, Math.floor((y + 1) * h / nh));
      for (let x = 0; x < nw; x++) {
        const x0 = Math.floor(x * w / nw), x1 = Math.max(x0 + 1, Math.floor((x + 1) * w / nw));
        let s = 0;
        for (let yy = y0; yy < y1; yy++) for (let xx = x0; xx < x1; xx++) s += g[yy * w + xx];
        out[y * nw + x] = s / ((y1 - y0) * (x1 - x0));
      }
    }
    return { g: out, w: nw, h: nh };
  }
  function roiRect(width, height, frac) {
    frac = clamp(Number(frac) || 0.5, 0.1, 1);
    const w = Math.max(1, Math.floor(width * frac)), h = Math.max(1, Math.floor(height * frac));
    return { x: Math.floor((width - w) / 2), y: Math.floor((height - h) / 2), w, h };
  }

  // ---------- 선명도 · 화질 ----------
  /** 관심 영역(이미 잘라서 축소한 영상)의 선명도 지표. 반사광(포화)·암부와 그 테두리는 빼고 계산. */
  function measure(im) {
    const w = im.width, h = im.height, n = w * h, g = gray(im);
    let sum = 0, over = 0, under = 0;
    for (let i = 0; i < n; i++) { const v = g[i]; sum += v; if (v >= 250) over++; else if (v <= 15) under++; }
    const b = blur3(g, w, h);
    let valid = new Uint8Array(n);
    for (let i = 0; i < n; i++) valid[i] = b[i] > 15 && b[i] < 245 ? 1 : 0;
    valid = erode(valid, w, h, 2);                                   // 5×5 — 반사광 테두리의 강한 경계 제외
    let nv = 0;
    for (let i = 0; i < n; i++) nv += valid[i];
    const out = { focus: 0, brightness: n ? sum / n : 0, over: over / (n || 1), under: under / (n || 1), valid: nv / (n || 1),
      small: shrinkGray(g, w, h, 96) };
    if (out.valid < 0.2) return out;
    let ten = 0, k = 0;
    sobel(b, w, h, (i, gx, gy) => { if (valid[i]) { ten += gx * gx + gy * gy; k++; } });
    out.focus = k ? ten / k : 0;
    return out;
  }
  function quality(m, rel) {
    const expPen = Math.max(0, 40 - m.brightness) * 2 + Math.max(0, m.brightness - 215) * 2;
    const raw = { focus: rel, exposure: 100 - expPen - m.under * 60, stability: 100 - (m.motion || 0) * 8, reflection: 100 - m.over * 600 };
    const q = {};
    for (const k of Object.keys(raw)) q[k] = Math.round(clamp(raw[k], 0, 100));
    const issues = [];
    if (q.focus < 70) issues.push('초점 흐림 — 조이스틱을 앞뒤로 천천히');
    if (m.over > 0.04) issues.push('반사광/노출 과다 — 조명 각도·밝기 조절');
    else if (m.brightness > 215) issues.push('노출 과다 — 조명 밝기 낮추기');
    if (m.brightness < 35) issues.push('노출 부족 — 조명 밝기 올리기');
    if ((m.motion || 0) > 8) issues.push('흔들림 — 잠시 고정');
    q.issues = issues; q.ok = !issues.length;
    return q;
  }
  /** 포커스 피킹: 초점이 맞은(경계가 날카로운) 곳 = 1. sensitivity 1(적게)~3(많이). 포화 반사광 주변 제외. */
  function peakingMask(im, sensitivity = 2) {
    const w = im.width, h = im.height, n = w * h, b = blur3(gray(im), w, h);
    let sat = new Uint8Array(n);
    for (let i = 0; i < n; i++) sat[i] = b[i] >= 245 ? 1 : 0;
    sat = dilate(sat, w, h, 4);
    const mag = new Float32Array(n);
    let s = 0, s2 = 0, c = 0;
    sobel(b, w, h, (i, gx, gy) => {
      if (sat[i]) return;
      const v = Math.sqrt(gx * gx + gy * gy);
      mag[i] = v;
      if (v > 0) { s += v; s2 += v * v; c++; }
    });
    const out = new Uint8Array(n);
    if (!c) return out;
    const mean = s / c, sd = Math.sqrt(Math.max(0, s2 / c - mean * mean));
    const k = { 1: 3.0, 2: 2.3, 3: 1.6 }[sensitivity] || 2.3;
    const thr = Math.max(40, mean + k * sd);
    for (let i = 0; i < n; i++) out[i] = mag[i] > thr ? 1 : 0;
    return out;
  }

  // ---------- 엔진: Best Shot · 자동 촬영 ----------
  const DEFAULTS = {
    autoMode: 'off', bestWindow: 1.0, bufferSeconds: 1.5, bufferMax: 45, window: 2.0, peakRatio: 0.90,
    stableFrames: 6, stableTol: 0.08, sweepRatio: 0.80, blinkJump: 0.12, blinkHold: 0.3, maxOver: 0.25,
    minBrightness: 20, maxMotion: 10, cooldownFreeze: 1.5, cooldownSave: 3.0, minFocus: 1.0,
  };
  class Engine {
    /** onEvict(frame): 버퍼에서 빠지는 프레임 정리 (ImageBitmap.close 등) */
    constructor(settings = {}, onEvict = null) {
      this.s = { ...DEFAULTS, ...settings }; this.onEvict = onEvict;
      this.reset();
    }
    reset() {
      if (this.buf && this.onEvict) for (const e of this.buf) if (e.frame != null) this.onEvict(e.frame);
      this.buf = []; this.hist = []; this.ref = []; this.prevSmall = null; this.prevBright = null;
      this.blockUntil = 0; this.cooldownUntil = this.cooldownUntil || 0; this.last = null;
    }
    /** m = measure() 결과, ts = 초, frame = 보관할 원본 프레임(무엇이든) → { m, rel, triggered, q } */
    push(m, ts, frame = null) {
      const s = this.s;
      let motion = 0;
      const sm = m.small;
      if (sm && this.prevSmall && this.prevSmall.g.length === sm.g.length) {
        let d = 0;
        for (let i = 0; i < sm.g.length; i++) d += Math.abs(sm.g[i] - this.prevSmall.g[i]);
        motion = d / sm.g.length;
      }
      this.prevSmall = sm;
      if (this.prevBright != null && Math.abs(m.brightness - this.prevBright) / Math.max(this.prevBright, 10) > s.blinkJump) {
        this.blockUntil = ts + s.blinkHold;
      }
      this.prevBright = m.brightness;
      const fm = { ts, focus: m.focus, brightness: m.brightness, over: m.over, under: m.under, valid: m.valid,
        motion, blink: ts < this.blockUntil };
      // Best Shot 버퍼 (시간 · 개수 제한)
      this.buf.push({ m: fm, frame });
      while (this.buf.length && (this.buf[0].m.ts < ts - s.bufferSeconds || this.buf.length > s.bufferMax)) {
        const old = this.buf.shift();
        if (this.onEvict && old.frame != null) this.onEvict(old.frame);
      }
      // 상대 초점 (최근 5초 최고점 대비 %)
      this.ref.push([ts, m.focus]);
      while (this.ref.length && this.ref[0][0] < ts - 5) this.ref.shift();
      const peak = Math.max(...this.ref.map((r) => r[1]));
      const rel = peak > s.minFocus ? 100 * m.focus / peak : 0;
      const triggered = this.updateAuto(fm);
      this.last = { m: fm, rel, triggered, q: quality(fm, rel) };
      return this.last;
    }
    /** 최근 window 초 중 가장 선명한 프레임 (깜빡임 구간 제외) → { frame, m } | null */
    best(window = null, now = null) {
      if (!this.buf.length) return null;
      window = window == null ? this.s.bestWindow : window;
      now = now == null ? this.buf[this.buf.length - 1].m.ts : now;
      const c = this.buf.filter((e) => e.m.ts >= now - window && !e.m.blink);
      if (!c.length) return this.buf[this.buf.length - 1];
      return c.reduce((a, b) => (b.m.focus > a.m.focus ? b : a));
    }
    updateAuto(m) {
      const s = this.s;
      this.hist.push(m);
      while (this.hist.length && this.hist[0].ts < m.ts - s.window) this.hist.shift();
      if (s.autoMode !== 'freeze' && s.autoMode !== 'save') return false;
      if (m.blink || m.ts < this.cooldownUntil) return false;
      const h = this.hist, n = s.stableFrames;
      if (h.length < n + 2 || h[h.length - 1].ts - h[0].ts < 0.4) return false;
      if (m.over > s.maxOver || m.brightness < s.minBrightness || m.valid < 0.3) return false;
      const peak = Math.max(...h.map((x) => x.focus));
      if (peak <= s.minFocus) return false;
      const recent = h.slice(-n), rf = recent.map((x) => x.focus);
      const lo = Math.min(...rf), hi = Math.max(...rf);
      if (lo < s.peakRatio * peak) return false;                       // 최고점 근처가 아님
      if ((hi - lo) / hi > s.stableTol) return false;                  // 아직 흔들림
      if (recent.some((x) => x.blink) || Math.max(...recent.slice(1).map((x) => x.motion)) > s.maxMotion) return false;
      if (Math.min(...h.map((x) => x.focus)) > s.sweepRatio * peak) return false;   // 초점을 맞춰 들어온 흔적 없음 (정지 화면)
      this.cooldownUntil = m.ts + (s.autoMode === 'save' ? s.cooldownSave : s.cooldownFreeze);
      this.hist = [];                                                   // 다음 자동 촬영은 새 스윕이 필요
      return true;
    }
  }

  // ---------- 측정 보조 ----------
  /** 타원 ROI 마스크. roi = 원본 좌표 {x1,y1,x2,y2}, scale = 작업 영상 / 원본. 없으면 전체. */
  function ellipseMask(w, h, roi, scale = 1) {
    const m = new Uint8Array(w * h);
    if (!roi) { m.fill(1); return m; }
    const cx = (roi.x1 + roi.x2) / 2 * scale, cy = (roi.y1 + roi.y2) / 2 * scale;
    const ax = Math.max(1, Math.abs(roi.x2 - roi.x1) / 2 * scale), ay = Math.max(1, Math.abs(roi.y2 - roi.y1) / 2 * scale);
    for (let y = 0; y < h; y++) {
      const dy = (y + 0.5 - cy) / ay;
      for (let x = 0; x < w; x++) { const dx = (x + 0.5 - cx) / ax; if (dx * dx + dy * dy <= 1) m[y * w + x] = 1; }
    }
    return m;
  }
  /** RGB → HSV (OpenCV 단위: H 0~180, S·V 0~255) */
  function hsv(r, g, b) {
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
    let H = 0;
    if (d) {
      if (mx === r) H = 60 * (((g - b) / d) % 6);
      else if (mx === g) H = 60 * ((b - r) / d + 2);
      else H = 60 * ((r - g) / d + 4);
      if (H < 0) H += 360;
    }
    return [H / 2, mx ? (d / mx) * 255 : 0, mx];
  }
  function classifyIllumination(im) {
    const d = im.data, n = im.width * im.height;
    let lit = 0, sat = 0, R = 0, G = 0, B = 0;
    for (let i = 0, j = 0; i < n; i++, j += 4) {
      const r = d[j], g = d[j + 1], b = d[j + 2], v = Math.max(r, g, b);
      if (v <= 40) continue;
      lit++; sat += v ? ((v - Math.min(r, g, b)) / v) * 255 : 0; R += r; G += g; B += b;
    }
    if (!lit) return 'slit';
    const dark = 1 - lit / n, s = sat / lit, r = R / lit, g = G / lit, b = B / lit;
    if (s >= 25 && ((b > 1.3 * r && b >= 0.9 * g) || (g + b) > 2.6 * Math.max(r, 1))) return 'cobalt';
    if (dark > 0.55) return 'slit';                    // 밝은 띠 + 어두운 배경 (백색 슬릿광은 채도가 낮아 IR 보다 먼저)
    if (s < 25) return 'ir';
    return 'diffuse';
  }
  function openMask(m, w, h) { return dilate(erode(m, w, h, 1), w, h, 1); }
  /** 형광 염색 면적: 녹색 형광 화소. im = 작업 영상(원본 × scale). → { ratio %, areaPx(원본), areaMm2, mask } */
  function fluorescein(im, roi = null, scale = 1, pxmm = 0) {
    const w = im.width, h = im.height, d = im.data, roiM = ellipseMask(w, h, roi, scale);
    let m = new Uint8Array(w * h);
    for (let i = 0, j = 0; i < w * h; i++, j += 4) {
      const r = d[j], g = d[j + 1], b = d[j + 2], [H, S, V] = hsv(r, g, b);
      m[i] = H >= 28 && H <= 90 && S >= 60 && V >= 80 && g > r && g >= b ? 1 : 0;
    }
    m = openMask(m, w, h);
    let roiN = 0, k = 0;
    for (let i = 0; i < m.length; i++) { if (roiM[i]) { roiN++; if (m[i]) k++; } else m[i] = 0; }
    const areaPx = k / (scale * scale);
    return { ratio: 100 * k / (roiN || 1), areaPx, areaMm2: pxmm > 0 ? areaPx / (pxmm * pxmm) : null, mask: m };
  }
  /** 충혈 지수 (상대 측정값): 붉은 기 0~100 + 혈관(적색 우세) 화소 % */
  function redness(im, roi = null, scale = 1) {
    const w = im.width, h = im.height, d = im.data, roiM = ellipseMask(w, h, roi, scale), mask = new Uint8Array(w * h);
    let n = 0, idx = 0, ves = 0;
    for (let i = 0, j = 0; i < w * h; i++, j += 4) {
      const r = d[j], g = d[j + 1], b = d[j + 2], v = Math.max(r, g, b);
      if (!roiM[i] || v <= 40 || v >= 250) continue;
      n++;
      idx += clamp((r / (r + g + b + 1e-3) - 1 / 3) / (0.6 - 1 / 3), 0, 1);
      if (r > 1.45 * g && r > 1.3 * b && v > 50) { ves++; mask[i] = 1; }
    }
    return { index: n ? idx / n * 100 : 0, vesselPct: n ? 100 * ves / n : 0, mask };
  }

  // ---------- 백내장: 수정체 혼탁 지수 (등급 판정 아님) ----------
  const catIndex = (ratio) => clamp((ratio - CAT.RATIO_CLEAR) / (CAT.RATIO_DENSE - CAT.RATIO_CLEAR), 0, 1) * 100;
  function percentile(arr, p) {
    const a = Float64Array.from(arr).sort();
    if (!a.length) return 0;
    const k = (a.length - 1) * p / 100, f = Math.floor(k), c = Math.min(a.length - 1, f + 1);
    return a[f] + (a[c] - a[f]) * (k - f);
  }
  /** 열 프로파일의 밝은 띠 [{x0, x1, peak}] */
  function bands(prof, minWidth = 2) {
    const base = percentile(prof, 10), spread = percentile(prof, 90) - base;
    if (spread < 8) return [];
    const thr = base + Math.max(8, 0.25 * spread), out = [];
    let start = -1;
    for (let x = 0; x <= prof.length; x++) {
      const on = x < prof.length && prof[x] > thr;
      if (on && start < 0) start = x;
      else if (!on && start >= 0) {
        if (x - start >= minWidth) out.push({ x0: start, x1: x, peak: Math.max(...prof.slice(start, x)) });
        start = -1;
      }
    }
    return out;
  }
  /** 핵 혼탁 지수 (슬릿 단면): 가장 좁은 밝은 띠 = 각막(기준자), 가장 넓은 띠 = 수정체 → 밝기비 0~100.
   *  im = 작업 영상(원본 × scale), roi = 원본 좌표 사각형 {x1,y1,x2,y2} (원 주석의 외접 사각형) */
  function nuclear(im, roi = null, scale = 1) {
    const W = im.width, H = im.height, g = gray(im);
    const x1 = roi ? clamp(Math.floor(Math.min(roi.x1, roi.x2) * scale), 0, W) : 0;
    const x2 = roi ? clamp(Math.ceil(Math.max(roi.x1, roi.x2) * scale), 0, W) : W;
    const y1 = roi ? clamp(Math.floor(Math.min(roi.y1, roi.y2) * scale), 0, H) : 0;
    const y2 = roi ? clamp(Math.ceil(Math.max(roi.y1, roi.y2) * scale), 0, H) : H;
    const cw = x2 - x1, out = { index: 0, ratio: 0, lensMean: 0, corneaMean: 0, lensBand: null, corneaBand: null, hasCornea: false, mask: new Uint8Array(W * H) };
    if (cw < 4 || y2 - y1 < 4) return out;
    const prof = new Float64Array(cw);
    for (let x = 0; x < cw; x++) {
      let s = 0, n = 0;
      for (let y = y1; y < y2; y++) { const v = g[y * W + x1 + x]; if (v < CAT.SAT_LEVEL) { s += v; n++; } }
      prof[x] = n ? s / n : 0;
    }
    const k = Math.max(1, Math.floor(cw / 200)), ps = new Float64Array(cw);   // 가벼운 평활
    for (let x = 0; x < cw; x++) { let s = 0, n = 0; for (let t = -k; t <= k; t++) { const xx = x + t; if (xx >= 0 && xx < cw) { s += prof[xx]; n++; } } ps[x] = s / n; }
    const bs = bands(Array.from(ps));
    if (!bs.length) return out;
    bs.sort((a, b) => (a.x1 - a.x0) - (b.x1 - b.x0));
    const lens = bs[bs.length - 1];
    const cands = bs.slice(0, -1).filter((b) => (b.x1 - b.x0) < 0.6 * (lens.x1 - lens.x0));
    const cornea = cands.length ? cands.reduce((a, b) => (b.peak > a.peak ? b : a)) : null;
    const base = percentile(Array.from(ps), 10);
    const bandMean = (b) => {                           // 띠 가장자리 열에 흔들리지 않게 최고값 절반 이상인 '심' 열만
      let s = 0, n = 0;
      for (let x = b.x0; x < b.x1; x++) {
        if (ps[x] < base + 0.5 * (b.peak - base)) continue;
        for (let y = y1; y < y2; y++) { const v = g[y * W + x1 + x]; if (v < CAT.SAT_LEVEL) { s += v; n++; } }
      }
      return n ? s / n : 0;
    };
    out.lensMean = bandMean(lens);
    out.lensBand = [(x1 + lens.x0) / scale, (x1 + lens.x1) / scale];
    if (cornea) {
      const cm = bandMean(cornea);
      if (cm > 1) {
        out.corneaMean = cm; out.hasCornea = true; out.ratio = out.lensMean / cm;
        out.corneaBand = [(x1 + cornea.x0) / scale, (x1 + cornea.x1) / scale];
      }
    }
    if (!out.hasCornea) out.ratio = out.lensMean / 255;                // 참고값: 절대 밝기 기준
    out.index = catIndex(out.ratio);
    const floor = Math.min(...ps) + 10;
    for (let y = y1; y < y2; y++) for (let x = x1 + lens.x0; x < x1 + lens.x1; x++) {
      const v = g[y * W + x];
      if (v < CAT.SAT_LEVEL && v > floor) out.mask[y * W + x] = 1;
    }
    return out;
  }
  /** 피질·후낭하 혼탁 지수 (역조명): 동공(원 주석) 안 주변보다 어두운 얼룩 면적 % + 동공 직경 */
  function cortical(im, pupil, scale = 1, pxmm = 0) {
    const W = im.width, H = im.height, g = gray(im);
    const ax = Math.abs(pupil.x2 - pupil.x1) / 2, ay = Math.abs(pupil.y2 - pupil.y1) / 2, dpx = 2 * Math.max(ax, ay);
    const out = { index: 0, areaPct: 0, pupilPx: dpx, pupilMm: pxmm > 0 ? dpx / pxmm : null, smallPupil: false, mask: new Uint8Array(W * H) };
    if (out.pupilMm != null) out.smallPupil = out.pupilMm < 5;
    const skip = 1 - CAT.PUPIL_EDGE_SKIP, cx = (pupil.x1 + pupil.x2) / 2, cy = (pupil.y1 + pupil.y2) / 2;
    const ins = ellipseMask(W, H, { x1: cx - ax * skip, y1: cy - ay * skip, x2: cx + ax * skip, y2: cy + ay * skip }, scale);
    const vals = [];
    for (let i = 0; i < ins.length; i++) if (ins[i]) vals.push(g[i]);
    if (!vals.length) return out;
    const ref = percentile(vals, 70);                                 // 동공 전체 기준 밝기 (붉은 반사)
    // 국소 배경: 동공 반경 0.9배 상자 평균 (적분 영상) — 붉은 반사의 밝기 기울기를 따라감
    const r = Math.max(4, Math.round(Math.max(ax, ay) * scale * 0.9)), I = new Float64Array((W + 1) * (H + 1));
    for (let y = 0; y < H; y++) { let rs = 0; for (let x = 0; x < W; x++) { rs += g[y * W + x]; I[(y + 1) * (W + 1) + x + 1] = I[y * (W + 1) + x + 1] + rs; } }
    let dark = new Uint8Array(W * H);
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      const i = y * W + x;
      if (!ins[i]) continue;
      const x0 = Math.max(0, x - r), x1 = Math.min(W, x + r + 1), y0 = Math.max(0, y - r), y1 = Math.min(H, y + r + 1);
      const local = (I[y1 * (W + 1) + x1] - I[y0 * (W + 1) + x1] - I[y1 * (W + 1) + x0] + I[y0 * (W + 1) + x0]) / ((x1 - x0) * (y1 - y0));
      const bg = Math.max(local, 0.85 * ref);
      dark[i] = g[i] < CAT.DARK_FRAC * bg && bg > 25 && g[i] < CAT.SAT_LEVEL ? 1 : 0;
    }
    dark = openMask(dark, W, H);
    let k = 0;
    for (let i = 0; i < dark.length; i++) { if (!ins[i]) dark[i] = 0; k += dark[i]; }
    out.areaPct = 100 * k / vals.length; out.index = Math.min(100, out.areaPct); out.mask = dark;
    return out;
  }

  // ---------- 경과 비교: 위치 정렬 (이동 + 작은 회전, 축소 영상 탐색) ----------
  function warp(g, w, h, ang, dx, dy) {            // 결과(x,y) = 원본을 중심 기준 ang(도) 회전 후 (dx,dy) 이동한 것
    const out = new Float32Array(w * h).fill(-1), c = Math.cos(ang * Math.PI / 180), s = Math.sin(ang * Math.PI / 180);
    const cx = w / 2, cy = h / 2;
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const u = x - dx - cx, v = y - dy - cy;
      const sx = Math.round(c * u + s * v + cx), sy = Math.round(-s * u + c * v + cy);
      if (sx >= 0 && sx < w && sy >= 0 && sy < h) out[y * w + x] = g[sy * w + sx];
    }
    return out;
  }
  function cost(a, b, n, step) {
    let s = 0, k = 0, ma = 0, mb = 0;
    for (let i = 0; i < n; i += step) if (b[i] >= 0) { ma += a[i]; mb += b[i]; k++; }
    if (k < n / step * 0.4) return Infinity;                          // 겹치는 부분이 너무 적음
    ma /= k; mb /= k;
    for (let i = 0; i < n; i += step) if (b[i] >= 0) s += Math.abs(a[i] - ma - (b[i] - mb));
    return s / k;
  }
  /** moving 을 reference 에 맞추는 { angle(도), dx, dy (reference 영상 비율 0~1) }. 두 영상은 같은 크기의 작업 영상. */
  function alignShift(moving, reference) {
    const w = reference.width, h = reference.height;
    const A = Float32Array.from(gray(reference)), B = Float32Array.from(gray(moving));
    const coarse = (src) => shrinkGray(src, w, h, Math.min(w, 80));
    const a = coarse(A), b = coarse(B), cw = a.w, ch = a.h, n = cw * ch;
    let best = { c: Infinity, ang: 0, dx: 0, dy: 0 };
    const R = Math.round(cw * 0.15);
    for (let ang = -4; ang <= 4; ang += 1) {
      for (let dy = -R; dy <= R; dy++) for (let dx = -R; dx <= R; dx++) {
        const c = cost(a.g, warp(b.g, cw, ch, ang, dx, dy), n, 2);
        if (c < best.c) best = { c, ang, dx, dy };
      }
    }
    // 2배 해상도에서 ±0.5° · ±2px 다듬기
    const f = Math.min(w, 160), a2 = shrinkGray(A, w, h, f), b2 = shrinkGray(B, w, h, f), k = a2.w / cw;
    let fine = { c: Infinity, ang: best.ang, dx: best.dx * k, dy: best.dy * k };
    for (let ang = best.ang - 0.5; ang <= best.ang + 0.51; ang += 0.25) {
      for (let dy = Math.round(best.dy * k) - 2; dy <= Math.round(best.dy * k) + 2; dy++) {
        for (let dx = Math.round(best.dx * k) - 2; dx <= Math.round(best.dx * k) + 2; dx++) {
          const c = cost(a2.g, warp(b2.g, a2.w, a2.h, ang, dx, dy), a2.g.length, 1);
          if (c < fine.c) fine = { c, ang, dx, dy };
        }
      }
    }
    let base = 0, kb = 0;                                            // 정렬 전 차이 (개선됐는지 판단)
    for (let i = 0; i < a2.g.length; i++) { base += Math.abs(a2.g[i] - b2.g[i]); kb++; }
    return { angle: fine.ang, dx: fine.dx / a2.w, dy: fine.dy / a2.h, cost: fine.c, before: base / kb, ok: fine.c < base / kb };
  }

  return { AUTO_MODES, CAT, ILLUMINATION_LABELS, DEFAULTS, gray, roiRect, measure, quality, peakingMask, Engine,
    ellipseMask, classifyIllumination, fluorescein, redness, nuclear, cortical, alignShift, bands, percentile };
}));
