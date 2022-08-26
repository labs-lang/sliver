#!/usr/bin/env python3
# Rudimentary value analysis for LAbS specifications

from collections import namedtuple
from functools import reduce
from itertools import product

from ..app.cli import Args

from .parser import FILE


class Interval:
    def __init__(self, mn, mx=None):
        if mx is not None and mn > mx:
            raise ArithmeticError(f"Invalid interval [{mn}, {mx}]")
        self.min = mn
        self.max = mn if mx is None else mx

    def __hash__(self):
        return hash((self.min, self.max))

    def is_within(self, other):
        return (
            self != other and
            self.min >= other.min and
            self.max <= other.max)

    def overlaps(self, other):
        return (
            self == other or
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
        if isinstance(other, int):
            other = Interval(other)
        return self.min == other.min and self.max == other.max

    def __ne__(self, other: object) -> bool:
        return not (self == other)

    def __add__(self, other):
        if isinstance(other, int):
            other = Interval(other)
        return Interval(self.min + other.min, self.max + other.max)

    def __repr__(self):
        return f"[{self.min}, {self.max}]"

    def __neg__(self):
        return Interval(-self.max, -self.min)

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


class Stripes:
    """The stripes "domain"

    Stripes are merely sets of (non-partially ordered) intervals, i.e., no
    interval in the stripe may lie within another. We make no claim that they
    constitute a proper "abstract domain".
    They carry some resemblance to "donut" domains
    (Ghorbal et al., VMCAI 2012), although we allow multiple "holes".
    """
    def __init__(self, *args) -> None:
        self.stripes = self._prune(set(args))

    @staticmethod
    def _prune(stripes, prune_adjacent=False) -> frozenset:
        enter = True
        to_join = set()
        while enter or any(len(j) > 1 for j in to_join):
            enter = False
            to_join = set(tuple(
                b for b in stripes
                if a.overlaps(b) or (prune_adjacent and a.adjacent(b)))
                for a in stripes)
            joins = set(reduce(lambda a, b: a.join(b), j) for j in to_join)
            stripes |= joins
            subsets = set(
                a for a, b in product(stripes, stripes)
                if a.is_within(b))
            stripes -= subsets
        return frozenset(stripes)

    def join_adjacent(self):
        return Stripes(*self._prune(self.stripes, True))

    def __hash__(self):
        return hash(self.stripes)

    def __or__(self, other):
        return Stripes(*(self.stripes | other.stripes))

    def __repr__(self):
        return f"{{ {', '.join(str(x) for x in self.stripes)} }}"

    def _combine(self, other, fn):
        x = set(fn(a, b) for a, b in product(self.stripes, other.stripes))
        return self._prune(x)

    def __eq__(self, other):
        return self.stripes == other.stripes

    def __neg__(self):
        return Stripes(*self._prune(set(-x for x in self.stripes)))

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


def I(mn, mx=None):  # noqa: E741, E743
    return Interval(mn, mx)


def S(mn, mx=None):
    return Stripes(I(mn, mx))


def merge(s0, s1, State):
    result = {k: getattr(s0, k) for k in s0._fields}
    for k in s1._fields:
        if result[k] is None:
            result[k] = getattr(s1, k)
        elif getattr(s1, k) is not None:
            result[k] |= getattr(s1, k)
    return State(**result)


def make_init(info):
    """Get value analysis in the initial state"""
    stores = (info.lstig, info.e, *(a.iface for a in info.spawn.values()))
    s0 = {}
    for store in stores:
        for var in store.values():
            for id in range(info.spawn.num_agents()):
                vals = var.values(id)
                stripe = (
                    S(min(vals), max(vals))
                    if isinstance(vals, range)
                    else Stripes(*(I(x) for x in vals)))
                if var.name in s0:
                    s0[var.name] |= stripe
                else:
                    s0[var.name] = stripe

    State = namedtuple("State", s0.keys())
    s0 = State(**s0)

    return State, s0


def find(proc, filter):
    try:
        if filter(proc):
            yield proc.asList()
        elif not isinstance(proc, str):
            for x in proc:
                yield from find(x, filter)
    except TypeError:
        pass


def eval_expr(expr, s, externs):
    OPS = {
            "+": lambda x, y: x+y,
            "-": lambda x, y: x-y,
            "*": lambda x, y: x*y,
            "/": lambda x, y: x//y,
            "%": lambda x, y: x % y,
            "min": lambda x, y: x.Min(y),
            "max": lambda x, y: x.Max(y)
        }
    if expr == "#self":
        return externs["id"]
    elif isinstance(expr, int):
        return S(expr)
    elif isinstance(expr, str) and expr in s._fields:
        return getattr(s, expr)
    elif isinstance(expr, str):
        return externs[expr]
    elif isinstance(expr, list) and len(expr) == 2:
        # unary expressions
        if expr[0] == "-":
            return -eval_expr(expr[1], s, externs)
        elif expr[0] == "abs":
            return abs(eval_expr(expr[1], s, externs))
    elif isinstance(expr, list) and expr and expr[0] == "#array":
        # Do not care about array indexes
        eval_expr([expr[1], *expr[3:]], s, externs)
    elif isinstance(expr, list):
        recur_tail = (eval_expr(e, s, externs) for e in expr[1:])
        return reduce(OPS[expr[0]], recur_tail)
    else:
        raise ValueError("unexpected", expr)


def apply_assignment(asgn, s0, externs, State):
    s1 = {k: getattr(s0, k) for k in s0._fields}

    def get_varname(x):
        if isinstance(x, str):
            return x
        elif isinstance(x, list) and x[0] == "#array":
            return x[1]
        else:
            raise ValueError(x)

    def apply_single(var, expr):
        # print(f"Applying {var} <- {expr} to {s0}")
        s1[var] = eval_expr(expr, s0, externs)

    if isinstance(asgn[1], list) and asgn[1][0] == "list":
        for var, expr in zip(asgn[1][1:], asgn[2][1:]):
            apply_single(get_varname(var), expr)
    else:
        apply_single(get_varname(asgn[1]), asgn[2])
    return State(**s1)


def value_analysis(cli, info):
    State, s0 = make_init(info)
    externs = {
        "id": S(0, info.spawn.num_agents() - 1)
    }
    for ext in cli[Args.VALUES]:
        name, value = ext.split("=")
        externs["_" + name] = S(int(value))
    with open(cli.file) as f:
        ast = FILE.parseFile(f)

    # Extract all assignment statements from specification.
    assignments = []
    for a in ast.agents:
        behavior = [p for p in a.processes if p.name == "Behavior"][0]
        all_calls = set(
            x[1] for x in find(behavior.body, lambda proc: proc[0] == "#call")
        )
        all_calls.add("Behavior")
        for name in all_calls:
            lookup = [p for p in a.processes if p.name == name]
            p = lookup[0] if lookup else [
                p for p in ast.system.processes if p.name == name
            ][0]
            assignments.extend(find(
                p.body,
                lambda proc: (
                    isinstance(proc[0], str) and
                    proc[0].startswith("assign"))))

    # We use a chaos automaton of all assignments
    # to overapproximate the range of feasible values
    fixpoint = False
    old_states = set([s0])
    # TODO make analysis bound configurable
    for _ in range(100):
        new_states = set(
            apply_assignment(a, s, externs, State)
            for s in old_states for a in assignments)

        if new_states <= old_states:
            fixpoint = True
            break
        else:
            old_states |= new_states

    def mergeStates(s0, s1):
        return merge(s0, s1, State)

    s1 = reduce(mergeStates, old_states)
    s1 = State(**{
        x: getattr(s1, x).join_adjacent()
        for x in s1._fields
    })
    return s1, fixpoint


if __name__ == "__main__":
    pass

    # Just some code for testing
    # FNAME, d = (
    #     # "/Users/luca/git/labs/labs-examples/leader.labs",
    #     # {"values": ["n=4"]})
    #     # "/Users/luca/git/labs/labs-examples/philosophers.labs",
    #     # {"values": ["n=39"]})
    #     "/Users/luca/git/labs/labs-examples/boids-aw.labs",
    #     {"values": ["birds=3", "grid=5", "delta=5"]})
    # cli = CliArgs(FNAME, d)  # leader
    # print(cli)
    # b = Cadp(Path("."), cli)
    # info = b.get_info(parsed=True)
    # ranges, fixpoint = value_analysis(cli, info)
    # print(ranges, fixpoint)
