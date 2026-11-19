# tokcat — 계획 (Plan)

> runcater (Raspberry Pi 4) + 3.5인치 TFT(480×320)에 **vLLM 실시간 상태 + RunCat 고양이 애니메이션**을 표시하는 전용 키오스크.
> 2026-11-08~09 대화에서 확정된 사항의 집대성. **P0·P1·P2 완료 2026-11-10** (P0: 스켈레톤+systemd+캡처 검증 루프, 리부트 자동 기동까지 전부 확인 / P1: /api/live 폴링+6개 지표+RunCat 애니메이션, 픽셀 단위 검증 통과 / P2: vLLM 직결 폴백). **P4 레이아웃 완료 2026-11-19** (목업 기반 5블록 재설계 — §4.1·§6).

## 1. 목적
- 특정 정보(vLLM 상태/토큰 지표) + 애니메이션(부하에 따라 달리는 고양이)을 3.5인치 TFT에 항상 표시
- 데스크톱이 아닌 **전용 표시기**: 부팅 시 자동 실행, X 서버 불필요

## 2. 확정된 결정
| # | 항목 | 결정 |
|---|---|---|
| 1 | 화면 구조 | **단일 화면** — 고양이 + 실시간 지표를 한 화면에 (패널 로테이션/클라이언트 순위는 옵션으로 유보) |
| 2 | 라벨 언어 | **영어** (한국어 전환 시 Pi에 CJK 폰트 설치 필요) |
| 3 | 데이터 소스 | **tokenbills `GET /api/live` 1초 폴링** — 6개 지표가 1개 엔드포인트에 전부 포함 |
| 4 | 폴백 | tokenbills 다운 시 **vLLM `:8001/metrics` 직결 폴백** (진행 중 요청 상세만 누락) |
| 5 | 표시 정보 | 진행 중 요청(IP·모델·경과) / KV Cache 사용률 / vLLM 실행·대기 / MTP 적중률 / 디코드 속도 / 프리필 속도 |
| 6 | 애니메이션 | gputils `core.py` **속도 모델 포트** (동일 파라미터, config 파일화) |
| 7 | 렌더링 | Python 앱 → **`/dev/fb0` 직접 렌더링** (X 없음) |
| 8 | 실행 | **systemd 서비스** — 부팅 시 자동 기동, 크래시 시 자동 재시작 |
| 9 | 기존 리포 | **gputils·tokenbills 무변경 (읽기 전용)** — 로직/스프라이트/API 재사용만 |

## 3. 하드웨어 & 접속
- 상세 스펙·핀아웃·작업 이력은 `README.md` 참조
- 핵심: Pi 4 (4GB) · Debian 13 trixie 64비트 · `/dev/fb0` 480×320 @~31fps · 터치(ads7846) 인식됨
- 접속: `ssh tokcat` (Wi-Fi **192.168.0.40** 기본 / 유선 192.168.0.24 — 접속 안 될 때 물리 연결 방식 먼저 확인)

## 4. UI 스펙

### 4.1 레이아웃 (P4 — 2026-11-19 목업 기반 재설계)

> 2026-11-19: 사용자가 그린 목업(`이미지.png`)을 바탕으로 5블록 레이아웃으로 재설계.
> 목업의 **중앙(요청 목록) ↔ 좌하(데이터 블록) 위치를 교환**해 확정.
> 고양이: 중앙→**좌상단**. 신규 블록: KV 게이지(우상), 총토큰속도 그래프(우하).

```
┌──────────────────────────────────────────────────┐
│ tokcat            12:22 Thu 11-19        [status]│  상단바 (유지)
├──────────────────────────────────────────────────┤
│ ┌──────────┐  ┌──────────────────────┐   ┌─────┐ │
│ │   cat    │  │ metrics (C)          │   │ KV  │ │
│ │  (TL)    │  │ cache hit     85%    │   │47%  │ │
│ │          │  │ decode      11.0 t/s │   │(TR) │ │
│ │          │  │ × running        3   │   └─────┘ │
│ └──────────┘  │ ──────────────────   │           │
│ ┌──────────┐  │ TOTAL      33.1 t/s  │           │
│ │in-flight │  └──────────────────────┘   ┌───────┐│
│ │  (BL)    │                            │ graph ││
│ │ a · 156s │                            │ (BR)  ││
│ │ b · 96s  │                            │ ~~~~  ││
│ │ c · 12s  │                            └───────┘│
│ └──────────┘                                     │
└──────────────────────────────────────────────────┘
```

