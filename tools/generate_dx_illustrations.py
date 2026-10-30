"""질환별 참고 모식도(SVG) 생성기 — assets/dx/*.svg 와 web/static/dx/*.svg 를 같은 내용으로 만든다.

    python tools/generate_dx_illustrations.py

모식도는 실제 사진이 아니라 소견 '위치·모양'을 설명하기 위한 그림이다. 전안부(눈꺼풀·결막·각막·홍채·동공)
기본 그림 위에 질환별 소견을 겹쳐 그린다. 질환 목록은 assets/dx/library.json 의 illustrations.file 과 맞춘다.
"""
from __future__ import annotations

import json
import math
import random
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets" / "dx"
WEB = ROOT / "web" / "static" / "dx"

W, H = 480, 320
CX, CY, R_IRIS, R_PUPIL = 240, 160, 78, 30
EYE_PATH = "M40 160 Q240 22 440 160 Q240 298 40 160 Z"


def vessels(seed: int, n: int, side: str, color: str = "#c0392b", width: float = 1.6,
            opacity: float = 0.55, toward_limbus: bool = True) -> str:
    """결막 혈관: 눈구석(side=left/right)에서 윤부 쪽으로 가는 가지 친 꺾은선."""
    rnd = random.Random(seed)
    out = []
    for _ in range(n):
        if side == "left":
            x, y = rnd.uniform(48, 95), rnd.uniform(120, 200)
            dx = 1
        else:
            x, y = rnd.uniform(385, 432), rnd.uniform(120, 200)
            dx = -1
        pts = [(x, y)]
        for _k in range(5):
            x += dx * rnd.uniform(12, 24)
            y += rnd.uniform(-14, 14) + (CY - y) * (0.12 if toward_limbus else 0)
            pts.append((x, y))
        d = "M" + " L".join(f"{px:.1f} {py:.1f}" for px, py in pts)
        w = width * rnd.uniform(0.6, 1.3)
        out.append(f'<path d="{d}" stroke="{color}" stroke-width="{w:.2f}" fill="none" '
                   f'stroke-linecap="round" opacity="{opacity}"/>')
        if rnd.random() < 0.6:   # 가지
            bx, by = pts[rnd.randint(1, 3)]
            ex, ey = bx + dx * rnd.uniform(14, 30), by + rnd.uniform(-22, 22)
            out.append(f'<path d="M{bx:.1f} {by:.1f} L{ex:.1f} {ey:.1f}" stroke="{color}" '
                       f'stroke-width="{w * 0.6:.2f}" fill="none" stroke-linecap="round" opacity="{opacity}"/>')
    return "\n".join(out)


def iris_strokes() -> str:
    out = []
    for i in range(48):
        a = i * (2 * math.pi / 48)
        r0 = R_PUPIL + 4
        r1 = R_IRIS - (6 if i % 2 else 12)
        out.append(f'<line x1="{CX + r0 * math.cos(a):.1f}" y1="{CY + r0 * math.sin(a):.1f}" '
                   f'x2="{CX + r1 * math.cos(a):.1f}" y2="{CY + r1 * math.sin(a):.1f}" '
                   f'stroke="#2b1a0f" stroke-width="{1.4 if i % 3 else 2.2}" opacity=".35"/>')
    return "\n".join(out)


def base(pupil: str | None = None, extra_eye: str = "", extra_over: str = "", sclera_fill: str = "url(#sclera)",
         lids: str = "", lashes: bool = True) -> str:
    pupil = pupil or f'<circle cx="{CX}" cy="{CY}" r="{R_PUPIL}" fill="#0b0b10"/>'
    lash = ""
    if lashes:
        parts = []
        for i in range(14):
            t = (i + 0.5) / 14
            x = 40 + 400 * t
            y = 160 - 138 * (1 - (2 * t - 1) ** 2)
            parts.append(f'<path d="M{x:.1f} {y + 2:.1f} q{(t - 0.5) * 10:.1f} -14 {(t - 0.5) * 22:.1f} -20" '
                         f'stroke="#3a2a22" stroke-width="2.2" fill="none" stroke-linecap="round"/>')
        lash = "\n".join(parts)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img">
