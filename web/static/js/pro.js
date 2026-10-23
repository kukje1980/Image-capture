/* 슬릿램프 영상 시스템 — Pro 모드 (전문가용 영상 검토, VK-2 스타일 워크플로)
 *
 *  LIVE     실시간 영상. CAPTURE(Space)로 정지/재개, SAVE로 환자 DB 저장
 *  1화면    단일 영상. PREV/NEXT(←/→), 휠 확대·드래그 이동, 보정, 텍스트/화살표 주석
 *  MULTI    16장(4×4) / 36장(6×6) 그리드. 클릭 = 비교 선택(최대 2), 더블클릭 = 1화면
 *  비교     선택한 2장 좌우 비교. 확대·이동 동기화, 보정 동일 적용
 *  보정본 저장 · 코멘트 · 환자정보 · 인쇄/PDF(A4 보고서)
 *
 * app.js 의 window.SlitApp API 와 'slit:patient' 이벤트에 의존한다.
 */
(() => {
  const App = window.SlitApp;
  if (!App) return;
  const $ = (id) => document.getElementById(id);
  const EYE_KO = { OD: '우안(OD)', OS: '좌안(OS)', OU: '양안(OU)' };
  const IDENTITY = { brightness: 0, contrast: 1, gamma: 1, negative: false, channel: 'rgb' };

  const P = {
    on: false, mode: 'multi', patient: null, caps: [], idx: -1,
    per: 16, page: 0, sel: [], adj: { ...IDENTITY }, tool: 'pan', frozen: false, pair: [null, null],
  };

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // ================= 이미지 보정 (LUT) =================
  const isIdentity = (a) => a.brightness === 0 && a.contrast === 1 && a.gamma === 1 && !a.negative && a.channel === 'rgb';
  function buildLut(a) {
    const lut = new Uint8ClampedArray(256);
    for (let v = 0; v < 256; v++) {
      let x = (v - 127.5) * a.contrast + 127.5 + a.brightness;
      x = Math.min(255, Math.max(0, x));
      if (a.gamma !== 1) x = 255 * Math.pow(x / 255, 1 / a.gamma);
      if (a.negative) x = 255 - x;
      lut[v] = x;
    }
    return lut;
  }
  function processed(src, a) {
    const w = src.naturalWidth || src.videoWidth || src.width;
    const h = src.naturalHeight || src.videoHeight || src.height;
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const ctx = c.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(src, 0, 0, w, h);
    if (!isIdentity(a)) {
      const im = ctx.getImageData(0, 0, w, h), d = im.data, lut = buildLut(a);
      for (let i = 0; i < d.length; i += 4) {
        let r = d[i], g = d[i + 1], b = d[i + 2];
        if (a.channel === 'green') { r = g; b = g; }                       // Red-free
        else if (a.channel === 'gray') { r = g = b = (r * 0.299 + g * 0.587 + b * 0.114) | 0; }
        d[i] = lut[r]; d[i + 1] = lut[g]; d[i + 2] = lut[b];
      }
      ctx.putImageData(im, 0, 0);
    }
    return c;
  }

  function drawArrow(ctx, a, s) {
    const { x1, y1, x2, y2 } = a;
    ctx.strokeStyle = '#facc15'; ctx.fillStyle = '#facc15';
    ctx.lineWidth = 3 * s; ctx.lineCap = 'round';
    ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
    const ang = Math.atan2(y2 - y1, x2 - x1), L = 18 * s;
    ctx.beginPath();
    ctx.moveTo(x2, y2);
    ctx.lineTo(x2 - L * Math.cos(ang - Math.PI / 7), y2 - L * Math.sin(ang - Math.PI / 7));
    ctx.lineTo(x2 - L * Math.cos(ang + Math.PI / 7), y2 - L * Math.sin(ang + Math.PI / 7));
    ctx.closePath(); ctx.fill();
  }

  // ================= 캔버스 뷰어 =================
  class Viewer {
    constructor(canvas) {
      this.cv = canvas; this.ctx = canvas.getContext('2d');
      this.src = null; this.proc = null; this.ann = []; this.caption = ''; this.peer = null;
      this.zoom = 1; this.px = 0; this.py = 0; this.autofit = true; this.drag = null; this.temp = null;
      canvas.addEventListener('wheel', (e) => this.onWheel(e), { passive: false });
      canvas.addEventListener('pointerdown', (e) => this.onDown(e));
      canvas.addEventListener('pointermove', (e) => this.onMove(e));
      canvas.addEventListener('pointerup', (e) => this.onUp(e));
      canvas.addEventListener('pointercancel', () => { this.drag = null; this.temp = null; this.draw(); });
      new ResizeObserver(() => this.resize()).observe(canvas);
    }
    get iw() { return this.proc ? this.proc.width : 0; }
    get ih() { return this.proc ? this.proc.height : 0; }
    setSource(src, keepAnn = false) {
      this.src = src;
      if (!keepAnn) this.ann = [];
      this.reprocess();
      this.autofit = true; this.fit(); this.draw();
    }
    setAdjust(a) { this.reprocess(a); this.draw(); }
    reprocess(a = P.adj) { this.proc = this.src ? processed(this.src, a) : null; }
    resize() {
      const r = this.cv.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
      const w = Math.max(1, Math.round(r.width * dpr)), h = Math.max(1, Math.round(r.height * dpr));
      if (this.cv.width !== w || this.cv.height !== h) { this.cv.width = w; this.cv.height = h; }
      if (this.autofit) this.fit();
      this.draw();
    }
    fit() {
      if (!this.proc) return;
      const W = this.cv.width, H = this.cv.height;
      this.zoom = Math.min(W / this.iw, H / this.ih);
      this.px = (W - this.iw * this.zoom) / 2; this.py = (H - this.ih * this.zoom) / 2;
    }
    resetView() { this.autofit = true; this.fit(); this.draw(); }
    zoomAt(f, cx, cy, fromPeer = false) {
      if (!this.proc) return;
      if (cx == null) { cx = this.cv.width / 2; cy = this.cv.height / 2; }
      this.autofit = false;
      this.px = cx - (cx - this.px) * f; this.py = cy - (cy - this.py) * f; this.zoom *= f;
      this.draw();
      if (this.peer && !fromPeer) this.peer.zoomAt(f, cx, cy, true);
    }
    pan(dx, dy, fromPeer = false) {
      this.autofit = false; this.px += dx; this.py += dy; this.draw();
      if (this.peer && !fromPeer) this.peer.pan(dx, dy, true);
    }
    toImg(e) {
      const r = this.cv.getBoundingClientRect(), k = this.cv.width / r.width;
      const sx = (e.clientX - r.left) * k, sy = (e.clientY - r.top) * k;
      return { x: (sx - this.px) / this.zoom, y: (sy - this.py) / this.zoom, sx, sy };
    }
    onWheel(e) {
      if (!this.proc) return;
      e.preventDefault();
      const p = this.toImg(e);
      this.zoomAt(e.deltaY < 0 ? 1.25 : 0.8, p.sx, p.sy);
    }
    onDown(e) {
      if (!this.proc || e.button !== 0) return;
      const p = this.toImg(e);
      if (P.tool === 'text') {
        const t = window.prompt('텍스트 주석:');
        if (t && t.trim()) { this.ann.push({ type: 'text', x: p.x, y: p.y, text: t.trim() }); this.draw(); }
        return;
      }
      this.cv.setPointerCapture(e.pointerId);
      if (P.tool === 'arrow') { this.drag = { arrow: true }; this.temp = { x1: p.x, y1: p.y, x2: p.x, y2: p.y }; return; }
      this.drag = { sx: p.sx, sy: p.sy };
      this.cv.style.cursor = 'grabbing';
    }
    onMove(e) {
      if (!this.drag) return;
      const p = this.toImg(e);
      if (this.drag.arrow) { this.temp.x2 = p.x; this.temp.y2 = p.y; this.draw(); return; }
      this.pan(p.sx - this.drag.sx, p.sy - this.drag.sy);
      this.drag = { sx: p.sx, sy: p.sy };
    }
    onUp() {
      if (!this.drag) return;
      if (this.drag.arrow && this.temp) {
        const t = this.temp;
        if (Math.hypot(t.x2 - t.x1, t.y2 - t.y1) > 4) this.ann.push({ type: 'arrow', ...t });
        this.temp = null;
      }
      this.drag = null;
      this.cv.style.cursor = P.tool === 'pan' ? 'grab' : 'crosshair';
      this.draw();
    }
    annScale() { return Math.max(1, Math.max(this.iw, this.ih) / 900); }
    drawAnn(ctx, s) {
      for (const a of this.ann) {
        if (a.type === 'text') {
          ctx.font = `bold ${Math.round(26 * s)}px "Malgun Gothic","Apple SD Gothic Neo","Noto Sans KR",sans-serif`;
          ctx.textBaseline = 'top'; ctx.lineJoin = 'round';
          ctx.lineWidth = 4 * s; ctx.strokeStyle = '#000'; ctx.strokeText(a.text, a.x, a.y);
          ctx.fillStyle = '#facc15'; ctx.fillText(a.text, a.x, a.y);
        } else drawArrow(ctx, a, s);
      }
      if (this.temp) drawArrow(ctx, this.temp, s);
    }
    draw() {
      const c = this.ctx, W = this.cv.width, H = this.cv.height, dpr = window.devicePixelRatio || 1;
      c.setTransform(1, 0, 0, 1, 0, 0);
      c.fillStyle = '#000'; c.fillRect(0, 0, W, H);
      if (!this.proc) {
        c.fillStyle = '#64748b'; c.font = `${14 * dpr}px sans-serif`;
        c.textAlign = 'center'; c.textBaseline = 'middle'; c.fillText('영상 없음', W / 2, H / 2); c.textAlign = 'left';
        return;
      }
      c.save();
      c.translate(this.px, this.py); c.scale(this.zoom, this.zoom);
      c.imageSmoothingQuality = 'high';
      c.drawImage(this.proc, 0, 0);
      this.drawAnn(c, this.annScale());
      c.restore();
      if (this.caption) {
        c.font = `${12 * dpr}px sans-serif`; c.textBaseline = 'middle';
        const w = c.measureText(this.caption).width + 16 * dpr;
        c.fillStyle = 'rgba(0,0,0,.6)'; c.fillRect(8 * dpr, 8 * dpr, w, 22 * dpr);
        c.fillStyle = '#e2e8f0'; c.fillText(this.caption, 16 * dpr, 19 * dpr);
      }
    }
    /** 보정 + 주석을 원본 해상도로 합성 */
    renderFull() {
      if (!this.proc) return null;
      const c = document.createElement('canvas');
      c.width = this.iw; c.height = this.ih;
      const x = c.getContext('2d');
      x.drawImage(this.proc, 0, 0);
      const t = this.temp; this.temp = null;
      this.drawAnn(x, this.annScale());
      this.temp = t;
      return c;
    }
  }

  const V = { single: new Viewer($('pcv-single')), left: new Viewer($('pcv-left')), right: new Viewer($('pcv-right')) };
  V.left.peer = V.right; V.right.peer = V.left;

  // ================= 데이터 =================
  const imgCache = new Map();
  function loadImage(url) {
    if (imgCache.has(url)) return imgCache.get(url);
    const p = new Promise((res, rej) => {
      const im = new Image();
      im.onload = () => res(im);
      im.onerror = () => rej(new Error('이미지를 불러오지 못했습니다.'));
      im.src = url;
    });
    imgCache.set(url, p);
    p.catch(() => imgCache.delete(url));
    return p;
  }

  const pageCount = () => Math.max(1, Math.ceil(P.caps.length / P.per));

  async function reload(selectLast = false) {
    const p = App.currentPatient() || null;
    const changed = !p || !P.patient || p.id !== P.patient.id;
    P.patient = p;
    if (!p) P.caps = [];
    else {
      try { P.caps = (await App.api(`/captures?patient_id=${p.id}&order=asc`)).filter((c) => c.media_type === 'photo'); }
      catch (e) { App.toast('영상 목록 조회 실패: ' + e.message, 'error'); P.caps = []; }
    }
    if (changed) P.sel = [];
    P.sel = P.sel.filter((i) => i < P.caps.length);
    if (selectLast || changed || P.idx < 0 || P.idx >= P.caps.length) P.idx = P.caps.length - 1;
    P.page = (selectLast || changed) ? pageCount() - 1 : Math.min(P.page, pageCount() - 1);
    updateInfo();
    renderMulti();
    if (P.mode === 'single') await showCurrent();
    if (P.mode === 'compare' && changed) await setMode('multi');
    updateSide();
  }

  function caption(c, n) {
    const t = [c.captured_at, EYE_KO[c.eye] || '', c.note || ''].filter(Boolean).join('  ·  ');
    return n ? `[${n}/${P.caps.length}]  ${t}` : t;
  }

  function updateInfo() {
    const p = P.patient, el = $('pro-info');
    if (!p) { el.textContent = '환자를 선택하세요'; return; }
    const sex = { M: '남', F: '여', O: '기타' }[p.sex] || '';
    const bits = [`<b>${esc(p.name)}</b> (${esc(p.chart_no || '-')})`];
    if (sex) bits.push(sex);
    if (p.birth_date) bits.push(esc(p.birth_date));
    bits.push(`진단명: <b>${esc(p.diagnosis || '-')}</b>`);
    bits.push(`담당의: ${esc(p.doctor || '-')}`);
    bits.push(`영상 ${P.caps.length}장`);
    el.innerHTML = bits.join('&nbsp;&nbsp;·&nbsp;&nbsp;');
  }

  function updateSide() {
    const el = $('pro-imginfo'), c = P.caps[P.idx];
    if (P.mode === 'single' && c) {
      el.textContent = `${P.idx + 1} / ${P.caps.length}\n촬영: ${c.captured_at}\n안구: ${EYE_KO[c.eye] || '미지정'}\n코멘트: ${c.note || '-'}`;
    } else if (P.mode === 'multi') {
      el.textContent = `페이지 ${P.page + 1} / ${pageCount()}  ·  ${P.per}장 보기\n전체 ${P.caps.length}장  ·  선택 ${P.sel.length}장`;
    } else if (P.mode === 'compare') {
      el.textContent = '2장 비교 (확대·이동 동기화)\n' +
        P.pair.filter(Boolean).map((x, i) => `${i ? '우' : '좌'}: ${x.captured_at} ${EYE_KO[x.eye] || ''}`).join('\n');
    } else if (P.mode === 'live') {
      el.textContent = 'LIVE — ' + (P.frozen ? '정지됨 · SAVE로 저장' : '실시간');
    } else el.textContent = '영상이 없습니다';
    $('pro-selinfo').textContent = P.sel.length
      ? `선택 ${P.sel.length}/2 — 2장이면 '비교'를 누르세요.`
      : "MULTI에서 영상 2장을 클릭해 선택한 뒤 '비교'를 누르세요.";
  }

  // ================= 모드 =================
  async function setMode(mode) {
    if (mode === 'compare' && !(await prepareCompare())) mode = P.mode === 'compare' ? 'multi' : P.mode;
    P.mode = mode;
    document.querySelectorAll('#pro-display .pro-view').forEach((v) => v.classList.toggle('on', v.dataset.view === mode));
    document.querySelectorAll('#pro-modes .pbtn').forEach((b) => b.classList.toggle('on', b.dataset.mode === mode));
    const live = mode === 'live';
    for (const id of ['pro-capture', 'pro-save', 'pro-eye']) $(id).disabled = !live;
    $('pro-per').disabled = mode !== 'multi';
    const ann = mode === 'single' || mode === 'compare';
    document.querySelectorAll('#pro-tools .pbtn').forEach((b) => { b.disabled = !ann; });
    $('pro-comment').disabled = mode !== 'single';
    if (mode === 'single') { await showCurrent(); V.single.resize(); }
    if (mode === 'compare') { V.left.resize(); V.right.resize(); }
    if (live) attachLive();
    updateSide();
  }

  async function showCurrent() {
    const c = P.caps[P.idx];
    if (!c) { V.single.caption = ''; V.single.setSource(null); updateSide(); return; }
    try {
      const im = await loadImage(c.url);
      V.single.caption = caption(c, P.idx + 1);
      V.single.setSource(im);
    } catch (e) { App.toast(e.message, 'error'); }
    updateSide();
  }

  // ================= MULTI =================
  function renderMulti() {
    const g = $('pro-multi');
    g.classList.toggle('n36', P.per === 36);
    g.innerHTML = '';
    const start = P.page * P.per;
    for (let k = 0; k < P.per; k++) {
      const i = start + k, c = P.caps[i];
      const cell = document.createElement('div');
      cell.className = 'mcell';
      if (!c) { cell.classList.add('empty'); g.appendChild(cell); continue; }
      cell.dataset.i = String(i);
      const when = (c.captured_at || '').slice(2, 16).replace(/-/g, '.');
      const eye = c.eye && c.eye !== 'NA' ? c.eye : '';
      cell.innerHTML = `<img src="${esc(c.url)}" alt="" loading="lazy" draggable="false">` +
        `<div class="mcap">${i + 1}&nbsp; ${esc(when)}&nbsp; ${esc(eye)}${c.note ? ' · ' + esc(c.note) : ''}</div>` +
        '<span class="mbadge" hidden></span>';
      cell.title = caption(c, i + 1);
      cell.addEventListener('click', () => {
        const now = performance.now();
        if (!(lastClick.i === i && now - lastClick.t < 500)) lastClick = { i, t: now, before: [...P.sel] };
        toggleSel(i);
      });
      cell.addEventListener('dblclick', () => {
        // 더블클릭은 '열기' — 앞선 클릭으로 바뀐 선택을 되돌린다
        if (lastClick.i === i && lastClick.before) { P.sel = lastClick.before; refreshSel(); }
        openIndex(i);
      });
      g.appendChild(cell);
    }
    refreshSel();
  }
  let lastClick = { i: -1, t: 0, before: null };
  function refreshSel() {
    document.querySelectorAll('#pro-multi .mcell[data-i]').forEach((cell) => {
      const rank = P.sel.indexOf(+cell.dataset.i);
      cell.classList.toggle('sel', rank >= 0);
      const b = cell.querySelector('.mbadge');
      b.hidden = rank < 0;
      b.textContent = rank >= 0 ? `선택 ${rank + 1}` : '';
    });
    updateSide();
  }
  function toggleSel(i) {
    const k = P.sel.indexOf(i);
    if (k >= 0) P.sel.splice(k, 1);
    else { P.sel.push(i); if (P.sel.length > 2) P.sel.shift(); }
    refreshSel();
  }
  function openIndex(i) { if (P.caps[i]) { P.idx = i; return setMode('single'); } }
  function step(d) {
    if (P.mode === 'multi') {
      const np = Math.min(Math.max(0, P.page + d), pageCount() - 1);
      if (np !== P.page) { P.page = np; renderMulti(); updateSide(); }
    } else if (P.mode === 'single' && P.caps.length) {
      const ni = Math.min(Math.max(0, P.idx + d), P.caps.length - 1);
      if (ni !== P.idx) { P.idx = ni; showCurrent(); }
    }
  }
  function setPer(n) {
    P.per = Number(n) === 36 ? 36 : 16;
    $('pro-per').value = String(P.per);
    P.page = Math.min(P.page, pageCount() - 1);
    renderMulti(); updateSide();
  }

  // ================= 비교 =================
  async function prepareCompare() {
    let i, j;
    if (P.sel.length === 2) [i, j] = [...P.sel].sort((a, b) => a - b);
    else if (P.mode === 'single' && P.idx > 0) { i = P.idx - 1; j = P.idx; }
    else { App.toast('MULTI에서 비교할 영상 2장을 클릭해 선택하세요.', 'error'); return false; }
    const a = P.caps[i], b = P.caps[j];
    try {
      const [ia, ib] = await Promise.all([loadImage(a.url), loadImage(b.url)]);
      P.pair = [a, b];
      V.left.caption = caption(a, i + 1); V.right.caption = caption(b, j + 1);
      V.left.setSource(ia); V.right.setSource(ib);
      return true;
    } catch (e) { App.toast(e.message, 'error'); return false; }
  }

  // ================= 보정 =================
  let adjRaf = 0;
  function readAdj() {
    P.adj = {
      brightness: +$('adj-bright').value,
      contrast: +$('adj-contrast').value / 100,
      gamma: +$('adj-gamma').value / 100,
      negative: $('adj-neg').checked,
      channel: $('adj-channel').value,
    };
    $('o-bright').value = String(P.adj.brightness);
    $('o-contrast').value = P.adj.contrast.toFixed(2);
    $('o-gamma').value = P.adj.gamma.toFixed(2);
  }
  function applyAdjNow() { for (const v of Object.values(V)) v.setAdjust(P.adj); }
  function onAdj() { readAdj(); cancelAnimationFrame(adjRaf); adjRaf = requestAnimationFrame(applyAdjNow); }
  function setAdj(a) {
    const x = { ...IDENTITY, ...a };
    $('adj-bright').value = x.brightness;
    $('adj-contrast').value = Math.round(x.contrast * 100);
    $('adj-gamma').value = Math.round(x.gamma * 100);
    $('adj-neg').checked = x.negative;
    $('adj-channel').value = x.channel;
    readAdj(); cancelAnimationFrame(adjRaf); applyAdjNow();
  }

  // ================= 주석 도구 =================
  function setTool(t) {
    P.tool = t;
    document.querySelectorAll('#pro-tools [data-tool]').forEach((b) => b.classList.toggle('on', b.dataset.tool === t));
    for (const v of Object.values(V)) v.cv.style.cursor = t === 'pan' ? 'grab' : 'crosshair';
  }
  function clearAnn() { for (const v of Object.values(V)) { v.ann = []; v.draw(); } }

  // ================= LIVE =================
  function attachLive() {
    const st = App.state.stream, vid = $('pro-video');
    if (st && vid.srcObject !== st) { vid.srcObject = st; const pr = vid.play && vid.play(); if (pr) pr.catch(() => {}); }
    $('pro-live-empty').style.display = st ? 'none' : 'flex';
  }
  function grabVideo() {
    const vid = $('pro-video');
    if (!vid.videoWidth) return null;
    const c = document.createElement('canvas');
    c.width = vid.videoWidth; c.height = vid.videoHeight;
    c.getContext('2d').drawImage(vid, 0, 0);
    return c;
  }
  function toggleCapture() {
    const view = document.querySelector('.pro-view[data-view="live"]');
    if (!P.frozen) {
      const g = grabVideo();
      if (!g) { App.toast('라이브 영상이 없습니다.', 'error'); return; }
      const fz = $('pro-freeze');
      fz.width = g.width; fz.height = g.height; fz.getContext('2d').drawImage(g, 0, 0);
      P.frozen = true;
    } else P.frozen = false;
    view.classList.toggle('frozen', P.frozen);
    $('pro-capture').classList.toggle('on', P.frozen);
    $('pro-capture').textContent = P.frozen ? '▶ RESUME' : '❄ CAPTURE';
    updateSide();
  }
  async function saveLive() {
    const p = App.currentPatient();
    if (!p) { App.toast('환자를 먼저 선택하세요.', 'error'); return; }
    const src = P.frozen ? $('pro-freeze') : grabVideo();
    if (!src) { App.toast('저장할 영상이 없습니다.', 'error'); return; }
    const blob = await new Promise((r) => src.toBlob(r, 'image/png'));
    if (!blob) return;
    if (await App.persistCapture(p, 'photo', blob, 'png', $('pro-eye').value, null, null, { silent: true })) {
      App.toast('환자 DB에 저장했습니다.', 'success');
      if (P.frozen) toggleCapture();
      await reload(true);
      App.renderThumbs();
    }
  }

  // ================= 보정본 저장 / 코멘트 / 환자정보 =================
  async function saveEdited() {
    const p = App.currentPatient();
    if (!p) { App.toast('환자를 먼저 선택하세요.', 'error'); return 0; }
    const targets = P.mode === 'single' ? [[V.single, P.caps[P.idx]]]
      : P.mode === 'compare' ? [[V.left, P.pair[0]], [V.right, P.pair[1]]] : [];
    let n = 0;
    for (const [v, src] of targets) {
      if (!v.proc || !src) continue;
      if (isIdentity(P.adj) && !v.ann.length) continue;
      const note = v.ann.length ? '주석' : '보정본';
      const blob = await new Promise((r) => v.renderFull().toBlob(r, 'image/png'));
      if (blob && await App.persistCapture(p, 'photo', blob, 'png', src.eye || 'NA', null, note, { silent: true })) n++;
    }
    if (!n) { App.toast('보정이나 주석이 없어 저장할 내용이 없습니다.', 'error'); return 0; }
    clearAnn();
    setAdj(IDENTITY);                                  // 저장본에 이미 반영 → 이중 적용 방지
    await reload(P.mode === 'single');
    App.renderThumbs();
    App.toast(`보정본 ${n}장을 저장했습니다 (원본 보존).`, 'success');
    return n;
  }
  async function setComment(text) {
    const c = P.caps[P.idx];
    if (!c) return;
    try {
      const r = await App.api(`/captures/${c.id}`, { method: 'PATCH', body: JSON.stringify({ note: text }) });
      c.note = r.note;
      renderMulti();
      V.single.caption = caption(c, P.idx + 1); V.single.draw();
      updateSide(); App.renderThumbs();
      App.toast('코멘트를 저장했습니다.', 'success');
    } catch (e) { App.toast(e.message, 'error'); }
  }
  function editComment() {
    const c = P.caps[P.idx];
    if (P.mode !== 'single' || !c) return;
    const t = window.prompt('이 영상의 코멘트:', c.note || '');
    if (t !== null) setComment(t);
  }
  function editPatient() {
    const p = App.currentPatient();
    if (!p) { App.toast('환자를 먼저 선택하세요.', 'error'); return; }
    App.openPatientDialog(p);
  }

  // ================= 인쇄 / PDF 보고서 =================
  async function printItems() {
    if (P.mode === 'single' && V.single.proc) return [[V.single.renderFull(), caption(P.caps[P.idx])]];
    if (P.mode === 'compare') {
      return [[V.left, P.pair[0]], [V.right, P.pair[1]]].filter(([v, c]) => v.proc && c)
        .map(([v, c]) => [v.renderFull(), caption(c)]);
    }
    if (P.mode === 'live') {
      const cv = P.frozen ? $('pro-freeze') : grabVideo();
      return cv ? [[cv, 'LIVE  ' + App.fmtDT(new Date())]] : [];
    }
    if (P.mode === 'multi') {
      const idx = P.sel.length ? [...P.sel].sort((a, b) => a - b)
        : Array.from({ length: Math.max(0, Math.min(P.per, P.caps.length - P.page * P.per)) }, (_, k) => P.page * P.per + k);
      const out = [];
      for (const i of idx) {
        try { out.push([processed(await loadImage(P.caps[i].url), P.adj), caption(P.caps[i])]); } catch (_) { /* skip */ }
      }
      return out;
    }
    return [];
  }
  function toDataURL(cv, max = 1600) {
    const s = Math.min(1, max / Math.max(cv.width, cv.height));
    if (s === 1) return cv.toDataURL('image/jpeg', 0.92);
    const c = document.createElement('canvas');
    c.width = Math.round(cv.width * s); c.height = Math.round(cv.height * s);
    c.getContext('2d').drawImage(cv, 0, 0, c.width, c.height);
    return c.toDataURL('image/jpeg', 0.92);
  }
  async function buildReport() {
    const items = await printItems();
    if (!items.length) return 0;
    const p = P.patient, sex = { M: '남', F: '여', O: '기타' }[p?.sex] || '';
    const pages = [];
    if (items.length > 2) for (let i = 0; i < items.length; i += 4) pages.push(items.slice(i, i + 4));
    else pages.push(items);
    const now = App.fmtDT(new Date());
    const area = $('print-area');
    area.innerHTML = pages.map((pg, pi) => `
      <section class="rp-page">
        <div class="rp-head"><div class="rp-title">슬릿램프 영상 보고서</div><div class="rp-date">출력 ${esc(now)}</div></div>
        <div class="rp-pt">
          <div><b>환자: ${esc(p ? p.name : '-')} (${esc(p?.chart_no || '-')})</b>${sex ? '&nbsp; · &nbsp;' + sex : ''}${p?.birth_date ? '&nbsp; · &nbsp;' + esc(p.birth_date) : ''}</div>
          <div class="rp-l2">진단명: ${esc(p?.diagnosis || '-')} &nbsp;&nbsp;&nbsp; 담당의: ${esc(p?.doctor || '-')}</div>
        </div>
        <div class="rp-imgs ${pg.length === 1 ? 'c1' : 'c2'}">
          ${pg.map(([cv, cap]) => `<figure class="rp-fig"><img src="${toDataURL(cv)}" alt=""><figcaption>${esc(cap)}</figcaption></figure>`).join('')}
        </div>
        <div class="rp-notes"><h4>소견</h4><div class="rp-box"></div></div>
        <div class="rp-foot"><span>확인자 서명: ________________</span><span>${pi + 1} / ${pages.length}</span></div>
      </section>`).join('');
    await Promise.all([...area.querySelectorAll('img')].map((im) => (im.decode ? im.decode().catch(() => {}) : null)));
    return pages.length;
  }
  async function doPrint() {
    const n = await buildReport();
    if (!n) { App.toast('출력할 영상이 없습니다.', 'error'); return; }
    App.toast("인쇄 창에서 '대상: PDF로 저장'을 고르면 PDF 보고서가 됩니다.", 'success');
    try { window.print(); } catch (_) { App.toast('이 환경에서는 인쇄 창을 열 수 없습니다.', 'error'); }
  }

  // ================= 토글 · 이벤트 =================
  async function setPro(on) {
    P.on = on;
    document.body.classList.toggle('pro-on', on);
    $('btn-pro').setAttribute('aria-pressed', String(on));
    if (on) { await reload(false); await setMode(P.mode); }
    else if (P.frozen) toggleCapture();
  }

  $('btn-pro').addEventListener('click', () => setPro(!P.on));
  document.querySelectorAll('#pro-modes .pbtn').forEach((b) => b.addEventListener('click', () => setMode(b.dataset.mode)));
  document.querySelectorAll('#pro-tools [data-tool]').forEach((b) => b.addEventListener('click', () => setTool(b.dataset.tool)));
  $('pro-capture').addEventListener('click', toggleCapture);
  $('pro-save').addEventListener('click', saveLive);
  $('pro-prev').addEventListener('click', () => step(-1));
  $('pro-next').addEventListener('click', () => step(1));
  $('pro-per').addEventListener('change', (e) => setPer(e.target.value));
  $('pro-comment').addEventListener('click', editComment);
  $('pro-patient').addEventListener('click', editPatient);
  $('pro-print').addEventListener('click', doPrint);
  $('pro-clear').addEventListener('click', clearAnn);
  $('pro-save-edited').addEventListener('click', saveEdited);
  $('pro-fit').addEventListener('click', () => { for (const v of Object.values(V)) v.resetView(); });
  $('pro-zin').addEventListener('click', () => (P.mode === 'compare' ? V.left : V.single).zoomAt(1.25));
  $('pro-zout').addEventListener('click', () => (P.mode === 'compare' ? V.left : V.single).zoomAt(0.8));
  $('adj-reset').addEventListener('click', () => setAdj(IDENTITY));
  for (const id of ['adj-bright', 'adj-contrast', 'adj-gamma']) $(id).addEventListener('input', onAdj);
  $('adj-channel').addEventListener('change', onAdj);
  $('adj-neg').addEventListener('change', onAdj);
  $('pro-start-camera').addEventListener('click', async () => { await App.startCamera(); attachLive(); });

  document.addEventListener('slit:patient', () => { if (P.on) reload(false); });
  document.addEventListener('keydown', (e) => {
    if (!P.on || e.target.matches('input, textarea, select') || document.querySelector('dialog[open]')) return;
    if (e.key === 'ArrowLeft') { e.preventDefault(); step(-1); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); step(1); }
    else if (e.key === ' ' && P.mode === 'live') { e.preventDefault(); toggleCapture(); }
  });

  setTool('pan');
  readAdj();
  setPer(16);
  document.querySelectorAll('#pro-display .pro-view').forEach((v) => v.classList.toggle('on', v.dataset.view === P.mode));
  document.querySelectorAll('#pro-modes .pbtn').forEach((b) => b.classList.toggle('on', b.dataset.mode === P.mode));

  // 자동화 테스트·디버깅용 핸들
  window.SlitPro = { state: P, viewers: V, setPro, setMode, setPer, openIndex, step, toggleSel, setAdj,
    setTool, saveEdited, setComment, buildReport, reload };
})();
