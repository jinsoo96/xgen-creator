"""디버거 리플레이 뷰 — 캡처된 실행을 IDE 디버거처럼 line-by-line으로 되짚는다.

트레이스의 flow(실행 순서)를 스텝 단위로 재생한다: 현재 라인 하이라이트, 콜스택
(func·depth 재구성), 앞으로/뒤로/자동재생. "돌아간 만큼의 소스를 건져서 따라간다"의
실제 열람 도구. 자기완결 단일 HTML(외부 리소스 0)이라 어디서든 연다.
"""
from __future__ import annotations

import html as _html
import json
from pathlib import Path


def _source_map(payload: dict) -> dict[str, dict[str, str]]:
    """slices의 발췌 텍스트 → {파일: {라인번호(str): 소스텍스트}}."""
    src: dict[str, dict[str, str]] = {}
    for sl in payload.get("slices", []):
        table = src.setdefault(sl["file"], {})
        for ex in sl.get("excerpts", []):
            for no, _hit, text in ex["lines"]:
                table[str(no)] = text
    return src


def build_debug_view(payload: dict, out_path: str | Path,
                     title: str | None = None) -> Path:
    """트레이스 payload → 디버거 리플레이 HTML 경로."""
    flow = [[f, ln, func, depth]  # kind 드롭 — line 이벤트만
            for kind, f, ln, func, depth in payload.get("flow", [])
            if kind == "line"]
    data = {
        "trace_id": payload.get("trace_id"),
        "request": f"{payload.get('method')} {payload.get('path')} → {payload.get('status')}",
        "duration_ms": payload.get("duration_ms"),
        "event_count": payload.get("event_count"),
        "file_count": payload.get("file_count", len(payload.get("files", {}))),
        "truncated": payload.get("truncated"),
        "flow": flow,
        "executed": {f: sorted(set(lines))  # 파일별 실행 라인(마커용)
                     for f, lines in (payload.get("files") or {}).items()},
        "src": _source_map(payload),
    }
    heading = title or f"디버거 리플레이 — {data['request']}"
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        _TEMPLATE
        .replace("__TITLE__", _html.escape(heading))
        .replace("__DATA__", json.dumps(data, ensure_ascii=False)),
        encoding="utf-8")
    return out


