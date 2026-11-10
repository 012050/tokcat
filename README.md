# tokcat

라즈베리파이 4 + 3.5인치 TFT 디스플레이 프로젝트.
**목표: 데스크톱이 아닌, 사용자가 원하는 특정 정보 + 애니메이션 효과를 디스플레이에 표시.**

> **확정된 계획(UI 스펙, 데이터 소스, 작업 단계)은 `PLAN.md` 참조** — 2026-11-09 대화 기준

## 하드웨어

| 항목 | 사양 |
|---|---|
| SBC | Raspberry Pi 4 Model B (4GB RAM), 호스트명 `runcater` |
| 디스플레이 | 3.5인치 TFT — LCDwiki **MPI3501** 계열 (40핀 GPIO 직결) |
| 패널 구동 IC | ILI9486 (SPI, 16MHz 동작) |
| 터치 | 저항성, **XP12046** (XPT2046 계열 — Linux `ads7846` 드라이버 사용) |
| 해상도 | 480×320 (가로, rotate=90), ~31fps |
| 저장공간 | SD 카드 `/dev/mmcblk0`, 루트 파티션 235GB |
| OS | Debian 13 (trixie) 64비트, 커널 6.18.60+rpt-rpi-v8, swap 2GB |
| 사용자 | `runcater` (패스워드 없는 sudo 가능) |

### 디스플레이 40핀 헤더 핀아웃 (MPI3501 매뉴얼 기준)

| 헤더 핀 | GPIO | 신호 |
|---|---|---|
| 1, 17 | — | 3.3V |
| 2, 4 | — | 5V |
| 6, 9, 14, 20, 25 | — | GND |
| 11 | GPIO17 | TP_IRQ (터치 인터럽트) |
| 18 | GPIO24 | LCD_RS (DC, 명령/데이터) |
| 19 | GPIO10 | SPI0_MOSI |
| 21 | GPIO9 | SPI0_MISO |
| 22 | GPIO25 | RST (리셋) |
| 23 | GPIO11 | SPI0_SCK |
| 24 | GPIO8 | LCD_CS (LCD 칩셀렉트) |
| 26 | GPIO7 | TP_CS (터치 칩셀렉트) |
| 3,5,7,8,10,12,13,15,16 | — | NC |

## 접속 방법

- SSH 설정: `~/.ssh/config` (프로젝트 폴더가 **아님** — 홈 디렉터리)
- 호스트 별칭: `runcater` → **192.168.0.40**:22 (Wi-Fi, 기본), key `~/.ssh/id_rsa`
- IP: Wi-Fi **192.168.0.40** (`wlan0`, **기본** — 작업은 무선으로 수행) / 유선 **192.168.0.24** (`eth0`) — 2026-11-09 현재 Wi-Fi 연결 확인. 물리 연결이 바뀌면 ssh config HostName만 교체
- VPN (2026-11-09 추가): WireGuard `wg0`으로 `192.168.1.x`(tokenbills/vLLM) 도달
  - 설정 값(엔드포인트/키/IP 할당/대역 등)은 문서에 기록하지 않음 — **사용자에게 문의**. 파일: 파이 `/etc/wireguard/wg0.conf`, systemd `wg-quick@wg0`으로 부팅 시 자동 기동
  - 2026-11-09 검증: `192.168.1.221:8000/api/live`·`:8001/metrics` 응답 확인
- 사용: `ssh runcater` (Windows PowerShell 어디서든 가능)
- **리부팅 후 접속이 안 되면**: 물리 네트워크(유선/Wi-Fi) 확인 → DHCP IP가 바뀔 수 있음 → 필요 시 ping 스캔
- PC(Windows) IP: 192.168.0.2 / 게이트웨이 192.168.0.1

## 작업 이력 (2026-11-09)

1. **P0 스켈레톤 배포** — `/opt/tokcat` (로컬 repo → scp):
   - `tokcat.py` — Python 앱, X 없이 `/dev/fb0` mmap 직접 렌더링 (480×320 RGB565)
     - Pillow RGB 렌더 후 수동 RGB565 변환 (Pillow에 RGB→565 코어 변환 없음)
     - 레이아웃: 타이틀·시계·상태 배지·고양이 자리·메트릭 2행·in-flight 행 (P1까지 placeholder)
     - 폰트: DejaVu Sans/Mono (Debian 기본)
   - `capture_fb0.py` — fb0 → PNG 캡처 (에이전트 화면 검증 루프: Pi에서 캡처 → scp → 로컬 확인)
   - `config.toml` — 색상/폰트/상태 텍스트/P1 폴링 엔드포인트
   - `tokcat.service` — systemd, 부팅 자동 기동 + `Restart=always` (kill -9 테스트로 자동 재기동 확인)
   - `deploy.ps1` (로컬) — 파일 push + 서비스 (재)설치, `scripts/capture.ps1` — 캡처→로컬
   - `test_565.py` — 565 인/디코더 자가테스트 (known-value + gradient 라운드트립)
