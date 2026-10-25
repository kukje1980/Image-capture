"""장면 분류 모델 학습 — 폴더(라벨별) 의 영상 → 특징 벡터 → 로지스틱 회귀
→ assets/models/scene_model.json

    python tools/agent_train/train_scene.py --data <폴더> [--out assets/models/scene_model.json]

<폴더> 구조: <폴더>/<label>/*.jpg|png
  (label = diffuse slit retro fluorescein ir_meibo external unusable)
  - 공개 데이터셋: tools/agent_train/DATASETS.md 대로 받아서 라벨 폴더에 나눠 넣는다.
  - 병원 데이터: 앱의 [에이전트 메뉴 → 학습 데이터 내보내기] 가 같은 구조로 만든다
    (여러 폴더를 --data 로 여러 번).
  - 'unlabeled' 폴더는 학습에서 뺀다 (손으로 분류해 옮기면 포함).

특징은 app/agent/scene.py 의 extract_features() 와 같으므로,
학습 결과는 앱에서 numpy 만으로 바로 추론된다.
scikit-learn 이 필요하다 (pip install scikit-learn).
표준화 + 다항 로지스틱 회귀(C=1.0), 5-겹 교차검증 정확도를 출력.
CNN(MobileNetV3 → ONNX) 으로 가려면 train_cnn_onnx.py 를 참고.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.agent.scene import FEATURE_NAMES, LABELS, extract_features, feature_vector  # noqa: E402

EXTS = {".jpg", ".jpeg", ".png", ".bmp"}


def load_folder(folder: Path, max_per_class: int = 0):
    xs, ys = [], []
    for label in LABELS:
        d = folder / label
        if not d.is_dir():
            continue
        files = sorted(p for p in d.iterdir() if p.suffix.lower() in EXTS)
        if max_per_class:
            files = files[:max_per_class]
        for p in files:
            img = cv2.imread(str(p), cv2.IMREAD_COLOR)
            if img is None:
                continue
            xs.append(feature_vector(extract_features(img)))
            ys.append(label)
    return xs, ys


def train(xs, ys, c: float = 1.0, folds: int = 5):
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_score
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    X = np.stack(xs).astype(np.float64)
    y = np.asarray(ys)
    pipe = make_pipeline(StandardScaler(), LogisticRegression(C=c, max_iter=2000))
    n_min = min(np.bincount(np.unique(y, return_inverse=True)[1]))
    cv_acc = None
    if folds > 1 and n_min >= folds:
        cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=0)
        cv_acc = float(cross_val_score(pipe, X, y, cv=cv).mean())
    pipe.fit(X, y)
    return pipe, cv_acc


def export(pipe, out: Path, meta: dict) -> dict:
    scaler, clf = pipe.steps[0][1], pipe.steps[1][1]
    model = {
        "kind": "logreg", "features": list(FEATURE_NAMES),
        "classes": [str(c) for c in clf.classes_],
        "mean": scaler.mean_.tolist(), "scale": scaler.scale_.tolist(),
        "coef": clf.coef_.tolist(), "intercept": clf.intercept_.tolist(), "meta": meta,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(model, ensure_ascii=False, indent=1), encoding="utf-8")
    return model


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", action="append", required=True,
                    help="라벨별 폴더 (여러 번 지정 가능)")
    ap.add_argument("--out", default=str(ROOT / "assets" / "models" / "scene_model.json"))
    ap.add_argument("--max-per-class", type=int, default=0)
    ap.add_argument("--C", type=float, default=1.0)
    a = ap.parse_args(argv)
    xs, ys = [], []
    for d in a.data:
        x, y = load_folder(Path(d), a.max_per_class)
        xs += x
        ys += y
    if not xs:
        print("학습할 영상이 없습니다 (폴더 구조: <data>/<label>/*.jpg)", file=sys.stderr)
        return 2
    counts = {lab: ys.count(lab) for lab in LABELS if lab in ys}
    print("데이터:", counts)
    pipe, cv_acc = train(xs, ys, a.C)
    if cv_acc is not None:
        print(f"5-겹 교차검증 정확도: {cv_acc * 100:.1f}%")
    acc = float((pipe.predict(np.stack(xs)) == np.asarray(ys)).mean())
    print(f"학습 데이터 정확도: {acc * 100:.1f}%")
    meta = {"trained_at": datetime.now().isoformat(timespec="seconds"), "counts": counts,
            "cv_accuracy": cv_acc, "train_accuracy": acc, "sources": a.data}
    export(pipe, Path(a.out), meta)
    print("저장:", a.out, "→ 앱을 다시 켜면 이 모델을 씁니다",
          "(설정 agent_model_path 로 다른 경로 지정 가능)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
