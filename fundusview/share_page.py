"""The page a web browser gets from the sharing server (share.py): the patient list, a patient's
photos by exam, a large view with zoom, and the notes — without installing anything. The tools
(3D, 몽타주, 녹내장 …) are in the viewer program, connected to the same server."""

WEB_PAGE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>안저 사진 뷰어</title>
<style>
:root{--bg:#0f1115;--panel:#181b21;--line:#2a2f38;--text:#e8eaed;--dim:#9aa3af;--blue:#3b82f6;--od:#2563eb;--os:#059669}
*{box-sizing:border-box}
html,body{height:100%;margin:0}
body{background:var(--bg);color:var(--text);font:15px/1.45 "Malgun Gothic","Apple SD Gothic Neo",system-ui,sans-serif}
button,input,select,textarea{font:inherit;color:inherit}
input,select,textarea{background:#0b0d11;border:1px solid var(--line);border-radius:6px;padding:7px 9px;width:100%}
button{white-space:nowrap;background:#252a33;border:1px solid var(--line);border-radius:6px;padding:7px 14px;cursor:pointer}
button.primary{background:var(--blue);border-color:var(--blue);color:#fff}
button:hover{filter:brightness(1.15)}
#login{max-width:340px;margin:16vh auto;padding:24px;background:var(--panel);border:1px solid var(--line);border-radius:10px}
#login h1{font-size:19px;margin:0 0 14px}
#login button{width:100%;margin-top:12px}
#app{display:none;height:100%;grid-template-columns:340px 1fr}
#side{border-right:1px solid var(--line);display:flex;flex-direction:column;min-height:0;background:var(--panel)}
#side header{padding:12px}
#side header b{display:block;margin-bottom:8px}
#plist{overflow:auto;flex:1}
.p{padding:9px 12px;border-top:1px solid var(--line);cursor:pointer}
.p:hover{background:#20242c}
.p.on{background:#1d2b45}
.p small{color:var(--dim);display:block}
#main{overflow:auto;padding:16px;min-width:0}
#phead{display:flex;gap:12px;align-items:baseline;flex-wrap:wrap;margin-bottom:6px}
#phead h2{margin:0;font-size:20px}
.dim{color:var(--dim)}
.exam{margin-top:18px}
.exam h3{font-size:15px;margin:0 0 8px;color:var(--dim);font-weight:600}
.grid{display:flex;flex-wrap:wrap;gap:10px}
.ph{width:150px;background:var(--panel);border:1px solid var(--line);border-radius:8px;overflow:hidden;cursor:pointer}
.ph img{width:100%;height:120px;object-fit:contain;background:#000;display:block}
.ph div{padding:5px 8px;font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.eye{display:inline-block;border-radius:4px;padding:0 5px;font-weight:700;font-size:11.5px;color:#fff;background:#4b5563}
.eye.OD{background:var(--od)}.eye.OS{background:var(--os)}
#viewer{position:fixed;inset:0;background:#000;display:none;flex-direction:column;z-index:5}
#vbar{display:flex;gap:8px;align-items:center;padding:8px 10px;background:var(--panel);flex-wrap:wrap}
#vbar .t{flex:1;min-width:120px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#stage{flex:1;overflow:hidden;position:relative;touch-action:none;cursor:grab}
#stage img{position:absolute;left:0;top:0;transform-origin:0 0;user-select:none;-webkit-user-drag:none;max-width:none}
#vnote input{flex:1;min-width:0}
#vnote{display:flex;gap:8px;padding:8px 10px;background:var(--panel)}
dialog{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:10px;padding:18px;width:min(420px,92vw)}
dialog::backdrop{background:rgba(0,0,0,.6)}
dialog label{display:block;margin:10px 0 3px;color:var(--dim);font-size:13px}
dialog .row{display:flex;gap:8px;justify-content:flex-end;margin-top:16px}
#msg{color:#f87171;min-height:1.4em;margin-top:8px;font-size:13px}
#back{display:none}
@media (max-width:760px){
  #app{grid-template-columns:1fr}
  #app.open #side{display:none}
  #app:not(.open) #main{display:none}
  #back{display:inline-block}
  .ph{width:calc(50% - 5px)}
}
</style>
</head>
<body>
<form id="login">
  <h1>안저 사진 뷰어</h1>
  <label class="dim">접속 암호</label>
  <input id="key" type="password" autocomplete="current-password" autofocus>
  <button class="primary">들어가기</button>
  <div id="msg"></div>
</form>

<div id="app">
  <div id="side">
    <header><b>환자 목록</b><input id="q" type="search" placeholder="이름 · 환자 ID · 생년월일 검색"></header>
    <div id="plist"></div>
  </div>
  <div id="main"><p class="dim">왼쪽에서 환자를 고르세요.</p></div>
</div>

<div id="viewer">
  <div id="vbar">
    <button id="vclose">‹ 닫기</button>
    <span class="t" id="vtitle"></span>
    <button id="vprev">이전</button><button id="vnext">다음</button>
    <button id="vfit">화면 맞춤</button><button id="v100">100%</button>
  </div>
  <div id="stage"><img id="vimg" alt=""></div>
  <div id="vnote"><input id="note" placeholder="이 사진의 메모"><button id="nsave" class="primary">메모 저장</button></div>
</div>

<dialog id="pdlg">
  <b>환자 정보</b>
  <label>이름</label><input id="e_name">
  <label>생년월일 (YYYY-MM-DD)</label><input id="e_birth" placeholder="1960-05-17">
  <label>성별</label><select id="e_sex"><option value="">미상</option><option value="M">남</option><option value="F">여</option></select>
  <label>메모</label><textarea id="e_note" rows="3"></textarea>
  <div class="row"><button id="e_cancel">취소</button><button id="e_ok" class="primary">저장</button></div>
</dialog>

<script>
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const SEX = {M:"남", F:"여"};
const MOD = {color:"컬러", redfree:"Red-free", af:"자가형광", fa:"형광조영", icg:"ICG", ir:"적외선", anterior:"전안부",
             montage:"몽타주", disc:"디스크 2장", glaucoma:"녹내장 분석"};
let patients = [], current = null, photos = [], shown = -1, rev = null;

async function db(method, args = [], kwargs = {}) {
  const r = await fetch("/api/db", {method:"POST", headers:{"Content-Type":"application/json"},
                                    body: JSON.stringify({method, args, kwargs})});
  if (r.status === 401) { showLogin(); throw new Error("unauthorized"); }
  if (!r.ok) throw new Error("서버 오류 " + r.status);
  const j = await r.json();
  rev = j.rev;
  return j.result;
}
function showLogin() { $("app").style.display = "none"; $("login").style.display = "block"; $("key").focus(); }
async function start() {
  $("login").style.display = "none"; $("app").style.display = "grid";
  await loadPatients();
}
$("login").onsubmit = async e => {
  e.preventDefault();
  const r = await fetch("/api/login", {method:"POST", body: JSON.stringify({key: $("key").value})});
  if (r.ok) { $("msg").textContent = ""; start(); } else $("msg").textContent = "접속 암호가 맞지 않습니다.";
};

async function loadPatients() {
  patients = await db("list_patients", [$("q").value.trim()]);
  const n = await db("count_unassigned");
  let html = n ? `<div class="p" data-ref="none"><b>★ 미분류</b><small>환자 ID 없는 사진 ${n}장</small></div>` : "";
  for (const p of patients)
    html += `<div class="p" data-ref="${p.id}"><b>${esc(p.name || "이름 없음")}</b> <span class="dim">${esc(p.patient_id)}</span>
      <small>${esc([p.birth_date, SEX[p.sex], "사진 " + p.n_images + "장", "최근 " + (p.last_exam || "-")].filter(Boolean).join(" · "))}</small></div>`;
  $("plist").innerHTML = html || '<p class="dim" style="padding:12px">환자가 없습니다.</p>';
  mark();
}
function mark() {
  const ref = current === null ? "" : current === "none" ? "none" : String(current.id);
  for (const el of $("plist").children) el.classList?.toggle("on", el.dataset.ref === ref);
}
let qt; $("q").oninput = () => { clearTimeout(qt); qt = setTimeout(loadPatients, 250); };
$("plist").onclick = e => { const el = e.target.closest(".p"); if (el) openPatient(el.dataset.ref); };

async function openPatient(ref) {
  current = ref === "none" ? "none" : await db("get_patient", [Number(ref)]);
  if (current === null) { await loadPatients(); return; }
  photos = await db("images_for_patient", [current === "none" ? null : current.id]);
  $("app").classList.add("open");
  mark(); draw();
}
function draw() {
  const p = current;
  let html = '<div id="phead"><button id="back">‹ 환자 목록</button>';
  if (p === "none") html += "<h2>★ 미분류</h2>";
  else html += `<h2>${esc(p.name || "이름 없음")}</h2><span class="dim">${esc([p.patient_id, p.birth_date, SEX[p.sex]].filter(Boolean).join(" · "))}</span>
    <button id="pedit">환자 정보 수정</button>`;
  html += "</div>";
  if (p !== "none" && p.note) html += `<div class="dim">메모: ${esc(p.note)}</div>`;
  const dates = [...new Set(photos.map(r => r.exam_date || ""))];
  for (const d of dates) {
    html += `<div class="exam"><h3>${esc(d || "날짜 없음")}</h3><div class="grid">`;
    photos.forEach((r, i) => { if ((r.exam_date || "") !== d) return;
      html += `<div class="ph" data-i="${i}"><img loading="lazy" src="/api/file/${r.id}/thumb" alt="">
        <div><span class="eye ${esc(r.laterality || "")}">${esc(r.laterality || "미상")}</span>
        ${esc(MOD[r.modality] || r.modality || "")} ${r.fov_deg ? esc(String(r.fov_deg)) + "°" : ""} ${esc((r.exam_time || "").slice(0,5))}
        ${r.note ? "· " + esc(r.note) : ""}</div></div>`; });
    html += "</div></div>";
  }
  if (!photos.length) html += '<p class="dim">사진이 없습니다.</p>';
  $("main").innerHTML = html;
  $("back").onclick = () => $("app").classList.remove("open");
  if ($("pedit")) $("pedit").onclick = editPatient;
}
$("main").onclick = e => { const el = e.target.closest(".ph"); if (el) view(Number(el.dataset.i)); };

function editPatient() {
  const p = current;
  $("e_name").value = p.name || ""; $("e_birth").value = p.birth_date || "";
  $("e_sex").value = p.sex === "M" || p.sex === "F" ? p.sex : ""; $("e_note").value = p.note || "";
  $("pdlg").showModal();
}
$("e_cancel").onclick = () => $("pdlg").close();
$("e_ok").onclick = async () => {
  const birth = $("e_birth").value.trim();
  if (birth && !/^\d{4}-\d{2}-\d{2}$/.test(birth)) { alert("생년월일을 YYYY-MM-DD 형식으로 입력하세요."); return; }
  await db("update_patient", [current.id], {name: $("e_name").value.trim() || null, birth_date: birth || null,
                                           sex: $("e_sex").value || null, note: $("e_note").value.trim() || null});
  $("pdlg").close();
  await loadPatients(); await openPatient(String(current.id));
};

// -- the large view: wheel / pinch zoom, drag ---------------------------------------------
let z = 1, ox = 0, oy = 0;
const img = $("vimg"), stage = $("stage");
function place() { img.style.transform = `translate(${ox}px,${oy}px) scale(${z})`; }
function fit() {
  if (!img.naturalWidth) return;
  z = Math.min(stage.clientWidth / img.naturalWidth, stage.clientHeight / img.naturalHeight);
  ox = (stage.clientWidth - img.naturalWidth * z) / 2; oy = (stage.clientHeight - img.naturalHeight * z) / 2; place();
}
function zoomAt(f, x, y) {
  const nz = Math.min(Math.max(z * f, 0.05), 16);
  ox = x - (x - ox) * nz / z; oy = y - (y - oy) * nz / z; z = nz; place();
}
img.onload = fit;
function view(i) {
  if (i < 0 || i >= photos.length) return;
  shown = i; const r = photos[i];
  $("vtitle").textContent = `${r.exam_date || ""} ${(r.exam_time || "").slice(0,5)} · ${r.laterality || "미상"} · ${MOD[r.modality] || r.modality || ""}`;
  $("note").value = r.note || "";
  img.src = `/api/file/${r.id}/view`;
  $("viewer").style.display = "flex";
}
$("vclose").onclick = () => { $("viewer").style.display = "none"; img.removeAttribute("src"); draw(); };
$("vprev").onclick = () => view(shown - 1);
$("vnext").onclick = () => view(shown + 1);
$("vfit").onclick = fit;
$("v100").onclick = () => zoomAt(1 / z, stage.clientWidth / 2, stage.clientHeight / 2);
$("nsave").onclick = async () => {
  const r = photos[shown], note = $("note").value.trim() || null;
  await db("update_image", [r.id], {note}); r.note = note;
  $("nsave").textContent = "저장됨"; setTimeout(() => $("nsave").textContent = "메모 저장", 1200);
};
stage.addEventListener("wheel", e => { e.preventDefault();
  const b = stage.getBoundingClientRect(); zoomAt(e.deltaY < 0 ? 1.2 : 1 / 1.2, e.clientX - b.left, e.clientY - b.top); }, {passive:false});
const pts = new Map(); let pinch = 0;
stage.onpointerdown = e => { stage.setPointerCapture(e.pointerId); pts.set(e.pointerId, [e.clientX, e.clientY]); pinch = 0; };
stage.onpointerup = stage.onpointercancel = e => { pts.delete(e.pointerId); pinch = 0; };
stage.onpointermove = e => {
  if (!pts.has(e.pointerId)) return;
  const [px, py] = pts.get(e.pointerId); pts.set(e.pointerId, [e.clientX, e.clientY]);
  if (pts.size === 1) { ox += e.clientX - px; oy += e.clientY - py; place(); return; }
  const [a, b] = [...pts.values()], d = Math.hypot(a[0] - b[0], a[1] - b[1]), r = stage.getBoundingClientRect();
  if (pinch) zoomAt(d / pinch, (a[0] + b[0]) / 2 - r.left, (a[1] + b[1]) / 2 - r.top);
  pinch = d;
};
document.onkeydown = e => {
  if ($("viewer").style.display !== "flex" || e.target.tagName === "INPUT") return;
  if (e.key === "Escape") $("vclose").onclick();
  if (e.key === "ArrowLeft") view(shown - 1);
  if (e.key === "ArrowRight") view(shown + 1);
};

// -- new photos and changes made on other computers ---------------------------------------
setInterval(async () => {
  if ($("app").style.display !== "grid" || $("pdlg").open) return;
  try {
    const r = await fetch("/api/rev"); if (!r.ok) return;
    const now = (await r.json()).rev;
    if (rev !== null && now !== rev) {
      rev = now; await loadPatients();
      if (current !== null && $("viewer").style.display !== "flex") await openPatient(current === "none" ? "none" : String(current.id));
    }
    rev = now;
  } catch (e) {}
}, 5000);

fetch("/api/ping").then(r => r.json()).then(j => j.auth ? start() : showLogin()).catch(showLogin);
</script>
</body>
</html>
"""
