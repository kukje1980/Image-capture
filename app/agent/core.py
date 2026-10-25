"""에이전트 상태 머신 — 관찰(품질·장면) 을 모아 판단하고 행동(자동 촬영·클립·안내) 을 결정한다.

Qt 를 모르는 순수 파이썬이라 테스트하기 쉽다. 행동은 Decision 목록으로 돌려주고, 실제 저장·표시는
main_window 가 한다. 원칙:
  - 같은 환자 세션에서 같은 (장면, 눈) 은 자동으로 한 번만 찍는다
    (의사가 체크리스트를 초기화하면 다시).
  - 장면이 1초 이상 안정되고(같은 라벨, 확신 ≥ min_conf), 초점이 맞고, 흔들림이 없을 때만 찍는다.
  - 자동 촬영 사이에는 쿨다운을 둔다.
  - 모든 판단에는 reason 문자열이 붙어 로그와 화면에 그대로 남는다 (왜 찍었는지 설명 가능).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional

from app.agent.protocol import Checklist
from app.agent.scene import LABEL_KO, SceneResult


@dataclass
class AgentSettings:
    auto_capture: bool = True
    min_conf: float = 0.6            # 장면 확신 하한
    stable_s: float = 1.0            # 같은 장면이 이 시간 이상 유지돼야 함
    cooldown_s: float = 3.0          # 자동 촬영 사이 최소 간격
    min_focus_pct: float = 85.0      # smart_capture 의 상대 초점 (%)
    min_stability: float = 60.0      # 흔들림 점수 하한 (0~100)
    protocol: str = "basic"
    retake_after_s: float = 0.0      # >0 이면 같은 조합을 이 시간 뒤 다시 허용 (0 = 세션당 한 번)


@dataclass
class Decision:
    kind: str        # auto_capture | scene_changed | hint | checklist_done | checklist_item
    reason: str = ""
    scene: Optional[SceneResult] = None
    eye: str = "NA"
    score: float = 0.0
    payload: dict = field(default_factory=dict)


@dataclass
class SceneState:
    label: str = "unusable"
    confidence: float = 0.0
    since: float = 0.0            # 이 라벨이 시작된 시각
    last: Optional[SceneResult] = None

    def stable_for(self, t: float) -> float:
        return t - self.since


class AgentCore:
    def __init__(self, settings: Optional[AgentSettings] = None):
        self.settings = settings or AgentSettings()
        self.checklist = Checklist.for_protocol(self.settings.protocol)
        self.state = SceneState()
        self._votes: Deque[str] = deque(maxlen=6)
        self._last_auto_t = -1e9
        self._last_taken: Dict[tuple, float] = {}
        self._hint = ""
        self.session_t0 = 0.0

    # ---- 설정·세션 ----
    def update_settings(self, s: AgentSettings) -> None:
        proto_changed = s.protocol != self.settings.protocol
        self.settings = s
        if proto_changed:
            self.checklist = Checklist.for_protocol(s.protocol)

    def new_session(self, t: float = 0.0) -> None:
        """환자가 바뀌면 체크리스트·촬영 기록을 새로 시작."""
        self.checklist = Checklist.for_protocol(self.settings.protocol)
        self._last_taken.clear()
        self._last_auto_t = -1e9
        self.session_t0 = t

    def reset_checklist(self) -> None:
        self.checklist.reset()
        self._last_taken.clear()

    # ---- 관찰 ----
    def observe_scene(self, r: SceneResult, t: float) -> Optional[Decision]:
        """장면 결과를 다수결로 부드럽게 하여 상태를 갱신.

        라벨이 바뀌면 scene_changed 를 돌려준다.
        """
        self._votes.append(r.label)
        label = max(set(self._votes), key=self._votes.count)
        self.state.last = r
        self.state.confidence = r.confidence if r.label == label else min(r.confidence, 0.5)
        if label != self.state.label:
            self.state.label = label
            self.state.since = t
            return Decision("scene_changed", reason=f"장면: {LABEL_KO.get(label, label)}", scene=r)
        return None

    def note_capture(self, scene_label: str, eye: str, t: float,
                     auto: bool = False) -> List[Decision]:
        """촬영(수동·자동)이 일어났음을 알린다 → 체크리스트 갱신."""
        out: List[Decision] = []
        self._last_taken[(scene_label, eye)] = t
        if auto:
            self._last_auto_t = t
        for it in self.checklist.mark(scene_label, eye):
            out.append(Decision("checklist_item", reason=f"체크: {it.text}", eye=eye,
                                payload={"item": it.text}))
        if self.checklist.items and self.checklist.complete:
            out.append(Decision("checklist_done", reason="프로토콜의 샷을 모두 찍었습니다"))
        return out

    def decide(self, quality, scene: SceneResult, t: float, eye: str,
               live: bool = True) -> List[Decision]:
        """매 분석 프레임마다 호출. quality 는 smart_capture.FrameQuality (없으면 None)."""
        out: List[Decision] = []
        changed = self.observe_scene(scene, t)
        if changed:
            out.append(changed)
        s = self.settings
        label = self.state.label
        hint = self._make_hint(quality, label, t)
        if hint != self._hint:
            self._hint = hint
            out.append(Decision("hint", reason=hint))
        if not (s.auto_capture and live) or label == "unusable" or quality is None:
            return out
        if self.state.stable_for(t) < s.stable_s or self.state.confidence < s.min_conf:
            return out
        if (not quality.usable or quality.focus_pct < s.min_focus_pct
                or quality.stability < s.min_stability):
            return out
        if t - self._last_auto_t < s.cooldown_s:
            return out
        key = (label, eye)
        last = self._last_taken.get(key)
        if last is not None and (s.retake_after_s <= 0 or t - last < s.retake_after_s):
            return out
        ko = LABEL_KO.get(label, label)
        reason = (f"{ko} 장면이 {self.state.stable_for(t):.1f}초 안정 · "
                  f"초점 {quality.focus_pct:.0f} · 흔들림 없음 · 이 눈의 첫 {ko} 샷")
        self._last_auto_t = t          # 저장이 실패해도 쿨다운은 지킨다 (연속 발사 방지)
        out.append(Decision("auto_capture", reason=reason, scene=scene, eye=eye,
                            score=quality.focus_pct))
        return out

    def _make_hint(self, quality, label: str, t: float) -> str:
        if label == "unusable":
            return "화면을 판독할 수 없습니다 (너무 어둡거나 밝음)"
        if quality is None:
            return ""
        if not quality.usable:
            return quality.hint if getattr(quality, "hint", "") else "촬영 조건이 아직 아닙니다"
        remaining = self.checklist.remaining()
        if remaining:
            nxt = remaining[0]
            return f"다음 샷: {nxt.text} (남은 {len(remaining)}장)"
        if self.checklist.items:
            return "프로토콜 완료 · 자유 촬영"
        return ""