_TEMPLATE = r"""<!doctype html><meta charset="utf-8"><title>__TITLE__</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
:root { --bg:#0b1017; --panel:#0e1621; --line:#1b2735; --fg:#d4deea; --dim:#6b7788;
        --accent:#4ecb8c; --blue:#6cb6ff; --cur:#243b2e; --curbar:#4ecb8c; }
body { height:100vh; display:flex; flex-direction:column; background:var(--bg); color:var(--fg);
       font-family:'Segoe UI','Malgun Gothic',sans-serif; }
header { flex:none; height:56px; background:var(--panel); border-bottom:1px solid var(--line);
         display:flex; align-items:center; gap:16px; padding:0 20px; }
header .t { font-weight:700; } header .t em { color:var(--accent); font-style:normal; }
header .req { font-family:Consolas,monospace; color:var(--blue); font-size:13px; }
header .meta { margin-left:auto; color:var(--dim); font-size:13px; font-family:Consolas,monospace; }
main { flex:1; display:grid; grid-template-columns:1fr 340px; min-height:0; }
.code { overflow:auto; padding:12px 0; font-family:Consolas,'D2Coding',monospace; font-size:13.5px;
        line-height:1.55; }
.fname { position:sticky; top:0; background:var(--bg); color:var(--dim); padding:6px 20px;
         border-bottom:1px solid var(--line); font-size:12px; }
.row { display:flex; padding:0 20px; white-space:pre; }
.row .no { color:#3f4b5b; width:56px; text-align:right; padding-right:16px; user-select:none;
           font-variant-numeric:tabular-nums; }
.row.exec .no { color:var(--accent); }
.row.cur { background:var(--cur); box-shadow:inset 3px 0 0 var(--curbar); }
.row.cur .no { color:var(--curbar); font-weight:700; }
.side { border-left:1px solid var(--line); background:var(--panel); display:flex;
        flex-direction:column; min-height:0; }
.side h3 { font-size:11px; letter-spacing:1.5px; color:var(--dim); padding:14px 18px 8px; }
.stack { overflow:auto; flex:1; min-height:0; }
.frame { padding:8px 18px; border-left:3px solid transparent; font-size:13px; }
.frame.top { border-left-color:var(--accent); background:#122019; }
.frame .fn { color:var(--fg); font-family:Consolas,monospace; }
.frame .loc { color:var(--dim); font-size:11px; font-family:Consolas,monospace; }
.controls { flex:none; border-top:1px solid var(--line); padding:14px 18px; }
.bar { height:5px; background:var(--line); border-radius:3px; overflow:hidden; margin-bottom:12px; }
.bar > span { display:block; height:100%; background:var(--accent); width:0; transition:width .05s; }
.pos { font-family:Consolas,monospace; font-size:12px; color:var(--dim); margin-bottom:10px;
       font-variant-numeric:tabular-nums; }
.btns { display:flex; gap:8px; align-items:center; }
button { background:#16202e; color:var(--fg); border:1px solid #2b3d55; border-radius:7px;
         padding:8px 12px; cursor:pointer; font-size:14px; }
button:hover { border-color:var(--accent); } button:disabled { opacity:.4; cursor:default; }
button.play { background:var(--accent); color:#06120c; border-color:var(--accent); font-weight:700; flex:1; }
select { background:#16202e; color:var(--fg); border:1px solid #2b3d55; border-radius:7px; padding:8px; }
kbd { background:#16202e; border:1px solid #2b3d55; border-radius:4px; padding:1px 6px; font-size:11px; color:var(--dim); }
.hint { margin-top:10px; color:var(--dim); font-size:11px; }
</style>
<header>
  <div class="t"><em>XGEN</em> CREATOR · 디버거 리플레이</div>
  <div class="req" id="req"></div>
  <div class="meta" id="meta"></div>
</header>
<main>
  <div class="code" id="code"></div>
  <div class="side">
    <h3>콜 스택 (현재)</h3>
    <div class="stack" id="stack"></div>
    <div class="controls">
      <div class="bar"><span id="fill"></span></div>
      <div class="pos" id="pos"></div>
      <div class="btns">
        <button id="back" title="이전 라인">◀</button>
        <button id="play" class="play">▶ 재생</button>
        <button id="fwd" title="다음 라인">▶</button>
        <select id="speed" title="재생 속도">
          <option value="200">1×</option>
          <option value="80">2.5×</option>
          <option value="30">6×</option>
          <option value="8">빠르게</option>
        </select>
      </div>
      <div class="hint">단축키: <kbd>←</kbd><kbd>→</kbd> 스텝 · <kbd>Space</kbd> 재생 · <kbd>Home</kbd> 처음</div>
    </div>
  </div>
</main>
<script>
const D = __DATA__;
document.getElementById("req").textContent = D.request;
document.getElementById("meta").textContent =
  `${D.event_count.toLocaleString()} 라인이벤트 · ${D.file_count} 파일 · ${D.duration_ms}ms`
  + (D.truncated ? " · truncated" : "");

const flow = D.flow;              // [ [file, line, func, depth], ... ]
let i = 0, timer = null;
const codeEl = document.getElementById("code");
const stackEl = document.getElementById("stack");
let renderedFile = null;

function shortPath(f) { return f.split(/[\\/]/).slice(-2).join("/"); }

function renderFile(file, curLine) {
  const src = D.src[file] || {};
  const execSet = new Set(D.executed[file] || []);
  const nums = Object.keys(src).map(Number).sort((a, b) => a - b);
  const frag = document.createElement("div");
  const head = document.createElement("div");
  head.className = "fname"; head.textContent = "# " + file;
  frag.appendChild(head);
  for (const n of nums) {
    const row = document.createElement("div");
    row.className = "row" + (execSet.has(n) ? " exec" : "") + (n === curLine ? " cur" : "");
    row.dataset.no = n;
    row.innerHTML = '<span class="no">' + n + '</span>';
    row.appendChild(document.createTextNode(src[String(n)] || ""));
    frag.appendChild(row);
  }
  codeEl.innerHTML = "";
  codeEl.appendChild(frag);
  renderedFile = file;
}

function callStack(idx) {
  // depth 진행으로 프레임 재구성: 각 depth 레벨의 최근 (func,file,line)
  const frames = [];
  for (let k = 0; k <= idx; k++) {
    const [file, line, func, depth] = flow[k];
    frames.length = depth;         // 얕아지면 상위 프레임 버림
    frames[depth - 1] = { file, line, func, depth };
  }
  return frames.filter(Boolean);
}

function render() {
  const [file, line, func, depth] = flow[i];
  if (file !== renderedFile) {
    renderFile(file, line);                 // 새 파일: 렌더하며 현재 라인을 cur로 표시
  } else {
    codeEl.querySelectorAll(".row.cur").forEach(r => r.classList.remove("cur"));
    const r = codeEl.querySelector('.row[data-no="' + line + '"]');
    if (r) r.classList.add("cur");
  }
  const cur = codeEl.querySelector(".row.cur");
  if (cur) cur.scrollIntoView({ block: "center" });   // 현재 라인 한 번만 중앙 정렬
  const frames = callStack(i);
  stackEl.innerHTML = "";
  frames.slice().reverse().forEach((f, idx) => {
    const el = document.createElement("div");
    el.className = "frame" + (idx === 0 ? " top" : "");
    const fn = document.createElement("div"); fn.className = "fn";
    fn.textContent = f.func + "()";          // <module>·<listcomp> 등 꺾쇠 이름 보존
    const loc = document.createElement("div"); loc.className = "loc";
    loc.textContent = shortPath(f.file) + ":" + f.line;
    el.appendChild(fn); el.appendChild(loc);
    stackEl.appendChild(el);
  });
  document.getElementById("fill").style.width = ((i + 1) / flow.length * 100) + "%";
  document.getElementById("pos").textContent =
    `스텝 ${(i + 1).toLocaleString()} / ${flow.length.toLocaleString()}  ·  ${func}()  ·  depth ${depth}`;
  document.getElementById("back").disabled = i === 0;
  document.getElementById("fwd").disabled = i === flow.length - 1;
}

function step(delta) {
  i = Math.max(0, Math.min(flow.length - 1, i + delta));
  render();
  if (i === flow.length - 1) stop();
}
function play() {
  if (timer) return stop();
  if (i === flow.length - 1) i = 0;
  document.getElementById("play").textContent = "⏸ 정지";
  const ms = +document.getElementById("speed").value;
  timer = setInterval(() => step(1), ms);
}
function stop() {
  clearInterval(timer); timer = null;
  document.getElementById("play").textContent = "▶ 재생";
}
document.getElementById("fwd").onclick = () => step(1);
document.getElementById("back").onclick = () => step(-1);
document.getElementById("play").onclick = play;
document.getElementById("speed").onchange = () => { if (timer) { stop(); play(); } };
document.addEventListener("keydown", (e) => {
  if (e.key === "ArrowRight") step(1);
  else if (e.key === "ArrowLeft") step(-1);
  else if (e.key === " ") { e.preventDefault(); play(); }
  else if (e.key === "Home") { i = 0; render(); }
});
render();
</script>
"""
