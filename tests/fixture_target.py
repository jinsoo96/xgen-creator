"""트레이서 테스트 대상 — 이 파일의 라인 번호가 단언에 쓰인다(구조 변경 주의)."""


def helper(n):
    total = 0
    for i in range(n):
        total += i
    return total


def untouched():
    marker = "실행되지 않는 함수"
    return marker
