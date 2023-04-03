#!/usr/bin/env python3
from itertools import product, permutations


class Sign:
    def __init__(self, minus=False, plus=False, zero=False):
        self.minus = minus
        self.plus = plus
        self.zero = zero

    def __repr__(self):
        if self.minus and self.plus and self.zero:
            return "<T>"
        else:
            return f"<{'-' if self.minus else ''}{'0' if self.zero else ''}{'+' if self.plus else ''}>"  # noqa: E501

    def __hash__(self) -> int:
        return hash((self.minus, self.plus, self.zero))

    def __contains__(self, n):
        if n < 0:
            return self.minus
        elif n == 0:
            return self.zero
        else:
            return self.plus

    def __iter__(self):
        raise NotImplementedError()

    def bisect(self):
        if self._is_zero() or self._is_positive() or self._is_negative():
            return None, None
        if self.minus and self.plus and self.zero:
            return Sign.NEG, Sign.MAYBE
        if self.minus and self.plus:
            return Sign.NEG, Sign.YES
        if self.minus and self.zero:
            return Sign.NEG, Sign.NO
        if self.plus and self.zero:
            return Sign.NO, Sign.YES
        raise ValueError("This should be unreachable")

    @staticmethod
    def abstract(*values):
        # copy just in case vals is a lazy iterable
        vals = [*values]
        return Sign(
            minus=any(x < 0 for x in vals),
            plus=any(x > 0 for x in vals),
            zero=any(x == 0 for x in vals))

    @staticmethod
    def abstract_range(rng):
        if not isinstance(rng, range):
            raise ValueError(f"{rng} is not a range")
        return Sign(
            minus=min(rng) < 0,
            plus=max(rng) > 0,
            zero=min(rng) * max(rng) <= 0)

    def is_within(self, other):
        return all((
            (not self.minus) or other.minus,
            (not self.plus) or other.plus,
            (not self.zero) or other.zero))

    def overlaps(self, other):
        return any((
            self.is_within(other),
            other.is_within(self),
            self.zero and other.zero))

    def adjacent(self, other):
        return not self.overlaps(other) and self.zero and other.zero

    def __eq__(self, other):
        return all((
            self.minus == other.minus,
            self.plus == other.plus,
            self.zero == other.zero))

    def __lt__(self, other):
        if other.plus:
            return Sign.MAYBE if self.plus else Sign.YES
        if other.zero:
            return Sign.MAYBE if self.zero else Sign.YES
        # other is <->
        return Sign.MAYBE if self.minus else Sign.NO

    def __le__(self, other):
        return self.equality(other) or self < other

    def __gt__(self, other):
        return other < self

    def __ge__(self, other):
        return self.equality(other) or self > other

    def _is_zero(self):
        return self.zero and not self.plus and not self.minus

    def _is_positive(self):
        return self.plus and not self.zero and not self.minus

    def _is_negative(self):
        return self.minus and not self.zero and not self.plus

    def equality(self, other):
        if self._is_zero() and other._is_zero():
            return Sign.YES
        elif self.overlaps(other):
            return Sign.MAYBE
        else:
            return Sign.NO

    def join_adjacent(self):
        return self

    def __ne__(self, other):
        return ~self.equality(other)

    def __neg__(self):
        return Sign(
            minus=self.plus,
            plus=self.minus,
            zero=self.zero)

    def __invert__(self):
        if self == Sign.YES:
            return Sign.NO
        elif self == Sign.NO:
            return Sign.YES
        else:
            return Sign.MAYBE

    def __or__(self, other):
        return Sign(
            minus=self.minus or other.minus,
            plus=self.plus or other.plus,
            zero=self.zero or other.zero)

    def __add__(self, other):
        if self._is_zero():
            return other
        if other._is_zero():
            return self
        return Sign(
            minus=(self.minus or other.minus),
            plus=(self.plus or other.plus),
            zero=(self.plus and other.minus) or (self.minus and other.plus))

    def __sub__(self, other):
        return self + (-other)

    def __mul__(self, other):
        if self._is_zero() or other._is_zero():
            return Sign.NO
        return Sign(
            plus=(self.plus and other.plus) or (self.minus and other.minus),
            minus=(self.plus and other.minus) or (self.minus and other.plus),
            zero=self.zero or other.zero)

    def __mod__(self, _):
        return self if self._is_zero() else Sign.MAYBE

    def __abs__(self):
        return self if self._is_zero() else Sign.MAYBE

    def Min(self, other):
        if self.minus or other.minus:
            return Sign.NEG
        # both self and other are <0+>
        if self.zero or other.zero:
            return Sign.NO
        # both self and other are <+>
        return Sign.YES

    def Max(self, other):
        if self.plus or other.plus:
            return Sign.YES
        # both self and other are <-0>
        if self.zero or other.zero:
            return Sign.NO
        # both self and other are <->
        return Sign.NEG

    def Or(self, other):
        if self._is_positive() or other._is_positive():
            return Sign.YES
        if self._is_zero() and other._is_zero():
            return Sign.NO
        return Sign.MAYBE

    def And(self, other):
        if self._is_positive() and other._is_positive():
            return Sign.YES
        if self._is_zero() and other._is_zero():
            return Sign.NO
        return Sign.MAYBE

    def Range(self, other):
        minus = self.minus or other.minus
        plus = self.plus or other.plus
        zero = self.zero or other.zero or (plus and minus)
        return Sign(
            minus=minus,
            plus=plus,
            zero=zero)


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
    def abstract(*values):
        intervals = set(I(val) for val in values)
        return Stripes(*Stripes._prune(intervals, True))

    @staticmethod
    def abstract_range(rng):
        if not isinstance(rng, range):
            raise ValueError(f"{rng} is not a range")
        return S(min(rng), max(rng))

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
                return self.NO
            elif my_max < other_min:
                return self.YES
            else:
                return self.MAYBE
        elif other_min == other_max:
            if my_min >= other_min:
                return self.NO
            elif my_max < other_min:
                return self.YES
            else:
                return self.MAYBE
        elif my_max < other_min:
            return self.YES
        elif my_min > other_max:
            return self.NO
        else:
            return self.MAYBE

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
        other_minus_1 = other - self.YES
        maxs = (i.max for i in other_minus_1.stripes)
        stripes = set(I(mn, mx) for mn, mx in product(mins, maxs) if mx > mn)
        if len(stripes) == 0:
            raise ValueError(f"[{self}..{other}] is an empty range")
        return Stripes(*self._prune(stripes))

    def And(self, other):
        if 0 in self or 0 in other:
            if 1 in self and 1 in other:
                return self.MAYBE
            else:
                return self.NO
        else:
            return self.YES

    def Or(self, other):
        my_min, my_max = self.extrema()
        other_min, other_max = other.extrema()
        if my_min == my_max == other_min == other_max == 0:
            return self.NO
        elif 0 not in self or 0 not in other:
            return self.YES
        else:
            return self.MAYBE


def I(mn, mx=None):  # noqa: E741, E743
    return Interval(mn, mx)


def S(mn, mx=None):
    return Stripes(I(mn, mx))


Stripes.YES = S(1)
Stripes.NO = S(0)
Stripes.MAYBE = S(0, 1)
