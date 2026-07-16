"""`creator trace run examples/demo_traced_script.py` 데모 — 돌아간 라인만 건져진다."""


def classify(n):
    if n < 0:
        return "음수"
    if n % 2 == 0:
        return "짝수"
    return "홀수"


def unused_branch():
    return "이 함수는 실행되지 않아 슬라이스에 나오지 않는다"


if __name__ == "__main__":
    for value in (4, 7):
        print(value, classify(value))
