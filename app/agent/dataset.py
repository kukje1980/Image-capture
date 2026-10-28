"""학습 데이터 내보내기 — 병원 설치본의 캡처(사진) + 라벨(장면·눈·품질) 을 익명 폴더로 만든다.

출력 구조 (tools/agent_train/train_scene.py 가 그대로 읽는다)
    <out>/<label>/<hash>.jpg          긴 변 640px 로 줄인 영상 (환자 정보 없음, 파일명은 내용 해시)
    <out>/manifest.csv                file,label,eye,source,quality_focus,quality_exposure,...,note
라벨 출처 우선순위: 1) 의사가 확정한 라벨(candidate_accepted·label 이벤트)
2) 자동 촬영 때의 장면 라벨  3) 코멘트의 조명 태그(없으면 제외).
라벨이 없는 캡처는 'unlabeled/' 로 보내 나중에 손으로 분류할 수 있게 한다.
"""
from __future__ import annotations

import csv
import hashlib
import logging
from pathlib import Path
from typing import Dict, Optional

import cv2

from app.agent.scene import LABELS

log = logging.getLogger(__name__)

NOTE_TAGS = {
    "형광": "fluorescein", "코발트": "fluorescein", "마이봄": "ir_meibo", "적외선": "ir_meibo",
    "슬릿": "slit", "후방": "retro", "확산": "diffuse", "외안부": "external", "안검": "external",
}


def label_from_note(note: Optional[str]) -> Optional[str]:
    if not note:
        return None
    for k, v in NOTE_TAGS.items():
        if k in note:
            return v
    return None


def export_training_data(db, out_dir, max_side: int = 640, include_unlabeled: bool = True,
                         progress=None) -> Dict[str, int]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    labels = db.agent_events.labels_by_capture() if getattr(db, "agent_events", None) else {}
    rows = db._conn.execute(
        "SELECT * FROM captures WHERE media_type='photo' ORDER BY id").fetchall()
    counts: Dict[str, int] = {}
    with open(out / "manifest.csv", "w", newline="", encoding="utf-8") as mf:
        w = csv.writer(mf)
        w.writerow(["file", "label", "eye", "source", "focus_pct", "exposure", "stability",
                    "reflection", "note"])
        for i, r in enumerate(rows):
            src = Path(r["file_path"])
            if not src.exists():
                continue
            info = labels.get(int(r["id"]))
            label = (info or {}).get("label") or label_from_note(r["note"])
            source = "doctor" if info and info["type"] in ("candidate_accepted", "label") else (
                "auto" if info else ("note" if label else ""))
            if label not in LABELS:
                if not include_unlabeled:
                    continue
                label, source = "unlabeled", "none"
            img = cv2.imread(str(src), cv2.IMREAD_COLOR)
            if img is None:
                continue
            h, wd = img.shape[:2]
            scale = max_side / max(h, wd)
            if scale < 1:
                img = cv2.resize(img, (int(wd * scale), int(h * scale)),
                                 interpolation=cv2.INTER_AREA)
            ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
            if not ok:
                continue
            name = hashlib.sha1(enc.tobytes()).hexdigest()[:16] + ".jpg"
            d = out / label
            d.mkdir(exist_ok=True)
            (d / name).write_bytes(enc.tobytes())
            q = (info or {}).get("data", {}).get("quality", {}) if info else {}
            w.writerow([f"{label}/{name}", label, r["eye"] or "", source,
                        q.get("focus_pct", ""), q.get("exposure", ""), q.get("stability", ""),
                        q.get("reflection", ""),
                        (r["note"] or "")[:80]])
            counts[label] = counts.get(label, 0) + 1
            if progress:
                progress(i + 1, len(rows))
    log.info("학습 데이터 내보내기: %s → %s", counts, out)
    return counts