| 블록 | 위치 | 내용 |
|---|---|---|
| cat 애니메이션 | 좌상단 | RunCat (sleep/walk/run/sprint/overload), 스프라이트 스플리스 |
| metrics | 중앙 | cache hit · decode · × running · **TOTAL = running × decode** (t/s) |
| in-flight 목록 | 좌하 | `in_flight[]` 2줄 구조(client·path / model·경과), 최대 3건, 폴백 시 n/a |
| KV cache 게이지 | 우상 | 원형 게이지, `kv_cache_usage` % (현재 1호스트 → 집계 단일 게이지) |
| 총토큰속도 그래프 | 우하 | `running × decode_tps` 시계열 롤링(1s×60), 영역 차트 |

### 4.2 표시 정보 6종 (소스 분석 완료 2026-11-09)
| 정보 | 소스 | 비고 |
|---|---|---|
| 진행 중 요청 (IP·모델·경과) | **tokenbills 전용** (`/api/live` INFLIGHT) | 프록시 인메모리 추적 — vLLM 직결로는 상세 불가(개수만) |
| vLLM 실행/대기 | `num_requests_running/waiting` | vLLM metrics 원본 — tokenbills 전용 아님 |
| KV Cache 사용률 | `kv_cache_usage_perc` | 0~100% |
| MTP 적중률 | Δ`spec_decode_num_accepted` / Δ`spec_decode_num_draft` | 실측 69% 기록 (vLLM MTP 활성화 확인) |
| 디코드 속도 | Δ`generation_tokens` / Δ`inter_token_latency` | tok/s — 실측 27 tok/s 기록 |
| 프리필 속도 | Δ`prompt_tokens` / Δ`time_to_first_token` | tok/s — **간헐적**: 신규 요청 프리필 구간에만 값, 없으면 `—` |

- 갱신 주기: 1초 (tokenbills 내부 metrics 캐시가 1초 상한이라 기기 수 무관)
- **tokenbills 경유가 필수인 정보는 "진행 중 요청 상세" 하나뿐** — 나머지는 vLLM metrics로 직접 계산 가능(폴백용)

### 4.3 고양이 속도 모델 (gputils `core.py` 포트)
```
speed = 0.6·min(EMA(tok/s)/40, 1) + 0.3·kv_cache + 0.1·min(waiting/5, 1)   # 0~100
```
| 상태 | 조건 | 애니메이션 |
|---|---|---|
| offline | 접속 실패 | 수면 + 오프라인 배지 |
| overload | waiting ≥ 1 또는 speed ≥ 91 | 0.08s/프레임 |
| sprint | 70 ≤ speed < 91 | 0.11s/프레임 |
| run | 30 ≤ speed < 70 | 0.22s/프레임 |
| walk | 1 ≤ speed < 30 | 0.55s/프레임 |
| sleep | speed = 0 | 수면(Zzz) 정지 |

### 4.4 엣지 케이스
| 상황 | 처리 |
|---|---|
| 프리필 값 공백 | `—` 표시 (최근값 유지 여부는 미정, §8) |
| tokenbills 다운 | vLLM `:8001/metrics` 직결 폴백, in-flight 섹션 `n/a`, 복구 시 자동 복귀 |
| vLLM 다운 | OFFLINE 배지 + 고양이 수면, 재접속 감지 후 자동 복귀 |
| 요청 없음 | 지표 0, 고양이 수면 |

## 5. 아키텍처

### 5.1 데이터 흐름
```
runcater (python app, systemd)
  ├─ GET http://192.168.1.221:8000/api/live  (1s, 1차)
  └─ GET http://192.168.1.221:8001/metrics   (폴백)
  ▼
 /dev/fb0 (480×320 RGB565)
```

### 5.2 렌더링
- 엔진: **Pillow + mmap** (2026-11-10 확정 — pygame vs Pillow 퀄리티 차이 없음, 검증된 파이프라인 유지. 애니메이션은 스프라이트 사전 변환 RGB565 스플리스로 커버)
- 스프라이트: gputils `cat_frames/` (RunCat 56×36 검정 실루엣 5프레임 + sleeping.png, Apache-2.0) → ~150×95 확대, 밝은색 채색
- 폰트: 영어 DejaVu (Debian 기본). 한국어 시 `fonts-noto-cjk`

### 5.3 서비스 & 설정
- systemd 서비스: 부팅 자동 기동 + `Restart=always`
- 설정: 톰(TOML) 파일 — 호스트/포트, 폴링 주기, 색상, 상태 밴드, 레이아웃 옵션

