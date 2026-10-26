/* 홈(시작) 화면 + 검사 기록 화면.
 * app.js 의 window.SlitApp API 와 'slit:patient' 이벤트, pro.js 의 #btn-pro 토글에 의존한다.
 * 화면 상태는 body 클래스: home-on · exam-on (Pro 는 pro-on, 아무것도 없으면 촬영).
 */
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const App = () => window.SlitApp;
  const DOW = ['일', '월', '화', '수', '목', '금', '토'];
  const SEX = { M: '남', F: '여', O: '기타' };
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  // 검사 종류 서식: 고르면 빈 소견란에 틀을 채워 준다 (데스크탑 app/ui/exam_screen.py 와 같다)
  const EXAM_TYPES = [
    ['', ''],
    ['세극등 검사', '전안부: \n각막: \n전방: \n홍채/동공: \n수정체: \n'],
    ['각막', '상피: \n실질: \n내피: \n형광 염색: \n'],
    ['결막/공막', '충혈: \n결막 부종: \n분비물: \n'],
    ['안검/마이봄샘', '안검연: \n마이봄샘 개구부: \n분비물 성상: \n탈락 등급: \n'],
    ['건성안', 'TBUT: \nSchirmer: \n각막 염색: \n'],
    ['수정체/백내장', '혼탁 위치: \n등급(LOCS): \n'],
    ['경과 관찰', '이전 대비: \n'],
    ['기타', ''],
  ];
  const E = { patient: null, exams: [], caps: [], day: null, dirty: false, loading: false, seq: 0 };

  // ================= 화면 전환 =================
  function screen() {
    const b = document.body.classList;
    return b.contains('home-on') ? 'home' : b.contains('exam-on') ? 'exam' : b.contains('pro-on') ? 'pro' : 'capture';
  }
  function setScreen(name) {
    if (screen() === 'exam' && name !== 'exam') flush();
    const b = document.body.classList;
    b.remove('home-on', 'exam-on');
    if (name === 'pro') { if (!b.contains('pro-on')) $('btn-pro').click(); return; }
    if (b.contains('pro-on')) $('btn-mode-capture').click();          // pro.js 가 pro-on 을 끈다
    if (name === 'home') b.add('home-on');
    else if (name === 'exam') { b.add('exam-on'); reload(); }
  }
  window.SlitScreen = { get: screen, set: setScreen };

  function dayLabel(d) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(d || '');
    if (!m) return d || '-';
    const dt = new Date(+m[1], +m[2] - 1, +m[3]);
    return `${m[1]}.${m[2]}.${m[3]} (${DOW[dt.getDay()]})`;
  }

  // ================= 검사 기록 =================
  async function reload(keepDay = true) {
    const my = ++E.seq;
    const p = App().currentPatient() || null;
    E.patient = p;
    renderPatient();
    const prev = keepDay ? E.day : null;
    E.exams = []; E.caps = [];
    if (p) {
      try {
        [E.exams, E.caps] = await Promise.all([App().api(`/patients/${p.id}/exams`), App().api(`/captures?patient_id=${p.id}&order=desc`)]);
      } catch (e) { App().toast('검사 기록 조회 실패: ' + e.message, 'error'); }
    }
    if (my !== E.seq) return;
    renderDays();
    const days = E.exams.map((x) => x.exam_date);
    showDay(days.includes(prev) ? prev : (days[0] || null));
  }

  function renderDays() {
    const list = $('exam-day-list');
    list.innerHTML = '';
    $('exam-day-count').textContent = E.exams.length;
    $('exam-days-empty').hidden = E.exams.length > 0;
    for (const x of E.exams) {
      const b = document.createElement('button');
      const noted = !!(x.notes || x.exam_type);
      b.className = 'exam-day' + (noted ? ' noted' : '') + (x.exam_date === E.day ? ' on' : '');
      b.dataset.day = x.exam_date;
      const bits = [`${x.count}장`];
      if (x.od) bits.push(`OD ${x.od}`);
      if (x.os) bits.push(`OS ${x.os}`);
      if (x.video) bits.push(`동영상 ${x.video}`);
      b.innerHTML = `<svg class="ic"><use href="#i-${noted ? 'check-circle' : 'clipboard'}"/></svg>
        <span><b>${esc(dayLabel(x.exam_date))}${x.exam_type ? ' · ' + esc(x.exam_type) : ''}</b><small>${bits.join(' · ')}</small></span>`;
      b.addEventListener('click', () => { flush(); showDay(x.exam_date); });
      list.appendChild(b);
    }
  }

  function dayCaps() { return E.caps.filter((c) => E.day && (c.captured_at || '').slice(0, 10) === E.day); }

  function showDay(day) {
    E.day = day;
    document.querySelectorAll('.exam-day').forEach((b) => b.classList.toggle('on', b.dataset.day === day));
    const caps = dayCaps();
    const grid = $('exam-grid');
    grid.innerHTML = '';
    for (const c of caps) {
      const ts = App().parseTs(c.captured_at);
      const eye = c.eye && c.eye !== 'NA' ? c.eye : '';
      const isVideo = c.media_type === 'video';
      const el = document.createElement('div');
      el.className = 'thumb';
      el.tabIndex = 0;
      el.innerHTML = `${isVideo ? '<div class="tvid"><svg class="ic"><use href="#i-play"/></svg></div>' : `<img src="${esc(c.url)}" alt="" loading="lazy">`}
        <span class="thumb-badges">${eye ? `<span class="thumb-badge e-${eye}">${eye}</span>` : ''}${isVideo ? `<span class="thumb-badge video">▶ ${Math.round((c.duration_ms || 0) / 1000)}s</span>` : ''}</span>
        <div class="thumb-caption"><span><span class="thumb-time">${esc((c.captured_at || '').slice(11, 19))}</span>${c.note ? `<span class="thumb-note">${esc(c.note)}</span>` : ''}</span></div>`;
      el.title = [App().fmtDT(ts), eye, c.note].filter(Boolean).join(' · ');
      el.addEventListener('click', () => openViewer(c));
      el.addEventListener('keydown', (e) => { if (e.key === 'Enter') openViewer(c); });
      grid.appendChild(el);
    }
    $('exam-grid-empty').hidden = !(day && caps.length === 0);
    if (!day) {
      $('exam-day-title').textContent = E.patient ? '촬영일을 선택하세요' : '환자를 선택하세요';
      $('exam-day-meta').textContent = '';
    } else {
      const first = caps.length ? (caps[caps.length - 1].captured_at || '').slice(11, 16) : '';
      const last = caps.length ? (caps[0].captured_at || '').slice(11, 16) : '';
      $('exam-day-title').textContent = dayLabel(day);
      $('exam-day-meta').textContent = `${caps.length}장` + (first ? ` · ${first === last ? first : first + ' ~ ' + last}` : '');
    }
    $('exam-print').disabled = !caps.some((c) => c.media_type === 'photo');
    $('exam-open-pro').disabled = !E.patient;
    // 소견
    E.loading = true;
    const x = E.exams.find((r) => r.exam_date === day) || {};
    const names = EXAM_TYPES.map((t) => t[0]);
    $('exam-type').value = names.includes(x.exam_type) ? x.exam_type : '';
    $('exam-text').value = x.notes || '';
    $('exam-saved').textContent = x.updated_at ? `저장됨 ${String(x.updated_at).slice(5, 16)}` : '';
    E.loading = false;
    E.dirty = false;
    for (const id of ['exam-type', 'exam-text', 'exam-save']) $(id).disabled = !day;
  }

  function openViewer(c) {
    App().openViewer(c, App().parseTs(c.captured_at));     // 촬영 화면의 썸네일 클릭과 같은 보기 창
  }

  async function save() {
    if (!E.patient || !E.day) return;
    const body = { exam_type: $('exam-type').value || null, notes: $('exam-text').value || null };
    try {
      const row = await App().api(`/patients/${E.patient.id}/exams/${E.day}`, { method: 'PUT', body: JSON.stringify(body) });
      const i = E.exams.findIndex((r) => r.exam_date === E.day);
      if (i >= 0) E.exams[i] = row; else E.exams.unshift(row);
      E.dirty = false;
      $('exam-saved').textContent = `저장됨 ${String(row.updated_at || '').slice(11, 16)}`;
      renderDays();
    } catch (e) { App().toast('소견 저장 실패: ' + e.message, 'error'); }
  }
  function flush() { if (E.dirty && E.patient && E.day) save(); }

  function renderPatient() {
    const p = E.patient;
    $('exam-edit').disabled = !p;
    if (!p) { $('exam-pinfo').innerHTML = '<span style="color:var(--ink-muted)">환자를 선택하세요</span>'; return; }
    const age = (() => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(p.birth_date || ''); if (!m) return null;
      const t = new Date(), a = t.getFullYear() - +m[1] - ((t.getMonth() + 1 < +m[2]) || (t.getMonth() + 1 === +m[2] && t.getDate() < +m[3]) ? 1 : 0); return a >= 0 && a < 150 ? a : null; })();
    const rows = [
      ['이름', `<b>${esc(p.name)}</b>`], ['차트번호', esc(p.chart_no || '-')], ['환자ID', esc(p.patient_id || '-')],
      ['성별 · 나이', [SEX[p.sex], age !== null ? `${age}세` : ''].filter(Boolean).join(' · ') || '-'],
      ['생년월일', esc(p.birth_date || '-')], ['연락처', esc(p.phone || '-')],
      ['진단명', `<b>${esc(p.diagnosis || '-')}</b>`], ['담당의', esc(p.doctor || '-')],
      ['증상', esc(p.symptoms || '-').replace(/\n/g, '<br>')], ['메모', esc(p.memo || '-').replace(/\n/g, '<br>')],
    ];
    $('exam-pinfo').innerHTML = rows.map(([k, v]) => `<div class="pi"><small>${k}</small>${v}</div>`).join('');
  }

  // ---- 인쇄: 그날의 사진 + 소견을 보고서로 ----
  async function printDay() {
    const caps = dayCaps().filter((c) => c.media_type === 'photo').reverse();     // 촬영 순서
    if (!caps.length) { App().toast('출력할 사진이 없습니다.', 'error'); return; }
    const p = E.patient, sex = SEX[p?.sex] || '';
    const B = window.SLIT_BRAND || {};
    const type = $('exam-type').value, notes = ($('exam-text').value || '').trim();
    const text = (type ? `[${type}]\n` : '') + notes;
    const pages = [];
    if (caps.length > 2) for (let i = 0; i < caps.length; i += 4) pages.push(caps.slice(i, i + 4)); else pages.push(caps);
    const now = App().fmtDT(new Date());
    const area = $('print-area');
    area.innerHTML = pages.map((pg, pi) => `
      <section class="rp-page">
        <div class="rp-head"><div class="rp-brand">${B.logo ? `<img class="rp-logo" src="${esc(B.logo)}" alt="">` : ''}<div class="rp-title">${esc(B.report_title || '슬릿램프 영상 보고서')}</div></div><div class="rp-date">출력 ${esc(now)}</div></div>
        <div class="rp-pt">
          <div><b>환자: ${esc(p ? p.name : '-')} (${esc(p?.chart_no || '-')})</b>${sex ? '&nbsp; · &nbsp;' + sex : ''}${p?.birth_date ? '&nbsp; · &nbsp;' + esc(p.birth_date) : ''}&nbsp; · &nbsp;검사일 ${esc(dayLabel(E.day))}</div>
          <div class="rp-l2">진단명: ${esc(p?.diagnosis || '-')} &nbsp;&nbsp;&nbsp; 담당의: ${esc(p?.doctor || '-')}</div>
        </div>
        <div class="rp-imgs ${pg.length === 1 ? 'c1' : 'c2'}">
          ${pg.map((c) => `<figure class="rp-fig"><img src="${esc(c.url)}" alt=""><figcaption>${esc([c.captured_at, c.eye && c.eye !== 'NA' ? c.eye : '', c.note].filter(Boolean).join('  ·  '))}</figcaption></figure>`).join('')}
        </div>
        <div class="rp-notes"><h4>소견</h4><div class="rp-box${text && pi === 0 ? ' filled' : ''}">${pi === 0 ? esc(text) : ''}</div></div>
        <div class="rp-foot"><span>확인자 서명: ________________</span><span>${pi + 1} / ${pages.length}</span></div>
      </section>`).join('');
    await Promise.all([...area.querySelectorAll('img')].map((im) => (im.decode ? im.decode().catch(() => {}) : null)));
    window.print();
  }

  // ================= 홈 =================
  function go(where) {
    switch (where) {
      case 'newPatient': setScreen('capture'); App().openPatientDialog(null); break;
      case 'patients': setScreen('capture'); $('btn-patients').click(); break;
      case 'capture': case 'pro': case 'exam': setScreen(where); break;
      case 'settings': $('btn-settings').click(); break;
    }
  }

  // ================= 초기화 =================
  function init() {
    const sel = $('exam-type');
    for (const [name] of EXAM_TYPES) { const o = document.createElement('option'); o.value = name; o.textContent = name || '선택 안 함'; sel.appendChild(o); }
    sel.addEventListener('change', () => {
      if (E.loading) return;
      const tpl = (EXAM_TYPES.find((t) => t[0] === sel.value) || [])[1] || '';
      if (tpl && !$('exam-text').value.trim()) $('exam-text').value = tpl;
      E.dirty = true; $('exam-saved').textContent = '수정 중…';
    });
    $('exam-text').addEventListener('input', () => { if (!E.loading) { E.dirty = true; $('exam-saved').textContent = '수정 중…'; } });
    $('exam-text').addEventListener('blur', flush);
    $('exam-save').addEventListener('click', save);
    $('exam-refresh').addEventListener('click', () => reload());
    $('exam-print').addEventListener('click', printDay);
    $('exam-open-pro').addEventListener('click', () => setScreen('pro'));
    $('exam-edit').addEventListener('click', () => { if (E.patient) App().openPatientDialog(E.patient); });
    $('btn-home').addEventListener('click', () => setScreen('home'));
    $('btn-exam').addEventListener('click', () => setScreen('exam'));
    // 촬영·Pro 버튼은 app.js/pro.js 가 처리하므로 홈·검사 기록 표시만 거둔다 (capture 단계에서 먼저)
    $('btn-mode-capture').addEventListener('click', () => { if (screen() === 'exam') flush(); document.body.classList.remove('home-on', 'exam-on'); }, true);
    $('btn-pro').addEventListener('click', () => { if (screen() === 'exam') flush(); document.body.classList.remove('home-on', 'exam-on'); }, true);
    document.querySelectorAll('.home-tile').forEach((b) => b.addEventListener('click', () => go(b.dataset.go)));
    $('home-keys').addEventListener('click', () => $('btn-settings').click());
    let skip = false;
    try { skip = localStorage.getItem('slitlamp-start') === 'capture'; } catch (_) {}
    $('home-skip').checked = skip;
    $('home-skip').addEventListener('change', (e) => { try { localStorage.setItem('slitlamp-start', e.target.checked ? 'capture' : 'home'); } catch (_) {} });
    document.addEventListener('slit:patient', () => { if (screen() === 'exam') reload(); });
    window.addEventListener('afterprint', () => { const a = $('print-area'); if (a) a.innerHTML = ''; });
    if (!skip) setScreen('home');
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
