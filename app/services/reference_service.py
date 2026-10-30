"""질환별 참고 사진 저장소: <media_root>/_references/<질환 id>/ 에 파일 복사 + reference_images 테이블.

패널·비교 화면에 보이는 항목은 모식도(assets/dx, 삭제 불가)와 병원 등록 사진(여기서 관리)을 합친 것이다.
"""
from __future__ import annotations

import logging
import secrets
import shutil
from datetime import datetime
from pathlib import Path

import numpy as np

from app import dx_library, paths
from app.models.reference import ReferenceImage

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

log = logging.getLogger(__name__)

ALLOWED_EXT = {"png", "jpg", "jpeg", "webp", "bmp"}


class ReferenceStore:
    def __init__(self, db, config):
        self.db = db
        self.config = config

    def root(self) -> Path:
        base = Path(self.config.media_root) if self.config.media_root else paths.get_appdata_dir() / "media"
        return base / "_references"

    def items(self, disease: str) -> list[dict]:
        """모식도 + 등록 사진. {kind: 'ill'|'user', path, caption, ref?}"""
        d = dx_library.get(disease)
        out = []
        for ill in (d.get("illustrations", []) if d else []):
            p = dx_library.illustration_path(ill.get("file", ""))
            if p:
                out.append({"kind": "ill", "path": p, "caption": ill.get("caption", "")})
        for r in self.db.references.list_by_disease(disease):
            out.append({"kind": "user", "path": r.file_path, "ref": r,
                        "caption": r.caption or f"참고 사진 {(r.created_at or '')[:10]}"})
        return out

    def add_file(self, disease: str, src, caption: str = "") -> ReferenceImage:
        src = Path(src)
        ext = src.suffix.lower().lstrip(".")
        if ext == "jpeg":
            ext = "jpg"
        if ext not in ALLOWED_EXT:
            raise ValueError("사진 파일(png·jpg·webp·bmp)만 등록할 수 있습니다.")
        dst = self._new_path(disease, ext)
        shutil.copy2(src, dst)
        return self._insert(disease, dst, caption)

    def add_frame(self, disease: str, frame: np.ndarray, caption: str = "") -> ReferenceImage:
        if frame is None:
            raise ValueError("등록할 영상이 없습니다.")
        dst = self._new_path(disease, "png")
        if cv2 is not None:
            ok, buf = cv2.imencode(".png", frame)
            if not ok:
                raise ValueError("PNG 로 저장하지 못했습니다.")
            buf.tofile(str(dst))                        # 한글 경로 대응
        else:  # pragma: no cover
            from PIL import Image
            Image.fromarray(frame[..., ::-1]).save(str(dst))
        return self._insert(disease, dst, caption)

    def delete(self, ref: ReferenceImage) -> None:
        row = self.db.references.delete(ref.id)
        if row and row.get("file_path"):
            try:
                Path(row["file_path"]).unlink(missing_ok=True)
            except OSError:
                log.warning("참고 사진 파일 삭제 실패: %s", row["file_path"], exc_info=True)

    # ---- 내부 ----
    def _new_path(self, disease: str, ext: str) -> Path:
        if dx_library.get(disease) is None:
            raise ValueError(f"알 수 없는 질환: {disease}")
        d = paths.ensure_dir(self.root() / paths.sanitize(disease))
        return d / f"{datetime.now():%Y%m%d_%H%M%S}_{secrets.token_hex(3)}.{ext}"

    def _insert(self, disease: str, path: Path, caption: str) -> ReferenceImage:
        ref = ReferenceImage(disease=disease, file_path=str(path), caption=(caption or "").strip()[:200] or None,
                             created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        ref.id = self.db.references.insert(ref)
        log.info("reference saved id=%s disease=%s path=%s", ref.id, disease, path)
        return ref
