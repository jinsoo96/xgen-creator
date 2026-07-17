"""creator web — 산출물 콘솔 (의존성 0, 단일 파일 UI).

"산출물 만들어줘" 버튼 하나로 러너가 돌고, 같은 화면에서
실행 로그 · 스텝 타임라인 · 라이브 소스 스크린 · 산출물이 흐른다.

    creator web --port 8990 --open
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from .runner import run_make

_CTYPES = {".html": b"text/html; charset=utf-8", ".md": b"text/plain; charset=utf-8",
           ".pdf": b"application/pdf", ".png": b"image/png", ".webm": b"video/webm",
           ".json": b"application/json; charset=utf-8"}


class MakeJob:
    def __init__(self, params: dict) -> None:
        self.params = params
        self.state = "running"          # running | done | error
        self.lines: list[str] = []
        self.result: dict | None = None
        self.error: str | None = None
        self.frame: dict | None = None  # 최신 화면 프레임 (라이브 화면 전환 스트리밍)
        self.frame_seq = 0
        self._lock = threading.Lock()

    def log(self, message: str) -> None:
        with self._lock:
            self.lines.append(f"[{time.strftime('%H:%M:%S')}] {message}")

    def add_frame(self, frame: dict) -> None:
        """브리지가 스텝마다 넘기는 화면 프레임 — 워커 스레드에서 호출된다."""
        with self._lock:
            self.frame_seq += 1
            self.frame = frame


class ConsoleApp:
    """동시 1작업(관측 도구)의 산출물 콘솔 ASGI 앱. make_fn 주입 가능(테스트)."""

    def __init__(self, config: dict, make_fn=run_make) -> None:
        self.config = config
        self.make_fn = make_fn
        self.job: MakeJob | None = None

    # -- 작업 -----------------------------------------------------------------
    def start_job(self, params: dict) -> bool:
        if self.job is not None and self.job.state == "running":
            return False
        job = MakeJob(params)
        self.job = job

        def worker():
            try:
                job.result = self.make_fn(
                    self.config, steps=params.get("steps") or None,
                    goal=params.get("goal") or None,
                    journey_id=params.get("id") or None,
                    title=params.get("title") or None,
                    narrate=bool(params.get("narrate", True)),
                    pdf=bool(params.get("pdf", False)),
                    on_frame=job.add_frame, log=job.log)
                job.state = "done"
            except Exception as exc:
                job.error = f"{type(exc).__name__}: {exc}"
                job.log(f"오류: {job.error}")
                job.state = "error"

        threading.Thread(target=worker, daemon=True).start()
        return True

    # -- 경로 안전 ---------------------------------------------------------------
    @staticmethod
    def _safe(root: str | Path, rel: str) -> Path | None:
        base = Path(root).resolve()
        target = (base / rel.lstrip("/")).resolve()
        return target if target.is_file() and target.is_relative_to(base) else None

    def _rel_media(self, path: str | None) -> str | None:
        if not path:
            return None
        try:
            rel = Path(path).resolve().relative_to(
                Path(self.config["journey_dir"]).resolve())
            return "/media/" + str(rel).replace("\\", "/")
        except ValueError:
            return None

    def _state_payload(self, since: int) -> dict:
        job = self.job
        if job is None:
            return {"state": "idle", "lines": [], "line_total": 0}
        result = None
        if job.result:
            result = dict(job.result)
            result["video_url"] = self._rel_media(result.get("video"))
            out_root = Path(self.config["out_dir"]).resolve()
            files = []
            for p in result.get("outputs", []) + result.get("pdfs", []):
                try:
                    rel = Path(p).resolve().relative_to(out_root)
                    files.append({"name": str(rel).replace("\\", "/"),
                                  "url": "/files/" + str(rel).replace("\\", "/")})
                except ValueError:
                    continue
            result["files"] = files
            for step in result.get("steps", []):
                step["shot_url"] = self._rel_media(step.get("screenshot"))
        frame = None
        if job.frame:
            frame = {"seq": job.frame_seq, "action": job.frame.get("action"),
                     "url_after": job.frame.get("url_after"),
                     "url_before": job.frame.get("url_before"),
                     "shot_url": self._rel_media(job.frame.get("shot"))}
        return {"state": job.state, "error": job.error,
                "lines": job.lines[since:], "line_total": len(job.lines),
                "frame": frame, "result": result}

    # -- ASGI ----------------------------------------------------------------
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return

        async def reply(body: bytes, ctype: bytes = b"text/html; charset=utf-8",
                        status: int = 200):
            await send({"type": "http.response.start", "status": status,
                        "headers": [(b"content-type", ctype),
                                    (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})

        path = scope["path"]
        query = dict(pair.split("=", 1) for pair in
                     scope.get("query_string", b"").decode().split("&") if "=" in pair)

        if path == "/":
            return await reply(self._page().encode("utf-8"))
        if path == "/gallery":  # 게이트웨이 — 산출물 인덱스를 콘솔이 직접 서빙
            from .docgen.index_page import build_index
            out_dir = Path(self.config["out_dir"])
            if not out_dir.exists():
                return await reply("아직 산출물이 없습니다.".encode())
            index = build_index(out_dir)
            html = index.read_text(encoding="utf-8").replace(
                'href="', 'href="/files/')  # 상대링크를 콘솔의 파일 서빙 경로로
            return await reply(html.encode("utf-8"))
        if path == "/api/state":
            return await reply(json.dumps(
                self._state_payload(int(query.get("since", 0))),
                ensure_ascii=False).encode("utf-8"), b"application/json; charset=utf-8")
        if path == "/api/run" and scope["method"] == "POST":
            message = await receive()
            params = json.loads(message.get("body") or b"{}")
            started = self.start_job(params)
            return await reply(json.dumps({"started": started}).encode(),
                               b"application/json", 200 if started else 409)
        for prefix, root_key in (("/files/", "out_dir"), ("/media/", "journey_dir")):
            if path.startswith(prefix):
                target = self._safe(self.config[root_key], path[len(prefix):])
                if target is None:
                    return await reply(b"not found", b"text/plain", 404)
                ctype = _CTYPES.get(target.suffix.lower(), b"application/octet-stream")
                return await reply(target.read_bytes(), ctype)
        return await reply(b"not found", b"text/plain", 404)

    # -- 페이지 ----------------------------------------------------------------
    def _steps_options(self) -> list[str]:
        options = []
        for pattern in ("examples/*.json", "steps/*.json"):
            options += [str(p).replace("\\", "/") for p in Path(".").glob(pattern)
                        if not p.name.startswith("creator.config")]
        return options

    def _page(self) -> str:
        live_url = (self.config.get("live_url")
                    or (self.config.get("base_url", "").rstrip("/") + "/creator/live"))
        boot = json.dumps({"base_url": self.config.get("base_url", ""),
                           "live_url": live_url,
                           "steps_options": self._steps_options()}, ensure_ascii=False)
        return _PAGE.replace("__BOOT__", boot)


_PAGE = """<!doctype html><meta charset="utf-8"><title>XGEN CREATOR 콘솔</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { height:100vh; display:flex; flex-direction:column; background:#0d1420; color:#d8e2ef;
       font-family:'Segoe UI','Malgun Gothic',sans-serif; }
