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


def test_dx_reference_feature_wired():
    """질환별 참고 사진: 상단 아이콘 줄 · 패널 · 비교 창의 id 가 템플릿에 있고 라이브러리 아이콘이 스프라이트에 있다."""
    import json
    DX_JS = (WEB / "static" / "js" / "dx.js").read_text(encoding="utf-8")
    used = set(re.findall(r"\$\('([a-z0-9-]+)'\)", DX_JS))
    assert {"dxbar", "dx-panel", "dxp-strip", "dx-dialog", "dxd-ref-img", "dxd-pt-img", "dxd-save", "dxd-print"} <= used
    missing = sorted(used - HTML_IDS)
    assert not missing, f"템플릿에 없는 id: {missing}"
    lib = json.loads((WEB / "static" / "dx" / "library.json").read_text(encoding="utf-8"))
    assert len(lib["diseases"]) >= 10
    for d in lib["diseases"]:
        assert f'id="{d["icon"]}"' in HTML, d["icon"]
        assert (WEB / "static" / "dx" / d["illustrations"][0]["file"]).is_file()
    assert '/static/js/dx.js' in HTML and "/references" in DX_JS
    APP_CSS = (WEB / "static" / "css" / "app.css").read_text(encoding="utf-8")
    for cls in (".dxbar", ".dx-btn", ".dxpanel", ".dx-card", "dialog.dx-dialog", ".dxd-body"):
        assert cls in APP_CSS, cls
    # '이 PC에만 저장' 모드도 같은 API 를 흉내낸다
    LOCAL = (WEB / "static" / "js" / "localstore.js").read_text(encoding="utf-8")
    assert "seg[0] === 'references'" in LOCAL and "'reffiles'" in LOCAL