2. 검증: 시계·텍스트·색상 픽셀 프로브로 확인 (설계값=양자화값 일치)
3. 2026-11-10: 리부트 테스트 — SSH reboot 후 서비스 단독 기동 + 화면 렌더링 확인 (P0 완료)
4. **P1 라이브+고양이 배포** (2026-11-10):
   - `tokcat.py` 리팩터링 — `/api/live` 1초 폴링(백그라운드 스레드), 6개 지표+in-flight 표시, gputils `core.py` 속도 모델 포트(`[speed]` config화), RunCat 애니메이션
   - 렌더링: 정적 화면 1초당 베이스 렌더 + 스프라이트 사전 변환 RGB565 스플리스 (애니메이션 틱 = memcpy)
   - `rgb_to_565` numpy화 (python3-numpy, 부재 시 pure-python 폴백), `cat_frames/` 6스프라이트 레포 내재화 (gputils 무변경)
   - `config.toml` `[speed]`/`[cat]`/`[poll].timeout` 추가, `deploy.ps1` cat_frames push
   - 검증: 유휴 상태에서 동시 `/api/live` json ↔ 화면 캡처 **픽셀 diff 0** (`scripts/verify_expect.py`), run 포즈(부하) → sleep 포즈(유휴) 전환 캡처 확인, CPU ~1%
5. git: `dev` 브랜치 분기 — 개발은 `dev`, 안정화 시 `main` 머지 (GitHub 기본 브랜치 main 유지)
6. **P2 폴백+폴리ッシュ 배포** (2026-11-10):
   - `tokcat.py` — vLLM `:8001/metrics` 직결 폴백 (`fallback_after=3`회 연속 실패 시 전환, 1회 성공 시 primary 복귀, 전환 시 `poll mode` journal 로그), `fetch_metrics`(Prometheus 파싱)/`delta_rates`(counter 델타로 MTP/decode/prefill), 배지 `· vLLM` 접미, in-flight `n/a`
   - `config.toml` — `[poll] fallback_after = 3`
   - `scripts/` — `test_p2_poller.py`(전환 테스트), `verify_fallback.py`(폴백/오프라인 화면 픽셀 검증, 배지 상태 자동 감지), `mock_metrics.py`(결정적 mock vLLM), `proxy_live.py`(primary on/off 토글), `probe_badge*.py`(배지 픽셀 식별)
   - 검증: mock 폴백 화면 **픽셀 diff 0** (WALK·vLLM 배지 + req 2/0, KV 42%, in-flight n/a), OFFLINE 화면 diff 0, 실 vLLM 폴백 RUN/WALK·vLLM 배지 diff 0, fallback→primary **자동 복귀**(리부트 없이, journal), primary 화면 diff 0
   - 남은 것: 24시간 안정 동작 검증 (진행 중)

## 작업 이력 (2026-11-08)

1. 디스플레이 모델 특정: LCDwiki MPI3501 계열 (ILI9486 + XP12046, SPI)
2. 패키지 설치 (apt): `xserver-xorg-input-evdev`, `xinput`, `xfce4`
3. 드라이버 리포 클론: `~/mpi3501-kernel-6.12-driver` (github.com/chessarisilvio/mpi3501-kernel-6.12-driver)
   - 이 보드(MPI3501) 전용 커뮤니티 드라이버, 커널 6.12+ 대상
4. Device Tree overlay 설치: `/boot/firmware/overlays/mpi3501-custom.dtbo`
   - SPI0 CS0에 `ilitek,ili9486` 패널, CS1에 `ti,ads7846` 터치, GPIO17 IRQ
5. `/boot/firmware/config.txt` 수정 (백업: `config.txt.bak-tokcat`):
   - `dtparam=spi=on` (주석 해제)
   - `dtoverlay=mpi3501-custom` 추가
   - `#dtoverlay=vc4-kms-v3d` (주석화 — fbdev 방식과 충돌 방지)
   - `#max_framebuffers=2` (주석화)
6. Xorg 설정:
   - `/usr/share/X11/xorg.conf.d/99-fbdev.conf` — fbdev 드라이버, **`/dev/fb0`** (원본은 fb1이었는데 ours는 fb0이라 수정), 480x320, depth 16
   - `/usr/share/X11/xorg.conf.d/99-touch.conf` — evdev, 터치 캘리브레이션 "200 3900 3900 200" + InvertY
   - 백업: `~/99-fbdev.conf`, `~/99-touch.conf`
7. 스크립트 (Pi의 `~`): `start-tft-desktop.sh` (Xorg :0 + xfce4 수동 시작), `switch-to-lcd.sh`, `switch-to-hdmi.sh`
8. 사용된 커널 모듈 (모두 커널 내장, 컴파일 불필요):
   - `fb_ili9486` (drivers/staging/fbtft — `ilitek,ili9486` compatible으로 바인딩)
   - `ads7846`, `spi-bcm2835`

## 현재 상태

