"""검사 프로토콜 — 검사 목적별로 '있어야 하는 샷' 목록과 체크리스트.

항목은 (장면 라벨, 눈) 이다. 눈 'ANY' 는 어느 눈이든 한 장이면 된다.
체크리스트는 환자(세션)마다 새로 시작한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

from app.agent.scene import LABEL_KO

PROTOCOLS: Dict[str, dict] = {
    "basic": {"name": "기본 전안부",
              "shots": [("diffuse", "OD"), ("diffuse", "OS"), ("slit", "OD"), ("slit", "OS")]},
    "cataract": {"name": "백내장",
                 "shots": [("diffuse", "ANY"), ("slit", "ANY"), ("retro", "ANY")]},
    "dry_eye": {"name": "건성안·각막", "shots": [("diffuse", "ANY"), ("fluorescein", "ANY")]},
    "meibo": {"name": "마이봄샘", "shots": [("ir_meibo", "ANY"), ("external", "ANY")]},
    "free": {"name": "자유 촬영 (목록 없음)", "shots": []},
}
EYE_KO = {"OD": "우안", "OS": "좌안", "OU": "양안", "ANY": "", "NA": ""}


@dataclass
class ChecklistItem:
    scene: str
    eye: str
    done: bool = False
    count: int = 0

    @property
    def text(self) -> str:
        eye = EYE_KO.get(self.eye, self.eye)
        return f"{LABEL_KO.get(self.scene, self.scene)}{(' ' + eye) if eye else ''}"


@dataclass
class Checklist:
    protocol: str = "basic"
    items: List[ChecklistItem] = field(default_factory=list)
    taken: Set[Tuple[str, str]] = field(default_factory=set)      # (scene, eye) 실제로 찍힌 조합

    @classmethod
    def for_protocol(cls, key: str) -> "Checklist":
        key = key if key in PROTOCOLS else "basic"
        return cls(protocol=key, items=[ChecklistItem(s, e) for s, e in PROTOCOLS[key]["shots"]])

    def mark(self, scene: str, eye: str) -> List[ChecklistItem]:
        """촬영이 일어났을 때 호출. 새로 완료된 항목을 돌려준다."""
        eye = eye if eye in ("OD", "OS", "OU") else "NA"
        self.taken.add((scene, eye))
        newly: List[ChecklistItem] = []
        for it in self.items:
            if it.scene != scene:
                continue
            if it.eye == "ANY" or it.eye == eye or eye == "OU":
                it.count += 1
                if not it.done:
                    it.done = True
                    newly.append(it)
        return newly

    def has(self, scene: str, eye: str) -> bool:
        eye = eye if eye in ("OD", "OS", "OU") else "NA"
        return (scene, eye) in self.taken

    def remaining(self) -> List[ChecklistItem]:
        return [it for it in self.items if not it.done]

    @property
    def complete(self) -> bool:
        return all(it.done for it in self.items)

    def reset(self) -> None:
        for it in self.items:
            it.done, it.count = False, 0
        self.taken.clear()
