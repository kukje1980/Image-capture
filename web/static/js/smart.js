/* 슬릿램프 영상 시스템 — Pro '스마트' · '분석' 탭 (데스크탑 앱 v0.2 와 같은 기능)
 *
 * 스마트 (LIVE)  초점 판정(중앙 관심 영역) · Best Shot(최근 프레임 중 가장 선명) · Smart Freeze / Auto Save
 *               · 포커스 피킹 · 실시간 화질 점검(초점·노출·안정·반사) · 백내장 모드 촬영 가이드
 * 분석          조명 모드 태그 · 형광 염색 면적 · 충혈 지수 · 경과 비교(고스트 · 위치 정렬 · 깜빡임)
 *               · 백내장 수정체 혼탁 지수(핵·피질) · 촬영 조건 메모 · LOCS III 의사 입력 · 경과 그래프
 * 계산은 smartcv.js 로 이 브라우저 안에서만 한다 (영상을 서버로 보내지 않음). 측정 기록만 /measurements 에 저장.
 * 모든 결과는 측정·기록 보조이며 질환 판정(진단)을 하지 않는다.
 */
(() => {
  const App = window.SlitApp, Pro = window.SlitPro, CV = window.SmartCV;
  if (!App || !Pro || !CV) return;
  const $ = (id) => document.getElementById(id);
  const P = Pro.state, V = Pro.viewers;
  const EYE_KO = { OD: '우안(OD)', OS: '좌안(OS)', OU: '양안(OU)' };
  const PEAK_RGB = { red: [255, 59, 48], green: [52, 211, 153], cyan: [34, 211, 238] };
  const newCanvas = (w, h) => { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; };
  const ctx2d = (c) => c.getContext('2d', { willReadFrequently: true });
  const BUFFER_BYTES = 200e6;                          // Best Shot 버퍼 상한 (1080p ≈ 24장, 4K ≈ 6장)

  // ================= 설정 (이 브라우저에 기억) =================
  const KEY = 'slitlamp-smart';
  const S = { auto: 'off', roi: 50, best: true, peak: false, sens: 2, color: 'red' };
  try { Object.assign(S, JSON.parse(localStorage.getItem(KEY) || '{}')); } catch (_) { /* 저장소 차단 */ }
  if (!CV.AUTO_MODES.includes(S.auto)) S.auto = 'off';
  const saveSettings = () => { try { localStorage.setItem(KEY, JSON.stringify(S)); } catch (_) { /* 무시 */ } };
  function readSettings() {
    S.auto = $('sm-auto').value; S.roi = Number($('sm-roi').value); S.best = $('sm-best').checked;
    S.peak = $('sm-peak').checked; S.sens = Number($('sm-sens').value); S.color = $('sm-color').value;
    $('o-sm-roi').textContent = `${S.roi}%`;
    eng.s.autoMode = S.auto;
    saveSettings();
    if (!S.peak) peakImg = null;
  }
  function syncSettings() {
    $('sm-auto').value = S.auto; $('sm-roi').value = S.roi; $('sm-best').checked = S.best;
    $('sm-peak').checked = S.peak; $('sm-sens').value = String(S.sens); $('sm-color').value = S.color;
    $('o-sm-roi').textContent = `${S.roi}%`;
  }

  // ================= 엔진 · Best Shot 버퍼 =================
  const pool = [];                                     // 다 쓴 프레임 캔버스 재사용 (매 프레임 할당 방지)
  const eng = new CV.Engine({ autoMode: S.auto }, (c) => { if (pool.length < 8) pool.push(c); });
  function copyFrame(src, w, h) {
    let c = pool.pop();
    if (!c || c.width !== w || c.height !== h) c = newCanvas(w, h);
    c.getContext('2d').drawImage(src, 0, 0, w, h);
    return c;
  }
  const clone = (c) => { const o = newCanvas(c.width, c.height); o.getContext('2d').drawImage(c, 0, 0); return o; };
  /** pro.js 가 CAPTURE/SAVE 때 부른다. Best Shot 이 켜져 있고 LIVE 중이면 최근 프레임 중 가장 선명한 것 (복사본). */
  function bestFrame(force = false) {
    if (!(force || S.best) || P.mode !== 'live') return null;
    const e = eng.best();
    return e && e.frame ? clone(e.frame) : null;
  }

  // ================= LIVE 루프 =================
  const vid = $('pro-video'), ov = $('pro-live-ov');
  const work = newCanvas(8, 8), pk = newCanvas(8, 8);
  let lastT = -1, tick = 0, peakImg = null, lastRes = null, saving = false, t0 = performance.now();
  const live = () => P.on && P.mode === 'live' && !P.frozen && vid.videoWidth > 0;

  function loop() {
    requestAnimationFrame(loop);
    if (!live()) { if (ov.dataset.drawn) clearOverlay(); return; }
    if (vid.currentTime === lastT) return;              // 새 프레임만 처리
    lastT = vid.currentTime;
    try { processFrame(); } catch (e) { console.warn('smart capture', e); }
  }
  function processFrame() {
    const W = vid.videoWidth, H = vid.videoHeight;
    eng.s.bufferMax = Math.max(4, Math.min(45, Math.floor(BUFFER_BYTES / (W * H * 4))));
    // 관심 영역을 ≤480px 로 축소해 선명도 계산
    const r = CV.roiRect(W, H, S.roi / 100), s = Math.min(1, 480 / Math.max(r.w, r.h));
    const ww = Math.max(8, Math.round(r.w * s)), wh = Math.max(8, Math.round(r.h * s));
    if (work.width !== ww || work.height !== wh) { work.width = ww; work.height = wh; }
    const wc = ctx2d(work);
    wc.drawImage(vid, r.x, r.y, r.w, r.h, 0, 0, ww, wh);
    const m = CV.measure(wc.getImageData(0, 0, ww, wh));
    const ts = (performance.now() - t0) / 1000;
    const res = eng.push(m, ts, S.best || S.auto !== 'off' ? copyFrame(vid, W, H) : null);
    lastRes = res;
    tick++;
    if (S.peak && tick % 2 === 0) peakImg = peakingImage(W, H);
    drawOverlay(res, W, H, r);
    if (tick % 5 === 0) showQuality(res.q);
    if (res.triggered) autoTrigger();
  }
  function peakingImage(W, H) {
    const s = Math.min(1, 640 / Math.max(W, H)), w = Math.round(W * s), h = Math.round(H * s);
    if (pk.width !== w || pk.height !== h) { pk.width = w; pk.height = h; }
    const c = ctx2d(pk);
    c.drawImage(vid, 0, 0, w, h);
    const mask = CV.peakingMask(c.getImageData(0, 0, w, h), S.sens);
    return maskCanvas(mask, w, h, PEAK_RGB[S.color] || PEAK_RGB.red, 230);
  }
  function maskCanvas(mask, w, h, rgb, alpha) {
    const c = newCanvas(w, h), x = c.getContext('2d'), im = x.createImageData(w, h), d = im.data;
    for (let i = 0; i < mask.length; i++) if (mask[i]) { const o = i * 4; d[o] = rgb[0]; d[o + 1] = rgb[1]; d[o + 2] = rgb[2]; d[o + 3] = alpha; }
    x.putImageData(im, 0, 0);
    return c;
  }
  function clearOverlay() {
    const c = ov.getContext('2d');
    c.setTransform(1, 0, 0, 1, 0, 0); c.clearRect(0, 0, ov.width, ov.height);
    delete ov.dataset.drawn;
  }
  function chip(c, text, color, xRight, y, dpr) {
    c.font = `600 ${12 * dpr}px sans-serif`;
    const w = c.measureText(text).width + 18 * dpr, h = 24 * dpr, x = xRight - w;
    c.fillStyle = 'rgba(8,11,16,.72)'; c.strokeStyle = color; c.lineWidth = 1.2 * dpr;
    c.beginPath(); c.roundRect ? c.roundRect(x, y, w, h, 6 * dpr) : c.rect(x, y, w, h); c.fill(); c.stroke();
    c.fillStyle = color; c.textBaseline = 'middle'; c.fillText(text, x + 9 * dpr, y + h / 2);
    return y + h + 6 * dpr;
  }
  function drawOverlay(res, W, H, r) {
    const dpr = window.devicePixelRatio || 1, rect = ov.getBoundingClientRect();
    const cw = Math.max(1, Math.round(rect.width * dpr)), ch = Math.max(1, Math.round(rect.height * dpr));
    if (ov.width !== cw || ov.height !== ch) { ov.width = cw; ov.height = ch; }
    const c = ov.getContext('2d');
    c.setTransform(1, 0, 0, 1, 0, 0); c.clearRect(0, 0, cw, ch);
    const k = Math.min(cw / W, ch / H), ox = (cw - W * k) / 2, oy = (ch - H * k) / 2;   // object-fit: contain
    if (S.peak && peakImg) { c.imageSmoothingEnabled = false; c.drawImage(peakImg, ox, oy, W * k, H * k); c.imageSmoothingEnabled = true; }
    c.setLineDash([8 * dpr, 6 * dpr]); c.lineWidth = 1.4 * dpr; c.strokeStyle = 'rgba(255,255,255,.6)';
    const guide = $('cat-guide').checked;
    if (guide) {                                         // 백내장 모드: 화면 중앙 슬릿 위치 띠
      const gw = Math.max(8, W / 40);
      c.strokeStyle = 'rgba(201,179,255,.85)';
      c.strokeRect(ox + (W / 2 - gw / 2) * k, oy + H * 0.08 * k, gw * k, H * 0.84 * k);
    } else c.strokeRect(ox + r.x * k, oy + r.y * k, r.w * k, r.h * k);
    c.setLineDash([]);
    const rel = res.rel, col = rel >= 85 ? '#3ccf7a' : rel >= 60 ? '#ffd08a' : '#f0524f';
    let y = 10 * dpr;
    const xr = cw - 10 * dpr;
    y = chip(c, `초점 ${Math.round(rel)}`, col, xr, y, dpr);
    if (S.auto === 'freeze') y = chip(c, 'AUTO FREEZE', '#33c2b1', xr, y, dpr);
    if (S.auto === 'save') y = chip(c, 'AUTO SAVE', '#33c2b1', xr, y, dpr);
    if (res.m.blink) y = chip(c, '깜빡임', '#ffd08a', xr, y, dpr);
    if (guide) {
      y = chip(c, '백내장 모드 · 슬릿을 중앙 띠에, 45°', '#c9b3ff', xr, y, dpr);
      if (lastCond) chip(c, `지난 검사: ${lastCond}`, '#c9b3ff', xr, y, dpr);
    }
    ov.dataset.drawn = '1';
  }
  function showQuality(q) {
    for (const k of ['focus', 'exposure', 'stability', 'reflection']) {
      $(`sm-q-${k}`).value = q ? q[k] : 0;
      $(`sm-v-${k}`).textContent = q ? String(q[k]) : '-';
    }
    const el = $('sm-advice');
    if (!q) { el.textContent = 'LIVE 화면에서 영상이 들어오면 점검을 시작합니다.'; el.className = 'sm-advice'; return; }
    el.textContent = q.ok ? '촬영 조건 좋음 ✓' : q.issues.join('\n');
    el.className = 'sm-advice ' + (q.ok ? 'ok' : 'warn');
  }
  const stamp = () => new Date().toTimeString().slice(0, 8);
  async function autoTrigger() {
    if (!live()) return;
    if (S.auto === 'freeze') {
      const f = bestFrame(true);
      if (f) { Pro.toggleCapture(f); $('sm-log').textContent = `자동 정지 ${stamp()} — 확인 후 SAVE 또는 RESUME`; clearOverlay(); }
      return;
    }
    const p = App.currentPatient();
    if (S.auto !== 'save' || saving) return;
    if (!p) { $('sm-log').textContent = '자동 저장: 환자를 먼저 선택하세요.'; return; }
    const f = bestFrame(true);
    if (!f) return;
    saving = true;
    try {
      App.sfx('shutter');
      const blob = await new Promise((r) => f.toBlob(r, 'image/png'));
      if (blob && await App.persistCapture(p, 'photo', blob, 'png', $('pro-eye').value, null, '자동 촬영', { silent: true })) {
        $('sm-log').textContent = `자동 저장 ${stamp()}`;
        await Pro.reload(true);
        App.renderThumbs();
      }
    } finally { saving = false; }
  }
  function freezeBestNow() {
    if (P.mode !== 'live') return;
    if (P.frozen) Pro.toggleCapture();                   // 정지 해제 후 다시
    const f = bestFrame(true) || Pro.grabVideo();
    if (f) Pro.toggleCapture(f);
  }

  // ================= 분석: 공통 =================
  /** 뷰어 영상(회전·자르기 반영, 보정 전)을 작업 크기로 → { im, scale } */
  function workImage(v, maxSide = 1200) {
    const b = v.base;
    if (!b) return null;
    const s = Math.min(1, maxSide / Math.max(b.width, b.height)), w = Math.max(1, Math.round(b.width * s)), h = Math.max(1, Math.round(b.height * s));
    const c = newCanvas(w, h), x = ctx2d(c);
    x.drawImage(b, 0, 0, w, h);
    return { im: x.getImageData(0, 0, w, h), scale: s, canvas: c };
  }
  function circleRoi(v) {
    const cs = v.ann.filter((a) => a.type === 'circle');
    if (!cs.length) return null;
    const a = cs[cs.length - 1];
    return { x1: a.x1, y1: a.y1, x2: a.x2, y2: a.y2 };
  }
  const A = { last: null, tag: '', cat: null, blink: 0 };
  function showMask(v, mask, w, h, rgb) {
    v.aOverlay = maskCanvas(mask, w, h, rgb, 150);
    v.draw();
  }
  function curCap() { return P.mode === 'single' ? P.caps[P.idx] : null; }
  function needSingle() {
    if (P.mode !== 'single' || !V.single.base) { App.toast('1화면에서 영상을 여세요.', 'error'); return false; }
    return true;
  }

  function updateTag() {
    const w = V.single.base ? workImage(V.single, 200) : null;
    A.tag = w ? CV.classifyIllumination(w.im) : '';
    $('an-tag').textContent = w ? `추정 조명: ${CV.ILLUMINATION_LABELS[A.tag]}  (색 분포 기준 · 기록 시 함께 저장)` : '1화면에서 영상을 열면 자동으로 추정합니다.';
  }
  function measureFluo() {
    if (!needSingle()) return null;
    const v = V.single, w = workImage(v), roi = circleRoi(v);
    const r = CV.fluorescein(w.im, roi, w.scale, P.pxmm);
    const mm = r.areaMm2 != null ? `, ${r.areaMm2.toFixed(2)} mm²` : ' (눈금 보정 시 mm²)';
    A.last = { kind: 'fluorescein', value: r.ratio, text: `형광 염색 면적 ${r.ratio.toFixed(1)}% (${roi ? '측정 영역' : '전체'})${mm}` };
    showMask(v, r.mask, w.im.width, w.im.height, [52, 211, 153]);
    $('an-result').textContent = A.last.text + '\n(표시 레이어는 저장본에 들어가지 않습니다)';
    return r;
  }
  function measureRed() {
    if (!needSingle()) return null;
    const v = V.single, w = workImage(v), roi = circleRoi(v);
    const r = CV.redness(w.im, roi, w.scale);
    A.last = { kind: 'redness', value: r.index, text: `충혈 지수 ${Math.round(r.index)}/100 · 혈관 화소 ${r.vesselPct.toFixed(1)}% (${roi ? '측정 영역' : '전체'})` };
    showMask(v, r.mask, w.im.width, w.im.height, [255, 59, 48]);
    $('an-result').textContent = A.last.text + '\n(표시 레이어는 저장본에 들어가지 않습니다)';
    return r;
  }
  async function appendNote(entry) {
    const c = curCap();
    if (!c) return;
    const tag = CV.ILLUMINATION_LABELS[A.tag];
    const e = tag ? `[${tag}] ${entry}` : entry;
    await Pro.setComment(c.note ? `${c.note} | ${e}` : e);
  }
  function clearAnalysis() {
    for (const v of [V.single]) { v.aOverlay = null; v.draw(); }
    A.last = null; A.cat = null;
    $('an-result').textContent = '-'; $('cat-result').textContent = '-';
  }

  // ================= 분석: 경과 비교 =================
  function setGhost(pct) {
    $('o-an-ghost').textContent = pct > 0 ? `${pct}%` : '끄기';
    if (P.mode !== 'compare' || !V.left.proc || !V.right.proc) return;
    V.right.ghost = pct > 0 || A.blink ? { cv: V.left.proc, alpha: pct / 100 } : null;
    V.right.draw();
  }
  function alignPair() {
    if (P.mode !== 'compare' || !V.left.base || !V.right.base) { App.toast('비교 화면에서 쓰세요.', 'error'); return null; }
    const ref = V.right.base, mov = V.left.base;
    const s = Math.min(1, 480 / Math.max(ref.width, ref.height)), w = Math.max(8, Math.round(ref.width * s)), h = Math.max(8, Math.round(ref.height * s));
    const a = newCanvas(w, h), b = newCanvas(w, h);
    ctx2d(a).drawImage(ref, 0, 0, w, h); ctx2d(b).drawImage(mov, 0, 0, w, h);
    const r = CV.alignShift(ctx2d(b).getImageData(0, 0, w, h), ctx2d(a).getImageData(0, 0, w, h));
    // 이전 영상을 현재 영상 크기로 맞춘 뒤 회전·이동 (smartcv.warp 와 같은 변환)
    const W = ref.width, H = ref.height, out = newCanvas(W, H), x = out.getContext('2d');
    x.fillStyle = '#000'; x.fillRect(0, 0, W, H);
    if (r.ok) { x.translate(r.dx * W + W / 2, r.dy * H + H / 2); x.rotate(r.angle * Math.PI / 180); x.drawImage(mov, -W / 2, -H / 2, W, H); }
    else x.drawImage(mov, 0, 0, W, H);
    const cap = V.left.caption;
    V.left.setSource(out);
    V.left.caption = cap.includes('정렬됨') ? cap : `${cap}  ·  정렬됨`; V.left.draw();
    $('an-cmp').textContent = r.ok ? `이전 영상을 정렬했습니다 (회전 ${r.angle.toFixed(1)}°, 이동 ${Math.round(r.dx * W)}, ${Math.round(r.dy * H)} px)`
      : '정렬 실패 — 두 영상의 겹치는 구조가 부족합니다 (크기만 맞춤).';
    setGhost(Number($('an-ghost').value));
    return r;
  }
  function setBlink(on) {
    clearInterval(A.blink); A.blink = 0;
    const b = $('an-blink');
    if (on && P.mode === 'compare' && V.left.proc && V.right.proc) {
      let show = false;
      V.right.ghost = { cv: V.left.proc, alpha: 0 };
      A.blink = setInterval(() => {
        if (P.mode !== 'compare') { setBlink(false); return; }
        show = !show;
        V.right.ghost = { cv: V.left.proc, alpha: show ? 1 : 0 }; V.right.draw();
      }, 500);
      b.setAttribute('aria-pressed', 'true');
    } else {
      b.setAttribute('aria-pressed', 'false');
      setGhost(Number($('an-ghost').value));
    }
  }

  // ================= 분석: 백내장 수정체 혼탁 지수 =================
  let lastCond = '';
  async function measurements(kind, eye) {
    const p = App.currentPatient();
    if (!p) return [];
    const q = new URLSearchParams({ patient_id: p.id });
    if (kind) q.set('kind', kind);
    if (eye && eye !== 'NA') q.set('eye', eye);
    try { return await App.api(`/measurements?${q}`); } catch (_) { return []; }
  }
  async function deltaText(kind, value) {
    const c = curCap();
    const prev = (await measurements(kind, c && c.eye)).filter((m) => !c || m.capture_id !== c.id);
    if (!prev.length) return '';
    const last = prev[prev.length - 1], d = value - last.value;
    return `\n지난 검사(${String(last.measured_at).slice(0, 10)}) 대비 ${d >= 0 ? '+' : ''}${Math.round(d)}`;
  }
  async function measureNuclear() {
    if (!needSingle()) return null;
    const v = V.single, w = workImage(v), r = CV.nuclear(w.im, circleRoi(v), w.scale);
    A.cat = { kind: 'nuclear', r };
    if (!r.lensBand) {
      $('cat-result').textContent = "슬릿 띠를 찾지 못했습니다 — 슬릿 단면(광학 절단면) 사진인지, '원'으로 측정 영역을 좁혀 보세요.";
      return r;
    }
    const ref = r.hasCornea ? '각막 기준' : '각막 띠 없음 · 절대 밝기 참고값';
    A.cat.text = `핵 혼탁 지수 ${Math.round(r.index)} (수정체/각막 밝기비 ${r.ratio.toFixed(2)}, ${ref})`;
    showMask(v, r.mask, w.im.width, w.im.height, [201, 179, 255]);
    $('cat-result').textContent = A.cat.text + await deltaText('nuclear', r.index);
    return r;
  }
  async function measureCortical() {
    if (!needSingle()) return null;
    const v = V.single, pupil = circleRoi(v);
    if (!pupil) { $('cat-result').textContent = "편집 탭 '원' 도구로 동공을 먼저 표시하세요 (역조명 사진)."; return null; }
    const w = workImage(v), r = CV.cortical(w.im, pupil, w.scale, P.pxmm);
    A.cat = { kind: 'cortical', r };
    const d = r.pupilMm != null ? `동공 ${r.pupilMm.toFixed(1)} mm` : `동공 ${Math.round(r.pupilPx)} px`;
    A.cat.text = `피질 혼탁 지수 ${Math.round(r.index)} (어두운 얼룩 ${r.areaPct.toFixed(1)}%, ${d}${r.smallPupil ? ' · 산동 부족 → 참고용' : ''})`;
    showMask(v, r.mask, w.im.width, w.im.height, [255, 59, 48]);
    $('cat-result').textContent = A.cat.text + await deltaText('cortical', r.index);
    return r;
  }
  function locsValues() {
    const o = {};
    for (const k of ['NO', 'NC', 'C', 'P']) { const v = parseFloat($(`cat-locs-${k}`).value); if (v > 0) o[k] = v; }
    return o;
  }
  async function recordCataract() {
    const c = curCap(), p = App.currentPatient();
    if (!A.cat || !A.cat.text || !c || !p) { App.toast("먼저 '핵 · 슬릿' 또는 '피질 · 역조명'을 측정하세요.", 'error'); return null; }
    const { kind, r } = A.cat;
    const detail = {};
    for (const [k, v] of Object.entries(r)) if (v != null && typeof v !== 'object') detail[k] = typeof v === 'number' ? Math.round(v * 1e4) / 1e4 : v;
    const body = { patient_id: p.id, capture_id: c.id, eye: c.eye || 'NA', kind, value: r.index, detail,
      locs: locsValues(), conditions: $('cat-cond').value.trim() };
    let m;
    try { m = await App.api('/measurements', { method: 'POST', body: JSON.stringify(body) }); }
    catch (e) { App.toast('측정 기록 저장 실패: ' + e.message, 'error'); return null; }
    const parts = [A.cat.text];
    if (m.conditions) parts.push(`조건: ${m.conditions}`);
    const lk = Object.entries(m.locs || {});
    if (lk.length) parts.push('LOCS ' + lk.map(([k, v]) => `${k}${v}`).join(' '));
    await appendNote(parts.join(' · '));
    lastCond = m.conditions || lastCond;
    await drawTrend();
    $('cat-result').textContent = A.cat.text + '\n측정 기록에 저장했습니다.';
    return m;
  }
  async function drawTrend() {
    const cv = $('cat-trend'), info = $('cat-trend-info');
    const dpr = window.devicePixelRatio || 1, W = Math.round(cv.clientWidth * dpr) || 236, H = Math.round(cv.clientHeight * dpr) || 84;
    cv.width = W; cv.height = H;
    const x = cv.getContext('2d');
    x.fillStyle = '#0b1220'; x.fillRect(0, 0, W, H);
    const c = curCap(), eye = c && c.eye !== 'NA' ? c.eye : null;
    const all = App.currentPatient() ? await measurements(null, eye) : [];
    const series = { nuclear: all.filter((m) => m.kind === 'nuclear'), cortical: all.filter((m) => m.kind === 'cortical') };
    const n = series.nuclear.length + series.cortical.length;
    if (!n) { info.textContent = '측정 기록이 없습니다 (같은 안구 · 같은 촬영 조건끼리 비교)'; return { n: 0 }; }
    x.strokeStyle = '#334155'; x.lineWidth = 1;
    for (const f of [0.25, 0.5, 0.75]) { x.beginPath(); x.moveTo(0, H * f); x.lineTo(W, H * f); x.stroke(); }
    for (const [kind, col] of [['nuclear', '#c9b3ff'], ['cortical', '#f87171']]) {
      const ms = series[kind];
      if (!ms.length) continue;
      const k = Math.max(1, ms.length - 1);
      const pts = ms.map((m, i) => [8 * dpr + i * (W - 16 * dpr) / k, H - 6 * dpr - (H - 12 * dpr) * Math.min(100, m.value) / 100]);
      x.strokeStyle = col; x.fillStyle = col; x.lineWidth = 2 * dpr;
      x.beginPath(); pts.forEach(([px, py], i) => (i ? x.lineTo(px, py) : x.moveTo(px, py))); x.stroke();
      for (const [px, py] of pts) { x.beginPath(); x.arc(px, py, 3 * dpr, 0, Math.PI * 2); x.fill(); }
    }
    const last = Object.entries(series).filter(([, v]) => v.length).map(([k, v]) => {
      const m = v[v.length - 1];
      return `${k === 'nuclear' ? '핵' : '피질'} ${Math.round(m.value)} (${String(m.measured_at).slice(0, 10)})`;
    });
    info.textContent = `${last.join('  ·  ')}  ·  기록 ${n}건${eye ? ' · ' + eye : ''}`;
    return { n };
  }
  async function refreshCond() {
    const eye = $('pro-eye').value;
    for (const kind of ['nuclear', 'cortical']) {
      const ms = await measurements(kind, eye);
      const withCond = ms.filter((m) => m.conditions);
      if (withCond.length) { lastCond = withCond[withCond.length - 1].conditions; return lastCond; }
    }
    lastCond = '';
    return lastCond;
  }

  // ================= 이벤트 =================
  syncSettings();
  for (const id of ['sm-auto', 'sm-roi', 'sm-best', 'sm-peak', 'sm-sens', 'sm-color']) {
    $(id).addEventListener(id === 'sm-roi' ? 'input' : 'change', readSettings);
  }
  $('sm-best-now').addEventListener('click', freezeBestNow);
  $('an-fluo').addEventListener('click', measureFluo);
  $('an-red').addEventListener('click', measureRed);
  $('an-note').addEventListener('click', () => { if (A.last) appendNote(A.last.text); else App.toast('먼저 측정하세요.', 'error'); });
  $('an-clear').addEventListener('click', clearAnalysis);
  $('an-ghost').addEventListener('input', (e) => setGhost(Number(e.target.value)));
  $('an-align').addEventListener('click', alignPair);
  $('an-blink').addEventListener('click', () => setBlink(!A.blink));
  $('cat-nuclear').addEventListener('click', measureNuclear);
  $('cat-cortical').addEventListener('click', measureCortical);
  $('cat-record').addEventListener('click', recordCataract);
  $('cat-guide').addEventListener('change', refreshCond);
  $('pro-eye').addEventListener('change', () => { if ($('cat-guide').checked) refreshCond(); });
  document.addEventListener('slit:patient', () => { lastCond = ''; if ($('cat-guide').checked) refreshCond(); drawTrend(); });
  document.addEventListener('slit:pro-image', () => {
    A.last = null; A.cat = null;
    $('an-result').textContent = '-'; $('cat-result').textContent = '-';
    for (const k of ['NO', 'NC', 'C', 'P']) $(`cat-locs-${k}`).value = '';   // LOCS 는 영상별 입력 (촬영 조건 메모는 유지)
    updateTag(); drawTrend();
  });
  document.addEventListener('slit:pro-mode', (e) => {
    const mode = e.detail;
    if (mode !== 'live') { eng.reset(); clearOverlay(); showQuality(null); }
    if (mode === 'compare') { $('an-cmp').textContent = ''; setGhost(Number($('an-ghost').value)); }
    else if (A.blink) setBlink(false);
    const single = mode === 'single', cmp = mode === 'compare';
    for (const id of ['an-fluo', 'an-red', 'an-note', 'an-clear', 'cat-nuclear', 'cat-cortical', 'cat-record']) $(id).disabled = !single;
    for (const id of ['an-ghost', 'an-align', 'an-blink']) $(id).disabled = !cmp;
    if (mode === 'live' && $('cat-guide').checked) refreshCond();
  });
  requestAnimationFrame(loop);

  // 자동화 테스트·디버깅용 핸들
  window.SlitSmart = { settings: S, engine: eng, bestFrame, freezeBestNow, measureFluo, measureRed, measureNuclear,
    measureCortical, recordCataract, drawTrend, alignPair, setGhost, setBlink, clearAnalysis, refreshCond,
    state: A, lastResult: () => lastRes };
})();
