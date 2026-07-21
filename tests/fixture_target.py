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


def _counter(n):
    i = 0
    while i < n:
        yield i            # yield로 suspend — caller가 올바른 깊이로 보여야
        i += 1


def gen_consumer():
    total = 0
    for v in _counter(3):  # 이 라인들은 gen_consumer 깊이여야(제너레이터 깊이 아님)
        total += v
    return total


async def _afetch(x):
    await __import__("asyncio").sleep(0)  # 진짜 suspend/resume 지점
    return x + 1


async def _ahandler():
    acc = 0
    for i in range(3):
        acc += await _afetch(i)   # await suspend 후 깊이 일관돼야
    return acc


def async_consumer():
    return __import__("asyncio").run(_ahandler())
