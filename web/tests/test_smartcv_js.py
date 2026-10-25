"""smartcv.js 단위 테스트(Node) 를 pytest 에서 함께 실행 — node 가 없으면 건너뜀."""
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node 가 설치되어 있지 않음")
def test_smartcv_js_unit_tests():
    r = subprocess.run(["node", "--test", str(WEB / "tests" / "js" / "smartcv.test.cjs")],
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