<defs>
  <radialGradient id="iris" cx="50%" cy="50%" r="50%">
    <stop offset="0" stop-color="#8c5a2f"/><stop offset=".55" stop-color="#6a3f1e"/><stop offset="1" stop-color="#2d1a0d"/>
  </radialGradient>
  <radialGradient id="sclera" cx="50%" cy="50%" r="55%">
    <stop offset="0" stop-color="#fbfaf6"/><stop offset=".78" stop-color="#f3f0e8"/><stop offset="1" stop-color="#ded8cf"/>
  </radialGradient>
  <radialGradient id="scleraPink" cx="50%" cy="50%" r="55%">
    <stop offset="0" stop-color="#fbeeee"/><stop offset=".7" stop-color="#f6d9d9"/><stop offset="1" stop-color="#e7b9b9"/>
  </radialGradient>
  <radialGradient id="flush" cx="50%" cy="50%" r="50%">
    <stop offset=".60" stop-color="#b3253a" stop-opacity="0"/><stop offset=".66" stop-color="#b3253a" stop-opacity=".7"/>
    <stop offset="1" stop-color="#b3253a" stop-opacity="0"/>
  </radialGradient>
  <radialGradient id="cloud" cx="45%" cy="40%" r="60%">
    <stop offset="0" stop-color="#f1ecd6"/><stop offset=".6" stop-color="#d9cfa8"/><stop offset="1" stop-color="#a3996f"/>
  </radialGradient>
  <radialGradient id="infil" cx="50%" cy="50%" r="50%">
    <stop offset="0" stop-color="#e9e6dc" stop-opacity=".98"/><stop offset=".7" stop-color="#d8d4c8" stop-opacity=".85"/>
    <stop offset="1" stop-color="#d8d4c8" stop-opacity="0"/>
  </radialGradient>
  <linearGradient id="skin" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#f2d7bd"/><stop offset="1" stop-color="#e3b893"/>
  </linearGradient>
  <filter id="soft" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="3"/></filter>
  <filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="1.6"/></filter>
  <clipPath id="eye"><path d="{EYE_PATH}"/></clipPath>
  <clipPath id="cornea"><circle cx="{CX}" cy="{CY}" r="{R_IRIS + 2}"/></clipPath>
</defs>
<rect width="{W}" height="{H}" fill="url(#skin)"/>
<!-- 눈꺼풀 주름 -->
<path d="M30 118 Q240 -22 450 118" stroke="#c99a79" stroke-width="3" fill="none" opacity=".55"/>
<path d="M44 196 Q240 318 436 196" stroke="#c99a79" stroke-width="2" fill="none" opacity=".4"/>
{lids}
<g clip-path="url(#eye)">
  <path d="{EYE_PATH}" fill="{sclera_fill}"/>
  {vessels(1, 4, "left", opacity=0.28, width=1.2)}
  {vessels(2, 4, "right", opacity=0.28, width=1.2)}
  {extra_eye}
  <circle cx="{CX}" cy="{CY}" r="{R_IRIS}" fill="url(#iris)"/>
  {iris_strokes()}
  <circle cx="{CX}" cy="{CY}" r="{R_IRIS}" fill="none" stroke="#1c110a" stroke-width="3" opacity=".55"/>
  {pupil}
  <ellipse cx="{CX - 26}" cy="{CY - 30}" rx="11" ry="7" fill="#fff" opacity=".92"/>
  <ellipse cx="{CX + 30}" cy="{CY + 34}" rx="5" ry="3.5" fill="#fff" opacity=".45"/>
  {extra_over}
  <path d="M40 160 Q240 22 440 160" stroke="#3a2a22" stroke-width="5" fill="none" opacity=".35"/>
</g>
<path d="{EYE_PATH}" fill="none" stroke="#5a3b2b" stroke-width="3.5"/>
{lash}
<text x="{W - 10}" y="{H - 10}" font-family="Pretendard, 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif" font-size="12"
      fill="#5a3b2b" text-anchor="end" opacity=".8">모식도 · 실제 사진 아님</text>