## 6. 작업 계획
| 단계 | 범위 | 수락 기준 |
|---|---|---|
| **P0** 스켈레톤 | fb0 렌더링(시계+텍스트) + systemd + **화면 검증 루프** (fb0→PNG 캡처로 에이전트가 직접 화면 확인) | 부팅 시 단독으로 화면 표시, 서비스 자동 재기동, PNG 캡처로 상태 확인 가능 | ✅ 2026-11-10 (리부트 후 자동 기동까지 전부 확인) |
| **P1** 라이브+고양이 | `/api/live` 폴링, 6개 지표 표시, 속도 모델+고양이 애니메이션 | 값이 tokenbills 대시보드와 일치, 부하에 따라 고양이 속도 반응, 오프라인 상태 표시 | ✅ 2026-11-10 (동시 json+캡처 픽셀 대조 diff 0, run/sleep 상태 전환 캡처 확인) |
| **P2** 폴백+폴리ッシュ | vLLM 직결 폴백, 프리필 공백 처리, 레이아웃/폰트/색상 확정, 안정화 | tokenbills·vLLM 정지/재기동 시 앱 다운 없음, 24시간 이상 안정 동작 | ✅ 2026-11-10 (픽셀 검증 diff 0×5, 자동 복귀 확인. 24시간 기준은 사용자 판단으로 생략 — 그간 문제 없음) |
| **P3** (옵션) | 사용량/비용(오늘·이번 달 KRW) 추가, 터치 조작(상세 전환), 클라이언트 IP 순위 | §8 결정에 따라 |
| **P4** 레이아웃 | 목업 기반 5블록 재설계: cat 좌상단 · metrics 중앙(TOTAL=running×decode) · in-flight 좌하 · KV 게이지 우상 · 총토큰속도 그래프 우하 | 캡처로 5블록 렌더링 확인, 실시간 데이터/고양이/그래프 동작, 재시작 무에러 | ✅ 2026-11-19 |

### P0 산출물 (2026-11-09)
- `tokcat.py` (fb0 mmap 렌더링, Pillow RGB→565 수동 변환), `capture_fb0.py` (캡처), `config.toml`, `tokcat.service`, `install.sh`, `deploy.ps1`, `scripts/capture.ps1` (캡처→로컬), `scripts/probe.py` (픽셀 검증), `test_565.py`
- Pi: `/opt/tokcat` + systemd `tokcat.service` (enabled)
- 함정 기록: README "함정" 섹션 (fb0 fstat=0, fb_fix_screeninfo 오프셋, Pillow 565 변환 부재, PS `$(...)`)

### P2 결정 사항 (2026-11-10)
- **프리필 공백**: `—` 표시 (최근값 유지 없음, P1 동작 유지)
- **폴백 전환**: **3회 연속 실패**(≈3초, `[poll] fallback_after`) 시 vLLM `:8001/metrics` 직결, **1회 성공 시 primary 복귀** (폴백 중에도 매 주기 primary 탐지)
- **폴백 표시**: 상단 상태 배지에 `· vLLM` 추가 (예: `RUN · vLLM`), in-flight 줄은 `n/a`
- **레이아웃/폰트/색상**: 2026-11-10 캡처 3종(폴백/정상/오프라인) 검토 후 **현 상태 그대로 확정** (수정 없음)

### P2 산출물 (2026-11-10)
- `tokcat.py` — `LivePoller` primary/fallback 상태 머신 (3회 연속 실패→폴백, 1회 성공→복귀, 폴백 중에도 매 주기 primary 탐지, 전환 시 `poll mode X -> Y` journal 로그), `fetch_metrics` (vLLM Prometheus 파싱 — **latency _sum 2종은 `vllm:` 접두사 없음**), `delta_rates` (counter 델타 → MTP/decode/prefill, 카운터 리셋 시 None), 배지 `· vLLM` 접미 + in-flight `n/a`
- `config.toml` — `[poll] fallback_after = 3`
- `scripts/` — `test_p2_poller.py` (전환 단위 테스트), `verify_fallback.py` (폴백/오프라인 화면 픽셀 검증, 배지 상태 자동 감지), `mock_metrics.py` (결정적 mock vLLM), `proxy_live.py` (tokenbills 프록시 — primary on/off 토글, 프로덕션 무접촉), `probe_badge.py`/`probe_badge_text.py` (배지 픽셀 식별)
- 검증 (프로덕션 tokenbills·vLLM 무접촉 — 프록시/mock/ 죽은 포트 사용):
  - mock 폴백 화면 **픽셀 diff 0** (WALK·vLLM 배지, req 2/0, KV 42%, MTP/decode/prefill —, in-flight n/a)
  - OFFLINE(양쪽 다운) 화면 **픽셀 diff 0**
  - 실 vLLM 폴백: RUN·vLLM / WALK·vLLM 배지 **diff 0** (실시간 부하 상태 정확 표시)
  - fallback→primary **자동 복귀** (리부트 없이, journal 확인) + primary 화면 픽셀 diff 0
