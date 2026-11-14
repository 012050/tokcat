# tokcat — 작업 요약 (2026-11-14 기준)

> 지금까지 작업한 내용 전체를 한 문서에 정리한 것.
> 하드웨어 스펙/핀아웃은 `README.md`, 계획·결정 이력은 `PLAN.md` 참조 — 이 문서는 **무엇을 했고 현재 어떤 상태인지**에 집중.

## 1. 프로젝트 개요

**목적**: 3.5인치 TFT에 **사용자가 원하는 특정 정보 + 애니메이션 효과**를 표시하는 전용 키오스크 (데스크톱이 아님).

| 항목 | 내용 |
|---|---|
| 표시 내용 | vLLM 실시간 상태 (6개 지표 + 진행 중 요청) + RunCat 고양이 애니메이션 (부하→속도) |
| 하드웨어 | Raspberry Pi 4 (4GB) `runcater` + LCDwiki MPI3501 3.5인치 TFT (ILI9486 SPI + XP12046 터치, 480×320 @~31fps) |
| OS | Debian 13 (trixie) 64비트, 커널 6.18.60+rpt-rpi-v8 |
| 데이터 소스 | tokenbills `GET /api/live` (1초 폴링) / 폴백: vLLM `:8001/metrics` (둘 다 192.168.1.221, WireGuard 경유) |
| 렌더링 | Python 앱 → **`/dev/fb0` 직접 렌더링** (X 서버 없음), Pillow + mmap, RGB565 |
| 실행 | systemd `tokcat.service` — 부팅 자동 기동, crash 자동 재시작 |
| 화면 방향 | **180° 회전 적용** (dtbo `rotate=270`, 2026-11-11) — 설치 장소에 파이를 정방향으로 놓을 수 없어서 |

```
runcater (tokcat.service, Python)
  ├─ GET http://192.168.1.221:8000/api/live   (1초, primary)
  └─ GET http://192.168.1.221:8001/metrics    (폴백 — 3회 연속 실패 시, 1회 성공 시 복귀)
        ▼
  /dev/fb0 (480×320 RGB565)
```

**독립성**: gputils(스프라이트·속도 모델 출처), tokenbills, vLLM 모두 **읽기 전용** — 로직/자재만 재사용, 본체 무변경.

## 2. 단계별 작업 이력

### P0 — 스켈레톤 (2026-11-09~10, ✅)
- `tokcat.py` — X 없이 `/dev/fb0` mmap 직접 렌더링 (480×320 RGB565)
  - Pillow는 RGB→565 코어 변환이 없어서 수동 변환 구현 (numpy 가속 + pure-python 폴백)
  - 레이아웃: 타이틀·시계·상태 배지 / 고양이 영역 / 지표 2행 / in-flight 행
- `capture_fb0.py` — fb0→PNG 캡처 (**에이전트 화면 검증 루프**의 핵심)
- `tokcat.service` — 부팅 자동 기동 + `Restart=always` (kill -9 테스트 통과)
- `deploy.ps1` (로컬) — 파일 push + 서비스 (재)설치, `scripts/capture.ps1` — 캡처→로컬
- **리부트 테스트 통과** (SSH reboot 후 서비스 단독 기동 + 화면 렌더링 확인)

### P1 — 라이브 지표 + 고양이 (2026-11-10, ✅)
- `/api/live` 1초 폴링 (백그라운드 스레드 — 폴링 실패해도 메인 루프 사망 안 함)
- **표시 지표 6종**: 진행 중 요청(IP·모델·경과) / vLLM 실행·대기 / KV Cache 사용률 / MTP 적중률 / 디코드 속도 / 프리필 속도
  - 프리필은 신규 요청 프리필 구간에만 값 → 없으면 `—`
- **고양이 속도 모델** — gputils `core.py` 동일 파라미터 포트 (`[speed]` config화):
  `speed = 0.6·min(EMA(tok/s)/40,1) + 0.3·kv_cache + 0.1·min(waiting/5,1)`
  상태: sleep(0) / walk(1~30) / run(30~70) / sprint(70~91) / overload(91+ 또는 waiting≥1) / offline
