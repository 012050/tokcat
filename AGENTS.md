# tokcat — 작업 노트

## 작업 규칙
- 작업을 시작하기 전에 **무조건 사용자에게 확인을 받고** 작업을 시작한다 (자발 판단으로 시작하지 않음)
- 브랜치: 개발은 **`dev`** (원격 `origin/dev`), 안정화되면 **`main`**으로 머지. GitHub 기본 브랜치는 `main` 유지

## 목적
- 3.5인치 TFT 디스플레이에 **사용자가 원하는 특정 정보 + 애니메이션 효과** 표시 (데스크톱 목적이 아님)

## 용어
- **"파이" = 이 프로젝트의 라즈베리파이 (`runcater`)** — 특별한 말이 없으면 "파이"라고 하면 이 기기를 의미

## 시스템
- `runcater` = Raspberry Pi 4 (4GB), Debian 13 (trixie) 64비트, 커널 6.18.60+rpt-rpi-v8
- 디스플레이: LCDwiki MPI3501 계열 (ILI9486 SPI + XP12046 저항성 터치), 480×320
- 프레임버퍼: `/dev/fb0` (480×320, ~31fps) — 부팅부터 CLI 콘솔이 여기에 표시됨
- 터치: `ads7846` 드라이버 → `ADS7846 Touchscreen` (`/dev/input/event*`)
- USB: ROYUAN 2.4G 무선 키보드/마우스, Logitech M350

## 접속
- `ssh runcater` (설정: `~/.ssh/config`, 키 인증, `sudo -n` 가능)
- IP: Wi-Fi **192.168.0.40** (**기본** — 작업은 무선으로 수행) / 유선 **192.168.0.24**
- 접속 안 될 때: 먼저 기기가 유선/Wi-Fi 어느 쪽에 물리적으로 연결됐는지 확인 (IP가 따라 바뀜, ssh config HostName도 교체 필요)
- VPN: WireGuard `wg0`으로 `192.168.1.x`(tokenbills/vLLM `192.168.1.221`) 도달
  - 설정 값(엔드포인트/키/IP 할당/대역 등)은 문서에 기록하지 않음 — **사용자에게 문의**. 파일: `/etc/wireguard/wg0.conf`, systemd `wg-quick@wg0`으로 부팅 시 자동 기동
  - 상태 확인: `sudo wg show wg0` (latest handshake 있어야 정상)

## Pi 안 주요 파일
- `/boot/firmware/config.txt` — `dtparam=spi=on`, `dtoverlay=mpi3501-custom`, `vc4-kms-v3d`/`max_framebuffers` 주석 처리 (백업: `config.txt.bak-tokcat`)
- `/boot/firmware/overlays/mpi3501-custom.dtbo` — 디스플레이+터치 Device Tree (출처: github.com/chessarisilvio/mpi3501-kernel-6.12-driver)
- `/usr/share/X11/xorg.conf.d/99-fbdev.conf` — Xorg fbdev 설정 (**/dev/fb0** — 원본 리포는 fb1이므로 수정했음), `99-touch.conf` — evdev 터치+캘리브레이션
- `~/start-tft-desktop.sh` — 데스크톱 수동 기동 (리부트 후엔 CLI만 뜸, lightdm 자동 부팅 불가)
- 커널 모듈: `fb_ili9486`(staging/fbtft), `ads7846`, `spi-bcm2835` — 전부 내장, 컴파일 불필요

## PowerShell → ssh 함정
- 원격 명령부에 **더블쿼트 안에 파이프(`|`)가 있으면 깨짐** → 원격 명령은 전체 싱글쿼트, 더블쿼트 사용 금지
- grep 대안 패턴: 문자 클래스로 (`grep -iE [t]ouch`) 또는 여러 grep으로 분리
- PowerShell 5.1: `Test-Connection -Timeout` 없음 (ping `-w` 사용)

## 상세 문서
- `README.md` — 하드웨어 스펙, 핀아웃, 작업 이력, 다음 단계
