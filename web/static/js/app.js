/* 슬릿램프 영상 시스템 웹앱 프런트엔드.
 * - navigator.mediaDevices.getUserMedia 로 캡처 장비 라이브
 * - canvas.toBlob (사진) / MediaRecorder (동영상)
 * - 저장: (a) 서버 POST /api/v1/captures  (b) File System Access API 로 지정 폴더에도 동시 write
 */
(() => {
  const $ = (id) => document.getElementById(id);
  const API = '/api/v1';

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
  async function api(path, options = {}) {
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
    bindEvents();
    syncEye();
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
    document.querySelectorAll('#eye-seg [data-eye]').forEach((b) => b.addEventListener('click', () => setEye(b.dataset.eye)));
    $('eye-select').addEventListener('change', syncEye);
    document.querySelectorAll('#thumb-filter .tf').forEach((b) => b.addEventListener('click', () => {
      state.thumbFilter = b.dataset.f;
      document.querySelectorAll('#thumb-filter .tf').forEach((x) => x.classList.toggle('on', x === b));
      renderThumbs();
    }));
    $('hint-close').addEventListener('click', () => $('hint').style.display = 'none');
    $('btn-folder').addEventListener('click', pickFolder);

    $('btn-start-camera').addEventListener('click', () => startCamera());
    $('camera-select').addEventListener('change', (e) => startCamera(e.target.value));
    $('btn-pause').addEventListener('click', togglePause);
    $('btn-capture').addEventListener('click', capturePhoto);
    $('btn-record').addEventListener('click', toggleRecord);
    $('btn-quad').addEventListener('click', toggleQuad);
    $('btn-freeze').addEventListener('click', freezeFrame);
    $('btn-save-quad').addEventListener('click', saveQuad);
    $('btn-clear-quad').addEventListener('click', clearQuad);
    document.querySelectorAll('#quad-grid .quad-cell').forEach((cell) => {
      cell.addEventListener('click', () => { if (state.quad) setQuadActive(+cell.dataset.i); });
    });

    $('viewer-close').addEventListener('click', () => $('viewer-dialog').close());
    $('viewer-close-2').addEventListener('click', () => $('viewer-dialog').close());

    document.addEventListener('keydown', (e) => {
      if (e.target.matches('input, textarea, select')) return;
      if (document.body.classList.contains('pro-on')) return;   // Pro 모드는 pro.js가 처리
      if (e.key === ' ') { e.preventDefault(); togglePause(); }
      else if (e.key.toLowerCase() === 'c') { if (!$('btn-capture').disabled) { e.preventDefault(); capturePhoto(); } }
      else if (e.key.toLowerCase() === 'r') { if (!$('btn-record').disabled) { e.preventDefault(); toggleRecord(); } }
    });
  }

  function debounce(fn, ms) {
    let t;
    return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
  }

  // ---- patients ----
  function currentPatient() {
    return state.patients.find(p => p.id === state.currentPatientId);
  }

  async function loadPatients() {
    const q = ($('patient-search').value || '').trim();
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
      state.currentPatientId = null;
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
      state.currentPatientId = inList ? state.currentPatientId : state.patients[0].id;
      sel.value = String(state.currentPatientId);
    }
    updateCaptureButtons();
    await renderThumbs();
    emitPatient();
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
  const EYE_TEXT = { OD: 'OD 우안', OS: 'OS 좌안', OU: 'OU 양안', NA: '안구 미지정' };
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
    const chip = $('hud-eye');
    chip.dataset.eye = v; chip.textContent = EYE_TEXT[v] || v;
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
  async function startCamera(deviceId) {
    if (state.isRecording) stopRecording();
    if (state.stream) { state.stream.getTracks().forEach(t => t.stop()); state.stream = null; }
    try {
      const video = $('video');
      const constraints = {
        video: deviceId ? { deviceId: { exact: deviceId } } : { width: { ideal: 1920 }, height: { ideal: 1080 } },
        audio: false,
      };
      const stream = await navigator.mediaDevices.getUserMedia(constraints);
      state.stream = stream;
      video.srcObject = stream;
      $('video-placeholder').style.display = 'none';
      video.onloadedmetadata = () => setStatus(`${video.videoWidth}×${video.videoHeight}`, 'ready');
      await populateCameraSelect();
      updateCaptureButtons();
    } catch (err) {
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
        opt.textContent = c.label || `카메라 ${i + 1}`;
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
  }

  // ---- capture ----
  let _fnSeq = 0;
  function buildFilename(patient, mediaType, ts, ext, eye, note) {
    const pad = (n, w = 2) => String(n).padStart(w, '0');
    const chart = (patient.chart_no || 'noChart').replace(/[^0-9A-Za-z._가-힣-]+/g, '_');
    const stamp = `${ts.getFullYear()}${pad(ts.getMonth() + 1)}${pad(ts.getDate())}_` +
      `${pad(ts.getHours())}${pad(ts.getMinutes())}${pad(ts.getSeconds())}${pad(ts.getMilliseconds(), 3)}`;
    const seq = pad((_fnSeq++) % 1000, 3);
    const tag = note === '4분할 합성' ? '_quad' : (note === '4분할' ? '_q' : '');
    return `${chart}_${stamp}_${seq}_${eye || 'NA'}${tag}.${ext}`;
  }

  async function capturePhoto() {
    const patient = currentPatient();
    if (!patient) { toast('환자를 먼저 선택하세요.', 'error'); return; }
    const video = $('video');
    if (!video.videoWidth) { toast('영상이 아직 준비되지 않았습니다.', 'error'); return; }
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const src = state.isPaused ? $('freeze') : video;
    canvas.getContext('2d').drawImage(src, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise(res => canvas.toBlob(res, 'image/png'));
    if (!blob) return;
    const eye = $('eye-select').value;
    await persistCapture(patient, 'photo', blob, 'png', eye, null);
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
    recorder.onstop = async () => {
      const blob = new Blob(chunks, { type: recorder.mimeType || 'video/webm' });
      const durationMs = Date.now() - state.recordStart;
      const ext = (blob.type && blob.type.includes('mp4')) ? 'mp4' : 'webm';
      await persistCapture(patient, 'video', blob, ext, $('eye-select').value, durationMs);
    };
    recorder.start();
    state.recorder = recorder;
    state.isRecording = true;
    state.recordStart = Date.now();
    $('rec-badge').classList.add('on');
    $('btn-record').classList.add('recording');
    $('rec-btn-label').textContent = '녹화 중지';
    setStatus('녹화 중', 'recording');
    state.recordTimer = setInterval(() => {
      const s = Math.floor((Date.now() - state.recordStart) / 1000);
      $('rec-time').textContent = `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
    }, 250);
  }

  function stopRecording() {
    if (!state.isRecording || !state.recorder) return;
    state.recorder.stop();
    state.isRecording = false;
    clearInterval(state.recordTimer);
    $('rec-badge').classList.remove('on');
    $('rec-time').textContent = '00:00';
    $('btn-record').classList.remove('recording');
    $('rec-btn-label').textContent = '녹화 시작';
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
    if (!IS_LOCAL && mediaType === 'photo' && ext === 'png') {
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
        toast('서버 저장 실패: ' + err.message, 'error');
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

    if (serverOk) document.dispatchEvent(new CustomEvent('slit:captures'));
    if (serverOk && !opts.silent) {
      renderThumbs();                      // 기다리지 않음 — 미리 보인 썸네일을 서버 목록으로 교체
      const where = folderOk ? '서버 + 지정 폴더' : (state.dirHandle ? '서버(폴더 실패)' : '서버');
      setStatus(`${mediaType === 'photo' ? '사진' : '동영상'} 저장됨 · ${where}`, 'ready', true);
    }
    return serverOk;
  }

  // ---- 4분할 정지영상 ----
  function quadCells() {
    return Array.from(document.querySelectorAll('#quad-grid .quad-cell'));
  }

  function toggleQuad() {
    state.quad = !state.quad;
    const frame = $('video-frame');
    frame.classList.toggle('quad', state.quad);
    $('btn-quad').classList.toggle('active', state.quad);
    $('btn-pause').style.display = state.quad ? 'none' : '';
    $('btn-save-quad').style.display = state.quad ? '' : 'none';
    $('btn-clear-quad').style.display = state.quad ? '' : 'none';
    if (state.quad) {
      clearQuad();
      startQuadLoop();
      setStatus("4분할 · '정지영상'으로 각 칸을 채우세요", 'ready');
    } else {
      stopQuadLoop();
      setStatus('단일 모드', 'ready');
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

  // ---- thumbnails ----
  const DOW = ['일', '월', '화', '수', '목', '금', '토'];
  const hms = (d) => [d.getHours(), d.getMinutes(), d.getSeconds()].map((n) => String(n).padStart(2, '0')).join(':');
  async function renderThumbs() {
    const list = $('thumb-list');
    const empty = $('thumb-empty');
    Array.from(list.querySelectorAll('.thumb, .thumb-day')).forEach(n => n.remove());
    if (!state.currentPatientId) {
      empty.style.display = 'block';
      empty.querySelector('div').innerHTML = '환자를 선택하세요';
      $('thumb-count').textContent = '0';
      return;
    }
    let items = [];
    try {
      items = await api(`/captures?patient_id=${state.currentPatientId}&order=desc`);
    } catch (e) {
      toast('촬영 목록 조회 실패: ' + e.message, 'error');
    }
    $('thumb-count').textContent = items.length;
    const f = state.thumbFilter || 'all';
    const shown = items.filter((c) => f === 'all' || (f === 'video' ? c.media_type === 'video' : c.eye === f));
    if (shown.length === 0) {
      empty.style.display = 'block';
      empty.querySelector('div').innerHTML = items.length ? '조건에 맞는 영상이 없습니다' : '선택한 환자의<br>촬영 이미지가 없습니다';
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
        h.innerHTML = `<span>${d.replace(/-/g, '.')} (${DOW[ts.getDay()] || ''})</span><span>${perDay[d]}장</span>`;
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
    dl.download = (c.url.split('/').pop()) || 'capture';
    dlg.showModal();
  }

  // ---- status / toast ----
  function updateCaptureButtons() {
    const has = !!state.stream && !!state.currentPatientId;
    $('btn-capture').disabled = !has;
    $('btn-record').disabled = !has;
    $('btn-pause').disabled = !state.stream;
    $('video-frame').classList.toggle('live', !!state.stream);
    $('btn-freeze').disabled = !has;
    $('btn-save-quad').disabled = !has;
  }
  function setStatus(text, kind, transient) {
    $('status-text').textContent = text;
    const dot = $('status-dot');
    dot.classList.remove('ready', 'recording');
    if (kind === 'ready') dot.classList.add('ready');
    if (kind === 'recording') dot.classList.add('recording');
    if (state.statusResetTimer) clearTimeout(state.statusResetTimer);
    if (transient) {
      state.statusResetTimer = setTimeout(() => {
        const v = $('video');
        if (v.videoWidth) setStatus(`${v.videoWidth}×${v.videoHeight}`, 'ready');
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
