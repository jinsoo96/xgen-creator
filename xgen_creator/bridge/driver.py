"""Playwright 브리지 — AI/스크립트가 실브라우저에서 액션을 수행하고 증거를 캡처한다.

스텝마다 고유 트레이스 ID를 발급해 X-Creator-Trace 헤더로 주입하고,
액션이 유발한 백엔드 실행(미들웨어가 저장)을 같은 ID로 회수해 상관시킨다.
playwright는 optional extra(`pip install xgen-creator[bridge]`).
"""
from __future__ import annotations

import uuid
from pathlib import Path
from urllib.parse import urlsplit

from ..trace.store import TraceStore

ACTIONS = ("goto", "click", "fill", "press")

# 화면의 상호작용 요소(버튼·링크·입력)를 selector와 함께 요약 — 계획자에게 넘길 스냅샷
_OUTLINE_JS = """(max) => {
    const sel = 'button, a[href], input, [role=button], [data-testid]';
    const out = [];
    for (const el of document.querySelectorAll(sel)) {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        const testid = el.dataset ? el.dataset.testid : null;
        let s = null;
        if (testid) s = '[data-testid=' + testid + ']';
        else if (el.id) s = '#' + el.id;
        else if (el.name) s = el.tagName.toLowerCase() + '[name=' + el.name + ']';
        else if (el.type) s = el.tagName.toLowerCase() + '[type=' + el.type + ']';
        else continue;
        out.push({ tag: el.tagName.toLowerCase(), selector: s,
            text: (el.innerText || el.value || el.placeholder || '').trim().slice(0, 60) || null,
            type: el.type || null });
        if (out.length >= max) break;
    }
    return out;
}"""


def resolve_goto(target: str | None, base_url: str) -> str | None:
    """goto 대상을 앱 URL로 정규화. 앱 경로(/x)·동일 오리진 http만 허용.

    about:blank·주소창·외부 URL 등 에이전트가 지어낼 수 있는 무효/이탈 대상은 None
    (스텝은 no-op으로 안전 처리). base_url 오리진을 벗어난 http도 거부한다.
    """
    if not target:
        return base_url + "/"
    target = target.strip()
    if target.startswith("/"):
        return base_url.rstrip("/") + target
    if target.startswith(base_url.rstrip("/") + "/") or target == base_url.rstrip("/"):
        return target
    return None  # about:blank, address-bar, 외부 도메인 등 → 거부


def swap_base(url: str, target_base: str) -> str:
    """URL의 스킴+호스트만 target_base로 교체 (경로·쿼리 보존) — 사이드카 션트용."""
    parts = urlsplit(url)
    base = target_base.rstrip("/")
    return base + parts.path + (f"?{parts.query}" if parts.query else "")


