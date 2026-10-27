"""분할 칸 수 고르기 메뉴 (기본판 · Keeler판 촬영 도크와 Explorer 판 공용).

처음 분할을 누를 때 2 · 4 · 6 · 8 · 16칸 중에서 고르면 그 칸 수가 저장되고(config.split_count_saved),
그다음부터 분할 버튼은 묻지 않고 바로 그 칸 수로 시작한다. 바꿀 때는 분할 버튼 오른쪽 클릭 · 설정.
메뉴 맨 아래 '누를 때마다 칸 수 묻기' 를 켜면 다시 매번 묻는다.
"""
from __future__ import annotations

from PySide6.QtWidgets import QMenu

from app.ui.quad_view import SPLIT_COUNTS

ASK_TEXT = "누를 때마다 칸 수 묻기"


def build_menu(parent, current: int, saved: bool) -> QMenu:
    menu = QMenu(parent)
    for n in SPLIT_COUNTS:
        a = menu.addAction(f"{n}분할")
        a.setCheckable(True)
        a.setChecked(n == current)
    menu.addSeparator()
    ask = menu.addAction(ASK_TEXT)
    ask.setCheckable(True)
    ask.setChecked(not saved)
    ask.setToolTip("끄면 고른 칸 수로 바로 분할을 시작합니다")
    return menu


def resolve(chosen) -> int | str | None:
    """고른 메뉴 항목 → 칸 수 · "ask"('누를 때마다 묻기' 전환) · None(닫음)."""
    if chosen is None:
        return None
    text = chosen.text()
    if text == ASK_TEXT:
        return "ask"
    if text.endswith("분할"):
        try:
            n = int(text[:-2])
        except ValueError:
            return None
        return n if n in SPLIT_COUNTS else None
    return None


def popup_pos(menu: QMenu, anchor):
    """버튼 바로 위에 메뉴를 띄울 위치 (도크 · 도구줄이 화면 아래쪽에 있어서)."""
    pos = anchor.mapToGlobal(anchor.rect().topLeft())
    pos.setY(pos.y() - menu.sizeHint().height() - 4)
    return pos


def choose(config, parent, anchor, exec_menu) -> int | None:
    """메뉴로 칸 수를 고르고 config 에 저장한다. 고른 칸 수(또는 None)를 돌려준다.

    '누를 때마다 칸 수 묻기' 를 누르면 저장 여부만 바꾸고 None (분할은 켜지 않음).
    """
    current = int(getattr(config, "split_count", 4) or 4)
    saved = bool(getattr(config, "split_count_saved", False))
    menu = build_menu(parent, current, saved)
    try:
        r = resolve(exec_menu(menu, popup_pos(menu, anchor)))
    finally:
        menu.deleteLater()
    if r is None:
        return None
    if r == "ask":
        config.split_count_saved = not saved
        _save(config)
        return None
    config.split_count = r
    config.split_count_saved = True
    _save(config)
    return r


def _save(config) -> None:
    try:
        config.save()
    except Exception:  # noqa: BLE001
        pass