- `/dev/fb0`: 480×320 프레임버퍼 정상 동작 (부팅 시 CLI 콘솔이 TFT에 표시됨)
- 터치: `ADS7846 Touchscreen` 입력 장치로 인식됨 (`/dev/input/event*`)
- **tokcat 서비스 (P2 코드 완료 2026-11-10, 24시간 검증 진행 중)**: `/opt/tokcat` + systemd `tokcat.service` — 부팅 자동 기동(리부트 테스트 통과), crash 자동 재기동. 화면: 라이브 지표 6종 + in-flight + RunCat 애니메이션 (부하→속도, 유휴→수면, 접속 실패→OFFLINE 배지). tokenbills 다운 시 vLLM `:8001/metrics` 직결 폴백(배지 `· vLLM`). `scripts/capture.ps1`로 화면 캡처 확인
- 데스크톱: **리부트 후 수동** `~/start-tft-desktop.sh` 실행으로만 기동 (lightdm 자동 부팅은 이 디스플레이에서 작동안함)
- 자동 기동: 미설정 (데스크톱 기준 — tokcat은 systemd로 자동)
- 2026-11-08 최종 확인 (Wi-Fi .40): fb0 480×320 정상, 터치 인식 정상, SSH 정상
- USB 주변기: ROYUAN 2.4G 무선 키보드/마우스, Logitech M350 연결 상태

## 목적에 맞는 다음 단계 (정보 + 애니메이션 표시)

데스크톱(XFCE)은 불필요해졌을 가능성이 큼. 전용 표시기 구성안:

- **방식 A (추천): 프레임버퍼 직접 구동** — X 서버 없이 앱이 `/dev/fb0`에 직접 렌더링
  - Python: `pygame` (SDL이 fb0 자동 사용) 또는 `/dev/fb0` mmap 직접 처리
  - 장점: 부팅부터 앱만, 자원 최소
- **방식 B: X 서버 + 전체화면 윈도우** — 기존 Xorg 설정 활용, 웹뷰/ GTK 앱 가능
- 두 경우 모두: **systemd 서비스**로 부팅 시 자동 실행 (기존 lightdm은 disable)
- 터치 캘리브레이션: 필요 시 `xinput_calibrator` 또는 evdev calibration 값 재조정

## 함정 기록

- PowerShell → ssh 원격 명령에서 **더블quote 안에 파이프(`|`)가 있으면 깨짐** (PowerShell 네이티브 인자 처리 문제)
  - 해결: 원격 명령은 싱글quote 문자열로, 더블quote 쓰지 않기. grep 대안 문자열은 문자 클래스로 (`grep -iE [t]ouch`), 또는 여러 grep으로 분리
- PowerShell → ssh: 원격 명령을 **더블quote**로 감싸면 `$(...)`가 PowerShell에서 로컬에서 먼저 처리됨 → 원격 변수 `$var`/`$(...)`는 피할 것. pkill/grep 패턴이 자기 자신 매칭할 때 문자 클래스(`[t]okcat.py`) 사용
- **`/dev/fb0` fstat 크기가 0** — mmap 크기는 `FBIOGET_FSCREENINFO`(0x4602)의 `smem_len`/`line_length`로 구할 것 (`fb_fix_screeninfo`: smem_len @offset 24, line_length @offset 48)
- `fb_var_screeninfo`는 `line_length` 필드가 **없음** (40×u32, bpp @index 6) — 구조체는 `/usr/include/linux/fb.h` 확인
- Pillow: **RGB→565 코어 변환 없음** (`convert("565")` unsupported, `frombytes("565")`도 인식 불가) → translate 테이블로 수동 변환 (참고: `tokcat.py rgb_to_565`)
- 리포 기본 Xorg 설정의 `/dev/fb1` → 이 시스템은 `/dev/fb0`
- goodtft 공식 드라이버(`LCD-show`/`LCD35-show`)는 32비트 구형 OS 기준이라 64비트 trixie에서 작동안함 → 커뮤니티 dtbo 사용
- GPIO 핫플러그 금지: 디스플레이 연결/해제 전 반드시 전원 차단
- `grep -q dtparam=spi=on config.txt`처럼 주석 라인(`#dtparam=spi=on`)이 부분 일치하므로, 주석 해제 확인은 `grep -n`으로 직접 보기
- `pkill -f proxy_live.py`는 **자기 자신의 `bash -c` 명령줄도 매칭**해서 원격 셸 자체를 죽임 (나머지 명령 미실행, 출력이 없음) → 패턴을 문자 클래스로 (`pkill -f [p]roxy_live.py`)
- vLLM `/metrics`: `inter_token_latency_seconds_sum`·`time_to_first_token_seconds_sum`은 **`vllm:` 접두사 없음** (나머지는 있음) — 파서에서 접두사 strip
- fb0 캡처 픽셀 비교: 기대 이미지를 **RGB565 라운드트립**(`rgb_to_565`→`decode_565`) 안 하면 배지 배경/텍스트가 전부 "차이"로 잡힘 (565 양자화 차이). `verify_*` 스크립트는 라운드트립 적용
- 상태 배지는 **오른쪽 정렬**이라 배지 텍스트가 길어지면 그 앞에 우정렬된 시계도 왼쪽으로 이동 → 픽셀 검증 배제 영역은 고정 값이 아니라 기대 이미지에서 배지 좌측 끝을 자동 감지
