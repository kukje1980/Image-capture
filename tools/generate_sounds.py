"""효과음(WAV) 생성기 — 외부 음원 없이 numpy 로 합성한다 (저작권 걱정 없음).

    python tools/generate_sounds.py            # assets/sounds/*.wav + web/static/sounds/*.wav 갱신

소리 구성
    shutter.wav    사진 캡처 — 예전 필름 카메라의 "찰칵" (미러 올라가는 '찰' + 셔터막 '칵')
    freeze.wav     정지영상(스틸) — 짧고 가벼운 '틱' 과 맑은 여운 (화면이 멎는 느낌)
    rec_start.wav  녹화 시작 — 캠코더식 짧은 '삐' 한 번
    rec_stop.wav   녹화 중지 — 조금 낮은 '삐삐' 두 번

출력은 44.1kHz · 모노 · 16-bit PCM. 난수 시드가 고정이라 다시 만들어도 같은 파일이 나온다.
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SR = 44100
ROOT = Path(__file__).resolve().parent.parent
OUT_DIRS = (ROOT / "assets" / "sounds", ROOT / "web" / "static" / "sounds")


def _t(ms: float) -> np.ndarray:
    return np.arange(int(SR * ms / 1000)) / SR


def _env(t: np.ndarray, attack_ms: float, decay_ms: float) -> np.ndarray:
    """빠른 어택 + 지수 감쇠 포락선."""
    a = np.clip(t / max(attack_ms / 1000, 1e-5), 0, 1)
    return a * np.exp(-t / (decay_ms / 1000))


def _noise(t: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    return rng.standard_normal(t.size)


def _bandpass(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """FFT 로 대역 통과 (짧은 소리라 충분히 정확하고 의존성이 없다)."""
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(x.size, 1 / SR)
    mask = (f >= lo) & (f <= hi)
    return np.fft.irfft(spec * mask, n=x.size)


def _place(buf: np.ndarray, part: np.ndarray, at_ms: float, gain: float = 1.0) -> None:
    i = int(SR * at_ms / 1000)
    n = min(part.size, buf.size - i)
    if n > 0:
        buf[i:i + n] += part[:n] * gain


def _normalize(x: np.ndarray, peak: float) -> np.ndarray:
    m = np.max(np.abs(x)) or 1.0
    y = x / m * peak
    # 끝부분 클릭 방지 (5ms 페이드아웃)
    n = min(int(SR * 0.005), y.size)
    y[-n:] *= np.linspace(1, 0, n)
    return y


def _write(path: Path, x: np.ndarray) -> None:
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


# ---------------------------------------------------------------- 소리
def shutter() -> np.ndarray:
    """필름 SLR 의 '찰칵': 미러 슬랩(둔탁한 '찰') → 약 70ms 뒤 셔터막 열림/닫힘('칵')."""
    rng = np.random.default_rng(7)
    buf = np.zeros(int(SR * 0.26))

    # 1) '찰' — 미러 슬랩: 저음 쿵 + 거친 노이즈
    t = _t(70)
    thump = np.sin(2 * np.pi * (170 - 90 * t / t[-1]) * t) * _env(t, 1.5, 22)
    slap = _bandpass(_noise(t, rng), 900, 6000) * _env(t, 0.5, 9)
    body = np.sin(2 * np.pi * 420 * t) * _env(t, 1, 14) * 0.5     # 바디 울림
    _place(buf, thump, 0, 0.9)
    _place(buf, slap, 0, 0.8)
    _place(buf, body, 0, 0.6)

    # 2) '칵' — 셔터막: 날카로운 클릭 두 개(열림·닫힘), 3.5kHz 근방 금속성 공명
    t2 = _t(60)
    click = _bandpass(_noise(t2, rng), 2200, 9000) * _env(t2, 0.3, 7)
    ring = np.sin(2 * np.pi * 3500 * t2) * _env(t2, 0.3, 12) * 0.45
    _place(buf, click, 72, 1.0)
    _place(buf, ring, 72, 1.0)
    _place(buf, click * 0.7, 86, 0.8)
    low2 = np.sin(2 * np.pi * 240 * t2) * _env(t2, 1, 25)
    _place(buf, low2, 72, 0.5)

    # 3) 기계 여운 — 아주 작은 스프링 잔향
    t3 = _t(120)
    tail = _bandpass(_noise(t3, rng), 1500, 5000) * _env(t3, 2, 30)
    _place(buf, tail, 95, 0.12)
    return _normalize(buf, 0.85)


def freeze() -> np.ndarray:
    """스틸: 가벼운 '틱' + 맑은 짧은 여운 (조용하고 깔끔하게)."""
    rng = np.random.default_rng(11)
    buf = np.zeros(int(SR * 0.16))
    t = _t(30)
    tick = _bandpass(_noise(t, rng), 2500, 8000) * _env(t, 0.3, 4)
    _place(buf, tick, 0, 1.0)
    t2 = _t(150)
    ping = (np.sin(2 * np.pi * 1760 * t2) + 0.4 * np.sin(2 * np.pi * 2640 * t2)) * _env(t2, 1, 38)
    _place(buf, ping, 6, 0.55)
    return _normalize(buf, 0.5)


def _beep(freq: float, ms: float, ramp_ms: float = 6) -> np.ndarray:
    t = _t(ms)
    env = np.ones_like(t)
    n = int(SR * ramp_ms / 1000)
    env[:n] = np.linspace(0, 1, n)
    env[-n:] = np.linspace(1, 0, n)
    tone = np.sin(2 * np.pi * freq * t) + 0.25 * np.sin(2 * np.pi * freq * 2 * t)
    return tone * env


def rec_start() -> np.ndarray:
    """녹화 시작: 캠코더식 짧은 '삐' 한 번."""
    buf = np.zeros(int(SR * 0.16))
    _place(buf, _beep(1320, 110), 0)
    return _normalize(buf, 0.45)


def rec_stop() -> np.ndarray:
    """녹화 중지: 조금 낮은 '삐삐' 두 번."""
    buf = np.zeros(int(SR * 0.26))
    _place(buf, _beep(990, 75), 0)
    _place(buf, _beep(990, 75), 125)
    return _normalize(buf, 0.45)


SOUNDS = {"shutter": shutter, "freeze": freeze, "rec_start": rec_start, "rec_stop": rec_stop}


def main() -> None:
    for name, fn in SOUNDS.items():
        data = fn()
        for d in OUT_DIRS:
            _write(d / f"{name}.wav", data)
        print(f"{name:10s} {data.size / SR * 1000:5.0f} ms")


if __name__ == "__main__":
    main()
