"""프런트엔드 정적 검사: Pro 모드 스크립트가 참조하는 요소가 템플릿에 모두 있는지."""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
HTML = (WEB / "templates" / "index.html").read_text(encoding="utf-8")
PRO_JS = (WEB / "static" / "js" / "pro.js").read_text(encoding="utf-8")
HTML_IDS = set(re.findall(r'\bid="([^"]+)"', HTML))


def test_pro_js_ids_exist_in_template():
    used = set(re.findall(r"\$\('([a-z0-9-]+)'\)", PRO_JS))
    used |= set(re.findall(r"\['(adj-[a-z]+)'", PRO_JS))
    assert used, "pro.js 에서 참조 id 를 찾지 못함"
    missing = sorted(used - HTML_IDS)
    assert not missing, f"템플릿에 없는 id: {missing}"


def test_edit_tabs_and_tools_present():
    tabs = re.findall(r'class="ptab[^"]*"[^>]*data-tab="(\w+)"', HTML)
    panes = re.findall(r'class="ppane[^"]*"\s+data-pane="(\w+)"', HTML)
    assert tabs == ["adj", "flt", "edit", "meibo"] and panes == tabs
    tools = re.findall(r'data-tool="(\w+)"', HTML)
    assert set(tools) == {"pan", "magnify", "crop", "text", "arrow", "circle", "length", "angle", "calibrate", "tarsus", "dropout"}
    for t in tools:                                 # 모든 도구에 사용 가능 모드 정의
        assert re.search(rf"\b{t}: \[", PRO_JS), t


def test_channel_and_filter_options_match_engine():
    chans = re.findall(r'<option value="(\w+)"', HTML[HTML.index('id="adj-channel"'):HTML.index("</select>", HTML.index('id="adj-channel"'))])
    assert chans == ["rgb", "green", "red", "blue", "gray"]
    for ch in chans[1:]:
        assert f"'{ch}'" in PRO_JS
    dn = re.findall(r'<option value="(\w+)"', HTML[HTML.index('id="adj-denoise"'):HTML.index("</select>", HTML.index('id="adj-denoise"'))])
    assert dn == ["none", "median", "average"]


def test_meibo_mode_wired():
    APP_JS = (Path(__file__).resolve().parents[1] / "static/js/app.js").read_text(encoding="utf-8")
    for el in ("btn-meibo", "mb-lid-seg", "btn-mb-enh", "btn-mb-inv", "hud-meibo", "meibo-guide",
               "mb-lid", "mb-enhance", "mb-auto", "mb-clear", "mb-save", "mb-result"):
        assert f'id="{el}"' in HTML, el
    assert "id: 'meibo'" in APP_JS and "id: 'lid'" in APP_JS       # 단축키 M / U
    assert "마이봄 ${LID_KO[meibo.lid]}" in APP_JS                 # 촬영 메모 → Pro 에서 안검 자동 선택
    # Arita 경계 (1/3, 2/3) 와 Pult 5단계
    assert "100 / 3" in PRO_JS and "200 / 3" in PRO_JS
    for cat in ("'0%'", "'<25%'", "'25–50%'", "'51–75%'", "'>75%'"):
        assert cat in PRO_JS


def test_sounds_wired():
    """효과음: 사진 캡처 '찰칵' · 정지영상 · 녹화 시작/중지 — 파일·스크립트·설정 버튼이 모두 있어야 한다."""
    APP_JS = (WEB / "static/js/app.js").read_text(encoding="utf-8")
    SND_JS = (WEB / "static/js/sounds.js").read_text(encoding="utf-8")
    for name in ("shutter", "freeze", "rec_start", "rec_stop"):
        f = WEB / "static" / "sounds" / f"{name}.wav"
        assert f.exists() and f.read_bytes()[:4] == b"RIFF", name
        assert f"/static/sounds/{name}.wav" in SND_JS
    assert '<script src="/static/js/sounds.js"></script>' in HTML
    assert HTML.index("sounds.js") < HTML.index("js/app.js")      # app.js 보다 먼저
    assert 'id="btn-sounds"' in HTML and 'id="sounds-label"' in HTML

    def body(start, end=None):
        i = APP_JS.index(start)
        return APP_JS[i:APP_JS.index(end, i)] if end else APP_JS[i:]

    # 촬영 동작마다 효과음
    assert "sfx('shutter')" in body("async function capturePhoto", "function toggleRecord")
    assert "sfx('shutter')" in body("async function saveQuad")
    assert "sfx('rec_start')" in body("function startRecording", "function stopRecording")
    assert "sfx('rec_stop')" in body("function stopRecording", "// 서버 + 지정 폴더 동시 저장")
    assert "sfx('freeze')" in body("function togglePause", "// ---- 효과음")
    assert "sfx('freeze')" in body("function freezeFrame", "function setQuadActive")
    assert "App.sfx('freeze')" in PRO_JS and "App.sfx('shutter')" in PRO_JS