- 24시간 안정화: 그간(배포→검증 과정 전체) 재기동/에러 없음 → 사용자 판단으로 기준 생략, **P2 완료 (2026-11-10)**

### P1 산출물 (2026-11-10)
- `tokcat.py` — `/api/live` 1s 폴링(백그라운드 스레드, 루프가 죽지 않음), gputils `core.py` SpeedModel/상태밴드 포트, 6개 지표+in-flight 표시, RunCat 애니메이션
  - 렌더링: 베이스 프레임(1s) + 스프라이트 사전 변환 RGB565 **스플리스** (애니메이션 틱 = memcpy)
  - `rgb_to_565` numpy화 (python3-numpy apt; 부재 시 pure-python 폴백 유지)
  - 스프라이트: `cat_frames/` (gputils RunCatNeo 56×36×5 + sleeping, Apache-2.0 — gputils 리포 무변경, 복사)
- `config.toml` — `[speed]`(gputils 동일 파라미터), `[cat]`(색/폭), `[poll]`(timeout)
- `scripts/verify_expect.py` — 동시 json+캡처 픽셀 대조 검증 (Pi 실행)
- 검증: 유휴 상태 json↔화면 **픽셀 diff 0**, run/sleep 포즈 전환 캡처 확인, CPU ~1%
- 개발 브랜치: `dev` (GitHub 기본 브랜치는 `main` 유지)

### P4 산출물 (2026-11-19)
- **목업**: `이미지.png` (사용자 작성, 1988×1324) — 5블록 레이아웃 설계도. 중앙(요청 목록)↔좌하(데이터) 위치 교환 확정
- `tokcat.py` —
  - `render_base` 5블록 재작성: cat 좌상단(`CAT_X0=16, CAT_Y0=60`) · metrics 중앙 · in-flight 좌하 · KV 게이지 우상 · 그래프 우하
  - 신규 helper: `total_tok_s` (running×decode), `draw_gauge` (원형 0..1 게이지), `draw_graph` (역사 영역 차트, 우측 정렬), `draw_request_list` (2줄 항목), `_wrap` (워드랩), `_blend`
  - `total = requests_running × decode_tokens_per_s` (사용자 지정 — vLLM 현재 총 토큰 생성 속도)
  - in-flight 2줄 포맷 (`_format_in_flight`: `client·path` / `model·경과`, path 8·model 12 자 절단) + `mono_xs`(12px) 폰트
  - 그래프 시계열: `main` 루프의 `deque(maxlen=HIST_MAX=60)`, 리빌드 시(≈1s) `total_tok_s` append
- `config.toml` — `[font] mono_xs_size = 12`
- `scripts/render_test.py` — **신규**: fb0/VT 비사용 순수 렌더 테스트 (online/fallback/offline 3프레임 PNG). 스테이징 디렉터리(`/tmp/tokcat_p4`)에서 실행 → 프로덕션 서비스 무접촉 레이아웃 검증
- 검증: render_test 3프레임(online/fallback/offline) 레이아웃 확인 → `/opt/tokcat` 배포 + `systemctl restart` → **라이브 캡처** 5블록+고양이+실시간 그래프 확인, journal 재시작 무에러

## 7. 작업 규칙
- 작업을 시작하기 전에 **무조건 사용자에게 확인을 받고** 시작한다 (자발 판단으로 시작하지 않음)
- 개발: `이 리포` (**`dev` 브랜치**, 안정화 시 `main` 머지) → ssh(tokcat)로 파이에 push → `/dev/fb0` PNG 캡처로 검증
- **gputils**(`~/gputils`)·**tokenbills**(`../tokenbills`)는 읽기 전용 — 그들 AGENTS.md의 "작업 전 확인" 규칙 준수
- tokenbills 프로덕션(`192.168.1.221:/opt/tokenbills`)은 절대 변경 금지 (API 읽기만)
- PowerShell → ssh: 원격 명령에 **더블쿼트 사용 금지** (파이프 깨짐), grep은 문자 클래스(`[t]ouch`)나 분리
- Pi 재부팅 전엔 반드시 `poweroff` (SSH로) — 하드 파워오프 금지

## 8. 미정 사항 (다음 세션에서 결정)
1. **사용량/비용(오늘·이번 달 KRW)**을 단일 화면에 넣을 것인가 — 넣으면 in-flight 줄과 레이아웃 경쟁 (P3로 유보 가능)
2. **터치 활용**: 탭으로 상세 전환 / 표시 전용(무터치)
3. ~~**프리필 공백**: `—` 표시 vs 최근값 유지~~ — **`—` 표시로 확정 (2026-11-10)**
4. ~~렌더링 엔진: pygame vs Pillow+mmap~~ — **Pillow+mmap으로 확정 (2026-11-10)**
