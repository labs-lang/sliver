#!/usr/bin/env python3
from itertools import product, permutations


class Interval:
    def __init__(self, mn, mx=None):
        if not isinstance(mn, int):
            print(mn, type(mn))
        if mx is not None and mn > mx:
            raise ArithmeticError(f"Invalid interval [{mn}, {mx}]")
        self.min = mn
        self.max = mn if mx is None else mx

    def __hash__(self):
        return hash((self.min, self.max))

    def __contains__(self, n):
        return self.min <= n <= self.max

    def __iter__(self):
        yield from range(self.min, self.max)
        yield self.max

    def is_within(self, other):
        return (
            self.min >= other.min and
            self.max <= other.max)

    def overlaps(self, other):
        return (
            self.is_within(other) or
            other.is_within(self) or
            other.min <= self.min <= other.max or
            other.min <= self.max <= other.max
        )

    def adjacent(self, other):
        return not self.overlaps(other) and (
            self.max == other.min - 1 or
            self.min == other.max + 1)

    def join(self, other):
        return Interval(min(self.min, other.min), max(self.max, other.max))

    def __eq__(self, other):
        return self.min == other.min and self.max == other.max

    # We cannot use __eq__ because it messes up sets
    def equality(self, other):
        if isinstance(other, int):
            other = Interval(other)
        if self.min > other.max or self.max < other.min:
            return I(0)
        elif self.min == self.max == other.min == other.max:
            return I(1)
        else:
            return I(0, 1)

    def __ne__(self, other: object) -> bool:
        eq = self.equality(other)
        if eq.min == eq.max:
            return I(int(not bool(eq.min)))
        else:
            return eq

    def __add__(self, other):
        if isinstance(other, int):
            other = Interval(other)
        return Interval(self.min + other.min, self.max + other.max)

    def __repr__(self):
        return f"[{self.min}, {self.max}]"

    def __neg__(self):
        return Interval(-self.max, -self.min)

    def __invert__(self):
        if 1 in self and 0 not in self:
            return I(0)
        elif 0 in self and 1 not in self:
            return I(1)
        else:
            return I(0, 1)

    def __sub__(self, other):
        return self + (-other)

    def __mod__(self, other):
        if isinstance(other, int):
            other = Interval(other)
        values = sorted(
            num % mod
            for num in range(self.min, self.max + 1)
            for mod in (other.min, other.max) if other != 0
        )
        if not values:
            raise ArithmeticError(f"Empty interval on {self} % {other}")
        return Interval(values[0], values[-1])

    def __mul__(self, other):
        if isinstance(other, int):
            other = Interval(other)
        values = sorted((
            self.min * other.min,
            self.min * other.max,
            self.max * other.min,
            self.max * other.max))
        return Interval(values[0], values[-1])

    def __floordiv__(self, other):
        if isinstance(other, int):
            other = Interval(other)

        values = sorted(
            num // den
            for num in (self.min, self.max)
            for den in (other.min, other.max) if den != 0
        )
        if not values:
            raise ArithmeticError(f"Empty interval on {self} // {other}")
        return Interval(values[0], values[-1])

    def __abs__(self):
        amin, amax = abs(self.min), abs(self.max)
        return Interval(min(amin, amax), max(amin, amax))

    def Min(self, other):
        return Interval(min(self.min, other.min), min(self.max, other.max))

    def Max(self, other):
        return Interval(max(self.min, other.min), max(self.max, other.max))

    def abstract(self, *values):
        intervals = set(I(val) for val in values)
        return Stripes(*self._prune(intervals, True))


def enumerate(state, State):
    for p in product(*(state[i] for i in range(len(state)))):
        yield State._make((S(x) for x in p))


