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

### 1) 백엔드에 미들웨어 장착 (로컬 구동 스크립트에서 1줄 — 대상 레포에 커밋하지 않는다)

```python
from xgen_creator.trace import CreatorTraceMiddleware
app = CreatorTraceMiddleware(app, roots=["/path/to/backend/src"])
```

### 2) 여정 기록 → 산출물 빌드

```bash
# 스텝 정의(JSON)대로 브라우저를 몰며 증거 수집 → 여정 JSON
creator record --steps examples/demo_steps.json --title "로그인 여정"

# 여정 → wikidocs식 챕터 문서 (변경된 여정만 재렌더)
creator doc build
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
| **Rule 컨텍스트** | `rules/*.md` = 산출물 규칙(용어·톤·규격). LLM 서술 단계에 자동 주입 |

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