- **RunCat 애니메이션** — 스프라이트 6종(러닝 5프레임 + 수면, gputils RunCatNeo, Apache-2.0) 사전 변환 RGB565 → **스플리스**(애니메이션 틱 = memcpy, 재렌더링 아님)
- 검증: 유휴 상태에서 동시 `/api/live` json ↔ 화면 캡처 **픽셀 diff 0**, run/sleep 포즈 전환 캡처 확인, CPU ~1%

### P2 — 폴백 + 폴리ッシュ (2026-11-10, ✅)
- **vLLM 직결 폴백** — tokenbills 다운 시 `:8001/metrics`에서 지표 5개 직접 계산 (진행 중 요청 상세만 `n/a`)
  - 전환: **3회 연속 실패(≈3초)** → 폴백 / **1회 성공 → primary 복귀** (폴백 중에도 매 주기 primary 탐지)
  - 전환 시 journal 로그: `tokcat: poll mode primary -> fallback`
  - `fetch_metrics` (Prometheus 파싱) + `delta_rates` (counter 델타 → MTP/decode/prefill, 리셋 감지)
  - 화면: 상단 배지에 **`· vLLM`** 접미 (예: `RUN · vLLM`)
- **결정 사항**: 프리필 공백 `—` 표시 / 3회 연속 실패 전환 / 배지 표시 / **레이아웃·폰트·색상 현재 상태 그대로 확정**
- 검증 (프로덕션 무접촉 — mock vLLM·프록시·죽은 포트 사용):
  | 테스트 | 결과 |
  |---|---|
  | mock 폴백 화면 (WALK·vLLM, req 2/0, KV 42%, in-flight n/a) | **픽셀 diff 0** |
  | OFFLINE (primary+폴백 둘 다 다운) 화면 | **픽셀 diff 0** |
  | 실 vLLM 폴백 (RUN·vLLM / WALK·vLLM 실시간 상태) | **diff 0** |
  | fallback→primary **자동 복귀** (리부트 없이) | journal 확인 |
  | primary 화면 (P1 회귀) | **diff 0** |
- 24시간 안정화 기준: 그간 재기동·에러 없음 → 사용자 판단으로 생략

### 화면 180° 회전 (2026-11-11, ✅)
- 배경: 설치 장소에 파이를 정방향으로 놓을 수 없음 → 화면 소프트웨어 회전 (패널은 물리적으로 뒤집힌 채 장착)
- `mpi3501-custom.dts` 의 `rotate = <90>` → `<270>` (fbtft `fb_ili9486` 드라이버가 0/90/180/270 지원 — MADCTL 레지스터)
- `dtc -@` 재컴파일 → `/boot/firmware/overlays/` 교체 (원본 백업: `mpi3501-custom.dtbo.bak-rotate90`)
- 리부트 후 커널 로그 `rotate = 270` 로드 확인 + 사용자 육안 확인 통과
- 부팅 CLI 콘솔 포함 전체 화면이 회전. **캡처 PNG는 프레임버퍼(앱 좌표계)를 읽어서 회전 전과 동일하게 보임** (정상)
- 원복: 백업 dtbo 복원 + 리부트

## 3. 현재 상태 (2026-11-14)

| 항목 | 상태 |
|---|---|
| 서비스 | `tokcat.service` active — 11-13 18:07 부팅 이후 재기동 0회 (에러 0) |
| 화면 | 라이브 지표 + 고양이 애니메이션 정상 표시, 180° 회전 적용 |
| 폴백 | 미사용 (tokenbills 정상) — 필요 시 자동 전환 |
| 브랜치 | `dev` = `main` = `3ceb0a6` (모든 작업 main에 머지 완료) |
| 터치 | **사용 안 함 (사용자 결정 2026-11-11)** — 하드웨어는 인식만 되고 앱은 미사용 |

## 4. 주요 결정 이력