class BridgeSession:
    def __init__(
        self,
        base_url: str,
        trace_store: TraceStore | str | None = None,
        shot_dir: str | Path = ".creator/journeys/shots",
        headless: bool = True,
        backend_wait: float = 8.0,
        video_dir: str | Path | None = None,
        reroute: list[tuple[str, str]] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.store = TraceStore(trace_store) if isinstance(trace_store, str) else trace_store
        self.shot_dir = Path(shot_dir)
        self.headless = headless
        self.backend_wait = backend_wait
        self.video_dir = Path(video_dir) if video_dir else None
        self.video_path: str | None = None  # __exit__ 후에 유효 (여정에 첨부)
        # [(url glob 패턴, target_base)] — 매칭 요청을 사이드카 등으로 션트(레포 무수정 관측)
        self.reroute = reroute or []
        self.extra_headers = dict(extra_headers or {})  # identity 헤더 등, 매 스텝 병합
        self._pw = None
        self._browser = None
        self._page = None
        self._step_no = 0

    # -- 수명 ---------------------------------------------------------------
    def __enter__(self) -> "BridgeSession":
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "playwright 미설치 — `pip install xgen-creator[bridge]` 후 "
                "`playwright install chromium`"
            ) from exc
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        context_args = {}
        if self.video_dir:
            self.video_dir.mkdir(parents=True, exist_ok=True)
            context_args = {"record_video_dir": str(self.video_dir),
                            "record_video_size": {"width": 1280, "height": 720}}
        self._context = self._browser.new_context(**context_args)
        for pattern, target_base in self.reroute:
            def _shunt(route, request, _tb=target_base):
                route.continue_(url=swap_base(request.url, _tb))
            self._context.route(pattern, _shunt)
        self._page = self._context.new_page()
        self.shot_dir.mkdir(parents=True, exist_ok=True)
        return self

    def __exit__(self, *exc) -> None:
        if self.video_dir and self._page is not None:
            try:
                self.video_path = self._page.video.path()
            except Exception:
                self.video_path = None
        for closer in (self._context.close, self._browser.close, self._pw.stop):
            try:
                closer()
            except Exception:
                pass

    # -- 계획용 화면 요약 ----------------------------------------------------
    def outline(self, url: str | None = None, max_elements: int = 45) -> list[dict]:
        """상호작용 요소(버튼·링크·입력) 목록 — 계획자에게 넘길 화면 스냅샷.

        로그인 후 리다이렉트 등 네비게이션 중이면 컨텍스트가 파괴될 수 있어,
        페이지 안정을 기다린 뒤 실행하고 네비게이션 충돌 시 1회 재시도한다.
        """
        page = self._page
        if url is not None:
            page.goto(url if url.startswith("http") else self.base_url + url)
        for state in ("domcontentloaded", "networkidle"):
            try:
                page.wait_for_load_state(state, timeout=6000)
            except Exception:
                pass
        for attempt in range(2):
            try:
                return page.evaluate(_OUTLINE_JS, max_elements)
            except Exception:
                if attempt == 0:  # 네비게이션으로 컨텍스트 파괴 → 안정 후 재시도
                    try:
                        page.wait_for_load_state("networkidle", timeout=6000)
                    except Exception:
                        page.wait_for_timeout(800)
                    continue
                return []  # 끝내 못 잡으면 빈 목록(정직) — 루프가 done 판단
        return []

    # -- 스텝 ---------------------------------------------------------------
    def step(self, action: str, selector: str | None = None,
             value: str | None = None, note: str = "") -> dict:
        """액션 1회 = 증거 1건. 반환 dict는 docgen.model.Step과 호환."""
        if action not in ACTIONS:
            raise ValueError(f"지원 액션 {ACTIONS} 중 하나여야 함: {action!r}")
        self._step_no += 1
        trace_id = uuid.uuid4().hex[:16]
        self._context.set_extra_http_headers(
            {**self.extra_headers, "X-Creator-Trace": trace_id})

        page = self._page
        url_before = page.url
        api_calls = []

        def _on_request(req):
            if req.resource_type in ("fetch", "xhr"):
                api_calls.append({"method": req.method, "url": req.url})

        page.on("request", _on_request)

        skipped = None
        if action == "goto":
            dest = resolve_goto(value or selector, self.base_url)
            if dest is None:  # 무효/이탈 대상은 이동하지 않고 정직 기록
                skipped = f"무효 goto 대상 무시: {value or selector!r}"
            else:
                page.goto(dest)
        elif action == "click":
            page.click(selector)
        elif action == "fill":
            page.fill(selector, value or "")
        elif action == "press":
            page.press(selector, value or "Enter")
        try:
            page.wait_for_load_state("networkidle", timeout=int(self.backend_wait * 1000))
        except Exception:
            pass  # SPA 폴링 등으로 idle 미도달 가능 — 증거 수집은 계속
        page.remove_listener("request", _on_request)  # 다음 스텝 증거 오염 방지

        shot = self.shot_dir / f"step-{self._step_no:02d}.png"
        page.screenshot(path=str(shot), full_page=False)

        element = None
        if selector and action != "goto":
            try:
                element = page.locator(selector).first.evaluate(
                    """el => ({
                        tag: el.tagName.toLowerCase(),
                        id: el.id || null,
                        testid: el.dataset ? (el.dataset.testid || null) : null,
                        classes: (el.className && el.className.split) ? el.className.split(/\\s+/).filter(Boolean) : [],
                        text: (el.innerText || '').trim().slice(0, 120) || null,
                    })"""
                )
            except Exception:
                element = {"selector_only": True}

        backend = self.store.wait(trace_id, timeout=self.backend_wait) if self.store else None

        return {
            "idx": self._step_no,
            "trace_id": trace_id,
            "action": action,
            "selector": selector,
            "value": value,
            "note": note,
            "url_before": url_before,
            "url_after": page.url,
            "screenshot": str(shot),
            "element": element,
            "api": api_calls,
            "backend": backend,
            "skipped": skipped,
        }
