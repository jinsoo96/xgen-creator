"""트레이서 테스트 대상 — 이 파일의 라인 번호가 단언에 쓰인다(구조 변경 주의)."""


def helper(n):
    total = 0
    for i in range(n):
        total += i
    return total


def untouched():
    marker = "실행되지 않는 함수"
    return marker


def _raiser():
    raise ValueError("boom")


def with_exception():
    """예외 unwind 후 콜스택 깊이가 부풀지 않아야 함 — 회귀 대상."""
    try:  # noqa: SIM105 — 예외 unwind 프레임을 실제로 만들어 depth 검증
        _raiser()
    except ValueError:
        pass
    after = 1  # 이 라인은 with_exception 깊이여야(raiser 깊이 아님)
    return after


def outer_after_exc():
    a = 0
    b = with_exception()   # 이 라인들은 outer 깊이 — 예외 후 부풀면 안 됨
    return a + b
