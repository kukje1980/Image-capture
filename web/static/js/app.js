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
      const inList = state.patients.find(p => p.id === state.currentPatientId);
      state.currentPatientId = inList ? state.currentPatientId : state.patients[0].id;
      sel.value = String(state.currentPatientId);
    }
    updateCaptureButtons();
    await renderThumbs();
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
    const cur = root.getAttribute('data-theme');
    const isDark = cur ? cur === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
    const next = isDark ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem('slitlamp-theme', next); } catch (_) {}
    syncThemeIcon();
  }
  function syncThemeIcon() {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark' ||
      (!document.documentElement.getAttribute('data-theme') && matchMedia('(prefers-color-scheme: dark)').matches);
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
      $('btn-pause').innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg> 재개';
    } else {
      video.play();
      frame.classList.remove('paused');
      state.isPaused = false;
      $('btn-pause').innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg> 일시정지';
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
  async function persistCapture(patient, mediaType, blob, ext, eye, durationMs, note, opts = {}) {
    const ts = new Date();
    const filename = buildFilename(patient, mediaType, ts, ext, eye, note);

    // (a) 서버 저장 (환자 DB + 미디어 폴더)
    let serverOk = false;
    try {
      const fd = new FormData();
      fd.append('patient_id', String(patient.id));
      fd.append('media_type', mediaType);
      fd.append('eye', eye || 'NA');
      fd.append('ext', ext);
      if (durationMs != null) fd.append('duration_ms', String(durationMs));
      if (note) fd.append('note', note);
      fd.append('file', blob, filename);
      await api('/captures', { method: 'POST', body: fd });
      serverOk = true;
    } catch (err) {
      toast('서버 저장 실패: ' + err.message, 'error');
    }

    // (b) 지정 로컬 폴더에도 동시 저장
    let folderOk = false;
    if (state.dirHandle) folderOk = await saveToFolder(filename, blob);

    if (serverOk && !opts.silent) {
      await renderThumbs();
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
  async function renderThumbs() {
    const list = $('thumb-list');
    const empty = $('thumb-empty');
    Array.from(list.querySelectorAll('.thumb')).forEach(n => n.remove());
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
    if (items.length === 0) {
      empty.style.display = 'block';
      empty.querySelector('div').innerHTML = '선택한 환자의<br>촬영 이미지가 없습니다';
      return;
    }
    empty.style.display = 'none';
    for (const c of items) {
      const ts = parseTs(c.captured_at);
      const el = document.createElement('div');
      el.className = 'thumb';
      const eyeLabel = c.eye && c.eye !== 'NA' ? c.eye : '';
      const isVideo = c.media_type === 'video';
      const dur = isVideo ? `▶ ${Math.round((c.duration_ms || 0) / 1000)}s` : '';
      const thumbSrc = isVideo ? '' : c.url;
      el.innerHTML = `
        ${isVideo
          ? `<div style="width:100%;aspect-ratio:4/3;background:#000;display:flex;align-items:center;justify-content:center;color:#64748b"><svg width="32" height="32" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg></div>`
          : `<img src="${thumbSrc}" alt="캡처 ${fmt(ts)}" loading="lazy">`}
        <div class="thumb-caption">
          <span>${fmt(ts)}</span>
          <span class="thumb-badges">
            ${eyeLabel ? `<span class="thumb-badge">${eyeLabel}</span>` : ''}
            ${dur ? `<span class="thumb-badge video">${dur}</span>` : ''}
          </span>
        </div>`;
      el.addEventListener('click', () => openViewer(c, ts));
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

  init();
})();
