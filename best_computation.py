import math
from typing import Optional


def _try_power(base: int, exp: int, bound: int, max_exponent: int):
    if exp < 0 or exp > max_exponent:
        return None
    if base == 0:
        return None if exp == 0 else 0
    if abs(base) == 1:
        return base ** exp
    if exp == 0:
        return 1
    if exp * math.log2(abs(base)) > math.log2(bound + 1) + 1:
        return None
    result = base ** exp
    return result if abs(result) <= bound else None


def _combine(x: int, y: int, bound: int, max_exponent: int):
    results = []

    results.append(("+", x, y, x + y))
    results.append(("*", x, y, x * y))
    results.append(("-", x, y, x - y))
    if x != y:
        results.append(("-", y, x, y - x))

    if y != 0 and x % y == 0:
        results.append(("/", x, y, x // y))
    if x != 0 and y % x == 0 and x != y:
        results.append(("/", y, x, y // x))

    p1 = _try_power(x, y, bound, max_exponent)
    if p1 is not None:
        results.append(("^", x, y, p1))
    if x != y:
        p2 = _try_power(y, x, bound, max_exponent)
        if p2 is not None:
            results.append(("^", y, x, p2))

    return [(op, a, b, w) for op, a, b, w in results if abs(w) <= bound]


def best_computation(a: int, b: int, bound: Optional[int] = None,
                      max_exponent: int = 20, max_cost: int = 8,
                      max_values: int = 400_000):
    if a < 1:
        raise ValueError("a doit être >= 1")

    if bound is None:
        bound = max(a, abs(b)) * 4 + 10

    parent: dict[int, tuple] = {}
    cost_of: dict[int, int] = {}
    levels: list[list[int]] = [list(range(1, a + 1))]

    for v in levels[0]:
        cost_of[v] = 0

    if b in cost_of:
        return 0, _build_expression(parent, b)

    k = 1
    total_values = len(levels[0])
    while k <= max_cost and total_values <= max_values:
        new_values: dict[int, tuple] = {}

        for i in range((k - 1) // 2 + 1):
            j = k - 1 - i
            if j < i:
                continue
            for x in levels[i]:
                ys = levels[j] if j != i else levels[i]
                for y in ys:
                    if j == i and y < x:
                        continue
                    for op, l, r, w in _combine(x, y, bound, max_exponent):
                        if w in cost_of or w in new_values:
                            continue
                        new_values[w] = (op, l, r)
                        if w == b:
                            parent.update(new_values)
                            for val, info in new_values.items():
                                cost_of[val] = k
                            return k, _build_expression(parent, b)

        for val, info in new_values.items():
            cost_of[val] = k
            parent[val] = info
        levels.append(list(new_values.keys()))
        total_values += len(new_values)
        k += 1

    return None, None


def _build_expression(parent: dict, value: int) -> str:
    if value not in parent:
        return str(value)
    op, left, right = parent[value]
    return f"({_build_expression(parent, left)} {op} {_build_expression(parent, right)})"


if __name__ == "__main__":
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    a, b = int(sys.argv[1]), int(sys.argv[2])
    cost, expr = best_computation(a, b)
    if cost is None:
        print(f"Impossible de calculer {b} avec les entiers 1..{a} dans les limites données.")
    else:
        print(f"Coût minimal : {cost}")
        print(f"Expression   : {expr} = {b}")