| # | 결정 | 시점 |
|---|---|---|
| 1 | 화면 구조: **단일 화면** (고양이+지표) — 패널 로테이션/클라이언트 순위는 옵션 유보 | 11-09 |
| 2 | 라벨 언어: **영어** (한국어 전환 시 Pi에 `fonts-noto-cjk` 설치 필요) | 11-09 |
| 3 | 데이터 소스: tokenbills `/api/live` 1초 폴링, vLLM metrics 폴백 | 11-09 |
| 4 | 렌더링: **Pillow + mmap** (pygame 배제 — 퀄리티 차이 없음) | 11-10 |
| 5 | gputils·tokenbills **무변경** (읽기 전용) | 11-09 |
| 6 | P2: 프리필 공백 `—` / 3회 연속 실패 폴백 / 배지 `· vLLM` | 11-10 |
| 7 | 레이아웃·폰트·색상: **현재 상태 그대로 확정** | 11-10 |
| 8 | 24시간 안정화 기준: 사용자 판단으로 생략 (그간 문제 없음) | 11-10 |
| 9 | 화면 180° 회전 (rotate=270) | 11-11 |
| 10 | **터치 미사용** — 관련 개발 생략 | 11-11 |

## 5. 남은 후보 (진행 여부는 사용자 결정)

P3 (옵션) 중 터치 제외 후 남은 것:

1. **사용량/비용 표시** (오늘·이번 달 KRW) — `GET /api/usage` 데이터 확인됨
2. **클라이언트 IP 순위** — `GET /api/clients` 데이터 확인됨 (상위 3~5개)
3. 위 2개를 위한 **표시 메커니즘** — 터치 대신 **패널 로테이션** (자동 화면 순환)이 자연스러운 대안

## 6. 리포 구성

```
tokcat/
├── tokcat.py              # 메인 앱 (fb0 렌더링 + 폴링 + 폴백, ~470줄)
├── capture_fb0.py         # fb0 → PNG 캡처 (검증 루프)
├── config.toml            # [display]/[poll]/[speed]/[cat]/[color]/[font]
├── tokcat.service         # systemd 유닛
├── install.sh             # Pi에서 서비스 (재)설치
├── deploy.ps1             # 로컬에서 push + 설치
├── test_565.py            # RGB565 인/디코더 자가테스트
├── cat_frames/            # RunCat 스프라이트 6종 (Apache-2.0)
├── scripts/
│   ├── capture.ps1        # 캡처→로컬
│   ├── verify_expect.py   # primary 화면 json↔캡처 픽셀 검증 (Pi 실행)
│   ├── verify_fallback.py # 폴백/오프라인 화면 픽셀 검증 (상태 자동 감지)
│   ├── test_p2_poller.py  # 폴백 전환 단위 테스트
│   ├── mock_metrics.py    # 결정적 mock vLLM (테스트용)
│   ├── proxy_live.py      # tokenbills 프록시 — primary on/off 토글 (테스트용)
│   ├── probe*.py          # 화면 픽셀 프로브 (디버깅)
│   └── flip_rotate.py     # dtbo rotate 90→270 원샷 스크립트
├── PLAN.md                # 계획·결정·산출물
└── README.md              # 하드웨어 스펙·핀아웃·작업 이력·함정 기록
```

Pi: `/opt/tokcat/` (위 파일) + systemd `tokcat.service`

## 7. 함정 기록 (요약 — 상세는 README "함정 기록" 참조)

- **PowerShell→ssh**: 원격 명령에 더블쿼트+파이프가 섞이면 깨짐 → 싱글쿼트만, grep은 문자 클래스(`[t]ouch`)
- **`pkill -f pattern`**: 자기 `bash -c` 명령줄까지 매칭 → `[p]attern` 사용
- **`/dev/fb0` fstat 크기 0**: mmap 크기는 `FBIOGET_FSCREENINFO` 로부터
- **Pillow**: RGB→565 코어 변환 없음 → 수동 변환
- **vLLM metrics**: `inter_token_latency_seconds_sum`·`time_to_first_token_seconds_sum` 은 **`vllm:` 접두사 없음**
- **픽셀 비교**: 기대 이미지 **RGB565 라운드트립** 안 하면 전부 "차이"로 잡힘
- **배지 우정렬**: 배지 텍스트 길이 변화 → 앞의 시계 위치 이동 → 검증 배제 영역은 자동 감지
- **캡처의 한계**: fb0(앱 좌표계)를 읽으므로 하드웨어 화면 회전(MADCTL)은 캡처에 반영 안 됨
