"""web3d/build.py: the program's 3D eye as one web page (3D 안구 미리보기). The page is built from the
program's own shaders, eye model, textures and photo analysis — these checks keep it buildable."""
import importlib.util
import json
import re
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

ROOT = Path(__file__).resolve().parents[1]


def _build_module():
    spec = importlib.util.spec_from_file_location("web3d_build", ROOT / "web3d" / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_shaders_are_rewritten_for_webgl2():
    b = _build_module()
    sh = b.shaders()
    assert set(sh) >= {"sclera", "cornea", "wall", "tissue", "clear", "section", "bg", "fade"}
    for name, s in sh.items():
        for stage in ("vs", "fs"):
            src = s[stage]
            assert src.startswith("#version 300 es\n"), name
            assert "gl_ClipVertex" not in src and "texture2D" not in src and "#version 120" not in src
            assert not re.search(r"@[A-Z_0-9]+@", src), name           # every model constant filled in
        assert "attribute" not in s["vs"] and re.search(r"\bin vec3 a_pos;", s["vs"])
        assert "gl_FragColor" not in s["fs"] and "out vec4 fragColor_;" in s["fs"]
    assert "uniform mat3  u_place;" in sh["wall"]["fs"]                 # the photo's placement on the eye
    # the page's own lines (WEB_PATCHES): every one still finds its place in the program's shaders
    for part in {p for p, _, _ in b.WEB_PATCHES}:
        assert b.block(part) != getattr(b.e3, part), part               # (each line must match once, in order)
    for name in ("sclera", "cornea", "wall", "tissue", "clear", "section"):
        assert "uniform float u_simple;" in sh[name]["fs"], name        # 단순하게 보기
    assert "u_scan_dir" in sh["wall"]["fs"] and "u_within" in sh["clear"]["fs"]   # 슬릿 방향; no studio lights inside


def test_the_page_is_built_in_one_file(tmp_path):
    b = _build_module()
    out, frag = tmp_path / "eye3d.html", tmp_path / "body.html"
    b.build(out, frag)
    page = out.read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>") and "<title>3D 안구 미리보기</title>" in page
    assert "/*@CSS@*/" not in page and "/*@JS@*/" not in page and "@DATA@" not in page
    assert out.stat().st_size < 8e6                                    # well under a web page's 16 MB
    body = frag.read_text(encoding="utf-8")
    assert not body.lstrip().lower().startswith(("<!doctype", "<html")) and body.lstrip().startswith("<title>")
    data = json.loads(re.search(r'<script type="application/json" id="eye-data">(.*?)</script>', page, re.S).group(1)
                      .replace("<\\/", "</"))
    assert {"shaders", "model", "textures", "photos"} <= set(data)
    assert all(v.startswith("data:image/") for v in data["textures"].values())
    photos = {p["key"]: p for p in data["photos"]}
    assert len(photos) >= 5
    for p in photos.values():                                         # found as the program finds them on import
        assert p["src"].startswith("data:image/jpeg;base64,") and len(p["circle"]) == 3 and p["disc"] is not None
    assert photos["cam45_nasal"]["fovea"] is not None and photos["cam30_disc"]["fovea"] is None   # the macula off the photo
    for control in ('id="autofind"', 'id="simple"', 'id="surface"', 'id="height"', 'name="slitdir"', 'id="journey"'):
        assert control in page, control
    assert 'id="autofind" checked' in page                             # finding the macula and disc is the default
    assert "사진 펼치기" not in page and 'id="unwrap"' not in page and "가로 단면" not in page
    from fundusview.ui import eye_model as em

    m = data["model"]
    assert m["consts"]["R_RET"] == pytest.approx(em.R_RET) and 0.9 < em.R_RET < 0.95 and len(m["wall_base"]["z"]) == len(m["wall_base"]["r"])