header { height:64px; background:#111b2a; border-bottom:2px solid #2b5aa8; display:flex;
         align-items:center; gap:18px; padding:0 26px; flex:none; }
header .logo { font-weight:700; font-size:20px; letter-spacing:.5px; }
header .logo em { color:#6cb6ff; font-style:normal; }
header .target { color:#8a97a8; font-size:14px; }
.badge { margin-left:auto; padding:5px 16px; border-radius:999px; font-size:14px; font-weight:600;
         background:#1d2a3d; color:#8a97a8; }
.badge.running { background:#2b5aa8; color:#fff; }
.badge.done { background:#1e5c33; color:#7ee787; }
.badge.error { background:#5c1e1e; color:#ff8f8f; }
main { flex:1; display:grid; grid-template-columns:400px 1fr 1fr; grid-template-rows:1fr 1fr;
       gap:12px; padding:12px; min-height:0; }
.panel { background:#0a0f16; border:1px solid #223247; border-radius:12px; display:flex;
         flex-direction:column; min-height:0; overflow:hidden; }
.panel > h2 { flex:none; font-size:13px; font-weight:600; color:#6cb6ff; letter-spacing:1.5px;
              padding:12px 18px 10px; border-bottom:1px solid #16202e; }
.panel .body { flex:1; overflow-y:auto; padding:14px 18px; min-height:0; }
#run-panel   { grid-row:1; grid-column:1; }
#timeline    { grid-row:2; grid-column:1; }
#logs        { grid-row:1; grid-column:2; }
#live-screen { grid-row:1; grid-column:3; }
#live        { grid-row:2; grid-column:2; }
#outputs     { grid-row:2; grid-column:3; }
#ls-body { display:flex; flex-direction:column; }
#ls-img { width:100%; flex:1; object-fit:contain; background:#05080d; min-height:0; }
#ls-url { flex:none; font-family:Consolas,monospace; font-size:11px; color:#8a97a8;
          padding:8px 14px; border-top:1px solid #16202e; white-space:nowrap; overflow:hidden;
          text-overflow:ellipsis; }
#ls-url b { color:#7ee787; }
header a.gallery { margin-left:16px; color:#6cb6ff; text-decoration:none; font-size:14px;
                   border:1px solid #2b3d55; border-radius:8px; padding:5px 14px; }
header a.gallery:hover { border-color:#6cb6ff; }
label { display:block; font-size:13px; color:#8a97a8; margin:14px 0 6px; }
select, input { width:100%; background:#111b2a; color:#d8e2ef; border:1px solid #2b3d55;
         border-radius:8px; padding:10px 12px; font-size:14px; }
.toggles { display:flex; gap:16px; margin-top:14px; font-size:14px; color:#aebfd4; }
.toggles input { accent-color:#2b5aa8; margin-right:6px; }
#go { width:100%; margin-top:22px; padding:16px; font-size:18px; font-weight:700;
      background:linear-gradient(135deg,#2b5aa8,#1d3f78); color:#fff; border:0;
      border-radius:10px; cursor:pointer; letter-spacing:.5px; }
#go:hover { filter:brightness(1.15); }
#go:disabled { background:#1d2a3d; color:#5b6b7f; cursor:default; }
.hint { font-size:12px; color:#5b6b7f; margin-top:12px; line-height:1.6; }
#log-body { font-family:Consolas,'D2Coding',monospace; font-size:13px; line-height:1.7;
            white-space:pre-wrap; color:#b9c8da; }
#log-body .t { color:#5b6b7f; margin-right:8px; }
.step { display:flex; gap:12px; align-items:center; padding:10px 0; border-bottom:1px solid #131d2b; }
.step img { width:96px; height:54px; object-fit:cover; border-radius:6px; border:1px solid #223247; }
.step .meta { font-size:13px; line-height:1.5; }
.step .meta b { color:#d8e2ef; }
.step .ev { font-size:12px; }
.ev.on { color:#7ee787; } .ev.off { color:#5b6b7f; }
iframe { width:100%; height:100%; border:0; background:#0a0f16; }
.chip { display:flex; justify-content:space-between; align-items:center; background:#111b2a;
        border:1px solid #223247; border-radius:8px; padding:9px 14px; margin-bottom:8px;
        font-size:13px; }
.chip a { color:#6cb6ff; text-decoration:none; }
.chip .k { color:#8a97a8; }
.empty { color:#43506180; font-size:13px; padding:8px 0; }
</style>
<header>
  <div class="logo"><em>XGEN</em> CREATOR 콘솔</div>
  <div class="target" id="target"></div>
  <a class="gallery" href="/gallery" target="_blank">산출물 갤러리 ↗</a>
  <div class="badge" id="badge">대기</div>
</header>
<main>
  <div class="panel" id="run-panel">
    <h2>실행</h2>
    <div class="body">
      <label>목표 (자연어 — AI가 화면 보고 스텝 계획)</label>
      <input id="goal" placeholder="예: 분석 버튼을 눌러 결과를 확인한다" />
      <label>또는 여정 소스</label>
      <select id="steps"><option value="">최근 여정 재사용 (재렌더)</option></select>
      <div class="toggles">
        <label style="margin:0"><input type="checkbox" id="narrate" checked>LLM 서술</label>
        <label style="margin:0"><input type="checkbox" id="pdf" checked>PDF</label>
      </div>
      <button id="go">산출물 만들어줘 ▶</button>
      <div class="hint">실브라우저 여정 수행 → 라인 트레이스 → 서술 → 화면정의서·테스트결과서·챕터 → PDF.
      모든 문장은 증거로 소급되고, 증거 없는 칸은 "증거 없음"으로 남는다.</div>
    </div>
  </div>
  <div class="panel" id="timeline"><h2>스텝 타임라인</h2><div class="body" id="tl-body"><div class="empty">실행하면 스텝이 차오른다</div></div></div>
  <div class="panel" id="logs"><h2>실행 로그</h2><div class="body" id="log-body"></div></div>
  <div class="panel" id="live-screen"><h2>라이브 화면 — AI가 지금 보는 브라우저</h2>
    <div class="body" style="padding:0" id="ls-body">
      <img id="ls-img" style="display:none" alt="live screen">
      <div class="empty" id="ls-empty" style="padding:14px 18px">실행하면 화면이 흐른다</div>
      <div id="ls-url" style="display:none"></div>
    </div></div>
  <div class="panel" id="live"><h2>라이브 소스 스크린 — 지금 도는 백엔드 라인</h2><iframe id="live-frame"></iframe></div>
  <div class="panel" id="outputs"><h2>산출물</h2><div class="body" id="out-body"><div class="empty">아직 없음</div></div></div>
</main>
<script>
const BOOT = __BOOT__;
document.getElementById("target").textContent = "대상: " + (BOOT.base_url || "(미설정)");
document.getElementById("live-frame").src = BOOT.live_url;
const sel = document.getElementById("steps");
for (const s of BOOT.steps_options) {
  const o = document.createElement("option"); o.value = s; o.textContent = "신규 수행: " + s;
  sel.appendChild(o);
}
let since = 0, timer = null, lastFrameSeq = 0;
const badge = document.getElementById("badge");
function setBadge(state) {
  badge.className = "badge " + state;
  badge.textContent = {running:"실행 중", done:"완료", error:"오류", idle:"대기"}[state] || state;
}
document.getElementById("go").onclick = async () => {
  since = 0; lastFrameSeq = 0;
  document.getElementById("log-body").textContent = "";
  document.getElementById("tl-body").innerHTML = '<div class="empty">수행 중…</div>';
  document.getElementById("out-body").innerHTML = '<div class="empty">생성 중…</div>';
  document.getElementById("ls-img").style.display = "none";
  document.getElementById("ls-empty").style.display = "block";
  document.getElementById("ls-url").style.display = "none";
  await fetch("/api/run", { method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({ goal: document.getElementById("goal").value, steps: sel.value,
                           narrate: document.getElementById("narrate").checked,
                           pdf: document.getElementById("pdf").checked }) });
  document.getElementById("go").disabled = true;
  if (!timer) timer = setInterval(poll, 700);
};
async function poll() {
  const s = await (await fetch("/api/state?since=" + since)).json();
  setBadge(s.state);
  if (s.lines && s.lines.length) {
    const el = document.getElementById("log-body");
    for (const line of s.lines) {
      const row = document.createElement("div");
      const m = line.match(/^\\[(.*?)\\] (.*)$/s);
      row.innerHTML = m ? '<span class="t">' + m[1] + '</span>' : "";
      row.appendChild(document.createTextNode(m ? m[2] : line));
      el.appendChild(row);
    }
    since = s.line_total;
    el.parentElement.scrollTop = el.parentElement.scrollHeight;
  }
  if (s.frame && s.frame.shot_url && s.frame.seq !== lastFrameSeq) {
    lastFrameSeq = s.frame.seq;
    const img = document.getElementById("ls-img");
    img.src = s.frame.shot_url + "?seq=" + s.frame.seq;   // 캐시 무시하고 최신 화면
    img.style.display = "block";
    document.getElementById("ls-empty").style.display = "none";
    const u = document.getElementById("ls-url"); u.style.display = "block";
    const t = (s.frame.url_before !== s.frame.url_after)
      ? (s.frame.url_before + "  →  ") : "";
    u.innerHTML = "스텝 " + s.frame.seq + " · " + t + "<b>" + (s.frame.url_after || "") + "</b>";
  }
  if (s.result) renderResult(s.result);
  if (s.state === "done" || s.state === "error") {
    document.getElementById("go").disabled = false;
    clearInterval(timer); timer = null;
  }
}
function renderResult(r) {
  const tl = document.getElementById("tl-body"); tl.innerHTML = "";
  for (const st of r.steps || []) {
    const d = document.createElement("div"); d.className = "step";
    d.innerHTML = (st.shot_url ? '<img src="' + st.shot_url + '">' : "") +
      '<div class="meta"><b>스텝 ' + st.idx + '</b> · ' + st.action +
      ' <code>' + (st.selector || "") + '</code><br>' +
      '<span class="ev ' + (st.backend ? "on" : "off") + '">' +
      (st.backend ? "● 백엔드 라인 트레이스 확보" : "○ 백엔드 증거 없음") + "</span></div>";
    tl.appendChild(d);
  }
  const out = document.getElementById("out-body"); out.innerHTML = "";
  for (const f of r.files || []) {
    const c = document.createElement("div"); c.className = "chip";
    c.innerHTML = '<a href="' + f.url + '" target="_blank">' + f.name + "</a>";
    out.appendChild(c);
  }
  if (r.video_url) {
    const c = document.createElement("div"); c.className = "chip";
    c.innerHTML = '<a href="' + r.video_url + '" target="_blank">수행 영상 (webm)</a><span class="k">bridge 녹화</span>';
    out.appendChild(c);
  }
  if (!r.files?.length && !r.video_url) out.innerHTML = '<div class="empty">산출물 없음</div>';
}
setInterval(() => { if (!timer) poll().catch(() => {}); }, 3000);
</script>
"""