</svg>
'''


def dots(seed: int, n: int, cx: float, cy: float, rx: float, ry: float, color: str, r: float,
         ymin: float | None = None) -> str:
    rnd = random.Random(seed)
    out = []
    for _ in range(n):
        a, d = rnd.uniform(0, 2 * math.pi), math.sqrt(rnd.random())
        x, y = cx + rx * d * math.cos(a), cy + ry * d * math.sin(a)
        if ymin is not None and y < ymin:
            continue
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r * rnd.uniform(0.7, 1.4):.2f}" fill="{color}" filter="url(#glow)"/>')
    return "\n".join(out)


def build() -> dict[str, str]:
    svgs: dict[str, str] = {}
    svgs["normal"] = base()

    svgs["cataract"] = base(
        pupil=f'<circle cx="{CX}" cy="{CY}" r="{R_PUPIL}" fill="url(#cloud)"/>'
              + "".join(f'<line x1="{CX}" y1="{CY}" x2="{CX + R_PUPIL * math.cos(a):.1f}" y2="{CY + R_PUPIL * math.sin(a):.1f}" '
                        f'stroke="#fff" stroke-width="2.4" opacity=".45"/>'
                        for a in (0.3, 1.1, 2.0, 2.9, 3.9, 4.8, 5.6))
              + f'<circle cx="{CX}" cy="{CY}" r="{R_PUPIL}" fill="none" stroke="#6b6140" stroke-width="1.5" opacity=".6"/>')

    ptg_vessels = "".join(
        f'<path d="M62 {150 + k * 6} Q130 {152 + k * 4} 196 {158 + k * 1.2}" stroke="#c0392b" stroke-width="1.5" fill="none" opacity=".75"/>'
        for k in range(-2, 3))
    svgs["pterygium"] = base(
        extra_eye=vessels(5, 6, "left", opacity=0.5),
        extra_over=(
            '<path d="M44 128 Q130 130 204 154 Q214 160 204 166 Q130 190 44 192 Z" fill="#f4e6df" opacity=".94"/>'
            + ptg_vessels
            + '<path d="M196 150 Q212 160 196 170" stroke="#7a4b3a" stroke-width="1.6" fill="none" opacity=".6"/>'))

    svgs["conjunctivitis"] = base(
        sclera_fill="url(#scleraPink)",
        extra_eye=vessels(11, 14, "left", width=2.0, opacity=0.78) + vessels(12, 14, "right", width=2.0, opacity=0.78)
        + '<path d="M120 236 Q200 262 300 250" stroke="#e8e4c8" stroke-width="5" fill="none" opacity=".75" stroke-linecap="round"/>')

    svgs["subconj_hemorrhage"] = base(
        extra_eye=(
            '<path d="M318 112 Q372 110 426 150 Q442 162 428 176 Q376 214 318 206 Q334 160 318 112 Z" fill="#b0161e"/>'
            '<path d="M330 128 Q372 128 416 154 Q400 184 330 192 Q342 160 330 128 Z" fill="#c8232b" opacity=".7"/>'))

    svgs["dry_eye"] = base(
        extra_over=(
            f'<g clip-path="url(#cornea)">{dots(21, 90, CX, CY + 18, 74, 60, "#43ff6a", 1.8, ymin=CY - 8)}</g>'
            + dots(22, 10, 150, 190, 40, 24, "#43ff6a", 1.5) + dots(23, 10, 330, 190, 40, 24, "#43ff6a", 1.5)
            + f'<path d="{EYE_PATH}" fill="#1d3fa8" opacity=".16"/>'
            + '<path d="M70 196 Q240 240 410 196" stroke="#8fffb0" stroke-width="2" fill="none" opacity=".55"/>'))

    svgs["keratitis"] = base(
        extra_eye=f'<circle cx="{CX}" cy="{CY}" r="{R_IRIS + 46}" fill="url(#flush)"/>'
        + vessels(31, 7, "left", width=1.8, opacity=0.6) + vessels(32, 7, "right", width=1.8, opacity=0.6),
        extra_over=(
            f'<ellipse cx="{CX + 24}" cy="{CY - 14}" rx="30" ry="24" fill="url(#infil)" filter="url(#soft)"/>'
            f'<ellipse cx="{CX + 24}" cy="{CY - 14}" rx="18" ry="14" fill="#efece2" opacity=".96"/>'
            f'<g clip-path="url(#cornea)"><rect x="{CX - 80}" y="{CY + 56}" width="160" height="30" fill="#f1e8b5" opacity=".9"/></g>'
            f'<circle cx="{CX}" cy="{CY}" r="{R_IRIS}" fill="#cfd6dc" opacity=".22"/>'))

    def lid_y(t: float, upper: bool) -> float:        # 눈꺼풀 가장자리(눈 모양 곡선) 위의 y
        c = 22 if upper else 298
        return (1 - t) ** 2 * 160 + 2 * (1 - t) * t * c + t * t * 160

    plugs = "".join(
        f'<circle cx="{40 + 400 * t:.1f}" cy="{lid_y(t, False) + 5:.1f}" r="3" fill="#f2e2a3" stroke="#b9a05e" stroke-width=".8"/>'
        for t in [0.14 + i * 0.06 for i in range(13)])
    collarettes = "".join(
        f'<ellipse cx="{40 + 400 * t:.1f}" cy="{lid_y(t, True) - 3:.1f}" rx="4" ry="2.4" fill="#efe9d8" stroke="#bfae8a" stroke-width=".6"/>'
        for t in [0.12 + i * 0.07 for i in range(11)])
    svgs["blepharitis"] = base(
        lids=('<path d="M40 160 Q240 298 440 160 Q240 326 40 160 Z" fill="#d9706e" opacity=".85"/>'
              '<path d="M40 160 Q240 22 440 160 Q240 0 40 160 Z" fill="#d9706e" opacity=".6"/>' + plugs + collarettes),
        extra_eye=vessels(41, 6, "left", opacity=0.45) + vessels(42, 6, "right", opacity=0.45))

    svgs["chalazion"] = base(
        lids=('<ellipse cx="300" cy="78" rx="46" ry="30" fill="#d98a7c" opacity=".55" filter="url(#soft)"/>'
              '<ellipse cx="300" cy="80" rx="36" ry="24" fill="#e5a08f" opacity=".9"/>'
              '<ellipse cx="290" cy="70" rx="14" ry="8" fill="#f3c7b7" opacity=".8"/>'
              '<path d="M250 112 Q300 92 350 112" stroke="#a86a5a" stroke-width="2" fill="none" opacity=".6"/>'))

    irregular_pupil = (
        f'<path d="M{CX - 22} {CY} C{CX - 22} {CY - 14} {CX - 14} {CY - 24} {CX} {CY - 22} '
        f'C{CX + 8} {CY - 30} {CX + 22} {CY - 20} {CX + 22} {CY - 6} C{CX + 30} {CY} {CX + 22} {CY + 16} {CX + 10} {CY + 20} '
        f'C{CX + 2} {CY + 28} {CX - 12} {CY + 22} {CX - 18} {CY + 14} C{CX - 28} {CY + 8} {CX - 22} {CY + 2} {CX - 22} {CY} Z" fill="#0b0b10"/>')
    svgs["uveitis"] = base(
        pupil=irregular_pupil,
        extra_eye=f'<circle cx="{CX}" cy="{CY}" r="{R_IRIS + 46}" fill="url(#flush)" opacity=".95"/>'
        + f'<circle cx="{CX}" cy="{CY}" r="{R_IRIS + 30}" fill="url(#flush)" opacity=".6"/>',
        extra_over=f'<g clip-path="url(#cornea)">{dots(51, 14, CX, CY + 40, 60, 28, "#d9d3c4", 1.7)}</g>')

    svgs["pinguecula"] = base(
        extra_eye=vessels(61, 3, "left", opacity=0.4),
        extra_over=('<ellipse cx="138" cy="168" rx="18" ry="12" fill="#efe1a5" stroke="#c7b36a" stroke-width="1.2"/>'
                    '<ellipse cx="134" cy="164" rx="8" ry="4" fill="#f8f1cf" opacity=".9"/>'))
    return svgs


def main() -> int:
    lib = json.loads((ASSETS / "library.json").read_text(encoding="utf-8"))
    wanted = {ill["file"] for d in lib["diseases"] for ill in d["illustrations"]}
    svgs = build()
    for d in lib["diseases"]:
        for ill in d["illustrations"]:
            assert ill["file"][:-4] in svgs, f"모식도 없음: {ill['file']}"
    for out in (ASSETS, WEB):
        out.mkdir(parents=True, exist_ok=True)
        for name, svg in svgs.items():
            if f"{name}.svg" in wanted:
                (out / f"{name}.svg").write_text(svg, encoding="utf-8")
    shutil.copyfile(ASSETS / "library.json", WEB / "library.json")
    print(f"{len(wanted)} illustrations → {ASSETS} , {WEB}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
