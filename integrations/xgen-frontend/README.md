# 모노레포 프론트엔드 게이트웨이 통합

Next.js 모노레포(App Router)를 XGEN CREATOR 산출물의 게이트웨이로 쓰는 두 가지 방법.
(대상 모노레포에 넣는 작업은 그쪽 레포의 브랜치/MR 절차를 따른다 — 이 폴더는 템플릿이다.)

## A. 콘솔 프록시 라우트 (권장 — 라이브 기능 전부)

`apps/web/src/app/creator/page.tsx` 로 [creator-page.tsx](creator-page.tsx) 를 복사하고,
환경변수 `NEXT_PUBLIC_CREATOR_URL` 에 콘솔 주소(`http://<host>:8990`)를 준다.
플랫폼 사이드바에 `/creator` 메뉴 하나 추가하면 끝 — "산출물 만들어줘" 버튼·실행 로그·
라이브 소스 스크린이 플랫폼 안에서 그대로 돈다.

## B. 정적 산출물 서빙 (읽기 전용 뷰)

```bash
creator export          # docs_out/index.html 인덱스 생성 (self-contained)
```

`docs_out/` 을 모노레포 `apps/web/public/creator-docs/` 로 복사(또는 심볼릭 링크/CI 단계)
하면 `/creator-docs/index.html` 에서 전 산출물이 열린다. 외부 리소스 0이라 CSP 무관.

## 경계

- 콘솔은 로컬 관측 도구다 — 사내망 밖 노출 금지, 인증은 플랫폼(게이트웨이) 레이어 몫.
- 이 템플릿은 대상 모노레포에서 빌드 검증을 거치지 않았다(플랫폼 반영 시 확인 필요).
