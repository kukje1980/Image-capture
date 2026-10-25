"""장면 인식 — 지금 화면이 어떤 조명·부위인지 (규칙 기반 기본, 학습 모델은 있으면 우선).

라벨
    diffuse      확산광 전안부 (각막·홍채 전체)
    slit         슬릿(광학 절단면) — 좁고 긴 밝은 띠
    retro        후방조명(retro-illumination) — 가운데가 밝고 주변이 어두운 원
    fluorescein  코발트블루 + 형광염색 (파란 바탕에 녹황색 발광)
    ir_meibo     적외선 마이봄샘 촬영 (거의 무채색)
    external     외안부·안검 (피부가 많이 보임, 저배율)
    unusable     너무 어둡거나(깜빡임·조명 꺼짐) 하얗게 날아간 화면

특징(feature) 은 320px 폭으로 줄인 영상에서 색·밝기·밝은 띠의 기하로 계산한다 (프레임당 약 2 ms).
같은 특징 벡터를 tools/agent_train/train_scene.py 가 학습에 쓰고,
결과(JSON 가중치)를 LearnedSceneClassifier 가 numpy 만으로 추론한다.
ONNX 모델(CNN) 은 onnxruntime 이 설치되어 있을 때만 쓴다.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

log = logging.getLogger(__name__)

LABELS: Tuple[str, ...] = ("diffuse", "slit", "retro", "fluorescein", "ir_meibo", "external",
                           "unusable")
LABEL_KO = {
    "diffuse": "확산광 전안부", "slit": "슬릿 단면", "retro": "후방조명",
    "fluorescein": "형광염색(코발트)",
    "ir_meibo": "적외선 마이봄", "external": "외안부·안검", "unusable": "판독 불가",
}
FEATURE_NAMES: Tuple[str, ...] = (
    "v_mean", "v_std", "v_p50", "v_p99", "s_mean", "dark_frac", "bright_frac", "gray_frac",
    "blue_frac", "glow_frac", "red_frac", "skin_frac",
    "band_area", "band_elong", "band_width_frac", "band_len_frac", "center_ring_ratio",
    "edge_density",
)
ANALYSIS_WIDTH = 320


@dataclass
class SceneResult:
    label: str = "unusable"
    confidence: float = 0.0
    scores: Dict[str, float] = field(default_factory=dict)
    features: Dict[str, float] = field(default_factory=dict)
    slit_width_px: float = 0.0        # 원본 프레임 픽셀 기준 (슬릿일 때)
    slit_angle_deg: float = 0.0       # 세로 = 0
    source: str = "heuristic"         # heuristic | model | onnx

    @property
    def label_ko(self) -> str:
        return LABEL_KO.get(self.label, self.label)


# ---------------------------------------------------------------- 특징
def to_small(frame: np.ndarray, width: int = ANALYSIS_WIDTH) -> np.ndarray:
    h, w = frame.shape[:2]
    if w <= width:
        return frame
    return cv2.resize(frame, (width, max(1, int(h * width / w))), interpolation=cv2.INTER_AREA)


def _band_geometry(v: np.ndarray) -> Tuple[float, float, float, float, float]:
    """가장 큰 밝은 덩어리의 (면적비, 신장도, 폭비, 길이비, 각도). 신장도 = 장축/단축."""
    p99 = float(np.percentile(v, 99))
    thr = max(0.55, 0.8 * p99)
    mask = (v > thr).astype(np.uint8)
    if mask.sum() < 8:
        return 0.0, 1.0, 0.0, 0.0, 0.0
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return 0.0, 1.0, 0.0, 0.0, 0.0
    idx = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    ys, xs = np.nonzero(lab == idx)
    area = float(xs.size) / mask.size
    if xs.size < 8:
        return area, 1.0, 0.0, 0.0, 0.0
    pts = np.stack([xs, ys], 1).astype(np.float32)
    pts -= pts.mean(0)
    cov = (pts.T @ pts) / pts.shape[0]
    evals, evecs = np.linalg.eigh(cov)
    l_minor, l_major = max(float(evals[0]), 1e-6), max(float(evals[1]), 1e-6)
    elong = math.sqrt(l_major / l_minor)
    width = 4.0 * math.sqrt(l_minor)            # ±2σ
    length = 4.0 * math.sqrt(l_major)
    major = evecs[:, 1]
    angle = math.degrees(math.atan2(float(major[0]), float(major[1])))   # 세로 = 0°
    if angle > 90:
        angle -= 180
    if angle < -90:
        angle += 180
    h, w = v.shape
    return area, elong, width / w, length / max(h, w), angle


def extract_features(frame: np.ndarray) -> Dict[str, float]:
    small = to_small(frame)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    hch = hsv[..., 0].astype(np.int16)
    s = hsv[..., 1].astype(np.float32) / 255.0
    v = hsv[..., 2].astype(np.float32) / 255.0
    f: Dict[str, float] = {}
    f["v_mean"] = float(v.mean())
    f["v_std"] = float(v.std())
    f["v_p50"] = float(np.percentile(v, 50))
    f["v_p99"] = float(np.percentile(v, 99))
    f["s_mean"] = float(s.mean())
    f["dark_frac"] = float((v < 0.08).mean())
    f["bright_frac"] = float((v > 0.92).mean())
    lit = v > 0.15
    chroma = small.max(2).astype(np.int16) - small.min(2).astype(np.int16)
    chroma = chroma.astype(np.float32) / 255.0
    f["gray_frac"] = float(((chroma < 0.07) & lit).sum() / max(1, lit.sum()))
    f["blue_frac"] = float(((hch >= 95) & (hch <= 135) & (s > 0.35) & (v > 0.18)).mean())
    f["glow_frac"] = float(((hch >= 28) & (hch <= 85) & (s > 0.3) & (v > 0.45)).mean())
    f["red_frac"] = float((((hch < 12) | (hch > 165)) & (s > 0.35) & (v > 0.25)).mean())
    f["skin_frac"] = float(((hch >= 3) & (hch <= 25) & (s > 0.15) & (s < 0.6) & (v > 0.35)).mean())
    area, elong, width_frac, len_frac, angle = _band_geometry(v)
    f["band_area"] = area
    f["band_elong"] = min(elong, 40.0)
    f["band_width_frac"] = width_frac
    f["band_len_frac"] = len_frac
    f["_band_angle"] = angle
    h, w = v.shape
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.hypot((xx - w / 2) / h, (yy - h / 2) / h)
    center = v[r < 0.18]
    ring = v[(r > 0.3) & (r < 0.48)]
    f["center_ring_ratio"] = (float(center.mean() / (ring.mean() + 1e-3))
                              if center.size and ring.size else 1.0)
    gray = hsv[..., 2]
    lap = cv2.Laplacian(gray, cv2.CV_16S, ksize=3)
    f["edge_density"] = float((np.abs(lap) > 24).mean())
    return f


def feature_vector(f: Dict[str, float]) -> np.ndarray:
    return np.array([f.get(k, 0.0) for k in FEATURE_NAMES], dtype=np.float32)


# ---------------------------------------------------------------- 규칙 기반
def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def heuristic_scores(f: Dict[str, float]) -> Dict[str, float]:
    sc = {k: 0.0 for k in LABELS}
    nothing_bright = f["v_p99"] < 0.12 or (f["dark_frac"] > 0.9 and f["bright_frac"] < 0.001)
    if nothing_bright or f["v_mean"] < 0.04:
        sc["unusable"] = 1.0                       # 암전·깜빡임 (밝은 구조가 전혀 없음)
    elif f["bright_frac"] > 0.5:
        sc["unusable"] = 1.0                       # 하얗게 날아감
    elif f["v_std"] < 0.03 and f["edge_density"] < 0.01:
        sc["unusable"] = 0.8                       # 균일한 빈 화면 (렌즈 캡·신호 없음)
    if (f["gray_frac"] > 0.85 and f["v_mean"] > 0.12 and f["bright_frac"] < 0.3
            and f["v_std"] > 0.04):
        sc["ir_meibo"] = 0.9                       # 무채색 + 구조가 있음 (적외선)
    if f["blue_frac"] > 0.15:
        sc["fluorescein"] = 0.7 + 0.25 * _clip01(f["glow_frac"] / 0.02)
    elong_ok = _clip01((f["band_elong"] - 2.5) / 4.0)
    if 0.002 <= f["band_area"] <= 0.25 and f["band_width_frac"] < 0.2 and f["band_elong"] > 2.5:
        sc["slit"] = 0.55 + 0.4 * elong_ok
        if f["gray_frac"] > 0.9:
            sc["slit"] *= 0.6                      # 무채색 영상의 세로 구조는 적외선 샘일 가능성
    if f["center_ring_ratio"] > 2.0 and f["band_elong"] < 2.5 and 0.01 <= f["band_area"] <= 0.45:
        sc["retro"] = 0.5 + 0.4 * _clip01((f["center_ring_ratio"] - 2.0) / 2.0)
        if f["dark_frac"] > 0.4:
            sc["retro"] = min(1.0, sc["retro"] + 0.1)   # 어두운 주변 + 밝은 원 = 후방조명
    if f["skin_frac"] > 0.2:
        sc["external"] = 0.5 + 0.45 * _clip01((f["skin_frac"] - 0.2) / 0.3)
    base = 0.45 if f["v_mean"] > 0.1 else 0.1
    if (f["band_elong"] < 2.5 and f["skin_frac"] < 0.15 and f["blue_frac"] < 0.1
            and f["gray_frac"] < 0.8):
        base += 0.3
    sc["diffuse"] = base
    return sc


def _finalize(scores: Dict[str, float], f: Dict[str, float], source: str,
              frame_w: int) -> SceneResult:
    order = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    label, top = order[0]
    second = order[1][1] if len(order) > 1 else 0.0
    conf = _clip01(top) * _clip01(0.5 + (top - second))
    res = SceneResult(label=label, confidence=round(conf, 3),
                      scores={k: round(v, 3) for k, v in scores.items()},
                      features={k: round(v, 4) for k, v in f.items() if not k.startswith("_")},
                      source=source)
    if label == "slit":
        res.slit_width_px = round(f["band_width_frac"] * frame_w, 1)
        res.slit_angle_deg = round(f.get("_band_angle", 0.0), 1)
    return res


class HeuristicSceneClassifier:
    name = "heuristic"

    def classify(self, frame: np.ndarray, f: Optional[Dict[str, float]] = None) -> SceneResult:
        f = f or extract_features(frame)
        return _finalize(heuristic_scores(f), f, "heuristic", frame.shape[1])


# ------------------------------------------------- 학습 모델 (JSON 가중치, numpy 추론)
class LearnedSceneClassifier:
    """tools/agent_train/train_scene.py 가 내보낸 로지스틱 회귀 가중치."""

    name = "model"

    def __init__(self, path):
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        if d.get("kind") != "logreg":
            raise ValueError(f"지원하지 않는 모델 종류: {d.get('kind')}")
        self.features: List[str] = list(d["features"])
        self.classes: List[str] = list(d["classes"])
        self.mean = np.asarray(d["mean"], np.float32)
        self.scale = np.asarray(d["scale"], np.float32)
        self.coef = np.asarray(d["coef"], np.float32)            # (classes, features)
        self.intercept = np.asarray(d["intercept"], np.float32)
        self.meta = d.get("meta", {})
        if self.coef.shape != (len(self.classes), len(self.features)):
            raise ValueError("모델 가중치 크기가 맞지 않습니다")

    def proba(self, f: Dict[str, float]) -> Dict[str, float]:
        x = np.array([f.get(k, 0.0) for k in self.features], np.float32)
        xs = (x - self.mean) / np.where(self.scale > 1e-9, self.scale, 1.0)
        z = self.coef @ xs + self.intercept
        z = z - z.max()
        p = np.exp(z)
        p /= p.sum()
        return {c: float(v) for c, v in zip(self.classes, p, strict=True)}

    def classify(self, frame: np.ndarray, f: Optional[Dict[str, float]] = None) -> SceneResult:
        f = f or extract_features(frame)
        scores = {k: 0.0 for k in LABELS}
        scores.update(self.proba(f))
        return _finalize(scores, f, "model", frame.shape[1])


class OnnxSceneClassifier:
    """CNN(ONNX). 입력 NCHW float32 RGB 0~1 (ImageNet 정규화), 출력 로짓.

    클래스 목록은 <model>.json 의 classes.
    """

    name = "onnx"

    def __init__(self, path):
        import onnxruntime as ort  # 선택 의존성

        path = Path(path)
        self.sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        inp = self.sess.get_inputs()[0]
        self.input_name = inp.name
        shape = inp.shape
        self.size = int(shape[-1]) if isinstance(shape[-1], int) else 128
        side = path.with_suffix(".json")
        meta = json.loads(side.read_text(encoding="utf-8")) if side.exists() else {}
        self.classes = list(meta.get("classes", LABELS))
        self.mean = np.array(meta.get("mean", [0.485, 0.456, 0.406]), np.float32).reshape(3, 1, 1)
        self.std = np.array(meta.get("std", [0.229, 0.224, 0.225]), np.float32).reshape(3, 1, 1)

    def classify(self, frame: np.ndarray, f: Optional[Dict[str, float]] = None) -> SceneResult:
        f = f or extract_features(frame)
        img = cv2.resize(frame, (self.size, self.size), interpolation=cv2.INTER_AREA)
        x = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32).transpose(2, 0, 1) / 255.0
        x = ((x - self.mean) / self.std)[None]
        z = np.asarray(self.sess.run(None, {self.input_name: x})[0], np.float32).reshape(-1)
        z = z - z.max()
        p = np.exp(z)
        p /= p.sum()
        scores = {k: 0.0 for k in LABELS}
        scores.update({c: float(v) for c, v in zip(self.classes, p, strict=False)})
        return _finalize(scores, f, "onnx", frame.shape[1])


class SceneClassifier:
    """모델이 있으면 모델, 확신이 낮으면 규칙 기반으로 보완."""

    def __init__(self, model_path: Optional[str] = None, min_model_conf: float = 0.55):
        self.heuristic = HeuristicSceneClassifier()
        self.model = None
        self.min_model_conf = min_model_conf
        if model_path:
            self.model = load_model(model_path)

    def classify(self, frame: np.ndarray) -> SceneResult:
        f = extract_features(frame)
        if self.model is not None:
            try:
                r = self.model.classify(frame, f)
                if r.confidence >= self.min_model_conf:
                    return r
            except Exception:  # noqa: BLE001
                log.warning("장면 모델 추론 실패 — 규칙 기반으로 계속", exc_info=True)
                self.model = None
        return self.heuristic.classify(frame, f)


def load_model(path):
    p = Path(path)
    if not p.exists():
        log.warning("장면 모델 파일이 없습니다: %s", p)
        return None
    try:
        if p.suffix.lower() == ".onnx":
            return OnnxSceneClassifier(p)
        return LearnedSceneClassifier(p)
    except Exception:  # noqa: BLE001
        log.warning("장면 모델을 불러오지 못했습니다: %s", p, exc_info=True)
        return None


def default_model_path():
    """번들/저장소의 assets/models/scene_model.json (있을 때만)."""
    from app.sounds import assets_dir

    for name in ("scene_model.onnx", "scene_model.json"):
        p = assets_dir() / "models" / name
        if p.exists():
            return p
    return None