class Stripes:
    """The stripes "domain"

    Stripes are merely sets of (non-partially ordered) intervals, i.e., no
    interval in the stripe may lie within another. We make no claim that they
    constitute a proper "abstract domain".
    They carry some resemblance to "donut" domains
    (Ghorbal et al., VMCAI 2012), although we allow multiple "holes".
    """

    def __init__(self, *args) -> None:
        self.stripes = frozenset(args)

    def extrema(self):
        return (
            min(i.min for i in self.stripes),
            max(i.max for i in self.stripes))

    def bisect(self):
        if len(self.stripes) > 1:
            lst = list(self.stripes)
            mid = len(lst) // 2
            return Stripes(*lst[:mid]), Stripes(*lst[mid:])
        else:
            st = next(iter(self.stripes))
            if st.min != st.max:
                mid = (st.min + st.max) // 2
                i0, i1 = I(st.min, mid), I(mid+1, st.max)
                return Stripes(i0), Stripes(i1)
            else:
                return None, None

    @staticmethod
    def _prune(stripes: set, prune_adjacent=False) -> frozenset:
        enter = len(stripes) > 1
        changed = True
        while enter or changed:
            enter = False
            joins = set(
                a.join(b) for a, b in permutations(stripes, 2)
                if a.overlaps(b) or (a.adjacent(b) and prune_adjacent))
            stripes |= joins
            subsets = set(
                a for a, b in product(stripes, stripes)
                if a.is_within(b) and not a == b)
            stripes -= subsets
            changed = len(joins) + len(subsets) > 0
        return frozenset(stripes)

    def join_adjacent(self):
        return Stripes(*self._prune(self.stripes, True))

    def __contains__(self, n):
        return any(n in i for i in self.stripes)

    def __iter__(self):
        for x in self.stripes:
            yield from x

    def __hash__(self):
        return hash(self.stripes)

    def __or__(self, other):
        return Stripes(*self._prune(self.stripes | other.stripes))

    def __repr__(self):
        return f"{{ {', '.join(str(x) for x in self.stripes)} }}"

    def _combine(self, other, fn):
        x = set(fn(a, b) for a, b in product(self.stripes, other.stripes))
        return self._prune(x)

    # We cannot use __eq__ because it messes up sets
    def equality(self, other):
        return Stripes(*self._combine(other, lambda a, b: a.equality(b)))

    def is_within(self, other, strict=False):
        if self == other and not strict:
            return True
        for x in self.stripes:
            if not any(x.is_within(y) for y in other.stripes):
                return False
        return True

    def __eq__(self, other):
        return self.stripes == other.stripes

    def __lt__(self, other):
        my_min, my_max = self.extrema()
        other_min, other_max = other.extrema()
        # Degenerate case: self is a single integer
        if my_min == my_max:
            if other_min == other_max:
                return Stripes(I(int(my_min < other_min)))
            elif my_min >= other_max:
                return NO
            elif my_max < other_min:
                return YES
            else:
                return MAYBE
        elif other_min == other_max:
            if my_min >= other_min:
                return NO
            elif my_max < other_min:
                return YES
            else:
                return MAYBE
        elif my_max < other_min:
            return YES
        elif my_min > other_max:
            return NO
        else:
            return MAYBE

    def __gt__(self, other):
        return other < self

    def __ge__(self, other):
        return self.equality(other).Or(self > other)

    def __le__(self, other):
        return self.equality(other).Or(self < other)

    def __neg__(self):
        return Stripes(*self._prune(set(-x for x in self.stripes)))

    def __invert__(self):
        return Stripes(*self._prune(set(~x for x in self.stripes)))

    def __abs__(self):
        return Stripes(*self._prune(set(abs(x) for x in self.stripes)))

    def __add__(self, other):
        return Stripes(*self._combine(other, lambda a, b: a + b))

    def __mod__(self, other):
        return Stripes(*self._combine(other, lambda a, b: a % b))

    def __mul__(self, other):
        return Stripes(*self._combine(other, lambda a, b: a * b))

    def __sub__(self, other):
        return Stripes(*self._combine(other, lambda a, b: a - b))

    def Min(self, other):
        return Stripes(*self._combine(other, lambda a, b: a.Min(b)))

    def Max(self, other):
        return Stripes(*self._combine(other, lambda a, b: a.Max(b)))

    def Range(self, other):
        # Evaluates [self..other] (note that range is exclusive)
        mins = (i.min for i in self.stripes)
        other_minus_1 = other - YES
        maxs = (i.max for i in other_minus_1.stripes)
        stripes = set(I(mn, mx) for mn, mx in product(mins, maxs) if mx > mn)
        if len(stripes) == 0:
            raise ValueError(f"[{self}..{other}] is an empty range")
        return Stripes(*self._prune(stripes))

    def And(self, other):
        if 0 in self or 0 in other:
            if 1 in self and 1 in other:
                return MAYBE
            else:
                return NO
        else:
            return YES

    def Or(self, other):
        my_min, my_max = self.extrema()
        other_min, other_max = other.extrema()
        if my_min == my_max == other_min == other_max == 0:
            return NO
        elif 0 not in self or 0 not in other:
            return YES
        else:
            return MAYBE


def I(mn, mx=None):  # noqa: E741, E743
    return Interval(mn, mx)


def S(mn, mx=None):
    return Stripes(I(mn, mx))


YES = S(1)
NO = S(0)
MAYBE = S(0, 1)
