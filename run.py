#!/usr/bin/env python3
"""개발용 실행기.

    python run.py                    # 설정 기반 (기본 device)
    python run.py --source synthetic # 합성 영상 (하드웨어 불필요)
    python run.py --source file      # 테스트 동영상 파일 재생
"""
import sys

from app.__main__ import main

if __name__ == "__main__":
    sys.exit(main(sys.argv))
