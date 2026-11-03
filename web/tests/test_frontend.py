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


def test_import_folder_wired():
    """설정 → 가져오기 폴더: 새로 들어온 사진을 지금 환자에게 가져오고 원본은 '가져옴' 으로 옮긴다."""
    APP_JS = (WEB / "static/js/app.js").read_text(encoding="utf-8")
    for el in ("import-status", "btn-import-folder", "btn-import-off"):
        assert f'id="{el}"' in HTML and f"$('{el}')" in APP_JS, el
    assert "showDirectoryPicker({ id: 'slit-import', mode: 'readwrite' })" in APP_JS
    assert "const IMPORT_DONE = '가져옴'" in APP_JS
    # 저장 폴더와 같은 폴더면 저장한 사진을 다시 가져오므로 양쪽에서 막는다
    assert "dir.isSameEntry(state.dirHandle)" in APP_JS and "dir.isSameEntry(imp.dir)" in APP_JS
    # 전부터 있던 사진은 묻고, 가져온 사진은 내려받기 대신 원본을 폴더에 둔다
    assert "held: imp.first || !havePatient" in APP_JS and "confirm(" in APP_JS
    assert "{ keepSource: true }" in APP_JS and "!opts.keepSource" in APP_JS
    # 옮겨지지 않았으면 다시 가져오지 않게
    assert "return !(await importHas(dir, name))" in APP_JS
    PRO = (WEB / "static/js/pro.js").read_text(encoding="utf-8")
    assert "'slit:imported'" in APP_JS and "'slit:imported'" in PRO
