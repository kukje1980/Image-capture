"""필름 카메라 '찰칵' 후보들 — 물리적 구성(미러 슬랩 → 셔터막 → 미러 복귀 → 필름 감기)을 모달 합성으로 흉내낸다.

    python tools/shutter_variants.py <출력폴더>     # 후보 wav 를 모두 써서 들어 보고 고른다

각 후보는 generate_sounds.py 에서 이름으로 골라 shutter.wav 로 쓴다 (SHUTTER_VARIANT).
외부 음원 없이 numpy 로만 만든다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

SR = 44100


# ---------------------------------------------------------------- 기본 재료
def t_of(ms: float) -> np.ndarray:
    return np.arange(int(SR * ms / 1000)) / SR


def env(t: np.ndarray, attack_ms: float, decay_ms: float) -> np.ndarray:
    a = np.clip(t / max(attack_ms / 1000, 1e-5), 0, 1)
    return a * np.exp(-t / (decay_ms / 1000))


def bandpass(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(x.size, 1 / SR)
    # 가장자리를 부드럽게 (딱딱한 필터 링잉 방지)
    w = np.clip((f - lo) / max(lo * 0.3, 40), 0, 1) * np.clip((hi - f) / max(hi * 0.3, 200), 0, 1)
    return np.fft.irfft(spec * w, n=x.size)


def modal(t: np.ndarray, modes, rng: np.random.Generator) -> np.ndarray:
    """감쇠 사인파 합 — (주파수Hz, 감쇠ms, 진폭). 금속·플라스틱 몸체의 '울림'."""
    out = np.zeros_like(t)
    for f, dec, amp in modes:
        ph = rng.uniform(0, 2 * np.pi)
        out += amp * np.sin(2 * np.pi * f * t + ph) * np.exp(-t / (dec / 1000))
    return out


def impact(rng, length_ms, modes, noise=(800, 6000), noise_ms=6.0, noise_amp=1.0, strike_ms=0.6):
    """타격음: 아주 짧은 노이즈 '때림' + 몸체 모달 울림."""
    t = t_of(length_ms)
    n = bandpass(rng.standard_normal(t.size), *noise) * env(t, strike_ms, noise_ms) * noise_amp
    return n + modal(t, modes, rng)


def place(buf, part, at_ms, gain=1.0):
    i = int(SR * at_ms / 1000)
    n = min(part.size, buf.size - i)
    if n > 0:
        buf[i:i + n] += part[:n] * gain


def room(x: np.ndarray, rng, rt_ms=60.0, mix=0.10, hi=5000) -> np.ndarray:
    """아주 짧은 방 울림 — 합성음이 '공중에 뜬' 느낌을 줄인다."""
    t = t_of(rt_ms * 3)
    ir = bandpass(rng.standard_normal(t.size), 150, hi) * np.exp(-t / (rt_ms / 1000))
    ir[0] = 0
    wet = np.convolve(x, ir)[: x.size]
    wet /= (np.max(np.abs(wet)) or 1.0)
    return x + wet * mix * (np.max(np.abs(x)) or 1.0)


def saturate(x: np.ndarray, drive=1.6) -> np.ndarray:
    return np.tanh(x * drive) / np.tanh(drive)


def finish(x: np.ndarray, peak=0.85) -> np.ndarray:
    x = x - np.mean(x)
    x = x / (np.max(np.abs(x)) or 1.0) * peak
    n = min(int(SR * 0.006), x.size)
    x[-n:] *= np.linspace(1, 0, n)
    x[:int(SR * 0.0005)] *= np.linspace(0, 1, int(SR * 0.0005))
    return x


# ---------------------------------------------------------------- 부품
def mirror_slap(rng, heavy=1.0, body=(130, 205, 330)):
    """미러가 올라가 멈추개에 부딪히는 둔탁한 '찰'. heavy 가 클수록 묵직."""
    modes = [(body[0], 16 * heavy, 0.7), (body[1], 14 * heavy, 0.6), (body[2], 11, 0.45),
             (560, 8, 0.4), (1200, 6, 0.3), (2300, 4, 0.2)]
    x = impact(rng, 90, modes, noise=(150, 4500), noise_ms=6.0, noise_amp=1.4, strike_ms=0.6)
    # 미러 바운스: 12~14ms 간격으로 두 번 더, 점점 작게
    for k, gap in enumerate((13, 25)):
        place(x, impact(rng, 40, modes[:3], noise=(120, 2500), noise_ms=4, noise_amp=0.7), gap, 0.3 / (k + 1))
    return x


def curtain(rng, bright=1.0, travel_ms=7.0):
    """셔터막(커튼) 한 장: 걸쇠 풀리는 날카로운 클릭 + 막이 달리는 '슥' + 끝에 멈추는 '탁'."""
    modes = [(2900 * bright, 9, 1.0), (4300 * bright, 7, 0.7), (6100 * bright, 5, 0.45), (8200, 3, 0.25),
             (1500, 8, 0.3)]
    x = impact(rng, 60, modes, noise=(1800, 11000), noise_ms=2.2, noise_amp=1.3, strike_ms=0.3)
    t = t_of(travel_ms + 6)
    slide = bandpass(rng.standard_normal(t.size), 900, 5000) * env(t, 0.5, travel_ms)
    place(x, slide, 1.0, 0.35)
    stop = impact(rng, 40, [(1900, 7, 1.0), (3100, 5, 0.6), (700, 9, 0.4)], noise=(500, 7000), noise_ms=2.5,
                  noise_amp=0.9)
    place(x, stop, travel_ms + 1, 0.7)
    return x


def mirror_return(rng, heavy=1.0):
    """미러가 내려와 자리에 돌아오며 '칵' — 올라갈 때보다 밝고 짧고, 스프링 잔떨림."""
    modes = [(160, 14 * heavy, 0.7), (260, 12 * heavy, 0.5), (900, 8, 0.4), (1700, 6, 0.35), (2800, 4, 0.2)]
    x = impact(rng, 110, modes, noise=(200, 6000), noise_ms=4.5, noise_amp=1.3)
    place(x, impact(rng, 40, modes[:2], noise=(200, 3000), noise_ms=3, noise_amp=0.6), 11, 0.4)
    t = t_of(90)
    spring = np.sin(2 * np.pi * 95 * t + 2.0 * np.sin(2 * np.pi * 18 * t)) * env(t, 2, 22)
    place(x, spring, 4, 0.25 * heavy)
    return x


def film_advance(rng, clicks=11, gap_ms=16.0, length_ms=None):
    """필름 감기 레버: 톱니(스프로킷) 래칫 '지르르륵' — 클릭이 이어지다 마지막에 '탁' 멈춤."""
    total = length_ms or (clicks * gap_ms + 90)
    x = np.zeros(int(SR * total / 1000))
    for i in range(clicks):
        at = i * gap_ms * rng.uniform(0.92, 1.08)
        f = 2300 + i * 60                                   # 레버를 당길수록 조금씩 높아짐
        c = impact(rng, 25, [(f, 4, 1.0), (f * 1.6, 3, 0.5), (900, 5, 0.3)], noise=(1500, 9000), noise_ms=1.2,
                   noise_amp=0.9, strike_ms=0.2)
        place(x, c, at, 0.55 + 0.03 * i)
    t = t_of(total)
    whir = bandpass(rng.standard_normal(t.size), 600, 3000) * env(t, 20, clicks * gap_ms * 0.6)
    x += whir * 0.12
    place(x, impact(rng, 60, [(1100, 10, 1.0), (1800, 7, 0.6), (420, 14, 0.5)], noise=(300, 6000), noise_ms=3,
                    noise_amp=1.0), clicks * gap_ms + 10, 0.9)
    return x


def motor_wind(rng, ms=320.0):
    """컴팩트 자동 카메라의 모터 필름 감기 '위이잉' — 기어 윙윙 + 끝에 딸깍."""
    t = t_of(ms)
    f0 = 85.0
    buzz = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, 9))
    gear = np.sin(2 * np.pi * 1850 * t + 0.6 * np.sin(2 * np.pi * 37 * t)) * 0.35
    gear += np.sin(2 * np.pi * 3700 * t) * 0.12
    ramp = np.minimum(1, t / 0.03) * np.where(t < (ms / 1000 - 0.04), 1, np.clip(((ms / 1000) - t) / 0.04, 0, 1))
    x = (buzz * 0.5 + gear) * ramp
    x += bandpass(rng.standard_normal(t.size), 1200, 6000) * ramp * 0.12
    place(x, impact(rng, 50, [(1400, 8, 1.0), (2600, 5, 0.5)], noise=(600, 7000), noise_ms=2.5), ms - 30, 0.8)
    return x


# ---------------------------------------------------------------- 후보
def classic_slr(seed=1):
    """A. 클래식 35mm SLR (펜탁스 K1000·캐논 AE-1 풍) — 표준 '찰칵'."""
    rng = np.random.default_rng(seed)
    buf = np.zeros(int(SR * 0.30))
    place(buf, mirror_slap(rng, heavy=1.0), 0, 1.0)                 # '찰'
    place(buf, curtain(rng, bright=1.0), 48, 0.5)                   # 1막 (작게)
    place(buf, curtain(rng, bright=1.08), 48 + 16, 0.75)            # 2막 (1/60s 뒤)
    place(buf, mirror_return(rng, heavy=1.0), 48 + 16 + 12, 1.05)   # '칵'
    return finish(room(saturate(buf, 1.15), rng, 45, 0.08), 0.88)


def heavy_slr_wind(seed=2):
    """B. 묵직한 금속 SLR + 레버로 필름 감기 (니콘 FM 풍) — '찰칵… 지르르륵'."""
    rng = np.random.default_rng(seed)
    buf = np.zeros(int(SR * 0.62))
    place(buf, mirror_slap(rng, heavy=1.35, body=(110, 175, 290)), 0, 1.1)
    place(buf, curtain(rng, bright=0.92, travel_ms=8), 52, 0.5)
    place(buf, curtain(rng, bright=1.0, travel_ms=8), 52 + 17, 0.8)
    place(buf, mirror_return(rng, heavy=1.3), 52 + 17 + 14, 1.1)
    place(buf, film_advance(rng, clicks=12, gap_ms=15), 215, 0.55)
    return finish(room(saturate(buf, 1.25), rng, 70, 0.12), 0.88)


def rangefinder_leaf(seed=3):
    """C. 레인지파인더 리프 셔터 (라이카·야시카 풍) — 미러 없이 조용하고 또렷한 '틱-틱'."""
    rng = np.random.default_rng(seed)
    buf = np.zeros(int(SR * 0.20))
    open_ = impact(rng, 50, [(3400, 6, 1.0), (5200, 4, 0.6), (7600, 3, 0.3), (1300, 7, 0.25)],
                   noise=(2000, 12000), noise_ms=1.6, noise_amp=1.2, strike_ms=0.25)
    close = impact(rng, 70, [(2600, 9, 1.0), (4000, 6, 0.6), (900, 12, 0.35), (480, 16, 0.3)],
                   noise=(800, 9000), noise_ms=2.4, noise_amp=1.1, strike_ms=0.3)
    place(buf, open_, 0, 0.8)
    place(buf, close, 22, 1.0)                                # 1/45s 뒤 닫힘
    t = t_of(60)
    place(buf, bandpass(rng.standard_normal(t.size), 1500, 6000) * env(t, 1, 10), 2, 0.12)
    return finish(room(buf, rng, 45, 0.08), 0.8)


def compact_motor(seed=4):
    """D. 90년대 컴팩트 자동 필름 카메라 — 작은 '찰칵' 뒤 모터 필름 감기 '위잉'."""
    rng = np.random.default_rng(seed)
    buf = np.zeros(int(SR * 0.55))
    click = impact(rng, 70, [(2100, 7, 1.0), (3300, 5, 0.6), (650, 10, 0.5), (5100, 3, 0.3)],
                   noise=(500, 9000), noise_ms=2.5, noise_amp=1.0)
    place(buf, click, 0, 0.9)
    place(buf, impact(rng, 50, [(1800, 6, 1.0), (2900, 4, 0.5), (500, 9, 0.4)], noise=(500, 8000), noise_ms=2),
          18, 0.7)
    place(buf, motor_wind(rng, 300), 120, 0.5)
    return finish(room(saturate(buf, 1.1), rng, 40, 0.08), 0.8)


def medium_format(seed=5):
    """E. 중형 카메라 (핫셀블라드 500 풍) — 크고 낮은 '카-쿵', 긴 기계 잔향."""
    rng = np.random.default_rng(seed)
    buf = np.zeros(int(SR * 0.42))
    place(buf, mirror_slap(rng, heavy=1.9, body=(85, 140, 230)), 0, 1.2)
    # 후면 차광판(baffle) 이 함께 올라가며 덜컹
    place(buf, impact(rng, 120, [(95, 40, 1.0), (170, 30, 0.6), (420, 15, 0.4)], noise=(80, 2500), noise_ms=9,
                      noise_amp=1.0), 30, 0.7)
    place(buf, curtain(rng, bright=0.8, travel_ms=10), 85, 0.45)   # 리프 셔터 열림
    place(buf, curtain(rng, bright=0.85, travel_ms=10), 85 + 20, 0.6)
    place(buf, mirror_return(rng, heavy=1.9), 85 + 20 + 18, 1.15)
    place(buf, impact(rng, 160, [(120, 45, 1.0), (210, 30, 0.5)], noise=(80, 1800), noise_ms=8, noise_amp=0.8),
          85 + 20 + 30, 0.6)
    return finish(room(saturate(buf, 1.3), rng, 90, 0.14, hi=4000), 0.9)


def quick_slr(seed=6):
    """F. 가볍고 빠른 SLR (올림푸스 OM 풍) — 짧고 경쾌한 '찰칵', 가장 짧다."""
    rng = np.random.default_rng(seed)
    buf = np.zeros(int(SR * 0.22))
    place(buf, mirror_slap(rng, heavy=0.7, body=(170, 260, 410)), 0, 0.9)
    place(buf, curtain(rng, bright=1.15, travel_ms=5.5), 36, 0.5)
    place(buf, curtain(rng, bright=1.2, travel_ms=5.5), 36 + 10, 0.8)
    place(buf, mirror_return(rng, heavy=0.7), 36 + 10 + 9, 1.0)
    return finish(room(saturate(buf, 1.1), rng, 40, 0.08), 0.85)


VARIANTS = {
    "classic_slr": (classic_slr, "A. 클래식 35mm SLR", "펜탁스 K1000·캐논 AE-1 풍의 표준 '찰칵'. 미러 '찰' → 셔터막 두 번 → 미러 복귀 '칵'."),
    "heavy_slr_wind": (heavy_slr_wind, "B. 묵직한 SLR + 필름 감기 레버", "니콘 FM 풍. '찰칵' 뒤에 레버로 필름을 감는 '지르르륵' 래칫 소리까지. 옛 필름 카메라 느낌이 가장 강함."),
    "rangefinder_leaf": (rangefinder_leaf, "C. 레인지파인더 리프 셔터", "라이카·야시카 풍. 미러가 없어 조용하고 또렷한 '틱-틱'. 진료실에서 가장 거슬리지 않음."),
    "compact_motor": (compact_motor, "D. 90년대 컴팩트 자동 카메라", "작은 '찰칵' 뒤 모터가 필름을 감는 '위잉'. 친숙한 자동 필름 카메라 소리."),
    "medium_format": (medium_format, "E. 중형 카메라", "핫셀블라드 풍. 크고 낮은 '카-쿵'에 긴 기계 잔향. 가장 묵직하고 존재감 있음."),
    "quick_slr": (quick_slr, "F. 가볍고 빠른 SLR", "올림푸스 OM 풍. 가장 짧고 경쾌한 '찰칵'. 연속 촬영에 부담 없음."),
}


def write_wav(path: Path, x: np.ndarray) -> None:
    import wave

    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "shutter_candidates")
    for key, (fn, title, _desc) in VARIANTS.items():
        x = fn()
        write_wav(out / f"{key}.wav", x)
        print(f"{key:18s} {x.size / SR * 1000:5.0f} ms  {title}")
