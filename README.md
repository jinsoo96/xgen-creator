# XGEN CREATOR

> **소스가 곧 산출물이다.** 브라우저에서 버튼을 누르면 —
> 그 UI 요소가 **어느 프론트 소스**인지 연결되고 · 클릭이 유발한 백엔드 Python이
> **실제로 돌린 라인들**(line-by-line)이 건져지고 · (스크린샷+소스링크+API+실행소스)가
> **한 스텝의 증거**가 되어 · wikidocs식 산출물 문서가 **자동 렌더**된다.
> 소스가 바뀌면 빌드 파이프라인이 재생성한다.

IDE 디버거를 브라우저 편으로 뒤집은 **Live Bridge**. 의존성 거의 0(Python 표준
라이브러리 중심, playwright만 optional). 로컬/온프레미스 자가 호스팅.

> ⚠️ **설정 없이는 아무것도 안 된다(의도된 것).** 대상 URL·레포 경로는 전부
> `.env`·`creator.config.json`에만 있고, 이 저장소엔 예시(placeholder)만 있다.

---

## 동작 원리

```
사람/AI ──클릭──► [브라우저 (Playwright)]
                     │  X-Creator-Trace: <id> 주입
                     ▼
       [프론트 (Next.js 모노레포)] ──API──► [백엔드 (Python/ASGI)]
                     │                        │ CreatorTraceMiddleware (1줄 장착)
      요소→소스 리졸버│                        │ 라인 트레이서: 돌아간 라인 전량 캡처
                     ▼                        ▼
            ┌────────────── 증거 (Step) ──────────────┐
            │ 스크린샷 · 요소↔프론트소스 · API · 실행된 소스 │
            └───────────────────┬────────────────────┘
                                ▼
              [빌드 파이프라인] → wikidocs식 문서 (md + self-contained html)
```

- **트레이스 상관**: 스텝마다 고유 ID를 발급해 헤더로 주입 → 백엔드 미들웨어가 같은
  ID로 실행 기록을 저장 → 브리지가 회수. 브라우저 액션과 백엔드 실행이 1:1로 묶인다.
- **검증 정직성**: 캡처하지 못한 것은 문서에 **"증거 없음"**으로 표기된다.
  채워 넣지 않는 것이 원칙이다.
- **모델 역할 분리**: 오케스트레이션(agent)과 소스 서술(source)에 서로 다른 모델을
  배정한다(설정 주도). LLM 없이도 결정론 코어(트레이스·렌더)는 완전 동작한다.

---

## 설치

```bash
pip install -e .            # → 어디서든 `creator` 명령
pip install -e .[bridge]    # 브라우저 브리지까지 (+ playwright install chromium)

cp .env.example .env                                  # 자기 값 채움
cp creator.config.example.json creator.config.json    # 레포 경로·URL 채움
creator doctor              # 자가검증 — 능력이 실제로 되는지
```

## 사용법

### 0) 원샷 — "산출물 만들어줘"

```bash
# 자연어 목표 → agent 모델(Opus)이 멀티턴 관측 루프로 브라우저를 몬다:
# 보고 → 행동 → 결과를 다시 보고 → 스스로 완료 판단 (AI가 버튼을 누른다)
creator make --goal "분석 실행 버튼을 눌러 결과를 확인한다" --pdf

# 로그인 게이트가 있는 화면은 로그인을 먼저 결정론으로 수행한 뒤 AI가 이어받는다
# ("mask": true 스텝의 값은 LLM에도 증거에도 남기지 않음)
creator make --goal "..." --pre-steps login.json

# 또는 스텝을 직접 정의
creator make --steps examples/demo_steps.json --pdf
# 명령 하나 = (계획) → 여정 기록(영상 webm) → 서술(source 모델) → 화면정의서·테스트결과서·챕터 → PDF

# 버튼 하나 UI로:  creator web --open   (자연어 입력·실행 로그·라이브 소스 스크린·산출물 한 화면)
```

### 1) 백엔드 관측 장착 — 두 가지 방법 (대상 레포에 커밋하지 않는다)

```python
# A. 구동 스크립트에서 1줄
from xgen_creator.trace import CreatorTraceMiddleware
app = CreatorTraceMiddleware(app, roots=["/path/to/backend/src"])
```

```bash
# B. 사이드카 — 앱 코드 수정 0. 대상 venv에서 감싸서 기동
creator sidecar main:app --dir /path/to/backend --port 8201
# 게이트웨이를 못 건드릴 땐 브리지 션트로 특정 API만 사이드카에 보낸다:
creator record --steps steps.json --reroute "**/api/workflow/**=http://127.0.0.1:8201"
```

