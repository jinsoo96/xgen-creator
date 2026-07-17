"""테스트 부트스트랩 — 실행 위치(cwd)·설치 여부와 무관하게 임포트가 되게 한다.

- 리포 루트를 sys.path에 넣어 `xgen_creator`를 어디서 돌려도 임포트 가능하게.
- tests 디렉터리를 넣어 테스트 간 헬퍼(`from test_docgen import ...`) 임포트가 되게.
pytest는 이 파일을 자동 로드한다. unittest는 리포 루트에서
`python -m unittest discover -s tests`로 실행한다(README 참조).
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
for _p in (_ROOT, _ROOT / "tests"):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)
