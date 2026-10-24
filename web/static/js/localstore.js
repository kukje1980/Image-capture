/* 슬릿램프 영상 시스템 — "이 PC에만 저장" 모드 (브라우저 IndexedDB)
 *
 * 이 모드에서는 환자 정보·사진·동영상을 인터넷 서버로 보내지 않고, 지금 쓰는 PC 의
 * 브라우저 저장소(IndexedDB)에만 보관한다. 상단 '저장 폴더'를 지정하면 그 폴더에도 파일이 함께 저장된다.
 * app.js 의 api() 가 이 모드일 때 서버 대신 SlitLocal.api() 를 호출한다 (같은 주소·같은 응답 형식).
 *
 * 저장 방식 선택: localStorage 'slitlamp-storage' = 'server' | 'local'
 * 서버가 SLITLAMP_STORAGE=local 로 배포되면 항상 이 모드 (window.SLIT_STORAGE_POLICY).
 */
(() => {
  const KEY = 'slitlamp-storage';
  const DB_NAME = 'slitlamp-local';
  const POLICY = (window.SLIT_STORAGE_POLICY || 'choice');      // choice | local | server

  function mode() {
    if (POLICY === 'local' || POLICY === 'server') return POLICY;
    try { return localStorage.getItem(KEY) === 'local' ? 'local' : 'server'; } catch (_) { return 'server'; }
  }
  function setMode(m) {
    try { localStorage.setItem(KEY, m === 'local' ? 'local' : 'server'); } catch (_) { /* 저장 불가 */ }
  }

  // ---------- IndexedDB ----------
  let dbp = null;
  function db() {
    if (dbp) return dbp;
    dbp = new Promise((resolve, reject) => {
      const rq = indexedDB.open(DB_NAME, 1);
      rq.onupgradeneeded = () => {
        const d = rq.result;
        d.createObjectStore('patients', { keyPath: 'id', autoIncrement: true });
        const c = d.createObjectStore('captures', { keyPath: 'id', autoIncrement: true });
        c.createIndex('patient_id', 'patient_id');
        d.createObjectStore('files');                       // key = capture id → Blob
      };
      rq.onsuccess = () => resolve(rq.result);
      rq.onerror = () => reject(rq.error || new Error('브라우저 저장소를 열 수 없습니다.'));
    });
    return dbp;
  }
  const done = (rq) => new Promise((res, rej) => { rq.onsuccess = () => res(rq.result); rq.onerror = () => rej(rq.error); });
  async function tx(stores, modeRW, fn) {
    const d = await db();
    const t = d.transaction(stores, modeRW);
    const out = await fn(...(Array.isArray(stores) ? stores : [stores]).map((s) => t.objectStore(s)));
    await new Promise((res, rej) => { t.oncomplete = res; t.onerror = () => rej(t.error); t.onabort = () => rej(t.error); });
    return out;
  }

  class HttpError extends Error {}
  const fail = (msg) => { throw new HttpError(msg); };
  const now = () => {
    const d = new Date(), p = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  };
  const PATIENT_FIELDS = ['chart_no', 'name', 'birth_date', 'sex', 'phone', 'memo', 'symptoms', 'diagnosis', 'doctor'];

  // 저장된 Blob → 화면에서 쓸 주소 (세션 동안 재사용)
  const urls = new Map();
  async function withUrl(cap) {
    if (!cap) return cap;
    if (!urls.has(cap.id)) {
      const blob = await tx('files', 'readonly', (f) => done(f.get(cap.id)));
      urls.set(cap.id, blob ? URL.createObjectURL(blob) : '');
    }
    return { ...cap, url: urls.get(cap.id) };
  }
  function dropUrl(id) {
    const u = urls.get(id);
    if (u) URL.revokeObjectURL(u);
    urls.delete(id);
  }

  // ---------- 서버 API 와 같은 동작 ----------
  async function api(path, options = {}) {
    const method = (options.method || 'GET').toUpperCase();
    const u = new URL(path, 'http://local/');
    const seg = u.pathname.split('/').filter(Boolean);       // ['patients', '3'] …
    const json = () => (typeof options.body === 'string' ? JSON.parse(options.body || '{}') : {});

    if (seg[0] === 'patients') {
      if (seg.length === 1 && method === 'GET') {
        const q = (u.searchParams.get('q') || '').trim().toLowerCase();
        const all = await tx('patients', 'readonly', (s) => done(s.getAll()));
        return all.filter((p) => !q || (p.name || '').toLowerCase().includes(q) || (p.chart_no || '').toLowerCase().includes(q))
          .sort((a, b) => (a.name || '').localeCompare(b.name || '', 'ko')).slice(0, 500);
      }
      if (seg.length === 1 && method === 'POST') {
        const b = json();
        if (!b.chart_no || !b.name) fail('차트번호와 이름은 필수입니다.');
        const all = await tx('patients', 'readonly', (s) => done(s.getAll()));
        if (all.some((p) => p.chart_no === b.chart_no)) fail('이미 존재하는 차트번호입니다.');
        const rec = { created_at: now() };
        for (const k of PATIENT_FIELDS) rec[k] = b[k] ?? null;
        const id = await tx('patients', 'readwrite', (s) => done(s.add(rec)));
        return { ...rec, id };
      }
      const id = Number(seg[1]);
      const cur = await tx('patients', 'readonly', (s) => done(s.get(id)));
      if (!cur) fail('환자를 찾을 수 없습니다.');
      if (method === 'GET') return cur;
      if (method === 'PUT') {
        const b = json();
        const all = await tx('patients', 'readonly', (s) => done(s.getAll()));
        if (b.chart_no && all.some((p) => p.chart_no === b.chart_no && p.id !== id)) fail('이미 존재하는 차트번호입니다.');
        const rec = { ...cur };
        for (const k of PATIENT_FIELDS) if (k in b) rec[k] = b[k];
        await tx('patients', 'readwrite', (s) => done(s.put(rec)));
        return rec;
      }
      if (method === 'DELETE') {
        await tx(['patients', 'captures', 'files'], 'readwrite', async (p, c, f) => {
          const caps = await done(c.index('patient_id').getAll(id));
          for (const cap of caps) { c.delete(cap.id); f.delete(cap.id); dropUrl(cap.id); }
          p.delete(id);
        });
        return null;
      }
    }

    if (seg[0] === 'captures') {
      if (seg.length === 1 && method === 'GET') {
        const pid = Number(u.searchParams.get('patient_id'));
        const order = (u.searchParams.get('order') || 'desc').toLowerCase();
        const caps = await tx('captures', 'readonly', (s) => done(s.index('patient_id').getAll(pid)));
        caps.sort((a, b) => (a.captured_at === b.captured_at ? a.id - b.id : a.captured_at < b.captured_at ? -1 : 1));
        if (order === 'desc') caps.reverse();
        return Promise.all(caps.map(withUrl));
      }
      if (seg.length === 1 && method === 'POST') {
        const fd = options.body;
        const pid = Number(fd.get('patient_id'));
        const p = await tx('patients', 'readonly', (s) => done(s.get(pid)));
        if (!p) fail('환자를 찾을 수 없습니다.');
        const file = fd.get('file');
        const media = fd.get('media_type');
        if (!['photo', 'video'].includes(media)) fail('media_type은 photo 또는 video 여야 합니다.');
        const eye = ['OD', 'OS', 'OU', 'NA'].includes(fd.get('eye')) ? fd.get('eye') : 'NA';
        const rec = {
          patient_id: pid, media_type: media, eye, captured_at: now(),
          duration_ms: fd.get('duration_ms') ? Number(fd.get('duration_ms')) : null,
          note: fd.get('note') || null, filename: (file && file.name) || null,
        };
        const id = await tx(['captures', 'files'], 'readwrite', async (c, f) => {
          const newId = await done(c.add(rec));
          f.put(file, newId);
          return newId;
        });
        return withUrl({ ...rec, id });
      }
      const id = Number(seg[1]);
      const cur = await tx('captures', 'readonly', (s) => done(s.get(id)));
      if (!cur) fail('영상을 찾을 수 없습니다.');
      if (method === 'PATCH') {
        const note = ((json().note || '') + '').trim() || null;
        await tx('captures', 'readwrite', (s) => done(s.put({ ...cur, note })));
        return withUrl({ ...cur, note });
      }
      if (method === 'DELETE') {
        await tx(['captures', 'files'], 'readwrite', (c, f) => { c.delete(id); f.delete(id); });
        dropUrl(id);
        return null;
      }
    }
    fail('지원하지 않는 요청입니다: ' + method + ' ' + path);
  }

  async function usage() {
    try { const e = await navigator.storage.estimate(); return { used: e.usage || 0, quota: e.quota || 0 }; }
    catch (_) { return null; }
  }
  async function persist() {
    try { return navigator.storage && navigator.storage.persist ? await navigator.storage.persist() : false; }
    catch (_) { return false; }
  }

  window.SlitLocal = { mode, setMode, api, usage, persist, policy: POLICY, HttpError };
})();
