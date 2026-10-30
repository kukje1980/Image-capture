/* 질환별 참고 사진 — 상단 아이콘 → 참고 사진 패널 → 촬영 사진과 나란히 비교 (환자 설명용).
 *
 * - 질환 목록·소견·설명·모식도: /static/dx/library.json (데스크탑 앱의 assets/dx 와 같은 내용)
 * - 병원 자체 참고 사진: /api/v1/references (서버) 또는 브라우저 저장소(localstore.js, '이 PC에만 저장' 모드)
 * - app.js 의 window.SlitApp API 와 'slit:patient' / 'slit:captures' 이벤트에 의존한다.
 */
(() => {
  const $ = (id) => document.getElementById(id);
  const App = window.SlitApp;
  if (!App) return;
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const BRAND = { report_title: '슬릿램프 영상 보고서', logo: null, ...(window.SLIT_BRAND || {}) };

  const D = {
    lib: null, byId: {},
    cur: null,            // 패널에 열린 질환 id
    refs: {},             // 질환 id → 병원 등록 참고 사진 목록
    ref: null,            // 비교 왼쪽 {kind:'ill'|'user', url, caption, id?}
    pt: null,             // 비교 오른쪽 {kind:'capture'|'live', url, caption, eye, canvas?}
    caps: [],             // 현재 환자의 사진 목록
    liveCanvas: null,
  };

  // ---------------- 라이브러리 · 상단 아이콘 ----------------
  async function loadLibrary() {
    try {
      const r = await fetch('/static/dx/library.json', { cache: 'no-cache' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      D.lib = await r.json();
    } catch (e) {
      $('dxbar').hidden = true;
      return;
    }
    D.byId = {};
    for (const d of D.lib.diseases) D.byId[d.id] = d;
    renderBar();
  }
  function renderBar() {
    const bar = $('dxbar');
    bar.innerHTML = '';
    for (const d of D.lib.diseases) {
      const b = document.createElement('button');
      b.className = 'dx-btn';
      b.type = 'button';
      b.dataset.dx = d.id;
      b.title = `${d.name} · ${d.en}\n${d.summary}\n(누르면 아래에 참고 사진)`;
      b.setAttribute('aria-pressed', 'false');
      b.innerHTML = `<svg class="ic"><use href="#${esc(d.icon)}"/></svg><span>${esc(d.short || d.name)}</span>`;
      b.addEventListener('click', () => togglePanel(d.id));
      bar.appendChild(b);
    }
  }
  function syncBar() {
    const open = !$('dx-panel').hidden;
    document.querySelectorAll('#dxbar .dx-btn').forEach((b) => {
      const on = open && b.dataset.dx === D.cur;
      b.classList.toggle('on', on);
      b.setAttribute('aria-pressed', String(on));
    });
  }

  // ---------------- 참고 사진 패널 ----------------
  function togglePanel(id) {
    if (D.cur === id && !$('dx-panel').hidden) closePanel();
    else openPanel(id);
  }
  async function openPanel(id) {
    const d = D.byId[id];
    if (!d) return;
    D.cur = id;
    $('dxp-icon').innerHTML = `<svg class="ic"><use href="#${esc(d.icon)}"/></svg>`;
    $('dxp-name').textContent = d.name;
    $('dxp-en').textContent = d.en;
    $('dxp-sum').textContent = d.summary;
    $('dx-panel').hidden = false;
    syncBar();
    renderStrip();                          // 모식도는 바로, 등록 사진은 불러온 뒤 갱신
    await loadRefs(id);
    if (D.cur === id) renderStrip();
  }
  function closePanel() {
    $('dx-panel').hidden = true;
    syncBar();
  }
  async function loadRefs(id) {
    try { D.refs[id] = await App.api(`/references?disease=${encodeURIComponent(id)}`); }
    catch (e) { D.refs[id] = D.refs[id] || []; App.toast('참고 사진 목록을 불러오지 못했습니다: ' + e.message, 'error'); }
  }
  function refItems(id) {
    const d = D.byId[id];
    if (!d) return [];
    const ill = (d.illustrations || []).map((i) => ({ kind: 'ill', url: `/static/dx/${i.file}`, caption: i.caption }));
    const user = (D.refs[id] || []).map((r) => ({ kind: 'user', id: r.id, url: r.url, caption: r.caption || `참고 사진 ${(r.created_at || '').slice(0, 10)}` }));
    return [...ill, ...user];
  }
  function renderStrip() {
    const strip = $('dxp-strip');
    strip.innerHTML = '';
    for (const it of refItems(D.cur)) {
      const c = document.createElement('button');
      c.type = 'button';
      c.className = 'dx-card';
      c.title = it.caption + ' — 누르면 촬영 사진과 비교';
      c.innerHTML = `<img src="${esc(it.url)}" alt="" loading="lazy">
        <span class="dxc-badge ${it.kind === 'user' ? 'user' : ''}">${it.kind === 'user' ? '참고 사진' : '모식도'}</span>
        <span class="dxc-cap">${esc(it.caption)}</span>`;
      if (it.kind === 'user') {
        const del = document.createElement('button');
        del.type = 'button';
        del.className = 'dxc-del';
        del.title = '이 참고 사진 삭제';
        del.setAttribute('aria-label', '삭제');
        del.innerHTML = '<svg class="ic"><use href="#i-trash"/></svg>';
        del.addEventListener('click', (e) => { e.stopPropagation(); deleteRef(it); });
        c.appendChild(del);
      }
      c.addEventListener('click', () => openCompare(D.cur, it));
      strip.appendChild(c);
    }
    const add = document.createElement('button');
    add.type = 'button';
    add.className = 'dx-card add';
    add.innerHTML = '<svg class="ic"><use href="#i-plus"/></svg><span>참고 사진 추가</span>';
    add.title = '파일에서 이 질환의 참고 사진 등록';
    add.addEventListener('click', () => $('dxp-file').click());
    strip.appendChild(add);
  }
  async function deleteRef(it) {
    if (!window.confirm(`참고 사진을 삭제할까요?\n${it.caption}`)) return;
    try {
      await App.api(`/references/${it.id}`, { method: 'DELETE' });
      await loadRefs(D.cur);
      renderStrip();
      if (D.ref && D.ref.kind === 'user' && D.ref.id === it.id) { D.ref = refItems(D.cur)[0] || null; renderCompare(); }
      App.toast('참고 사진을 삭제했습니다.', 'success');
    } catch (e) { App.toast('삭제 실패: ' + e.message, 'error'); }
  }
  async function uploadRef(disease, blob, filename, caption) {
    const fd = new FormData();
    fd.append('disease', disease);
    if (caption) fd.append('caption', caption);
    fd.append('file', blob, filename);
    return App.api('/references', { method: 'POST', body: fd });
  }
  async function onFiles(e) {
    const files = Array.from(e.target.files || []);
    e.target.value = '';
    if (!files.length || !D.cur) return;
    let ok = 0;
    for (const f of files) {
      try {
        await uploadRef(D.cur, f, f.name, f.name.replace(/\.[^.]+$/, ''));
        ok++;
      } catch (err) { App.toast(`'${f.name}' 등록 실패: ${err.message}`, 'error'); }
    }
    if (ok) {
      await loadRefs(D.cur);
      renderStrip();
      if (!$('dx-dialog').open) App.toast(`참고 사진 ${ok}장을 등록했습니다.`, 'success');
    }
  }

  // ---------------- 비교 화면 ----------------
  const capCaption = (c) => {
    const ts = App.parseTs(c.captured_at);
    return `${App.fmtDT(ts)}${c.eye && c.eye !== 'NA' ? ' · ' + c.eye : ''}${c.note ? ' · ' + c.note : ''}`;
  };
  async function loadCaps() {
    const p = App.currentPatient();
    if (!p) { D.caps = []; return; }
    try { D.caps = (await App.api(`/captures?patient_id=${p.id}&order=desc`)).filter((c) => c.media_type === 'photo'); }
    catch (_) { D.caps = []; }
  }
  function grabLive() {
    const v = $('video');
    if (!App.state.stream || !v.videoWidth) return null;
    const cv = document.createElement('canvas');
    cv.width = v.videoWidth; cv.height = v.videoHeight;
    cv.getContext('2d').drawImage(v, 0, 0, cv.width, cv.height);
    D.liveCanvas = cv;
    return { kind: 'live', url: cv.toDataURL('image/png'), caption: `실시간 화면 ${App.fmtDT(new Date())}`, eye: $('eye-select').value || 'NA', canvas: cv };
  }
  async function openCompare(disease, refItem) {
    D.cur = disease;
    D.ref = refItem || refItems(disease)[0] || null;
    await loadCaps();
    const dlg = $('dx-dialog');
    if (!D.pt || D.pt.kind !== 'capture' || !D.caps.some((c) => c.id === D.pt.capture.id)) {
      const c = D.caps[0];
      D.pt = c ? { kind: 'capture', url: c.url, caption: capCaption(c), eye: c.eye, capture: c } : grabLive();
    }
    renderCompare();
    if (!dlg.open) dlg.showModal();
  }
  function renderCompare() {
    const d = D.byId[D.cur];
    if (!d) return;
    const p = App.currentPatient();
    $('dxd-title').innerHTML = `<svg class="ic"><use href="#${esc(d.icon)}"/></svg>${esc(d.name)} <small>${esc(d.en)}</small>`
      + `<small>·</small><small>${p ? esc(p.name) + (p.chart_no ? ' #' + esc(p.chart_no) : '') : '환자 미선택'}</small>`;
    // 왼쪽: 참고
    const ri = $('dxd-ref-img');
    if (D.ref) { ri.src = D.ref.url; $('dxd-ref-cap').textContent = D.ref.caption; }
    else { ri.removeAttribute('src'); $('dxd-ref-cap').textContent = '—'; }
    $('dxd-ref-empty').hidden = !!D.ref;
    const rs = $('dxd-ref-strip');
    rs.innerHTML = '';
    for (const it of refItems(D.cur)) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'dxs' + (D.ref && D.ref.url === it.url ? ' on' : '');
      b.title = it.caption;
      b.innerHTML = `<img src="${esc(it.url)}" alt=""><span>${esc(it.caption)}</span>`;
      b.addEventListener('click', () => { D.ref = it; renderCompare(); });
      rs.appendChild(b);
    }
    // 오른쪽: 환자
    const pi = $('dxd-pt-img');
    if (D.pt) { pi.src = D.pt.url; $('dxd-pt-cap').textContent = D.pt.caption; }
    else { pi.removeAttribute('src'); $('dxd-pt-cap').textContent = '—'; }
    $('dxd-pt-empty').hidden = !!D.pt;
    $('dxd-pt-empty').innerHTML = !p ? '상단에서 환자를 선택하세요' : (App.state.stream ? '촬영 사진이 없습니다<br>아래 \'실시간 화면\'을 누르면 지금 화면과 비교합니다' : '이 환자의 촬영 사진이 없습니다');
    const ps = $('dxd-pt-strip');
    ps.innerHTML = '';
    if (App.state.stream) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'dxs live' + (D.pt && D.pt.kind === 'live' ? ' on' : '');
      b.title = '지금 카메라 화면을 가져와 비교';
      b.innerHTML = '<svg class="ic"><use href="#i-live"/></svg>실시간 화면';
      b.addEventListener('click', () => { const g = grabLive(); if (g) { D.pt = g; renderCompare(); } });
      ps.appendChild(b);
    }
    for (const c of D.caps) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'dxs' + (D.pt && D.pt.kind === 'capture' && D.pt.capture.id === c.id ? ' on' : '');
      const ts = App.parseTs(c.captured_at);
      b.title = capCaption(c);
      b.innerHTML = `<img src="${esc(c.url)}" alt="" loading="lazy"><span>${esc(ts.toLocaleDateString('ko-KR', { month: '2-digit', day: '2-digit' }))} ${esc(c.eye && c.eye !== 'NA' ? c.eye : '')}</span>`;
      b.addEventListener('click', () => { D.pt = { kind: 'capture', url: c.url, caption: capCaption(c), eye: c.eye, capture: c }; renderCompare(); });
      ps.appendChild(b);
    }
    if (!ps.children.length) { const e = document.createElement('span'); e.className = 'dxs-empty'; e.textContent = p ? '촬영 사진 없음' : '환자 미선택'; ps.appendChild(e); }
    // 설명
    $('dxd-findings').innerHTML = (d.findings || []).map((f) => `<li>${esc(f)}</li>`).join('');
    $('dxd-explain').textContent = d.explain || '';
    $('dxd-points').innerHTML = (d.compare || []).map((f) => `<li>${esc(f)}</li>`).join('');
    $('dxd-notice').textContent = D.lib.notice || '';
    $('dxd-register').disabled = !D.pt;
    $('dxd-save').disabled = !(D.pt && D.ref && p);
    $('dxd-print').disabled = !(D.pt || D.ref);
    for (const id of ['dxd-ref-box', 'dxd-pt-box']) $(id).classList.remove('zoom');
  }
  function zoomToggle(e) {
    const box = e.currentTarget, img = box.querySelector('img');
    if (!img.getAttribute('src')) return;
    if (box.classList.contains('zoom')) { box.classList.remove('zoom'); return; }
    const r = box.getBoundingClientRect();
    img.style.transformOrigin = `${((e.clientX - r.left) / r.width * 100).toFixed(1)}% ${((e.clientY - r.top) / r.height * 100).toFixed(1)}%`;
    box.classList.add('zoom');
  }

  // 환자 사진 → 이 질환의 참고 사진으로 등록 (환자 이름은 캡션에 넣지 않는다)
  async function registerCurrent() {
    if (!D.pt || !D.cur) return;
    const d = D.byId[D.cur];
    const today = new Date().toISOString().slice(0, 10);
    const cap = window.prompt('참고 사진 설명 (환자 이름은 넣지 마세요):', `${d.name} 사례 ${today}`);
    if (cap === null) return;
    try {
      let blob, name;
      if (D.pt.kind === 'live') { blob = await new Promise((res) => D.pt.canvas.toBlob(res, 'image/png')); name = 'live.png'; }
      else {
        const r = await fetch(D.pt.url);
        if (!r.ok) throw new Error('HTTP ' + r.status);
        blob = await r.blob();
        name = (D.pt.capture.filename || D.pt.url.split('/').pop() || 'capture.png').split('?')[0];
        if (!/\.(png|jpe?g|webp)$/i.test(name)) name += blob.type === 'image/jpeg' ? '.jpg' : '.png';
      }
      if (!blob || !blob.size) throw new Error('사진을 읽지 못했습니다.');
      await uploadRef(D.cur, blob, name, cap.trim());
      await loadRefs(D.cur);
      renderStrip();
      renderCompare();
      App.toast(`'${d.name}' 참고 사진으로 등록했습니다.`, 'success');
    } catch (e) { App.toast('등록 실패: ' + e.message, 'error'); }
  }

  // ---------------- 비교 이미지 합성 · 저장 · 인쇄 ----------------
  function loadImage(url) {
    return new Promise((res, rej) => {
      const im = new Image();
      im.onload = () => res(im);
      im.onerror = () => rej(new Error('이미지를 불러오지 못했습니다.'));
      im.src = url;
    });
  }
  async function compose() {
    const d = D.byId[D.cur];
    const [a, b] = await Promise.all([loadImage(D.ref.url), loadImage(D.pt.url)]);
    const H = 900, label = 54, gap = 24, pad = 24;
    const wa = Math.round(a.naturalWidth * H / a.naturalHeight), wb = Math.round(b.naturalWidth * H / b.naturalHeight);
    const cv = document.createElement('canvas');
    cv.width = pad * 2 + wa + gap + wb; cv.height = pad + label + H + pad;
    const ctx = cv.getContext('2d');
    ctx.fillStyle = '#000'; ctx.fillRect(0, 0, cv.width, cv.height);
    ctx.drawImage(a, pad, pad + label, wa, H);
    ctx.drawImage(b, pad + wa + gap, pad + label, wb, H);
    ctx.fillStyle = '#e7eaf0';
    ctx.font = 'bold 26px Pretendard, "Malgun Gothic", "Apple SD Gothic Neo", sans-serif';
    ctx.textBaseline = 'middle';
    ctx.fillText(`참고 · ${d.name}${D.ref.kind === 'ill' ? ' (모식도)' : ''}`, pad, pad + label / 2);
    ctx.fillText('환자 촬영', pad + wa + gap, pad + label / 2);
    ctx.font = '20px Pretendard, "Malgun Gothic", "Apple SD Gothic Neo", sans-serif';
    ctx.fillStyle = '#a3acba';
    ctx.textAlign = 'right';
    ctx.fillText(D.pt.caption, cv.width - pad, pad + label / 2);
    return cv;
  }
  async function saveComposite() {
    const p = App.currentPatient();
    if (!p) { App.toast('환자를 먼저 선택하세요.', 'error'); return; }
    if (!D.ref || !D.pt) return;
    const d = D.byId[D.cur];
    try {
      const cv = await compose();
      const blob = await new Promise((res) => cv.toBlob(res, 'image/png'));
      if (!blob) throw new Error('이미지를 만들지 못했습니다.');
      const ok = await App.persistCapture(p, 'photo', blob, 'png', D.pt.eye || 'NA', null, `비교: ${d.name}`);
      if (ok) { App.toast(`비교 이미지를 저장했습니다 (메모 '비교: ${d.name}').`, 'success'); await loadCaps(); renderCompare(); }
    } catch (e) { App.toast('저장 실패: ' + e.message, 'error'); }
  }
  async function toDataURL(url, max = 1400) {
    const im = await loadImage(url);
    const s = Math.min(1, max / Math.max(im.naturalWidth, im.naturalHeight));
    const c = document.createElement('canvas');
    c.width = Math.round(im.naturalWidth * s); c.height = Math.round(im.naturalHeight * s);
    c.getContext('2d').drawImage(im, 0, 0, c.width, c.height);
    return c.toDataURL('image/jpeg', 0.92);
  }
  async function doPrint() {
    const d = D.byId[D.cur];
    if (!d || !(D.ref || D.pt)) return;
    const p = App.currentPatient(), sex = { M: '남', F: '여', O: '기타' }[p?.sex] || '';
    const figs = [];
    try {
      if (D.ref) figs.push([await toDataURL(D.ref.url), `참고 · ${d.name}${D.ref.kind === 'ill' ? ' (모식도)' : ''} — ${D.ref.caption}`]);
      if (D.pt) figs.push([await toDataURL(D.pt.url), `환자 촬영 — ${D.pt.caption}`]);
    } catch (e) { App.toast('인쇄용 이미지를 만들지 못했습니다: ' + e.message, 'error'); return; }
    const li = (xs) => (xs || []).map((x) => `<li>${esc(x)}</li>`).join('');
    $('print-area').innerHTML = `
      <section class="rp-page">
        <div class="rp-head"><div class="rp-brand">${BRAND.logo ? `<img class="rp-logo" src="${esc(BRAND.logo)}" alt="">` : ''}<div class="rp-title">${esc(BRAND.report_title)} · ${esc(d.name)} 비교 설명</div></div><div class="rp-date">출력 ${esc(App.fmtDT(new Date()))}</div></div>
        <div class="rp-pt">
          <div><b>환자: ${esc(p ? p.name : '-')} (${esc(p?.chart_no || '-')})</b>${sex ? '&nbsp; · &nbsp;' + sex : ''}${p?.birth_date ? '&nbsp; · &nbsp;' + esc(p.birth_date) : ''}</div>
          <div class="rp-l2">진단명: ${esc(p?.diagnosis || '-')} &nbsp;&nbsp;&nbsp; 담당의: ${esc(p?.doctor || '-')} &nbsp;&nbsp;&nbsp; 비교 질환: ${esc(d.name)} (${esc(d.en)})</div>
        </div>
        <div class="rp-imgs ${figs.length === 1 ? 'c1' : 'c2'}">
          ${figs.map(([src, cap]) => `<figure class="rp-fig"><img src="${src}" alt=""><figcaption>${esc(cap)}</figcaption></figure>`).join('')}
        </div>
        <div class="rp-dx">
          <div><h4>세극등 소견</h4><ul>${li(d.findings)}</ul></div>
          <div><h4>비교 포인트</h4><ul>${li(d.compare)}</ul></div>
          <div class="full"><h4>환자에게 설명</h4><p>${esc(d.explain)}</p></div>
          <div class="full rp-small">${esc(D.lib.notice || '')}</div>
        </div>
        <div class="rp-foot"><span>확인자 서명: ________________</span><span>1 / 1</span></div>
      </section>`;
    await Promise.all([...$('print-area').querySelectorAll('img')].map((im) => (im.decode ? im.decode().catch(() => {}) : null)));
    try { window.print(); } catch (_) { App.toast('이 환경에서는 인쇄 창을 열 수 없습니다.', 'error'); }
  }

  // ---------------- 이벤트 ----------------
  $('dxp-close').addEventListener('click', closePanel);
  $('dxp-add').addEventListener('click', () => $('dxp-file').click());
  $('dxp-file').addEventListener('change', onFiles);
  $('dxp-compare').addEventListener('click', () => openCompare(D.cur, refItems(D.cur)[0]));
  $('dxd-x').addEventListener('click', () => $('dx-dialog').close());
  $('dxd-close').addEventListener('click', () => $('dx-dialog').close());
  $('dxd-register').addEventListener('click', registerCurrent);
  $('dxd-save').addEventListener('click', saveComposite);
  $('dxd-print').addEventListener('click', doPrint);
  $('dxd-ref-box').addEventListener('click', zoomToggle);
  $('dxd-pt-box').addEventListener('click', zoomToggle);
  $('dx-dialog').addEventListener('close', () => { if (D.pt && D.pt.kind === 'live') D.pt = null; D.liveCanvas = null; });
  document.addEventListener('slit:patient', async () => {
    if (!$('dx-dialog').open) return;
    D.pt = null;
    await openCompare(D.cur, D.ref);
  });
  document.addEventListener('slit:captures', async () => {
    if (!$('dx-dialog').open) return;
    await loadCaps();
    if (D.pt && D.pt.kind === 'capture' && !D.caps.some((c) => c.id === D.pt.capture.id)) D.pt = null;
    renderCompare();
  });

  window.SlitDx = { state: D, openPanel, closePanel, openCompare, refItems, compose };
  loadLibrary();
})();
