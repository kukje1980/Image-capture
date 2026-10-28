# Keeler 브랜드 자료 출처

- `logo-dark.svg` — Keeler 공식 홈페이지 로고 원본 (흰색 글자, 어두운 배경용)
  https://www.keelerglobal.com/wp-content/uploads/2024/02/logo.svg
  (https://www.keelerusa.com 의 logo.svg 와 동일 파일)
- `logo.svg` — 위 원본에서 흰색(#fff) 글자만 Keeler 네이비(#052133)로 바꾼 밝은 배경용
- `favicon.png` — 원본 로고의 갈매기 마크(하늘색·주황)만 잘라 네이비 바탕에 배치
- `theme.css` 색 — keeler.co.uk · keelerusa.com · keelerglobal.com 스타일시트에서 가장 많이 쓰인 브랜드 색
  #052133(네이비) · #1981b7(파랑) · #6cbce8(하늘) · #ed6f1e(주황) · #cde1ef / #f1f8fd(옅은 파랑)

- 홈 화면 사진 (모두 사용자 제공, 2026-10-27) — 원본 `home-*.jpg`, 배경을 떼어 낸 투명 PNG `home-*.png` (앱에서 쓰는 파일):
  - `home-slitlamp` — Keeler 슬릿램프 단독 (옅은 그라데이션 배경 · 바닥 반사 제거) — Keeler 판 기본 홈 사진
  - `home-system` — Keeler 슬릿램프 + 영상 시스템(KONNECT 화면) 장비 (흰 배경)
  - `home-eyepiece` — 접안렌즈 확대 (흰 배경, 잘린 쪽은 서서히 사라지게)
  다시 만들기: `python tools/make_home_cutout.py` (사진마다 떼는 방법 · 값은 그 파일의 PRESETS).
  앱의 '홈 사진 바꾸기' 에서 셋 중 하나를 고르거나 내 사진을 넣을 수 있고, 파일이 없으면 Keeler 색으로 그린 슬릿 빛줄기 그림이 보입니다.

로고·상표는 Keeler Ltd 소유이며, Keeler 측 사용 허락 범위에서 사용합니다.
