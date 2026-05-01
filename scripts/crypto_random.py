from __future__ import annotations

import secrets
from typing import Iterable, Sequence, TypeVar

T = TypeVar("T")
SYSTEM_RANDOM = secrets.SystemRandom()


def rand_int(min_value: int, max_value: int) -> int:
    if max_value < min_value:
        raise ValueError("max_value must be >= min_value")
    return min_value + secrets.randbelow(max_value - min_value + 1)


def choice(items: Sequence[T]) -> T:
    if not items:
        raise ValueError("cannot choose from an empty sequence")
    return secrets.choice(items)


def pick_unique(min_value: int, max_value: int, count: int, sort_result: bool = True) -> list[int]:
    pool = list(range(min_value, max_value + 1))
    if count > len(pool):
        raise ValueError("count exceeds unique pool size")
    selected: list[int] = []
    for _ in range(count):
        index = secrets.randbelow(len(pool))
        selected.append(pool.pop(index))
    return sorted(selected) if sort_result else selected


def pick_digits(count: int, min_value: int = 0, max_value: int = 9) -> list[int]:
    return [rand_int(min_value, max_value) for _ in range(count)]


def weighted_none(_: Iterable[T]) -> None:
    return None
