/* 슬릿램프 영상 시스템 — Pro '참조' 탭: 부위별 · 정상/비정상(질환명) 참조 샘플 라이브러리
 *
 * 등록   1화면에서 보고 있는 영상(회전·자르기 반영, 보정 전) 또는 PC 의 영상 파일을 참조 샘플로 저장
 * 보기   부위 · 정상/비정상으로 걸러 썸네일 목록
 * 비교   현재 영상 ↔ 선택한 샘플,  정상 샘플 ↔ 현재 영상(또는 선택한 비정상 샘플) 을 비교 화면에 나란히
 * 저장   서버 모드 /api/v1/refs (ref_samples 테이블 + media/_reference),  '이 PC에만 저장' 모드는 브라우저 저장소
 * 정상/비정상·질환명은 사용자가 붙이는 분류이며 프로그램이 판정하지 않는다.
 */
(() => {
  const App = window.SlitApp, Pro = window.SlitPro;
  if (!App || !Pro) return;
  const $ = (id) => document.getElementById(id);
  const P = Pro.state, V = Pro.viewers;
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const REGION_KO = { eyelid: '안검', conjunctiva: '결막', cornea: '각막', ac: '전방', iris: '홍채', lens: '수정체', meibo: '마이봄샘', other: '기타' };
  const COND_KO = { normal: '정상', abnormal: '비정상' };
  // 질환명 입력 도움말 (분류용 이름 — 자유 입력 가능)
  const DISEASES = {
    eyelid: ['안검염', '다래끼(맥립종)', '산립종', '안검내반', '안검외반'],
    conjunctiva: ['결막염', '알레르기 결막염', '결막하출혈', '익상편', '검열반', '결막결석'],
    cornea: ['각막염', '각막궤양', '점상각막염', '각막혼탁', '원추각막', '각막이물', '각막부종'],
    ac: ['전방출혈', '전방축농', '전방세포·플레어', '얕은 전방'],
    iris: ['홍채염', '홍채후유착', '홍채 신생혈관', '홍채모반'],
    lens: ['핵백내장', '피질백내장', '후낭하백내장', '인공수정체', '후낭혼탁'],
    meibo: ['마이봄샘기능장애', '마이봄샘 소실', '마이봄샘 단축'],
    other: [],
  };
  const KEY = 'slitlamp-ref';
  const S = { region: '', cond: '', addRegion: 'cornea', addCond: 'normal' };
  try { Object.assign(S, JSON.parse(localStorage.getItem(KEY) || '{}')); } catch (_) { /* 저장소 차단 */ }
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(S)); } catch (_) { /* 무시 */ } };

  let refs = [], selected = null;
  const label = (r) => `${REGION_KO[r.region] || r.region} · ${COND_KO[r.condition]}${r.disease ? ' · ' + r.disease : ''}`;
  const msg = (t) => { $('ref-msg').textContent = t || ''; };

  async function load() {
    const q = new URLSearchParams();
    if (S.region) q.set('region', S.region);
    if (S.cond) q.set('condition', S.cond);
    try { refs = await App.api('/refs' + (q.toString() ? '?' + q : '')); }
    catch (e) { refs = []; msg('참조 샘플을 불러오지 못했습니다: ' + e.message); }
    if (selected && !refs.some((r) => r.id === selected.id)) selected = null;
    render();
    return refs;
  }
  function render() {
    const box = $('ref-list');
    box.innerHTML = refs.map((r) => `<button class="ref-item${selected && selected.id === r.id ? ' on' : ''}" data-id="${r.id}" title="${esc(label(r))}${r.note ? '\n' + esc(r.note) : ''}">
      <img src="${esc(r.url)}" alt="" loading="lazy">
      <span><b class="${r.condition === 'normal' ? 'n' : 'a'}">${COND_KO[r.condition]}</b> · ${esc(REGION_KO[r.region] || r.region)}</span>
      <span>${esc(r.disease || (r.condition === 'normal' ? '대표 정상' : '-'))}</span></button>`).join('');
    box.querySelectorAll('.ref-item').forEach((b) => b.addEventListener('click', () => {
      selected = refs.find((r) => r.id === Number(b.dataset.id)) || null;
      render();
    }));
    $('ref-del').disabled = !selected;
    syncButtons();
  }
  function syncButtons() {
    const single = P.mode === 'single' && !!V.single.base;
    $('ref-add-cur').disabled = !single;
    $('ref-cmp-cur').disabled = !(single && selected);
  }
  function syncDiseaseList() {
    $('ref-disease-list').innerHTML = (DISEASES[$('ref-region').value] || []).map((d) => `<option value="${esc(d)}">`).join('');
    $('ref-disease').disabled = $('ref-cond').value === 'normal';
  }

  // ---- 등록 ----
  async function upload(blob, ext) {
    const fd = new FormData();
    fd.append('region', $('ref-region').value);
    fd.append('condition', $('ref-cond').value);
    if ($('ref-cond').value === 'abnormal' && $('ref-disease').value.trim()) fd.append('disease', $('ref-disease').value.trim());
    if ($('ref-note').value.trim()) fd.append('note', $('ref-note').value.trim());
    fd.append('ext', ext);
    fd.append('file', blob, `ref.${ext}`);
    let r;
    try { r = await App.api('/refs', { method: 'POST', body: fd }); }
    catch (e) { App.toast('참조 샘플 저장 실패: ' + e.message, 'error'); return null; }
    App.toast(`참조 샘플로 등록했습니다 — ${label(r)}`, 'success');
    S.addRegion = r.region; S.addCond = r.condition; save();
    $('ref-note').value = '';
    // 등록한 샘플이 보이도록 필터를 맞춤
    if (S.region && S.region !== r.region) { S.region = r.region; $('ref-f-region').value = r.region; }
    if (S.cond && S.cond !== r.condition) { S.cond = ''; $('ref-f-cond').value = ''; }
    await load();
    selected = refs.find((x) => x.id === r.id) || null; render();
    return r;
  }
  async function addCurrent() {
    if (P.mode !== 'single' || !V.single.base) { App.toast('1화면에서 등록할 영상을 여세요.', 'error'); return null; }
    if ($('ref-cond').value === 'abnormal' && !$('ref-disease').value.trim()) {
      App.toast('비정상 샘플은 질환명을 입력하세요 (분류용 이름).', 'error'); $('ref-disease').focus(); return null;
    }
    const blob = await new Promise((r) => V.single.base.toBlob(r, 'image/png'));
    return blob ? upload(blob, 'png') : null;
  }
  async function addFile(file) {
    if (!file) return null;
    const ext = ({ 'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp' })[file.type];
    if (!ext) { App.toast('PNG · JPG · WEBP 영상만 등록할 수 있습니다.', 'error'); return null; }
    if ($('ref-cond').value === 'abnormal' && !$('ref-disease').value.trim()) {
      App.toast('비정상 샘플은 질환명을 입력하세요 (분류용 이름).', 'error'); $('ref-disease').focus(); return null;
    }
    return upload(file, ext);
  }
  async function remove() {
    if (!selected) return false;
    if (!window.confirm(`참조 샘플을 삭제할까요?\n${label(selected)}`)) return false;
    try { await App.api(`/refs/${selected.id}`, { method: 'DELETE' }); }
    catch (e) { App.toast('삭제 실패: ' + e.message, 'error'); return false; }
    selected = null; await load();
    return true;
  }

  // ---- 비교 ----
  const refCap = (r) => ({ ref: true, id: null, eye: 'NA', captured_at: '참조 샘플', note: label(r) });
  function current() {
    const c = P.caps[P.idx];
    if (P.mode !== 'single' || !V.single.base || !c) return null;
    return { src: V.single.base, cap: c, caption: Pro.caption(c, P.idx + 1) };
  }
  async function asSide(r) {
    const im = await Pro.loadImage(r.url);
    return { src: im, cap: refCap(r), caption: `참조 샘플  ·  ${label(r)}` };
  }
  async function compareCurrent() {
    const cur = current();
    if (!cur) { App.toast('1화면에서 비교할 영상을 여세요.', 'error'); return false; }
    if (!selected) { App.toast('비교할 참조 샘플을 목록에서 고르세요.', 'error'); return false; }
    try { await Pro.compareImages(cur, await asSide(selected)); }
    catch (e) { App.toast(e.message, 'error'); return false; }
    msg(`왼쪽: 현재 영상 · 오른쪽: ${label(selected)}`);
    return true;
  }
  async function compareNormal() {
    const cur = current();
    const region = (selected && selected.region) || S.region || $('ref-region').value;
    let normals;
    try { normals = await App.api(`/refs?region=${encodeURIComponent(region)}&condition=normal`); } catch (_) { normals = []; }
    if (!normals.length) { App.toast(`${REGION_KO[region]} 정상 샘플이 없습니다. 먼저 정상 샘플을 등록하세요.`, 'error'); return false; }
    const normal = normals[normals.length - 1];                // 가장 최근 등록한 정상 샘플
    let right = cur;
    if (!right && selected && selected.id !== normal.id) right = await asSide(selected);
    if (!right) { App.toast('1화면에서 영상을 열거나, 목록에서 비교할 샘플을 고르세요.', 'error'); return false; }
    try { await Pro.compareImages(await asSide(normal), right); }
    catch (e) { App.toast(e.message, 'error'); return false; }
    msg(`왼쪽: ${label(normal)} · 오른쪽: ${right.cap.ref ? right.cap.note : '현재 영상'}`);
    return true;
  }

  // ---- 이벤트 ----
  $('ref-f-region').value = S.region; $('ref-f-cond').value = S.cond;
  $('ref-region').value = S.addRegion; $('ref-cond').value = S.addCond;
  syncDiseaseList();
  $('ref-f-region').addEventListener('change', (e) => { S.region = e.target.value; save(); load(); });
  $('ref-f-cond').addEventListener('change', (e) => { S.cond = e.target.value; save(); load(); });
  $('ref-region').addEventListener('change', syncDiseaseList);
  $('ref-cond').addEventListener('change', syncDiseaseList);
  $('ref-add-cur').addEventListener('click', addCurrent);
  $('ref-add-file').addEventListener('click', () => $('ref-file').click());
  $('ref-file').addEventListener('change', async (e) => { await addFile(e.target.files[0]); e.target.value = ''; });
  $('ref-del').addEventListener('click', remove);
  $('ref-cmp-cur').addEventListener('click', compareCurrent);
  $('ref-cmp-normal').addEventListener('click', compareNormal);
  document.addEventListener('slit:pro-mode', syncButtons);
  document.addEventListener('slit:pro-image', syncButtons);
  document.querySelectorAll('.ptab[data-tab="ref"]').forEach((b) => b.addEventListener('click', load));
  load();

  // 자동화 테스트·디버깅용 핸들
  window.SlitRefs = { load, addCurrent, addFile, remove, compareCurrent, compareNormal,
    select: (id) => { selected = refs.find((r) => r.id === id) || null; render(); return selected; },
    list: () => refs, selected: () => selected };
})();