### 2) 여정 기록 → 산출물 빌드

```bash
# 스텝 정의(JSON)대로 브라우저를 몰며 증거 수집 → 여정 JSON (--video로 녹화)
creator record --steps examples/demo_steps.json --title "로그인 여정" --video

# 여정 → 산출물 양식 (변경된 여정만 재렌더, --pdf로 Edge headless PDF)
creator doc build --form test-report --pdf     # 테스트결과서
creator doc build --form screen-spec           # 화면정의서
creator doc build --form api-spec              # API 명세서
creator doc build                              # 챕터 문서(journey)
```

### 3) 단독 트레이스 (브라우저 없이)

```bash
creator trace run examples/demo_traced_script.py     # 돌아간 라인을 그 자리에서 확인
```

```
# .../demo_traced_script.py  (실행 8줄 / 전체 21줄)
  … 6–14 …
>     8 | def classify(n):
>     9 |     if n < 0:
     10 |         return "음수"
>    11 |     if n % 2 == 0:
>    12 |         return "짝수"
```

### 4) 보조

```bash
creator routes --root /path/to/frontend    # Next.js 라우트맵 (URL ↔ page 소스)
creator rules --compose                    # 산출물 Rule 컨텍스트 (LLM 주입용)
creator roles                              # 모델 역할 (agent / source)
```

---

## 핵심 개념

| 개념 | 설명 |
|---|---|
| **증거(Step)** | 액션 1회의 완전한 기록 — 스크린샷 · UI요소→프론트소스 후보 · API 호출 · 실행된 백엔드 소스 슬라이스 |
| **여정(Journey)** | 증거의 연쇄. JSON 원본이 진실이고 문서는 그 렌더일 뿐 |
| **실행 슬라이스** | 트레이스된 라인을 소스 발췌로 렌더(`>` 마커 = 실행됨). "돌아간 만큼만" 보여준다 |
| **트레이스 저장소** | 미들웨어(쓰기)↔브리지(읽기)가 파일시스템으로 공유. 원자적 교체로 반쯤 쓴 파일 없음 |
| **빌드 파이프라인** | 여정 해시 변경 감지 → 바뀐 것만 재렌더. 소스 변경 → 재수집 → 자동 재생성 |
| **산출물 양식** | 화면정의서(screen-spec)·테스트결과서(test-report)·API 명세서(api-spec) 레지스트리. 새 양식 = 렌더 함수 한 쌍 등록 |
| **모델 역할** | agent(Opus, 화면 보고 여정 계획)와 source(Fable, 증거 서술)를 분리 배정. LLM은 증거에 있는 것만 서술하고, 없는 건 "증거 없음" |
| **자동 재생성** | `creator watch` — 여정이 바뀌면 재렌더, `--sources`면 백엔드/프론트 소스 변경 시 여정 재수집까지(빌드 파이프라인) |
| **저오버헤드 트레이서** | py3.12+는 sys.monitoring(PEP 669) 기본 — 스코프 밖 코드 위치는 영구 배제. 구버전은 settrace 폴백 |
| **게이트웨이** | `creator export`가 산출물 인덱스(self-contained)를 만든다. 모노레포 프론트 통합 템플릿 = `integrations/xgen-frontend/` |
| **Rule 컨텍스트** | `rules/*.md` = 산출물 규칙(용어·톤·규격). LLM 서술 단계에 자동 주입 |
| **라이브 소스 스크린** | 트레이서 이벤트를 SSE로 스트리밍 — 화면 옆에서 "지금 도는 소스 라인"이 흐른다 |

## 경계 (설계 원칙)

- **대상 레포 불가침** — 읽기와 실행 관측만. 유일한 접점은 로컬 구동 시 미들웨어 1줄.
- **관측은 opt-in** — 트레이스 헤더 없는 요청은 오버헤드 0으로 통과. 트레이스는
  전역 락으로 한 번에 하나(관측 도구지 프로덕션 프로파일러가 아니다).
- **공개 안전** — 코드에 자격·조직 정보 0. 실값은 전부 gitignore된 로컬 파일에만.

## 개발

```bash
python -m unittest discover -s tests -v
```

## 형제 프로젝트

[xgen-maker](https://github.com/jinsoo96/xgen-maker) — 쿼리 하나로 코드를 **바꾸는** 쪽
(개발 자동화, MR-only). CREATOR는 소스로 산출물을 **만드는** 쪽. CREATOR가 수집한
실측 런타임 엣지(버튼→핸들러→라인)는 MAKER의 지식그래프를 보강할 수 있다.
