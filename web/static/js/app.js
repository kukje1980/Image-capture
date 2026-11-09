/* 안저 영상 시스템 웹앱 프런트엔드.
 * - navigator.mediaDevices.getUserMedia 로 캡처 장비 라이브
 * - canvas.toBlob (사진) / MediaRecorder (동영상)
 * - 저장: (a) 서버 POST /api/v1/captures  (b) File System Access API 로 지정 폴더에도 동시 write
 */
(() => {
  const $ = (id) => document.getElementById(id);
  const API = '/api/v1';
  // 안저 촬영 전용: 마이봄샘(눈꺼풀) 모드는 숨김 — 다시 쓰려면 true (body.feat-meibo 로 버튼·Pro 탭이 보임)
  const FEATURES = { meibo: false };
  document.body.classList.toggle('feat-meibo', FEATURES.meibo);

  const state = {
    patients: [],
    currentPatientId: null,
    stream: null,
    isPaused: false,
    isRecording: false,
    recorder: null,
    recordStart: 0,
    recordTimer: null,
    editingPatientId: null,
    statusResetTimer: null,
    dirHandle: null,     // File System Access API 디렉토리 핸들
    // 4분할
    quad: false,
    quadActive: 0,
    quadFrozen: [false, false, false, false],
    quadHasImg: [false, false, false, false],
    quadEyes: ['NA', 'NA', 'NA', 'NA'],
    quadRAF: null,
  };

  const fmt = (d) => d.toLocaleTimeString('ko-KR', { hour12: false });
  const fmtDT = (d) => d.toLocaleString('ko-KR', { hour12: false });
  const parseTs = (s) => {
    // 'YYYY-MM-DD HH:MM:SS' (localtime) → Date
    const [date, time] = (s || '').split(' ');
    if (!date) return new Date();
    const [y, m, d] = date.split('-').map(Number);
    const [hh, mm, ss] = (time || '0:0:0').split(':').map(Number);
    return new Date(y, (m || 1) - 1, d || 1, hh || 0, mm || 0, ss || 0);
  };

  // ---- API helper ----
  const LOCAL_MODE = !!(window.SlitLocal && window.SlitLocal.mode() === 'local');
  async function api(path, options = {}) {
    // '이 PC에만 저장' 모드: 서버로 보내지 않고 브라우저 저장소(IndexedDB)에서 처리
    if (LOCAL_MODE) return window.SlitLocal.api(path, options);
    const res = await fetch(`${API}${path}`, {
      headers: options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' },
      ...options,
    });
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try { detail = (await res.json()).detail || detail; } catch (_) {}
      throw new Error(detail);
    }
    if (res.status === 204) return null;
    return res.json();
  }

  // ---- init ----
  async function init() {
    try {
      const saved = localStorage.getItem('slitlamp-theme');
      if (saved) document.documentElement.setAttribute('data-theme', saved);
    } catch (_) {}
    syncThemeIcon();
    syncStorageUI();
    applyKeyHints();
    try { if (localStorage.getItem('slitlamp-hint-closed') === '1' && !LOCAL_MODE) $('hint').style.display = 'none'; } catch (_) {}
    bindEvents();
    syncEye();
    setView(prefGet('slitlamp-view') || 'all', { quiet: true });
    syncViewUI();
    if (!('showDirectoryPicker' in window)) {
      $('btn-folder').disabled = true;
      $('btn-folder').title = '이 브라우저는 폴더 저장을 지원하지 않습니다 (Chrome/Edge 사용)';
    }
    await loadPatients();
    updateCaptureButtons();
    setStatus('대기 중', 'idle');
  }

  function bindEvents() {
    $('patient-search').addEventListener('input', debounce(loadPatients, 250));
    $('patient-select').addEventListener('change', (e) => {
      state.currentPatientId = parseInt(e.target.value, 10) || null;
      renderThumbs();
      updateCaptureButtons();
      emitPatient();
    });
    $('btn-new-patient').addEventListener('click', () => openPatientDialog(null));
    $('btn-edit-patient').addEventListener('click', () => {
      const p = currentPatient();
      if (p) openPatientDialog(p);
    });
    $('patient-form').addEventListener('submit', savePatient);
    $('patient-cancel').addEventListener('click', () => $('patient-dialog').close());
    $('patient-x').addEventListener('click', () => $('patient-dialog').close());
    $('patient-delete').addEventListener('click', deletePatient);

    $('btn-theme').addEventListener('click', toggleTheme);
    $('btn-storage').addEventListener('click', openStorageDialog);
    $('storage-x').addEventListener('click', () => $('storage-dialog').close());
    $('storage-cancel').addEventListener('click', () => $('storage-dialog').close());
    $('storage-apply').addEventListener('click', applyStorage);
    document.querySelectorAll('#eye-seg [data-eye]').forEach((b) => b.addEventListener('click', () => setEye(b.dataset.eye)));
    $('eye-select').addEventListener('change', syncEye);
    document.querySelectorAll('#thumb-filter .tf').forEach((b) => b.addEventListener('click', () => {
      state.thumbFilter = b.dataset.f;
      document.querySelectorAll('#thumb-filter .tf').forEach((x) => x.classList.toggle('on', x === b));
      renderThumbs();
    }));
    $('hint-close').addEventListener('click', () => {
      $('hint').style.display = 'none';
      try { localStorage.setItem('slitlamp-hint-closed', '1'); } catch (_) {}
    });
    // 환자 목록 · 전체 화면
    $('pb-chip').addEventListener('click', openPatientList);
    $('btn-patients').addEventListener('click', openPatientList);
    $('pd-close').addEventListener('click', () => $('patient-drawer').close());
    $('pd-new').addEventListener('click', () => openPatientDialog(null));
    $('btn-fullscreen').addEventListener('click', toggleFullscreen);
    $('btn-fs-exit').addEventListener('click', toggleFullscreen);
    $('btn-fs-capture').addEventListener('click', () => { if (!$('btn-capture').disabled) capturePhoto(); });
    $('btn-fs-freeze').addEventListener('click', () => $('btn-freeze').click());
    $('btn-fs-record').addEventListener('click', () => $('btn-record').click());
    document.addEventListener('fullscreenchange', syncFullscreen);
    $('btn-folder').addEventListener('click', pickFolder);

    $('btn-start-camera').addEventListener('click', () => startCamera());
    $('camera-select').addEventListener('change', (e) => { prefSet('slitlamp-cam', e.target.value); startCamera(e.target.value); });
    $('res-select').value = prefGet('slitlamp-res') || '1080';
    $('res-select').addEventListener('change', (e) => {
      prefSet('slitlamp-res', e.target.value);
      if (state.stream) startCamera($('camera-select').value || undefined);
    });
    document.querySelectorAll('.btn-sony-help').forEach((b) => b.addEventListener('click', () => $('sony-dialog').showModal()));
    $('sony-x').addEventListener('click', () => $('sony-dialog').close());
    $('sony-ok').addEventListener('click', () => $('sony-dialog').close());
    $('btn-pause').addEventListener('click', togglePause);
    $('btn-capture').addEventListener('click', capturePhoto);
    $('btn-record').addEventListener('click', toggleRecord);
    // 화면 보기 (큰 · 멀티 · 확대 · 3D)
    document.querySelectorAll('#view-seg [data-view], .pane-head[data-view]').forEach((b) => b.addEventListener('click', () => setView(b.dataset.view)));
    $('zoom-in').addEventListener('click', () => stepZoom(1));
    $('zoom-out').addEventListener('click', () => stepZoom(-1));
    $('zoom-center').addEventListener('click', () => { view.cx = 0.5; view.cy = 0.5; applyZoom(); });
    bindZoomPointer();
    $('d3-height').addEventListener('input', (e) => { D3.setScale(+e.target.value / 100); prefSet('slitlamp-d3h', e.target.value); });
    $('d3-color').addEventListener('change', (e) => { D3.setMode(e.target.value); prefSet('slitlamp-d3c', e.target.value); });
    $('d3-reset').addEventListener('click', () => D3.reset());
    $('d3-save').addEventListener('click', saveD3);
    { const h = prefGet('slitlamp-d3h'), c = prefGet('slitlamp-d3c');
      if (h !== null && h !== '' && !isNaN(+h)) $('d3-height').value = h;
      if (c === 'tex' || c === 'map') $('d3-color').value = c;
      D3.setScale(+$('d3-height').value / 100); D3.setMode($('d3-color').value); }
    $('video').addEventListener('loadedmetadata', () => { fitPanes(); applyZoom(); });
    if (window.ResizeObserver) {
      const ro = new ResizeObserver(() => { fitPanes(); applyZoom(); D3.touch(); });
      ro.observe($('video-frame')); ro.observe($('stage')); ro.observe($('pane-zoom'));
    }
    // 하단 촬영 이미지 띠: 세로 휠로 가로 이동 · 접기
    $('thumb-list').addEventListener('wheel', (e) => {
      const l = $('thumb-list');
      if (Math.abs(e.deltaY) > Math.abs(e.deltaX) && l.scrollWidth > l.clientWidth) { e.preventDefault(); l.scrollBy({ left: e.deltaY, behavior: 'auto' }); }
    }, { passive: false });
    $('thumbs-fold').addEventListener('click', () => setThumbsFolded(!$('thumbs').classList.contains('folded')));
    setThumbsFolded(prefGet('slitlamp-thumbs-folded') === '1');
    $('btn-meibo').addEventListener('click', () => setMeibo(!meibo.on));
    $('btn-mb-enh').addEventListener('click', () => { meibo.enh = !meibo.enh; saveMeibo(); syncMeibo(); });
    $('btn-mb-inv').addEventListener('click', () => { meibo.inv = !meibo.inv; saveMeibo(); syncMeibo(); });
    document.querySelectorAll('#mb-lid-seg [data-lid]').forEach((x) => x.addEventListener('click', () => setLid(x.dataset.lid)));
    syncMeibo();
    $('btn-freeze').addEventListener('click', freezeFrame);
    $('btn-save-quad').addEventListener('click', saveQuad);
    $('btn-clear-quad').addEventListener('click', clearQuad);
    document.querySelectorAll('#quad-grid .quad-cell').forEach((cell) => {
      cell.addEventListener('click', () => { if (state.quad) setQuadActive(+cell.dataset.i); });
    });

    $('viewer-close').addEventListener('click', () => $('viewer-dialog').close());
    $('viewer-dialog').addEventListener('close', () => { $('viewer-body').innerHTML = ''; });   // 닫으면 동영상 재생·내려받기 중지
    $('viewer-close-2').addEventListener('click', () => $('viewer-dialog').close());

    // 단축키 (사용자 지정 — 단축키 설정 창)
    document.addEventListener('keydown', onShortcutKey);
    $('btn-keys').addEventListener('click', openKeysDialog);
    $('btn-settings').addEventListener('click', () => $('settings-dialog').showModal());
    $('settings-x').addEventListener('click', () => $('settings-dialog').close());
    $('cam-chip').addEventListener('click', () => $('settings-dialog').showModal());
    // 바깥(배경) 클릭으로 설정 창 닫기
    $('settings-dialog').addEventListener('click', (e) => { if (e.target === $('settings-dialog')) $('settings-dialog').close(); });
    $('keys-x').addEventListener('click', () => $('keys-dialog').close());
    $('keys-ok').addEventListener('click', () => $('keys-dialog').close());
    $('keys-reset').addEventListener('click', () => { keymap = defaultKeymap(); saveKeymap(); renderKeysTable(); applyKeyHints(); });
  }

  // ---- 단축키 (사용자 지정) ----
  // 물리 키 기준(e.code)으로 읽어서 한글 입력 상태에서도 동작한다. USB 발판 스위치처럼 키를 보내는 장치도 지정 가능.
  const KEY_ACTIONS = [
    { id: 'capture', label: '사진 캡처', def: 'C', scope: 'capture', btns: ['btn-capture', 'btn-fs-capture'],
      run: () => { if (!$('btn-capture').disabled) capturePhoto(); } },
    { id: 'record', label: '녹화 시작 / 중지', def: 'R', scope: 'capture', btns: ['btn-record', 'btn-fs-record'],
      run: () => { if (!$('btn-record').disabled) toggleRecord(); } },
    { id: 'pause', label: '일시정지 / 재개', def: 'Space', scope: 'capture', btns: ['btn-pause'], run: () => togglePause() },
    { id: 'freeze', label: '정지영상 (4분할 칸 채우기)', def: 'X', scope: 'capture', btns: ['btn-freeze', 'btn-fs-freeze'],
      run: () => { if (!$('btn-freeze').disabled) freezeFrame(); } },
    { id: 'quad', label: '멀티 화면 (4분할) 켜기 / 끄기', def: 'Q', scope: 'capture', btns: ['view-multi'],
      run: () => setView(view.mode === 'multi' ? 'single' : 'multi') },
    { id: 'view', label: '화면 보기 전환 (모두 → 큰 → 멀티 → 확대 → 3D)', def: 'V', scope: 'capture',
      run: () => setView(VIEWS[(VIEWS.indexOf(view.mode) + 1) % VIEWS.length]) },
    { id: 'meibo', label: '마이봄샘 촬영 모드 켜기 / 끄기', def: 'M', scope: 'capture', btns: ['btn-meibo'], run: () => setMeibo(!meibo.on) },
    { id: 'lid', label: '마이봄 상안검 ↔ 하안검', def: 'U', scope: 'capture', run: () => { if (meibo.on) setLid(meibo.lid === 'upper' ? 'lower' : 'upper'); } },
    { id: 'eyeOD', label: '안구 OD (우안)', def: '1', scope: 'all', run: () => setEyeAny('OD') },
    { id: 'eyeOS', label: '안구 OS (좌안)', def: '2', scope: 'all', run: () => setEyeAny('OS') },
    { id: 'eyeOU', label: '안구 OU (양안)', def: '3', scope: 'all', run: () => setEyeAny('OU') },
    { id: 'eyeNA', label: '안구 미지정', def: '0', scope: 'all', run: () => setEyeAny('NA') },
    { id: 'fullscreen', label: '전체 화면', def: 'F', scope: 'all', btns: ['btn-fullscreen', 'pro-fullscreen'], run: () => toggleFullscreen() },
    { id: 'mode', label: '촬영 ↔ Pro 검토 전환', def: 'P', scope: 'all', btns: ['btn-pro'], run: () => $('btn-pro').click() },
    { id: 'patients', label: '환자 목록', def: 'L', scope: 'all', btns: ['btn-patients'], run: () => openPatientList() },
    { id: 'newPatient', label: '신규 환자', def: 'N', scope: 'all', btns: ['btn-new-patient'], run: () => openPatientDialog(null) },
  ];
  // 숨긴 기능의 단축키는 빼고 쓴다 (단축키 설정 창에도 나오지 않음)
  for (let i = KEY_ACTIONS.length - 1; i >= 0; i--) {
    if (!FEATURES.meibo && (KEY_ACTIONS[i].id === 'meibo' || KEY_ACTIONS[i].id === 'lid')) KEY_ACTIONS.splice(i, 1);
  }
  const RESERVED = new Set(['Escape', 'Tab', 'Ctrl+Z', 'Ctrl+Y', 'Ctrl+Shift+Z', 'Meta+Z', 'Meta+Y', 'ArrowLeft', 'ArrowRight']);
  const defaultKeymap = () => Object.fromEntries(KEY_ACTIONS.map((a) => [a.id, a.def]));
  let keymap = defaultKeymap();
  try { keymap = { ...keymap, ...JSON.parse(localStorage.getItem('slitlamp-keys') || '{}') }; } catch (_) { /* 기본값 */ }
  function saveKeymap() { try { localStorage.setItem('slitlamp-keys', JSON.stringify(keymap)); } catch (_) { /* 저장 불가 */ } }

  /** 키 이벤트 → 'Ctrl+Shift+C', 'Space', 'F5', 'Num1' 같은 이름 (수정키만 누르면 null) */
  function keyName(e) {
    if (['Control', 'Shift', 'Alt', 'Meta', 'Process'].includes(e.key) || e.isComposing && !e.code) return null;
    let k;
    if (/^Key[A-Z]$/.test(e.code)) k = e.code.slice(3);
    else if (/^Digit\d$/.test(e.code)) k = e.code.slice(5);
    else if (/^Numpad\d$/.test(e.code)) k = 'Num' + e.code.slice(6);
    else if (e.code === 'Space') k = 'Space';
    else if (e.key && e.key.length === 1) k = e.key.toUpperCase();
    else k = e.key || e.code;
    const mods = [e.ctrlKey && 'Ctrl', e.altKey && 'Alt', e.shiftKey && 'Shift', e.metaKey && 'Meta'].filter(Boolean);
    return [...mods, k].join('+');
  }
  function setEyeAny(v) {
    if (document.body.classList.contains('pro-on')) {
      const s = $('pro-eye'); if (s) s.value = v;
      toast(`안구: ${v === 'NA' ? '미지정' : v}`, 'success');
    } else setEye(v);
  }
  function onShortcutKey(e) {
    if (capturingKey) return;
    if (e.repeat) return;                              // 키·발판을 누르고 있어도 한 번만 실행
    if ((e.target instanceof Element && e.target.matches('input, textarea, select')) || document.querySelector('dialog[open]')) return;
    const name = keyName(e);
    if (!name) return;
    const pro = document.body.classList.contains('pro-on');
    const act = KEY_ACTIONS.find((a) => keymap[a.id] === name && (a.scope === 'all' || (a.scope === 'capture' && !pro)));
    if (!act) return;
    e.preventDefault();
    act.run();
  }
  /** 버튼 툴팁에 현재 단축키 표시 */
  function applyKeyHints() {
    for (const a of KEY_ACTIONS) {
      for (const id of a.btns || []) {
        const b = $(id); if (!b) continue;
        const base = (b.dataset.tip ??= (b.title || '').replace(/\s*\([^)]*\)\s*$/, ''));
        b.title = keymap[a.id] ? `${base} (${keymap[a.id]})` : base;
      }
    }
    document.querySelectorAll('#eye-seg [data-eye]').forEach((b) => {
      const k = keymap['eye' + b.dataset.eye];
      b.title = (b.dataset.tip ??= b.title) + (k ? ` (${k})` : '');
    });
  }

  let capturingKey = null;
  function openKeysDialog() { renderKeysTable(); $('keys-dialog').showModal(); }
  function renderKeysTable() {
    const tb = $('keys-rows');
    tb.innerHTML = '';
    for (const a of KEY_ACTIONS) {
      const tr = document.createElement('tr');
      const k = keymap[a.id];
      tr.innerHTML = `<td>${escHtml(a.label)}<small>${a.scope === 'capture' ? '촬영 화면' : '모든 화면'}</small></td>`
        + `<td><kbd class="${k ? '' : 'none'}">${escHtml(k || '없음')}</kbd></td>`
        + '<td class="keys-act"><button class="btn btn-sm" data-act="set">변경</button><button class="btn btn-sm btn-ghost" data-act="clear" title="단축키 없애기">지우기</button></td>';
      tr.querySelector('[data-act="set"]').addEventListener('click', () => startCapture(a, tr));
      tr.querySelector('[data-act="clear"]').addEventListener('click', () => { keymap[a.id] = ''; saveKeymap(); renderKeysTable(); applyKeyHints(); });
      tb.appendChild(tr);
    }
  }
  function startCapture(action, tr) {
    const kbd = tr.querySelector('kbd');
    kbd.textContent = '키를 누르세요… (Esc 취소)'; kbd.className = 'waiting';
    const handler = (e) => {
      e.preventDefault(); e.stopPropagation();
      if (e.key === 'Escape') { finish(); return; }
      const name = keyName(e);
      if (!name) return;                              // 수정키만 눌렀으면 계속 기다림
      if (RESERVED.has(name)) { kbd.textContent = `${name} 는 쓸 수 없습니다 — 다른 키`; return; }
      const other = KEY_ACTIONS.find((a) => a.id !== action.id && keymap[a.id] === name);
      if (other) { keymap[other.id] = ''; toast(`'${other.label}'에 쓰던 ${name} 를 옮겼습니다`, 'success'); }
      keymap[action.id] = name;
      saveKeymap(); applyKeyHints();
      finish();
    };
    function finish() {
      document.removeEventListener('keydown', handler, true);
      capturingKey = null;
      renderKeysTable();
    }
    if (capturingKey) capturingKey();
    capturingKey = finish;
    document.addEventListener('keydown', handler, true);
  }

  function debounce(fn, ms) {
    let t;
    return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
  }

  // ---- patients ----
  function currentPatient() {
    return state.patients.find(p => p.id === state.currentPatientId)
      || (state.selectedPatient && state.selectedPatient.id === state.currentPatientId ? state.selectedPatient : undefined);
  }

  async function loadPatients() {
    const q = ($('patient-search').value || '').trim();
    const prev = currentPatient();
    if (prev) state.selectedPatient = prev;           // 검색 결과에 없어도 현재 환자 정보는 유지
    try {
      state.patients = await api(`/patients?q=${encodeURIComponent(q)}`);
    } catch (e) {
      toast('환자 목록을 불러오지 못했습니다: ' + e.message, 'error');
      state.patients = [];
    }
    const sel = $('patient-select');
    sel.innerHTML = '';
    if (state.patients.length === 0) {
      const opt = document.createElement('option');
      opt.textContent = q ? '(검색 결과 없음)' : '(등록된 환자 없음)';
      opt.disabled = true;
      sel.appendChild(opt);
      if (!q) state.currentPatientId = null;          // 검색 중에는 선택한 환자를 바꾸지 않는다
    } else {
      for (const p of state.patients) {
        const opt = document.createElement('option');
        opt.value = String(p.id);
        opt.textContent = `${p.name} (${p.chart_no || '-'})`;
        sel.appendChild(opt);
      }
      let inList = state.patients.find(p => p.id === state.currentPatientId);
      if (!inList && state.currentPatientId && !q) {
        // 목록(최대 500명)에 없는 방금 저장한 환자도 선택이 유지되도록 따로 불러와 맨 앞에 둔다
        try {
          inList = await api(`/patients/${state.currentPatientId}`);
          state.patients.unshift(inList);
          const opt = document.createElement('option');
          opt.value = String(inList.id);
          opt.textContent = `${inList.name} (${inList.chart_no || '-'})`;
          sel.insertBefore(opt, sel.firstChild);
        } catch (_) { inList = null; }
      }
      // 검색 결과에 현재 환자가 없어도 선택은 유지 (검색만 하고 닫았는데 다른 환자로 바뀌어 촬영되는 일 방지)
      if (!inList && !(q && state.currentPatientId)) state.currentPatientId = state.patients[0].id;
      sel.value = String(state.currentPatientId);
    }
    updateCaptureButtons();
    renderPatientTable();
    await renderThumbs();
    emitPatient();
  }

  // ---- 환자 목록 (표) ----
  const SEX_KO = { M: '남', F: '여', O: '기타' };
  function openPatientList() {
    renderPatientTable();
    const d = $('patient-drawer');
    if (!d.open) d.showModal();
    setTimeout(() => $('patient-search').focus(), 30);
  }
  function renderPatientTable() {
    const tb = $('pd-rows');
    tb.innerHTML = '';
    $('pd-count').textContent = state.patients.length;
    $('pd-empty').hidden = state.patients.length > 0;
    $('pd-empty').textContent = ($('patient-search').value || '').trim() ? '검색 결과가 없습니다' : '등록된 환자가 없습니다';
    for (const p of state.patients) {
      const tr = document.createElement('tr');
      tr.tabIndex = 0;
      tr.classList.toggle('on', p.id === state.currentPatientId);
      const age = ageOf(p.birth_date);
      const sexAge = [SEX_KO[p.sex] || '', age != null ? age + '세' : ''].filter(Boolean).join(' · ');
      tr.innerHTML = `<td class="pd-name">${escHtml(p.name)}</td><td class="pd-chart">${escHtml(p.chart_no || '-')}</td>`
        + `<td>${escHtml(sexAge || '-')}</td><td>${escHtml(p.birth_date || '-')}</td>`
        + `<td class="pd-dx" title="${escHtml(p.diagnosis || '')}">${escHtml(p.diagnosis || '-')}</td><td>${escHtml(p.doctor || '-')}</td>`
        + '<td><button class="btn btn-sm btn-ghost pd-edit" title="정보 수정" aria-label="정보 수정"><svg class="ic"><use href="#i-edit"/></svg></button></td>';
      tr.addEventListener('click', (e) => {
        if (e.target.closest('.pd-edit')) { openPatientDialog(p); return; }
        selectPatient(p.id);
        $('patient-drawer').close();
      });
      tr.addEventListener('keydown', (e) => { if (e.key === 'Enter') { selectPatient(p.id); $('patient-drawer').close(); } });
      tb.appendChild(tr);
    }
  }
  function selectPatient(id) {
    if (state.isRecording && state.recordPatientId !== id) {   // 다른 환자로 바꾸면 녹화를 끝내 앞 환자에게 저장
      stopRecording();
      toast('환자를 바꿔 녹화를 끝내고 이전 환자에게 저장했습니다.', 'success');
    }
    state.currentPatientId = id;
    state.selectedPatient = state.patients.find((p) => p.id === id) || null;
    $('patient-select').value = String(id);
    renderPatientTable();
    renderThumbs();
    updateCaptureButtons();
    emitPatient();
  }

  // ---- 전체 화면 ----
  function toggleFullscreen() {
    const el = document.body.classList.contains('pro-on') ? $('pro-display') : $('video-frame');
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    else if (el.requestFullscreen) el.requestFullscreen().catch((e) => toast('전체 화면을 열 수 없습니다: ' + e.message, 'error'));
  }
  function syncFullscreen() {
    const on = !!document.fullscreenElement;
    for (const id of ['btn-fullscreen', 'pro-fullscreen']) {
      const b = $(id);
      if (b) b.innerHTML = on ? '<svg class="ic"><use href="#i-shrink"/></svg>전체 화면 끝' : '<svg class="ic"><use href="#i-expand"/></svg>전체 화면';
    }
  }

  function emitPatient() {
    renderBanner();
    document.dispatchEvent(new CustomEvent('slit:patient', { detail: currentPatient() || null }));
  }

  // ---- 환자 배너 · 영상 HUD ----
  const escHtml = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  function ageOf(birth) {
    const m = /^(\d{4})-(\d{1,2})-(\d{1,2})/.exec(birth || '');
    if (!m) return null;
    const now = new Date(), b = new Date(+m[1], +m[2] - 1, +m[3]);
    let a = now.getFullYear() - b.getFullYear();
    if (now < new Date(now.getFullYear(), b.getMonth(), b.getDate())) a--;
    return a >= 0 && a < 150 ? a : null;
  }
  function renderBanner() {
    const p = currentPatient();
    $('btn-edit-patient').disabled = !p;
    if (!p) {
      $('pb-avatar').innerHTML = '<svg class="ic"><use href="#i-user"/></svg>';
      $('pb-name').textContent = '환자를 선택하세요';
      $('pb-chart').textContent = '';
      $('pb-meta').innerHTML = '<span>검색하거나 신규 환자를 등록하세요</span>';
      $('hud-patient').textContent = '환자 미선택';
      return;
    }
    $('pb-avatar').textContent = (p.name || '?').trim().charAt(0);
    $('pb-name').textContent = p.name;
    $('pb-chart').textContent = p.chart_no ? '#' + p.chart_no : '';
    const sex = { M: '남', F: '여', O: '기타' }[p.sex] || '';
    const age = ageOf(p.birth_date);
    const bits = [];
    if (sex || age != null) bits.push(`<span>${[sex, age != null ? age + '세' : ''].filter(Boolean).join(' · ')}</span>`);
    if (p.birth_date) bits.push(`<span><b>생년월일</b>${escHtml(p.birth_date)}</span>`);
    bits.push(`<span><b>진단명</b><span class="dx">${escHtml(p.diagnosis || '-')}</span></span>`);
    bits.push(`<span><b>담당의</b>${escHtml(p.doctor || '-')}</span>`);
    $('pb-meta').innerHTML = bits.join('');
    $('hud-patient').textContent = `${p.name}${p.chart_no ? '  ·  ' + p.chart_no : ''}`;
  }
  function setEye(v) {
    const sel = $('eye-select');
    if (sel.value !== v) { sel.value = v; }
    syncEye();
  }
  function syncEye() {
    const v = $('eye-select').value || 'NA';
    document.querySelectorAll('#eye-seg [data-eye]').forEach((b) => {
      const on = b.dataset.eye === v;
      b.classList.toggle('on', on); b.setAttribute('aria-checked', String(on));
    });
    const fs = $('fs-eye');
    if (fs) fs.textContent = v === 'NA' ? '안구 —' : v;
  }

  function openPatientDialog(patient) {
    state.editingPatientId = patient?.id ?? null;
    $('patient-dialog-title').textContent = patient ? '환자 정보 수정' : '신규 환자';
    $('patient-delete').style.display = patient ? 'inline-flex' : 'none';
    $('p-chart').value = patient?.chart_no || '';
    $('p-name').value = patient?.name || '';
    $('p-birth').value = patient?.birth_date || '';
    $('p-sex').value = patient?.sex || '';
    $('p-phone').value = patient?.phone || '';
    $('p-memo').value = patient?.memo || '';
    $('p-symptoms').value = patient?.symptoms || '';
    $('p-diagnosis').value = patient?.diagnosis || '';
    $('p-doctor').value = patient?.doctor || '';
    $('patient-dialog').showModal();
  }

  async function savePatient(e) {
    e.preventDefault();
    const body = {
      chart_no: $('p-chart').value.trim(),
      name: $('p-name').value.trim(),
      birth_date: $('p-birth').value.trim() || null,
      sex: $('p-sex').value || null,
      phone: $('p-phone').value.trim() || null,
      memo: $('p-memo').value.trim() || null,
      symptoms: $('p-symptoms').value.trim() || null,
      diagnosis: $('p-diagnosis').value.trim() || null,
      doctor: $('p-doctor').value.trim() || null,
    };
    if (!body.chart_no || !body.name) return;
    try {
      let saved;
      if (state.editingPatientId) {
        saved = await api(`/patients/${state.editingPatientId}`, { method: 'PUT', body: JSON.stringify(body) });
      } else {
        saved = await api('/patients', { method: 'POST', body: JSON.stringify(body) });
      }
      state.currentPatientId = saved.id;
      $('patient-dialog').close();
      $('patient-search').value = '';
      await loadPatients();
      toast('환자 정보가 저장되었습니다.', 'success');
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function deletePatient() {
    if (!state.editingPatientId) return;
    if (!confirm('이 환자와 관련 촬영 기록을 삭제하시겠습니까?')) return;
    try {
      await api(`/patients/${state.editingPatientId}`, { method: 'DELETE' });
      $('patient-dialog').close();
      state.currentPatientId = null;
      await loadPatients();
      toast('삭제되었습니다.', 'success');
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  // ---- 저장 방식 (서버 / 이 PC에만) ----
  function syncStorageUI() {
    const btn = $('btn-storage');
    $('storage-label').textContent = LOCAL_MODE ? '저장: 이 PC 전용' : '저장: 서버';
    btn.classList.toggle('local', LOCAL_MODE);
    if (window.SlitLocal.policy !== 'choice') {
      btn.disabled = true;
      btn.title = '이 사이트는 저장 방식이 고정되어 있습니다 (' + (LOCAL_MODE ? '이 PC 전용' : '서버') + ')';
    }
    if (LOCAL_MODE) {
      $('hint-body').innerHTML = '<strong>이 PC 전용 모드</strong> — 환자 정보·사진·동영상을 인터넷 서버로 보내지 않고 이 PC의 브라우저에만 보관합니다. '
        + '브라우저 기록 삭제 시 함께 지워지므로 상단 <strong>"저장 폴더"</strong>를 지정해 PC 폴더에도 파일을 남기세요(Chrome/Edge).';
    }
  }
  async function openStorageDialog() {
    document.querySelectorAll('input[name="storage"]').forEach((r) => { r.checked = r.value === (LOCAL_MODE ? 'local' : 'server'); });
    const u = await window.SlitLocal.usage();
    $('storage-note').textContent = u && LOCAL_MODE
      ? `이 PC 저장소 사용량: ${(u.used / 1048576).toFixed(1)}MB / 사용 가능 ${(u.quota / 1073741824).toFixed(1)}GB`
      : '바꾸면 화면을 다시 불러옵니다. 두 저장 방식의 기록은 서로 옮겨지지 않습니다.';
    $('storage-dialog').showModal();
  }
  async function applyStorage() {
    const v = (document.querySelector('input[name="storage"]:checked') || {}).value || 'server';
    $('storage-dialog').close();
    if ((v === 'local') === LOCAL_MODE) return;
    window.SlitLocal.setMode(v);
    if (v === 'local') await window.SlitLocal.persist();   // 브라우저가 저장소를 임의로 비우지 않도록 요청
    location.reload();
  }

  // ---- theme ----
  function toggleTheme() {
    const root = document.documentElement;
    const isDark = root.getAttribute('data-theme') !== 'light';   // 기본은 어두운 영상 작업 공간
    const next = isDark ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem('slitlamp-theme', next); } catch (_) {}
    syncThemeIcon();
  }
  function syncThemeIcon() {
    const isDark = document.documentElement.getAttribute('data-theme') !== 'light';
    $('theme-icon-light').style.display = isDark ? 'block' : 'none';
    $('theme-icon-dark').style.display = isDark ? 'none' : 'block';
    $('theme-label').textContent = isDark ? '밝은 테마로' : '어두운 테마로';
  }

  // ---- folder (File System Access API) ----
  async function pickFolder() {
    try {
      state.dirHandle = await window.showDirectoryPicker({ mode: 'readwrite' });
      const status = $('folder-status');
      status.classList.add('linked');
      status.innerHTML = `<span class="dot"></span> ${state.dirHandle.name} 폴더 연결됨`;
      toast('지정 폴더가 연결되었습니다. 이후 캡처가 이 폴더에도 저장됩니다.', 'success');
    } catch (err) {
      if (err && err.name !== 'AbortError') toast('폴더 연결 실패: ' + err.message, 'error');
    }
  }

  async function saveToFolder(filename, blob) {
    if (!state.dirHandle) return false;
    try {
      const fh = await state.dirHandle.getFileHandle(filename, { create: true });
      const w = await fh.createWritable();
      await w.write(blob);
      await w.close();
      return true;
    } catch (err) {
      toast('지정 폴더 저장 실패: ' + err.message, 'error');
      return false;
    }
  }

  // ---- camera ----
  // ---- 카메라 (소니 USB 스트리밍 자동 인식 · 해상도) ----
  // 장치 이름 끝의 USB id '(054c:0e10)' 는 떼고 단어 단위로 비교 (웹캠 id 의 'a7' 오인식 방지). 054c = 소니 제조사 id
  const SONY_RE = /\bsony\b|\bzv-?e10|\bilme\b|\bfx30?\b|\bilce\b|\ba7\w*\b|\balpha\b/i;
  const isSony = (label) => /\(054c:[0-9a-f]{4}\)/i.test(label || '') || SONY_RE.test((label || '').replace(/\([0-9a-f]{4}:[0-9a-f]{4}\)/ig, ''));
  const RES = { '2160': [3840, 2160], '1080': [1920, 1080], '720': [1280, 720] };
  function prefGet(k) { try { return localStorage.getItem(k); } catch (_) { return null; } }
  function prefSet(k, v) { try { localStorage.setItem(k, v); } catch (_) { /* 저장 불가 */ } }

  let camGen = 0;
  async function startCamera(deviceId) {
    const gen = ++camGen;                              // 연달아 바꿀 때 늦게 끝난 이전 요청의 스트림은 버린다
    const stale = (st) => { if (gen === camGen) return false; if (st) st.getTracks().forEach((t) => t.stop()); return true; };
    if (state.isRecording) stopRecording();
    if (state.isPaused) togglePause();                 // 정지 화면이 새 카메라 영상 위에 남지 않게
    if (state.stream) { state.stream.getTracks().forEach(t => t.stop()); state.stream = null; }
    try {
      const video = $('video');
      const [w, h] = RES[$('res-select').value] || RES['1080'];
      deviceId = deviceId || prefGet('slitlamp-cam') || undefined;
      const want = { width: { ideal: w }, height: { ideal: h }, frameRate: { ideal: 30 } };
      let stream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: deviceId ? { ...want, deviceId: { exact: deviceId } } : want, audio: false });
      } catch (e) {
        if (!deviceId) throw e;
        if (stale()) return;
        stream = await navigator.mediaDevices.getUserMedia({ video: want, audio: false });   // 저장된 장치가 없어졌으면 기본 장치
      }
      if (stale(stream)) return;
      // 처음 권한을 받은 뒤 소니 카메라(USB 스트리밍)가 연결돼 있으면 그쪽으로 자동 전환
      if (!deviceId && !prefGet('slitlamp-cam')) {
        const cams = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === 'videoinput');
        if (stale(stream)) return;
        const cur = stream.getVideoTracks()[0];
        const sony = cams.find((c) => isSony(c.label));
        if (sony && !isSony(cur && cur.label)) {
          stream.getTracks().forEach((t) => t.stop());
          stream = await navigator.mediaDevices.getUserMedia({ video: { ...want, deviceId: { exact: sony.deviceId } }, audio: false });
          if (stale(stream)) return;
          toast(`소니 카메라를 찾아 연결했습니다: ${sony.label}`, 'success');
        }
      }
      state.stream = stream;
      video.srcObject = stream;
      $('zoom-video').srcObject = stream;                // 모두 보기의 확대 칸 (같은 스트림)
      if (view.mode !== 'all') $('zoom-video').pause();
      const track = stream.getVideoTracks()[0];
      const set = track && track.getSettings ? track.getSettings() : {};
      if (set.deviceId) prefSet('slitlamp-cam', set.deviceId);
      $('video-placeholder').style.display = 'none';
      video.onloadedmetadata = () => {
        const sonyTag = isSony(track && track.label) ? ' · Sony' : '';
        setStatus(`${video.videoWidth}×${video.videoHeight}${sonyTag}`, 'ready');
      };
      await populateCameraSelect();
      updateCaptureButtons();
    } catch (err) {
      if (gen !== camGen) return;
      $('video').srcObject = null;                     // 멈춘 이전 영상으로 촬영되지 않게 버튼도 끈다
      $('zoom-video').srcObject = null;
      updateCaptureButtons();
      showHintError(`카메라 접근 실패: ${err.message || err.name} (HTTPS/localhost 필요)`);
      $('video-placeholder').style.display = 'flex';
      setStatus('대기 중', 'idle');
    }
  }

  async function populateCameraSelect() {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const cams = devices.filter(d => d.kind === 'videoinput');
      const sel = $('camera-select');
      const currentId = state.stream?.getVideoTracks?.()[0]?.getSettings?.().deviceId;
      sel.innerHTML = '';
      cams.forEach((c, i) => {
        const opt = document.createElement('option');
        opt.value = c.deviceId;
        opt.textContent = (isSony(c.label) ? '★ ' : '') + (c.label || `카메라 ${i + 1}`);
        sel.appendChild(opt);
      });
      if (cams.length === 0) {
        const opt = document.createElement('option'); opt.textContent = '(카메라 없음)'; opt.disabled = true; sel.appendChild(opt);
      } else if (currentId) {
        sel.value = currentId;
      }
    } catch (_) {}
  }

  function togglePause() {
    if (!state.stream) return;
    const video = $('video'), frame = $('video-frame');
    if (!state.isPaused) {
      const cnv = $('freeze');
      cnv.width = video.videoWidth || 640;
      cnv.height = video.videoHeight || 480;
      cnv.getContext('2d').drawImage(video, 0, 0, cnv.width, cnv.height);
      video.pause();
      frame.classList.add('paused');
      state.isPaused = true;
      $('btn-pause').innerHTML = '<svg class="ic"><use href="#i-play"/></svg>재개';
    } else {
      video.play();
      frame.classList.remove('paused');
      state.isPaused = false;
      $('btn-pause').innerHTML = '<svg class="ic"><use href="#i-pause"/></svg>일시정지';
    }
    D3.touch(true);
    drawZoomMap();
  }

  // ---- capture ----
  let _fnSeq = 0;
  function buildFilename(patient, mediaType, ts, ext, eye, note) {
    const pad = (n, w = 2) => String(n).padStart(w, '0');
    const chart = (patient.chart_no || 'noChart').replace(/[^0-9A-Za-z._가-힣-]+/g, '_');
    const stamp = `${ts.getFullYear()}${pad(ts.getMonth() + 1)}${pad(ts.getDate())}_` +
      `${pad(ts.getHours())}${pad(ts.getMinutes())}${pad(ts.getSeconds())}${pad(ts.getMilliseconds(), 3)}`;
    const seq = pad((_fnSeq++) % 1000, 3);
    const tag = { '4분할 합성': '_quad', '4분할': '_q', '3D': '_3d' }[note] || '';
    return `${chart}_${stamp}_${seq}_${eye || 'NA'}${tag}.${ext}`;
  }

  // ---- 마이봄샘 촬영 모드 ----
  // 근적외선(NIR, 850nm 권장) 조명 + 뒤집은 눈꺼풀. 화면은 흑백·대비 강화, 저장은 흑백 원본(PNG) + 메모 '마이봄 상안검/하안검'
  const meibo = { on: false, lid: 'upper', enh: true, inv: false };
  try { Object.assign(meibo, JSON.parse(localStorage.getItem('slitlamp-meibo') || '{}'), { on: false }); } catch (_) { /* 기본값 */ }
  const LID_KO = { upper: '상안검', lower: '하안검' };
  function saveMeibo() { try { localStorage.setItem('slitlamp-meibo', JSON.stringify({ lid: meibo.lid, enh: meibo.enh, inv: meibo.inv })); } catch (_) { /* 저장 불가 */ } }
  function syncMeibo() {
    const b = document.body;
    b.classList.toggle('meibo-on', meibo.on);
    b.classList.toggle('mb-enh', meibo.enh);
    b.classList.toggle('mb-inv', meibo.inv);
    b.classList.toggle('mb-lower', meibo.lid === 'lower');
    $('btn-meibo').setAttribute('aria-pressed', String(meibo.on));
    $('btn-mb-enh').setAttribute('aria-pressed', String(meibo.enh));
    $('btn-mb-inv').setAttribute('aria-pressed', String(meibo.inv));
    document.querySelectorAll('#mb-lid-seg [data-lid]').forEach((x) => x.setAttribute('aria-checked', String(x.dataset.lid === meibo.lid)));
    $('hud-meibo').textContent = `MEIBO · ${LID_KO[meibo.lid]}`;
  }
  function setMeibo(on) {
    if (on && usesQuad(view.mode)) setView('single');   // 마이봄은 4분할을 쓰지 않음
    meibo.on = !!on; syncMeibo();
    toast(meibo.on ? `마이봄 촬영 모드 · ${LID_KO[meibo.lid]} (눈꺼풀을 뒤집어 틀에 맞추세요)` : '마이봄 촬영 모드 끔', 'success');
  }
  function setLid(lid) { meibo.lid = lid === 'lower' ? 'lower' : 'upper'; saveMeibo(); syncMeibo(); }

  async function capturePhoto() {
    const patient = currentPatient();
    if (!patient) { toast('환자를 먼저 선택하세요.', 'error'); return; }
    const video = $('video');
    if (!video.videoWidth) { toast('영상이 아직 준비되지 않았습니다.', 'error'); return; }
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const src = state.isPaused ? $('freeze') : video;
    const cx = canvas.getContext('2d');
    if (meibo.on) cx.filter = 'grayscale(1)';      // 마이봄: 흑백 원본 (대비 강화·반전은 화면 보기 전용)
    cx.drawImage(src, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise(res => canvas.toBlob(res, 'image/png'));
    if (!blob) return;
    const eye = $('eye-select').value;
    await persistCapture(patient, 'photo', blob, 'png', eye, null, meibo.on ? `마이봄 ${LID_KO[meibo.lid]}` : null);
  }

  function toggleRecord() {
    if (state.isRecording) stopRecording();
    else startRecording();
  }

  function startRecording() {
    if (!state.stream) return;
    const patient = currentPatient();
    if (!patient) { toast('환자를 먼저 선택하세요.', 'error'); return; }
    const mimes = ['video/mp4;codecs=avc1', 'video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'];
    const mime = mimes.find(m => window.MediaRecorder && MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(m));
    let recorder;
    try {
      recorder = new MediaRecorder(state.stream, mime ? { mimeType: mime } : {});
    } catch (err) { toast('녹화 시작 실패: ' + (err.message || err.name), 'error'); return; }
    const chunks = [];
    recorder.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    const eye = $('eye-select').value, start = Date.now();   // 시작할 때의 안구·시각으로 저장
    recorder.onstop = async () => {
      const blob = new Blob(chunks, { type: recorder.mimeType || 'video/webm' });
      const durationMs = (recorder.stoppedAt || Date.now()) - start;
      const ext = (blob.type && blob.type.includes('mp4')) ? 'mp4' : 'webm';
      await persistCapture(patient, 'video', blob, ext, eye, durationMs);
    };
    recorder.start();
    state.recorder = recorder;
    state.isRecording = true;
    state.recordStart = start;
    state.recordPatientId = patient.id;
    $('rec-badge').classList.add('on');
    $('btn-record').classList.add('recording');
    $('rec-btn-label').textContent = '녹화 중지';
    $('btn-fs-record').classList.toggle('recording', true); $('fs-rec-label').textContent = true ? '녹화 중지' : '녹화';
    setStatus('녹화 중', 'recording');
    state.recordTimer = setInterval(() => {
      const s = Math.floor((Date.now() - state.recordStart) / 1000);
      $('rec-time').textContent = `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
    }, 250);
  }

  function stopRecording() {
    if (!state.isRecording || !state.recorder) return;
    state.recorder.stoppedAt = Date.now();
    state.recorder.stop();
    state.isRecording = false;
    clearInterval(state.recordTimer);
    $('rec-badge').classList.remove('on');
    $('rec-time').textContent = '00:00';
    $('btn-record').classList.remove('recording');
    $('rec-btn-label').textContent = '녹화 시작';
    $('btn-fs-record').classList.toggle('recording', false); $('fs-rec-label').textContent = false ? '녹화 중지' : '녹화';
  }

  // 서버 + 지정 폴더 동시 저장
  // 인터넷 호스팅(Vercel 등)은 업로드 크기 제한(약 4.5MB)이 있어, 큰 PNG 사진은 고화질 JPEG 로 바꿔 올린다
  const IS_LOCAL = ['localhost', '127.0.0.1', '[::1]', ''].includes(location.hostname);
  const UPLOAD_SOFT_LIMIT = 4 * 1024 * 1024;
  async function shrinkPhoto(blob) {
    try {
      const bmp = await createImageBitmap(blob);
      const c = document.createElement('canvas');
      c.width = bmp.width; c.height = bmp.height;
      c.getContext('2d').drawImage(bmp, 0, 0);
      for (const q of [0.95, 0.9, 0.82]) {
        const j = await new Promise((res) => c.toBlob(res, 'image/jpeg', q));
        if (j && j.size <= UPLOAD_SOFT_LIMIT) return j;
      }
    } catch (_) { /* 변환 실패 시 원본 그대로 */ }
    return null;
  }

  // 촬영 직후 썸네일을 바로 보여 준다 (서버 저장이 끝나면 목록을 다시 그려 교체)
  function addPendingThumb(blob, eye, ts) {
    const list = $('thumb-list');
    $('thumb-empty').style.display = 'none';
    const el = document.createElement('div');
    el.className = 'thumb pending';
    const url = URL.createObjectURL(blob);
    el.innerHTML = `<img src="${url}" alt="">
      <span class="thumb-badges">${eye && eye !== 'NA' ? `<span class="thumb-badge e-${eye}">${eye}</span>` : ''}<span class="thumb-badge">저장 중…</span></span>
      <div class="thumb-caption"><span><span class="thumb-time">${hms(ts)}</span></span></div>`;
    const first = list.querySelector('.thumb-day, .thumb');
    list.insertBefore(el, first);
    return { el, url };
  }

  async function persistCapture(patient, mediaType, blob, ext, eye, durationMs, note, opts = {}) {
    const ts = new Date();
    // 지정 폴더에는 원본(무손실 PNG), 인터넷 서버에는 고화질 JPEG(약 1/3 크기)로 올려 저장 시간을 줄인다
    const folderBlob = blob, folderExt = ext;
    let upBlob = blob, upExt = ext;
    if (!IS_LOCAL && !LOCAL_MODE && mediaType === 'photo' && ext === 'png') {
      const j = await shrinkPhoto(blob);
      if (j) { upBlob = j; upExt = 'jpg'; }
    }
    const filename = buildFilename(patient, mediaType, ts, folderExt, eye, note);
    const upName = buildFilename(patient, mediaType, ts, upExt, eye, note);
    const pending = !opts.silent && mediaType === 'photo' ? addPendingThumb(folderBlob, eye, ts) : null;
    if (!opts.silent) setStatus('저장 중…', 'ready');

    // (a) 서버 저장 (환자 DB + 미디어 폴더) 과 (b) 지정 로컬 폴더 저장을 동시에
    const serverP = (async () => {
      try {
        const fd = new FormData();
        fd.append('patient_id', String(patient.id));
        fd.append('media_type', mediaType);
        fd.append('eye', eye || 'NA');
        fd.append('ext', upExt);
        if (durationMs != null) fd.append('duration_ms', String(durationMs));
        if (note) fd.append('note', note);
        fd.append('file', upBlob, upName);
        await api('/captures', { method: 'POST', body: fd });
        return true;
      } catch (err) {
        toast((LOCAL_MODE ? '이 PC 저장 실패: ' : '서버 저장 실패: ') + err.message, 'error');
        return false;
      }
    })();
    const folderP = state.dirHandle ? saveToFolder(filename, folderBlob) : Promise.resolve(false);
    const [serverOk, folderOk] = await Promise.all([serverP, folderP]);
    if (pending) {
      setTimeout(() => URL.revokeObjectURL(pending.url), 30000);
      if (!serverOk) pending.el.remove();
    }
    blob = folderBlob;

    // (c) 서버·폴더 모두 실패하면 촬영본을 잃지 않도록 파일로 내려받는다
    //     (예: 인터넷 호스팅의 업로드 크기 제한에 걸린 긴 동영상)
    if (!serverOk && !folderOk) {
      try {
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = filename;
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 60000);
        toast(`서버에 저장하지 못해 '${filename}' 파일로 내려받았습니다. 상단 '저장 폴더'를 지정하면 PC 폴더에 자동 보관됩니다.`, 'error');
      } catch (_) { /* 내려받기도 불가한 환경 */ }
    }

    if (!serverOk && !opts.silent) setStatus('저장 실패', 'idle', true);
    if (serverOk) document.dispatchEvent(new CustomEvent('slit:captures'));
    if (serverOk && !opts.silent) {
      renderThumbs();                      // 기다리지 않음 — 미리 보인 썸네일을 서버 목록으로 교체
      const base = LOCAL_MODE ? '이 PC' : '서버';
      const where = folderOk ? `${base} + 지정 폴더` : (state.dirHandle ? `${base}(폴더 실패)` : base);
      setStatus(`${mediaType === 'photo' ? '사진' : '동영상'} 저장됨 · ${where}`, 'ready', true);
    }
    return serverOk;
  }

  // ---- 4분할 정지영상 ----
  function quadCells() {
    return Array.from(document.querySelectorAll('#quad-grid .quad-cell'));
  }

  function toggleQuad() {
    if (!state.quad && meibo.on) setMeibo(false);
    state.quad = !state.quad;
    if (state.quad && state.isPaused) togglePause();   // 4분할에서는 일시정지 버튼이 숨겨지므로 라이브로
    const frame = $('video-frame');
    frame.classList.toggle('quad', state.quad && view.mode === 'multi');
    $('btn-pause').style.display = state.quad ? 'none' : '';
    $('btn-save-quad').style.display = state.quad ? '' : 'none';
    $('btn-clear-quad').style.display = state.quad ? '' : 'none';
    if (state.quad) {
      clearQuad();
      startQuadLoop();
      setStatus("4분할 · '정지영상'으로 각 칸을 채우세요", 'ready');
    } else {
      stopQuadLoop();
    }
  }

  function startQuadLoop() {
    const cells = quadCells();
    const video = $('video');
    const tick = () => {
      if (!state.quad) return;
      const i = state.quadActive;
      if (i != null && !state.quadFrozen[i] && video.videoWidth) {
        const cnv = cells[i].querySelector('canvas');
        if (cnv.width !== video.videoWidth) { cnv.width = video.videoWidth; cnv.height = video.videoHeight; }
        cnv.getContext('2d').drawImage(video, 0, 0, cnv.width, cnv.height);
        state.quadHasImg[i] = true;
      }
      state.quadRAF = requestAnimationFrame(tick);
    };
    stopQuadLoop();
    state.quadRAF = requestAnimationFrame(tick);
  }
  function stopQuadLoop() {
    if (state.quadRAF) cancelAnimationFrame(state.quadRAF);
    state.quadRAF = null;
  }

  function refreshQuadCells() {
    quadCells().forEach((cell, i) => {
      cell.classList.toggle('active', i === state.quadActive);
      cell.classList.toggle('frozen', state.quadFrozen[i]);
      const tag = cell.querySelector('.quad-tag');
      if (i === state.quadActive) tag.textContent = '● 라이브';
      else if (state.quadFrozen[i]) tag.textContent = '정지' + (state.quadEyes[i] !== 'NA' ? ' · ' + state.quadEyes[i] : '');
      else tag.textContent = '';
    });
  }

  function freezeFrame() {
    if (!state.quad) {
      // 단일 모드: 일시정지(정지영상)와 동일하게 현재 프레임 고정 토글
      togglePause();
      return;
    }
    const i = state.quadActive;
    if (i == null || !state.quadHasImg[i]) { toast('라이브 영상이 준비되지 않았습니다.', 'error'); return; }
    state.quadFrozen[i] = true;
    state.quadEyes[i] = $('eye-select').value;
    // 다음 빈 칸 찾기
    let nxt = null;
    for (let j = 1; j <= 4; j++) { const k = (i + j) % 4; if (!state.quadFrozen[k]) { nxt = k; break; } }
    if (nxt == null) {
      state.quadActive = null;
      setStatus("4칸 모두 채움 · '4분할 저장' 또는 칸 클릭으로 교체", 'ready');
    } else {
      state.quadActive = nxt;
      state.quadHasImg[nxt] = false;
      setStatus('정지영상 추가됨 (다음 칸으로 이동)', 'ready');
    }
    refreshQuadCells();
  }

  function setQuadActive(idx) {
    state.quadActive = idx;
    state.quadFrozen[idx] = false;
    state.quadHasImg[idx] = false;
    refreshQuadCells();
  }

  function clearQuad() {
    state.quadActive = 0;
    state.quadFrozen = [false, false, false, false];
    state.quadHasImg = [false, false, false, false];
    state.quadEyes = ['NA', 'NA', 'NA', 'NA'];
    quadCells().forEach((cell) => {
      const c = cell.querySelector('canvas');
      if (c.width) c.getContext('2d').clearRect(0, 0, c.width, c.height);
    });
    refreshQuadCells();
  }

  async function saveQuad() {
    const patient = currentPatient();
    if (!patient) { toast('환자를 먼저 선택하세요.', 'error'); return; }
    const cells = quadCells();
    const indices = [0, 1, 2, 3].filter(i => state.quadFrozen[i] || i === state.quadActive);
    const withImg = indices.filter(i => state.quadHasImg[i]);
    if (withImg.length === 0) { toast('저장할 정지영상이 없습니다.', 'error'); return; }
    let saved = 0;
    // 개별 저장
    for (const i of withImg) {
      const cnv = cells[i].querySelector('canvas');
      const blob = await new Promise(res => cnv.toBlob(res, 'image/png'));
      if (!blob) continue;
      const eye = state.quadFrozen[i] ? state.quadEyes[i] : $('eye-select').value;
      const ok = await persistCapture(patient, 'photo', blob, 'png', eye, null, '4분할', { silent: true });
      if (ok) saved++;
    }
    // 2×2 합성 저장
    const ref = cells[withImg[0]].querySelector('canvas');
    const cw = ref.width, ch = ref.height;
    const comp = document.createElement('canvas');
    comp.width = cw * 2; comp.height = ch * 2;
    const cx = comp.getContext('2d');
    cx.fillStyle = '#000'; cx.fillRect(0, 0, comp.width, comp.height);
    for (const i of withImg) {
      const cnv = cells[i].querySelector('canvas');
      const r = Math.floor(i / 2), c = i % 2;
      cx.drawImage(cnv, c * cw, r * ch, cw, ch);
    }
    const compBlob = await new Promise(res => comp.toBlob(res, 'image/png'));
    if (compBlob) {
      const ok = await persistCapture(patient, 'photo', compBlob, 'png', 'NA', null, '4분할 합성', { silent: true });
      if (ok) saved++;
    }
    await renderThumbs();
    setStatus(`4분할 저장됨 (개별+합성 ${saved}장)`, 'ready', true);
    toast(`4분할 저장 완료 (${saved}장)`, 'success');
  }

  // ---- 화면 보기: 모두 보기 · 큰 화면 · 멀티 화면(4분할) · 확대 화면 · 3D 화면 ----
  // 모두 보기 = 왼쪽 큰 화면(라이브) + 오른쪽 작은 화면 3개(멀티 · 확대 · 3D)를 한 번에.
  // 확대·3D 는 보기 전용이다. 사진 캡처·녹화는 어느 화면에서든 원본 전체 프레임을 저장한다.
  const VIEWS = ['all', 'single', 'multi', 'zoom', '3d'];
  const VIEW_NAME = { all: '모두 보기', single: '큰 화면', multi: '멀티 화면', zoom: '확대 화면', '3d': '3D 화면' };
  const VIEW_HINT = {
    all: '큰 화면을 누르면 그 곳을 확대 · 작은 화면 제목을 누르면 크게',
    single: '',
    multi: "'정지영상'으로 칸 채우기 · 칸 클릭으로 교체",
    zoom: '휠 확대 · 드래그 이동 · 더블클릭 가운데 · 저장은 원본 전체',
    '3d': '밝을수록 높게 · 드래그 회전 · 휠 확대 · 저장은 원본 전체',
  };
  const ZOOM_STEPS = [1.5, 2, 3, 4, 6, 8];
  const view = { mode: 'single', z: 2, cx: 0.5, cy: 0.5 };
  { const z = parseFloat(prefGet('slitlamp-zoom')); if (z >= 1.25 && z <= 8) view.z = z; }
  let zoomMapTimer = null;
  const usesQuad = (m) => m === 'multi' || m === 'all';
  const usesD3 = (m) => m === '3d' || m === 'all';

  function setView(mode, opts = {}) {
    if (!VIEWS.includes(mode)) mode = 'all';
    if (mode === view.mode) return;
    const prev = view.mode;
    view.mode = mode;
    if (state.quad !== usesQuad(mode)) toggleQuad();
    if (usesD3(prev) && !usesD3(mode)) D3.stop();
    placeViews();
    const frame = $('video-frame');
    frame.classList.toggle('quad', mode === 'multi');
    frame.classList.toggle('zoom', mode === 'zoom');
    frame.classList.toggle('d3', mode === '3d');
    if (usesD3(mode) && !usesD3(prev)) D3.start(); else D3.touch();
    const zv = $('zoom-video');                          // 확대 칸 영상은 모두 보기에서만 재생
    if (mode === 'all' && zv.srcObject) zv.play().catch(() => {}); else zv.pause();
    clearInterval(zoomMapTimer);
    zoomMapTimer = mode === 'zoom' ? setInterval(drawZoomMap, 150) : null;
    fitPanes();
    applyZoom();
    syncViewUI();
    prefSet('slitlamp-view', mode);
    if (!opts.quiet && mode !== 'multi') {
      setStatus(mode === 'all' ? "모두 보기 · '정지영상'은 멀티 화면 칸 채우기" : VIEW_NAME[mode], state.stream ? 'ready' : 'idle', true);
    }
  }
  /** 모두 보기: 4분할 격자·3D 캔버스를 오른쪽 작은 화면으로, 아니면 큰 화면 안으로 */
  function placeViews() {
    const frame = $('video-frame'), q = $('quad-grid'), c = $('d3-canvas');
    if (view.mode === 'all') {
      if (q.parentElement !== $('pane-multi')) $('pane-multi').appendChild(q);
      if (c.parentElement !== $('pane-3d')) $('pane-3d').appendChild(c);
    } else if (q.parentElement !== frame) {
      frame.insertBefore(q, $('d3-msg'));
      frame.insertBefore(c, $('d3-msg'));
    }
  }
  /** 작은 화면 3개가 영상 비율에 맞게 — 오른쪽 열 폭을 높이에서 계산 */
  function fitPanes() {
    if (view.mode !== 'all') return;
    const st = $('stage'), v = $('video');
    if (!st.clientHeight) return;
    const ar = v.videoWidth && v.videoHeight ? v.videoWidth / v.videoHeight : 16 / 9;
    const paneH = (st.clientHeight - 16) / 3 - 28;
    const w = Math.max(200, Math.min(st.clientWidth * 0.36, paneH * ar));
    $('side-panes').style.width = Math.round(w) + 'px';
  }
  function syncViewUI() {
    document.body.dataset.view = view.mode;
    document.querySelectorAll('#view-seg [data-view]').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.view === view.mode)));
    $('view-hint').textContent = VIEW_HINT[view.mode] || '';
    $('zoom-level').textContent = '×' + view.z.toFixed(1);
    $('pane-zoom-level').textContent = '×' + view.z.toFixed(1);
    $('hud-view').textContent = view.mode === 'zoom' ? `확대 ×${view.z.toFixed(1)}` : (view.mode === '3d' ? '3D' : '');
    $('d3-save').disabled = !(usesD3(view.mode) && state.stream && state.currentPatientId && D3.ok());
  }

  // 확대: 영상 좌표(0~1)의 (cx, cy) 를 화면 가운데에 두고 z 배로 키운다
  // 확대 화면 = 큰 영상 자체를, 모두 보기 = 오른쪽 확대 칸(별도 video)을 키운다
  function zoomTarget() {
    if (view.mode === 'zoom') return { box: $('video-frame'), media: [$('video'), $('freeze')] };
    if (view.mode === 'all') return { box: $('pane-zoom'), media: [$('zoom-video')] };
    return null;
  }
  function zoomGeom(box) {
    box = box || (zoomTarget() || {}).box;
    const v = $('video');
    if (!box) return null;
    const W = box.clientWidth, H = box.clientHeight, vw = v.videoWidth, vh = v.videoHeight;
    if (!W || !H || !vw || !vh) return null;
    const k = Math.min(W / vw, H / vh), dw = vw * k, dh = vh * k;
    return { W, H, ox: (W - dw) / 2, oy: (H - dh) / 2, dw, dh };
  }
  function applyZoom() {
    const t = zoomTarget();
    for (const e of [$('video'), $('freeze'), $('zoom-video')]) if (!t || !t.media.includes(e)) e.style.transform = '';
    const g = t ? zoomGeom(t.box) : null;
    if (!g) return;
    const z = view.z;
    const hx = g.W / 2 / (z * g.dw), hy = g.H / 2 / (z * g.dh);   // 보이는 반폭·반높이 (영상 좌표)
    view.cx = hx >= 0.5 ? 0.5 : Math.min(1 - hx, Math.max(hx, view.cx));
    view.cy = hy >= 0.5 ? 0.5 : Math.min(1 - hy, Math.max(hy, view.cy));
    const tx = g.W / 2 - z * (g.ox + view.cx * g.dw), ty = g.H / 2 - z * (g.oy + view.cy * g.dh);
    const tr = `translate(${tx.toFixed(1)}px, ${ty.toFixed(1)}px) scale(${z})`;
    t.media.forEach((e) => { e.style.transform = tr; });
    drawZoomMap();
    if (view.mode === 'all') {                           // 큰 화면 위에 확대 칸이 보여 주는 곳 표시
      const b = zoomGeom($('video-frame')), roi = $('zoom-roi');
      if (b) {
        const rx = Math.min(0.5, hx), ry = Math.min(0.5, hy);
        roi.style.left = (b.ox + (view.cx - rx) * b.dw).toFixed(1) + 'px';
        roi.style.top = (b.oy + (view.cy - ry) * b.dh).toFixed(1) + 'px';
        roi.style.width = (2 * rx * b.dw).toFixed(1) + 'px';
        roi.style.height = (2 * ry * b.dh).toFixed(1) + 'px';
      }
    }
  }
  function setZoom(z, anchor) {
    z = Math.min(8, Math.max(1.25, z));
    const g = zoomGeom();
    if (g && anchor) {                                   // 커서 아래 지점이 그대로 있게
      const qx = view.cx + (anchor.x - g.W / 2) / (view.z * g.dw), qy = view.cy + (anchor.y - g.H / 2) / (view.z * g.dh);
      view.cx = qx - (anchor.x - g.W / 2) / (z * g.dw);
      view.cy = qy - (anchor.y - g.H / 2) / (z * g.dh);
    }
    view.z = z;
    prefSet('slitlamp-zoom', String(Math.round(z * 100) / 100));
    applyZoom();
    syncViewUI();
  }
  function stepZoom(dir) {
    const z = dir > 0 ? (ZOOM_STEPS.find((s) => s > view.z + 0.01) || 8) : ([...ZOOM_STEPS].reverse().find((s) => s < view.z - 0.01) || 1.25);
    setZoom(z);
  }
  function bindZoomPointer() {
    const frame = $('video-frame');
    const live = (e) => state.stream && !e.target.closest('button, .fs-bar, .zoom-map');
    // 끌어서 이동 · 휠 확대 · 더블클릭 가운데 (확대 화면 = 큰 영상, 모두 보기 = 오른쪽 확대 칸)
    const panOn = (el, active) => {
      let drag = null;
      el.addEventListener('pointerdown', (e) => {
        if (!active() || !live(e) || e.button !== 0) return;
        drag = { x: e.clientX, y: e.clientY, id: e.pointerId };
        el.setPointerCapture(e.pointerId);
        el.classList.add('dragging');
      });
      el.addEventListener('pointermove', (e) => {
        if (!drag || e.pointerId !== drag.id) return;
        const g = zoomGeom(); if (!g) return;
        view.cx -= (e.clientX - drag.x) / (view.z * g.dw);
        view.cy -= (e.clientY - drag.y) / (view.z * g.dh);
        drag.x = e.clientX; drag.y = e.clientY;
        applyZoom();
      });
      const end = () => { drag = null; el.classList.remove('dragging'); };
      el.addEventListener('pointerup', end);
      el.addEventListener('pointercancel', end);
      el.addEventListener('wheel', (e) => {
        if (!active() || !live(e)) return;
        e.preventDefault();
        const r = el.getBoundingClientRect();
        setZoom(view.z * Math.exp(-e.deltaY * 0.0015), { x: e.clientX - r.left, y: e.clientY - r.top });
      }, { passive: false });
      el.addEventListener('dblclick', (e) => { if (active() && live(e)) { view.cx = 0.5; view.cy = 0.5; applyZoom(); } });
    };
    panOn(frame, () => view.mode === 'zoom');
    panOn($('pane-zoom'), () => view.mode === 'all');
    // 모두 보기: 큰 화면을 누르거나 끌면 그 곳을 오른쪽 확대 칸에
    let aim = false;
    const aimAt = (e) => {
      const b = zoomGeom(frame), r = frame.getBoundingClientRect();
      if (!b) return;
      view.cx = (e.clientX - r.left - b.ox) / b.dw;
      view.cy = (e.clientY - r.top - b.oy) / b.dh;
      applyZoom();
    };
    frame.addEventListener('pointerdown', (e) => {
      if (view.mode !== 'all' || !live(e) || e.button !== 0) return;
      aim = true;
      frame.setPointerCapture(e.pointerId);
      aimAt(e);
    });
    frame.addEventListener('pointermove', (e) => { if (aim) aimAt(e); });
    frame.addEventListener('pointerup', () => { aim = false; });
    frame.addEventListener('pointercancel', () => { aim = false; });
    // 미니맵: 누르거나 끌어서 그 위치로
    const map = $('zoom-map');
    let mapDrag = false;
    const goto = (e) => {
      const r = map.getBoundingClientRect();
      view.cx = (e.clientX - r.left) / r.width; view.cy = (e.clientY - r.top) / r.height;
      applyZoom();
    };
    map.addEventListener('pointerdown', (e) => { e.stopPropagation(); mapDrag = true; map.setPointerCapture(e.pointerId); goto(e); });
    map.addEventListener('pointermove', (e) => { if (mapDrag) goto(e); });
    map.addEventListener('pointerup', () => { mapDrag = false; });
    map.addEventListener('dblclick', (e) => e.stopPropagation());
  }
  function drawZoomMap() {
    if (view.mode !== 'zoom') return;
    const v = $('video'), c = $('zoom-map'), g = zoomGeom();
    if (!g) return;
    const src = state.isPaused ? $('freeze') : v;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const cw = 168, ch = Math.round(cw * v.videoHeight / v.videoWidth);
    if (c.width !== cw * dpr || c.height !== ch * dpr) { c.width = cw * dpr; c.height = ch * dpr; c.style.height = ch + 'px'; }
    const x = c.getContext('2d');
    if (meibo.on) x.filter = 'grayscale(1)'; else x.filter = 'none';
    x.drawImage(src, 0, 0, c.width, c.height);
    x.filter = 'none';
    const hw = Math.min(0.5, g.W / 2 / (view.z * g.dw)), hh = Math.min(0.5, g.H / 2 / (view.z * g.dh));
    const rx = (view.cx - hw) * c.width, ry = (view.cy - hh) * c.height, rw = 2 * hw * c.width, rh = 2 * hh * c.height;
    x.fillStyle = 'rgba(0,0,0,.5)';
    x.beginPath(); x.rect(0, 0, c.width, c.height); x.rect(rx, ry, rw, rh); x.fill('evenodd');
    x.strokeStyle = '#33c2b1'; x.lineWidth = 2 * dpr;
    x.strokeRect(rx + dpr, ry + dpr, rw - 2 * dpr, rh - 2 * dpr);
  }

  // 3D: 영상 밝기를 높이로 바꾼 표면을 WebGL 로 그린다 (색 = 원본 영상 또는 높이 컬러맵)
  const D3 = (() => {
    const MAXG = 200;                                    // 격자 긴 변 꼭짓점 수 (200×113 ≈ 2.3만)
    let gl = null, prog = null, failed = '';
    const loc = {}, buf = {};
    let tex = null, GW = 0, GH = 0, aspect = 0, nIdx = 0;
    let Hr = null, Hs = null, N = null, tmp = null;
    let small = null, sctx = null, texC = null, tctx = null;
    let running = false, raf = 0, dirty = true, lastData = -1e9, forceData = false, opaque = false;
    const DEF = { yaw: -0.42, pitch: 0.98, k: 1 };
    const cam = { ...DEF };
    const ui = { scale: 0.4, map: false };

    const VS = `
      attribute vec2 a_xy; attribute vec2 a_uv; attribute float a_h; attribute vec3 a_n;
      uniform mat4 u_mvp; uniform float u_scale;
      varying vec2 v_uv; varying vec3 v_n; varying float v_h;
      void main() { v_uv = a_uv; v_n = a_n; v_h = a_h; gl_Position = u_mvp * vec4(a_xy, a_h * u_scale, 1.0); }`;
    const FS = `
      precision mediump float;
      uniform sampler2D u_tex; uniform float u_map; uniform float u_gray;
      varying vec2 v_uv; varying vec3 v_n; varying float v_h;
      vec3 cmap(float t) {   // 낮음 파랑 → 청록 → 초록 → 노랑 → 높음 빨강
        t = clamp(t, 0.0, 1.0);
        return clamp(vec3(1.5 - abs(4.0 * t - 3.0), 1.5 - abs(4.0 * t - 2.0), 1.5 - abs(4.0 * t - 1.0)), 0.0, 1.0);
      }
      void main() {
        vec3 c = texture2D(u_tex, v_uv).rgb;
        if (u_gray > 0.5) c = vec3(dot(c, vec3(0.299, 0.587, 0.114)));
        if (u_map > 0.5) c = cmap(v_h);
        float d = max(dot(normalize(v_n), normalize(vec3(-0.35, 0.45, 0.82))), 0.0);
        gl_FragColor = vec4(c * (0.42 + 0.7 * d), 1.0);
      }`;

    function init() {
      if (gl) return true;
      if (failed) return false;
      const c = $('d3-canvas');
      const opts = { antialias: true, preserveDrawingBuffer: true };
      gl = c.getContext('webgl', opts) || c.getContext('experimental-webgl', opts);
      if (!gl) { failed = '이 브라우저(그래픽)에서는 3D 화면을 쓸 수 없습니다 — WebGL 미지원'; return false; }
      const sh = (type, src) => {
        const o = gl.createShader(type); gl.shaderSource(o, src); gl.compileShader(o);
        if (!gl.getShaderParameter(o, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(o) || 'shader');
        return o;
      };
      try {
        prog = gl.createProgram();
        gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS));
        gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS));
        gl.linkProgram(prog);
        if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog) || 'link');
      } catch (e) { failed = '3D 화면을 시작하지 못했습니다: ' + e.message; gl = null; return false; }
      for (const a of ['a_xy', 'a_uv', 'a_h', 'a_n']) loc[a] = gl.getAttribLocation(prog, a);
      for (const u of ['u_mvp', 'u_scale', 'u_tex', 'u_map', 'u_gray']) loc[u] = gl.getUniformLocation(prog, u);
      tex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      small = document.createElement('canvas'); sctx = small.getContext('2d', { willReadFrequently: true });
      texC = document.createElement('canvas'); tctx = texC.getContext('2d');
      if (!c.dataset.bound) { bindPointer(c); c.dataset.bound = '1'; }
      c.addEventListener('webglcontextlost', (e) => { e.preventDefault(); gl = null; GW = GH = 0; aspect = 0; for (const k in buf) delete buf[k]; }, { once: true });
      c.addEventListener('webglcontextrestored', () => { if (running) start(); }, { once: true });
      return true;
    }
    function upload(name, target, data, usage) {
      if (!buf[name]) buf[name] = gl.createBuffer();
      gl.bindBuffer(target, buf[name]);
      gl.bufferData(target, data, usage);
    }
    function buildMesh(vw, vh) {
      aspect = vw / vh;
      if (aspect >= 1) { GW = MAXG; GH = Math.max(2, Math.round(MAXG / aspect)); } else { GH = MAXG; GW = Math.max(2, Math.round(MAXG * aspect)); }
      const n = GW * GH, xy = new Float32Array(n * 2), uv = new Float32Array(n * 2);
      for (let j = 0; j < GH; j++) for (let i = 0; i < GW; i++) {
        const k = j * GW + i, u = i / (GW - 1), v = j / (GH - 1);
        xy[2 * k] = (u - 0.5) * aspect; xy[2 * k + 1] = 0.5 - v;
        uv[2 * k] = u; uv[2 * k + 1] = v;
      }
      const idx = new Uint16Array((GW - 1) * (GH - 1) * 6);
      let q = 0;
      for (let j = 0; j < GH - 1; j++) for (let i = 0; i < GW - 1; i++) {
        const a = j * GW + i, b = a + 1, c = a + GW, d = c + 1;
        idx[q++] = a; idx[q++] = c; idx[q++] = b; idx[q++] = b; idx[q++] = c; idx[q++] = d;
      }
      nIdx = q;
      Hr = new Float32Array(n); Hs = new Float32Array(n); tmp = new Float32Array(n); N = new Float32Array(n * 3);
      upload('xy', gl.ARRAY_BUFFER, xy, gl.STATIC_DRAW);
      upload('uv', gl.ARRAY_BUFFER, uv, gl.STATIC_DRAW);
      upload('idx', gl.ELEMENT_ARRAY_BUFFER, idx, gl.STATIC_DRAW);
      upload('h', gl.ARRAY_BUFFER, Hs, gl.DYNAMIC_DRAW);
      upload('n', gl.ARRAY_BUFFER, N, gl.DYNAMIC_DRAW);
      small.width = GW; small.height = GH;
      texC.width = Math.min(1024, vw); texC.height = Math.max(1, Math.round(texC.width / aspect));
    }
    function updateData(src, vw, vh) {
      if (!GW || Math.abs(vw / vh - aspect) > 1e-3 || texC.width !== Math.min(1024, vw)) buildMesh(vw, vh);
      sctx.drawImage(src, 0, 0, GW, GH);
      const d = sctx.getImageData(0, 0, GW, GH).data;
      const n = GW * GH;
      for (let k = 0; k < n; k++) Hr[k] = (0.299 * d[4 * k] + 0.587 * d[4 * k + 1] + 0.114 * d[4 * k + 2]) / 255;
      // 3×3 평균 (센서 잡티로 표면이 거칠어지지 않게) — 가로 → 세로
      for (let j = 0; j < GH; j++) {
        const r = j * GW;
        for (let i = 0; i < GW; i++) tmp[r + i] = (Hr[r + Math.max(0, i - 1)] + Hr[r + i] + Hr[r + Math.min(GW - 1, i + 1)]) / 3;
      }
      for (let j = 0; j < GH; j++) {
        const up = Math.max(0, j - 1) * GW, dn = Math.min(GH - 1, j + 1) * GW, r = j * GW;
        for (let i = 0; i < GW; i++) Hs[r + i] = (tmp[up + i] + tmp[r + i] + tmp[dn + i]) / 3;
      }
      gl.bindBuffer(gl.ARRAY_BUFFER, buf.h);
      gl.bufferSubData(gl.ARRAY_BUFFER, 0, Hs);
      normals();
      tctx.filter = meibo.on ? 'grayscale(1)' : 'none';
      tctx.drawImage(src, 0, 0, texC.width, texC.height);
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, texC);
    }
    function normals() {
      if (!gl || !GW) return;
      const s = ui.scale, sx = s / (2 * aspect / (GW - 1)), sy = s / (2 / (GH - 1));
      for (let j = 0; j < GH; j++) {
        const up = Math.max(0, j - 1) * GW, dn = Math.min(GH - 1, j + 1) * GW, r = j * GW;
        for (let i = 0; i < GW; i++) {
          const nx = -(Hs[r + Math.min(GW - 1, i + 1)] - Hs[r + Math.max(0, i - 1)]) * sx;
          const ny = -(Hs[up + i] - Hs[dn + i]) * sy;          // 영상 위쪽(j 작음)이 +y
          const l = Math.hypot(nx, ny, 1), k = 3 * (r + i);
          N[k] = nx / l; N[k + 1] = ny / l; N[k + 2] = 1 / l;
        }
      }
      gl.bindBuffer(gl.ARRAY_BUFFER, buf.n);
      gl.bufferSubData(gl.ARRAY_BUFFER, 0, N);
    }
    // 열 우선(column-major) 4×4 행렬
    const mul = (a, b) => {
      const o = new Array(16);
      for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) {
        let v = 0; for (let k = 0; k < 4; k++) v += a[k * 4 + r] * b[c * 4 + k];
        o[c * 4 + r] = v;
      }
      return o;
    };
    function matrix(ar) {
      const f = 1 / Math.tan((38 * Math.PI / 180) / 2), near = 0.05, far = 60;
      const P = [f / ar, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) / (near - far), -1, 0, 0, (2 * far * near) / (near - far), 0];
      const fit = Math.max(1.05, 0.62 * aspect / ar + 0.55, 1.3 * Math.sin(cam.pitch) + 0.55);   // 표면 전체가 보이는 거리
      const dist = fit * 1.55 * cam.k;
      const cy = Math.cos(cam.yaw), sy = Math.sin(cam.yaw), a = -cam.pitch, ca = Math.cos(a), sa = Math.sin(a);
      const T = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0.04, -dist, 1];
      const Rx = [1, 0, 0, 0, 0, ca, sa, 0, 0, -sa, ca, 0, 0, 0, 0, 1];
      const Rz = [cy, sy, 0, 0, -sy, cy, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
      const Z = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, -0.3 * ui.scale, 1];
      return mul(P, mul(T, mul(Rx, mul(Rz, Z))));
    }
    function attr(name, size) {
      const l = loc[name]; if (l < 0) return;
      gl.bindBuffer(gl.ARRAY_BUFFER, buf[name.slice(2)]);
      gl.enableVertexAttribArray(l);
      gl.vertexAttribPointer(l, size, gl.FLOAT, false, 0, 0);
    }
    function render() {
      if (!gl || !GW) return;
      const c = $('d3-canvas'), dpr = Math.min(2, window.devicePixelRatio || 1);
      const w = Math.max(1, Math.round(c.clientWidth * dpr)), h = Math.max(1, Math.round(c.clientHeight * dpr));
      if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
      gl.viewport(0, 0, w, h);
      if (opaque) gl.clearColor(0.035, 0.045, 0.06, 1); else gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.enable(gl.DEPTH_TEST);
      gl.useProgram(prog);
      attr('a_xy', 2); attr('a_uv', 2); attr('a_h', 1); attr('a_n', 3);
      gl.uniformMatrix4fv(loc.u_mvp, false, new Float32Array(matrix(w / h)));
      gl.uniform1f(loc.u_scale, ui.scale);
      gl.uniform1f(loc.u_map, ui.map ? 1 : 0);
      gl.uniform1f(loc.u_gray, meibo.on ? 1 : 0);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.uniform1i(loc.u_tex, 0);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, buf.idx);
      gl.drawElements(gl.TRIANGLES, nIdx, gl.UNSIGNED_SHORT, 0);
    }
    function source() {
      const fr = $('freeze'), v = $('video');
      if (!state.stream) return null;
      if (state.isPaused) return fr.width ? { el: fr, w: fr.width, h: fr.height } : null;
      return v.videoWidth ? { el: v, w: v.videoWidth, h: v.videoHeight } : null;
    }
    function loop(t) {
      if (!running) return;
      raf = requestAnimationFrame(loop);
      if (!gl || document.hidden || document.body.classList.contains('pro-on')) return;   // Pro 화면·숨은 탭에서는 쉼
      const src = source();
      if (src && (forceData || t - lastData > (state.isPaused ? 500 : 50))) {   // 라이브 약 20 fps 로 표면 갱신
        updateData(src.el, src.w, src.h);
        lastData = t; forceData = false; dirty = true;
      }
      if (dirty) { render(); dirty = false; }
    }
    function bindPointer(c) {
      let drag = null;
      c.addEventListener('pointerdown', (e) => {
        if (e.button !== 0) return;
        drag = { x: e.clientX, y: e.clientY }; c.setPointerCapture(e.pointerId); c.classList.add('dragging');
      });
      c.addEventListener('pointermove', (e) => {
        if (!drag) return;
        cam.yaw += (e.clientX - drag.x) * 0.008;
        cam.pitch = Math.min(1.45, Math.max(0, cam.pitch + (e.clientY - drag.y) * 0.006));
        drag = { x: e.clientX, y: e.clientY }; dirty = true;
      });
      const end = () => { drag = null; c.classList.remove('dragging'); };
      c.addEventListener('pointerup', end);
      c.addEventListener('pointercancel', end);
      c.addEventListener('wheel', (e) => { e.preventDefault(); cam.k = Math.min(3, Math.max(0.35, cam.k * Math.exp(e.deltaY * 0.0012))); dirty = true; }, { passive: false });
      c.addEventListener('dblclick', reset);
    }
    function start() {
      if (!init()) { $('d3-msg').textContent = failed; return; }
      $('d3-msg').textContent = '드래그: 회전 · 휠: 확대 · 더블클릭: 시점 초기화';
      running = true; dirty = true; forceData = true;
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(loop);
    }
    function stop() { running = false; cancelAnimationFrame(raf); }
    function reset() { Object.assign(cam, DEF); dirty = true; }
    function setScale(v) { ui.scale = Math.max(0, Math.min(1, v)); normals(); dirty = true; }
    function setMode(m) { ui.map = m === 'map'; dirty = true; }
    function touch(data) { dirty = true; if (data) forceData = true; }
    async function snapshot() {
      if (!gl || !GW) return null;
      opaque = true; render(); opaque = false;
      const blob = await new Promise((res) => $('d3-canvas').toBlob(res, 'image/png'));
      dirty = true;
      return blob;
    }
    return { start, stop, reset, setScale, setMode, touch, snapshot, ok: () => !failed };
  })();

  async function saveD3() {
    const patient = currentPatient();
    if (!patient) { toast('환자를 먼저 선택하세요.', 'error'); return; }
    const blob = await D3.snapshot();
    if (!blob) { toast('3D 화면이 아직 준비되지 않았습니다.', 'error'); return; }
    await persistCapture(patient, 'photo', blob, 'png', $('eye-select').value, null, '3D');
  }

  // ---- thumbnails ----
  const DOW = ['일', '월', '화', '수', '목', '금', '토'];
  const hms = (d) => [d.getHours(), d.getMinutes(), d.getSeconds()].map((n) => String(n).padStart(2, '0')).join(':');
  let thumbSeq = 0;
  async function renderThumbs() {
    const my = ++thumbSeq, pid = state.currentPatientId;
    const list = $('thumb-list');
    const empty = $('thumb-empty');
    const clear = () => Array.from(list.querySelectorAll('.thumb, .thumb-day')).forEach(n => n.remove());
    if (!pid) {
      clear();
      empty.style.display = '';
      empty.querySelector('div').innerHTML = '환자를 선택하세요';
      $('thumb-count').textContent = '0';
      return;
    }
    let items = [];
    try {
      items = await api(`/captures?patient_id=${pid}&order=desc`);
    } catch (e) {
      if (my === thumbSeq) toast('촬영 목록 조회 실패: ' + e.message, 'error');
    }
    if (my !== thumbSeq || pid !== state.currentPatientId) return;   // 그 사이 다른 환자·필터로 바뀜 → 늦은 결과는 버림
    clear();
    $('thumb-count').textContent = items.length;
    const f = state.thumbFilter || 'all';
    const shown = items.filter((c) => f === 'all' || (f === 'video' ? c.media_type === 'video' : c.eye === f));
    if (shown.length === 0) {
      empty.style.display = '';
      empty.querySelector('div').innerHTML = items.length ? '조건에 맞는 영상이 없습니다' : '선택한 환자의 촬영 이미지가 없습니다';
      return;
    }
    empty.style.display = 'none';
    // 촬영일별 묶음 (최근 → 과거)
    let day = '';
    const perDay = {};
    for (const c of shown) { const d = (c.captured_at || '').slice(0, 10); perDay[d] = (perDay[d] || 0) + 1; }
    for (const c of shown) {
      const ts = parseTs(c.captured_at);
      const d = (c.captured_at || '').slice(0, 10);
      if (d !== day) {
        day = d;
        const h = document.createElement('div');
        h.className = 'thumb-day';
        h.title = `${d.replace(/-/g, '.')} (${DOW[ts.getDay()] || ''}) · ${perDay[d]}장`;
        h.innerHTML = `<span class="td-y">${d.slice(0, 4)}</span><span class="td-date">${d.slice(5).replace('-', '.')}</span><span class="td-n">${DOW[ts.getDay()] || ''} · ${perDay[d]}장</span>`;
        list.appendChild(h);
      }
      const el = document.createElement('div');
      el.className = 'thumb';
      el.tabIndex = 0;
      const eye = c.eye && c.eye !== 'NA' ? c.eye : '';
      const isVideo = c.media_type === 'video';
      const dur = isVideo ? `▶ ${Math.round((c.duration_ms || 0) / 1000)}s` : '';
      el.innerHTML = `
        ${isVideo
          ? '<div class="tvid"><svg class="ic"><use href="#i-play"/></svg></div>'
          : `<img src="${c.url}" alt="캡처 ${fmt(ts)}" loading="lazy">`}
        <span class="thumb-badges">
          ${eye ? `<span class="thumb-badge e-${eye}">${eye}</span>` : ''}
          ${dur ? `<span class="thumb-badge video">${dur}</span>` : ''}
        </span>
        <div class="thumb-caption">
          <span><span class="thumb-time">${hms(ts)}</span>${c.note ? `<span class="thumb-note">${escHtml(c.note)}</span>` : ''}</span>
        </div>`;
      el.title = [fmtDT(ts), eye, c.note].filter(Boolean).join(' · ');
      el.addEventListener('click', () => openViewer(c, ts));
      el.addEventListener('keydown', (e) => { if (e.key === 'Enter') openViewer(c, ts); });
      list.appendChild(el);
    }
    list.scrollLeft = 0;                    // 최신 촬영(왼쪽)부터
  }

  function setThumbsFolded(on) {
    $('thumbs').classList.toggle('folded', on);
    const b = $('thumbs-fold');
    b.setAttribute('aria-expanded', String(!on));
    b.setAttribute('aria-label', on ? '목록 펼치기' : '목록 접기');
    b.title = on ? '촬영 이미지 목록 펼치기' : '촬영 이미지 목록 접기 (영상을 더 크게)';
    prefSet('slitlamp-thumbs-folded', on ? '1' : '0');
  }

  function openViewer(c, ts) {
    const dlg = $('viewer-dialog');
    const body = $('viewer-body');
    body.innerHTML = '';
    const patient = state.patients.find(p => p.id === c.patient_id);
    $('viewer-title').textContent = `${patient?.name || ''} · ${fmtDT(ts)}${c.eye && c.eye !== 'NA' ? ' · ' + c.eye : ''}`;
    if (c.media_type === 'photo') {
      const img = document.createElement('img'); img.src = c.url; body.appendChild(img);
    } else {
      const v = document.createElement('video'); v.src = c.url; v.controls = true; v.autoplay = true; body.appendChild(v);
    }
    const dl = $('viewer-download');
    dl.href = c.url;
    dl.download = c.filename || (c.url.split('/').pop()) || 'capture';
    dlg.showModal();
  }

  // ---- status / toast ----
  function updateCaptureButtons() {
    const has = !!state.stream && !!state.currentPatientId;
    $('btn-capture').disabled = !has;
    $('btn-record').disabled = !has;
    $('btn-pause').disabled = !state.stream;
    $('btn-fs-capture').disabled = !has;
    $('btn-fs-freeze').disabled = !has;
    $('btn-fs-record').disabled = !has;
    $('video-frame').classList.toggle('live', !!state.stream);
    $('btn-freeze').disabled = !has;
    $('btn-save-quad').disabled = !has;
    syncViewUI();
  }
  function syncCamChip() {
    const v = $('video'), track = state.stream && state.stream.getVideoTracks()[0];
    const dot = $('cam-chip-dot');
    dot.classList.toggle('ready', !!track);
    if (!track) { $('cam-chip-text').textContent = '카메라 꺼짐'; return; }
    const name = (track.label || '카메라').replace(/\s*\([0-9a-f]{4}:[0-9a-f]{4}\)\s*$/i, '');
    $('cam-chip-text').textContent = `${isSony(track.label) ? '★ ' : ''}${name}${v.videoWidth ? ` · ${v.videoHeight >= 2000 ? '4K' : v.videoHeight + 'p'}` : ''}`;
    $('cam-chip').title = `${track.label} · ${v.videoWidth}×${v.videoHeight} (설정에서 변경)`;
  }

  function setStatus(text, kind, transient) {
    syncCamChip();
    $('status-text').textContent = text;
    const dot = $('status-dot');
    dot.classList.remove('ready', 'recording');
    if (kind === 'ready') dot.classList.add('ready');
    if (kind === 'recording') dot.classList.add('recording');
    if (state.statusResetTimer) clearTimeout(state.statusResetTimer);
    if (transient) {
      state.statusResetTimer = setTimeout(() => {
        const v = $('video'), tr = state.stream && state.stream.getVideoTracks()[0];
        if (state.isRecording) setStatus('녹화 중', 'recording');
        else if (v.videoWidth) setStatus(`${v.videoWidth}×${v.videoHeight}${isSony(tr && tr.label) ? ' · Sony' : ''}`, 'ready');
        else setStatus('대기 중', 'idle');
      }, 2500);
    }
  }
  function showHintError(msg) {
    const hint = $('hint');
    hint.classList.add('error');
    $('hint-body').innerHTML = `<strong>안내:</strong> ${msg}`;
    hint.style.display = 'flex';
  }
  function toast(msg, kind) {
    const wrap = $('toast-wrap');
    const el = document.createElement('div');
    el.className = 'toast' + (kind ? ' ' + kind : '');
    el.textContent = msg;
    wrap.appendChild(el);
    requestAnimationFrame(() => el.classList.add('show'));
    setTimeout(() => {
      el.classList.remove('show');
      setTimeout(() => el.remove(), 220);
    }, 3200);
  }

  // Pro 모드(pro.js)에서 쓰는 공개 API
  window.SlitApp = {
    state, api, currentPatient, persistCapture, renderThumbs, toast, setStatus,
    startCamera, openPatientDialog, parseTs, fmtDT,
  };

  init();
})();
