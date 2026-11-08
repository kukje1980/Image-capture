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


def test_app_js_ids_exist_in_template():
    app_js = (WEB / "static" / "js" / "app.js").read_text(encoding="utf-8")
    used = set(re.findall(r"\$\('([a-z0-9-]+)'\)", app_js))
    missing = sorted(used - HTML_IDS)
    assert not missing, f"템플릿에 없는 id: {missing}"


def test_capture_views_and_bottom_strip():
    """촬영 화면: 위 = 모두·큰·멀티·확대·3D 화면 전환, 아래 = 촬영 이미지 가로 띠."""
    app_js = (WEB / "static" / "js" / "app.js").read_text(encoding="utf-8")
    css = (WEB / "static" / "css" / "app.css").read_text(encoding="utf-8")
    views = re.findall(r'role="radio" data-view="(\w+)"', HTML)
    assert views == ["all", "single", "multi", "zoom", "3d"]
    assert "const VIEWS = ['all', 'single', 'multi', 'zoom', '3d'];" in app_js
    for el in ("view-bar", "zoom-opts", "d3-opts", "d3-canvas", "zoom-map", "hud-view",
               "thumbs-fold"):
        assert f'id="{el}"' in HTML or f'class="{el}"' in HTML, el
    # 4분할은 도크가 아니라 '멀티 화면' 탭으로, 단축키 Q(멀티) · V(보기 전환)
    assert 'id="btn-quad"' not in HTML and "btn-quad" not in app_js
    assert "id: 'view'" in app_js and "btns: ['view-multi']" in app_js
    # 촬영 이미지 띠가 영상 열(video-col) 뒤 = 화면 아래쪽, 가로 스크롤
    assert HTML.index('class="video-col"') < HTML.index('id="thumbs"')
    assert re.search(r"\.thumbs-list \{[^}]*flex-direction: row[^}]*overflow-x: auto", css)
    assert re.search(r"\.workspace \{[^}]*flex-direction: column", css)
    # 3D 저장은 메모 '3D', 파일 이름 꼬리표 _3d
    assert "'3D': '_3d'" in app_js and "null, '3D')" in app_js


def test_all_view_side_panes():
    """모두 보기: 큰 화면 옆 작은 화면 3개(멀티·확대·3D), 기본 보기, 큰 화면에 확대 위치 표시."""
    app_js = (WEB / "static" / "js" / "app.js").read_text(encoding="utf-8")
    panes = re.findall(r'class="pane" data-pane="(\w+)"', HTML)
    assert panes == ["multi", "zoom", "3d"]
    heads = re.findall(r'class="pane-head" data-view="(\w+)"', HTML)      # 제목 = 그 화면 크게
    assert heads == panes
    for el in ("stage", "side-panes", "pane-multi", "pane-zoom", "pane-3d", "zoom-video",
               "zoom-roi"):
        assert f'id="{el}"' in HTML, el
    # 큰 화면(video-frame) 과 작은 화면들이 같은 stage 안, 순서대로
    assert HTML.index('id="stage"') < HTML.index('id="video-frame"') < HTML.index('id="side-panes"')
    assert "setView(prefGet('slitlamp-view') || 'all'" in app_js      # 기본 = 모두 보기, 마지막 기억
    assert "$('zoom-video').srcObject = stream" in app_js             # 확대 칸 = 같은 카메라 스트림
    assert "const usesQuad = (m) => m === 'multi' || m === 'all';" in app_js
