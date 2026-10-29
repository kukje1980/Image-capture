## 안저 사진 뷰어 — 최신 빌드 (Windows · Mac)

아래 **Assets** 에서 내 컴퓨터에 맞는 파일을 눌러 내려받으세요 (로그인 필요 없음).

| 컴퓨터 | 파일 |
|---|---|
| Windows 10 / 11 | **FundusViewer-windows.zip** |
| Mac — Apple Silicon (M1 · M2 · M3 · M4 …) | **FundusViewer-mac-AppleSilicon.dmg** |
| Mac — Intel | **FundusViewer-mac-Intel.dmg** |

Mac 종류는 화면 왼쪽 위 사과 메뉴 → **이 Mac에 관하여** 의 "칩"(Apple M…) 또는 "프로세서"(Intel …) 에서 확인합니다.

### Windows 설치·실행
1. 내려받은 zip 파일의 압축을 풉니다.
2. `FundusViewer` 폴더 안의 **FundusViewer.exe** 를 실행합니다.
3. "Windows의 PC 보호" 창이 뜨면 **추가 정보 → 실행** 을 누릅니다 (서명하지 않은 프로그램이라 나오는 경고입니다).

### Mac 설치·실행 (macOS 11 Big Sur 이상)
1. 내려받은 dmg 파일을 열고 **FundusViewer** 를 **Applications** 폴더로 끌어다 놓습니다.
2. 응용 프로그램 폴더에서 FundusViewer 를 엽니다.
3. 처음 열 때 "확인할 수 없는 개발자" 경고가 나오면 (애플 인증서로 서명하지 않은 프로그램이라 나오는 경고입니다):
   - **macOS 15 Sequoia 이상:** 경고 창을 닫고 사과 메뉴 → **시스템 설정 → 개인정보 보호 및 보안** 맨 아래의 **그래도 열기** 를 누른 뒤 암호를 입력합니다.
   - **macOS 14 이하:** FundusViewer 를 **Control + 클릭 (또는 오른쪽 클릭) → 열기** → **열기** 를 누릅니다.
   - 한 번 열면 다음부터는 바로 열립니다.
4. 문서 폴더·USB·네트워크 폴더 접근을 물으면 **허용** 을 누릅니다 (사진을 가져오는 데 필요합니다).

Mac 에서는 Ctrl 대신 **⌘** 를 씁니다 (⌘+클릭 = 두 번째 사진 고르기). 트랙패드로 두 손가락 스크롤 또는 벌리기/오므리기로 확대·축소합니다.

### 사진 확대·축소
도구를 고를 필요 없이 사진 위에서 **위로 드래그하면 확대, 아래로 드래그하면 축소**됩니다 (누른 곳 중심).
이동은 가운데 버튼(휠) 드래그나 [이동] 도구, 더블클릭은 화면 맞춤입니다.

### 사진 가져오기
설정할 것이 없습니다. 실행하면 레티캠(`reticam`·`레티캠`) 등 장비 폴더와 `문서\안저사진 가져오기` 폴더(Mac: `문서/안저사진 가져오기`)를 찾아 자동으로 감시하고, 새 사진의 환자 ID·이름을 읽어 환자별로 정리합니다. Mac 에서는 연결된 USB 디스크와 NAS(공유 폴더)에서도 장비 폴더를 찾습니다.

가상 데모 사진으로 먼저 써 보려면 Windows 명령 프롬프트에서 `FundusViewer.exe --demo`, Mac 터미널에서 `/Applications/FundusViewer.app/Contents/MacOS/FundusViewer --demo` 로 실행합니다.

### 항상 최신 버전 주소
- Windows: https://github.com/kukje1980/Image-capture/releases/download/fundus-viewer-latest/FundusViewer-windows.zip
- Mac (Apple Silicon): https://github.com/kukje1980/Image-capture/releases/download/fundus-viewer-latest/FundusViewer-mac-AppleSilicon.dmg
- Mac (Intel): https://github.com/kukje1980/Image-capture/releases/download/fundus-viewer-latest/FundusViewer-mac-Intel.dmg
