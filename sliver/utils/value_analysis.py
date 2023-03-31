#!/usr/bin/env python3
# Rudimentary value analysis for LAbS specifications

from collections import defaultdict, namedtuple
from functools import reduce
from itertools import permutations, product
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..app.cli import Args
from ..labsparse.labs_parser import Attr, NodeType, parse_to_dict
from ..labsparse.labs_ast import Expr, Node


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
        # if not self.stripes:
        #     return None
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
        # enter = True
        enter = len(stripes) > 1
        changed = True
        # print("Before prune", stripes)
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
        # print("After prune", stripes)
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
        return Stripes(*(self.stripes | other.stripes))

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


def merge(s0, s1, State):
    result = {k: getattr(s0, k) for k in s0._fields}
    for k in s1._fields:
        if result[k] is None:
            result[k] = getattr(s1, k)
        elif getattr(s1, k) is not None:
            result[k] |= getattr(s1, k)
    return State(**result)


def make_init(info, local_names):
    """Get value analysis in the initial state"""
    stores = (info.lstig, info.e, *(a.iface for a in info.spawn.values()))
    s0 = {}
    for store in stores:
        for var in store.values():
            for id_ in range(info.spawn.num_agents()):
                vals = var.values(id_)
                stripe = (
                    S(min(vals), max(vals))
                    if isinstance(vals, range)
                    else Stripes(*(I(x) for x in vals)))
                if var.name in s0:
                    s0[var.name] |= stripe
                else:
                    s0[var.name] = stripe

    names = [*local_names, *s0.keys()]
    State = namedtuple("State", names)
    for x in local_names:
        s0[x] = Stripes(I(0))
    s0 = State(**s0)

    return State, s0


def eval_expr(expr, s, externs) -> Stripes:
    OPS = {
        "+": lambda x, y: x+y,
        "-": lambda x, y: x-y,
        "*": lambda x, y: x*y,
        "/": lambda x, y: x//y,
        "%": lambda x, y: x % y,
        "min": lambda x, y: x.Min(y),
        "max": lambda x, y: x.Max(y),
        "and": lambda x, y: x.And(y),
        "or": lambda x, y: x.Or(y)
    }
    CMP = {
        ">": lambda x, y: x > y,
        "<": lambda x, y: x < y,
        ">=": lambda x, y: x >= y,
        "<=": lambda x, y: x <= y,
        "=": lambda x, y: x.equality(y),
        "!=": lambda x, y: not x.equality(y),
    }
    UNARY_OPS = {
        "unary-minus": lambda x: -x,
        "unary-not": lambda x: not x,
        "abs": abs
    }

    if expr.matches(NodeType.LITERAL):
        return S(expr[Attr.VALUE])
    elif expr.matches(NodeType.REF) and expr[Attr.NAME] in s._fields:
        return getattr(s, expr[Attr.NAME])
    elif expr.matches(NodeType.REF) or expr.matches(NodeType.REF_EXT):
        return externs[expr[Attr.NAME]]
    elif expr.matches(NodeType.BUILTIN) and expr[Attr.NAME] in UNARY_OPS:
        return UNARY_OPS[expr[Attr.NAME]](eval_expr(expr[Attr.OPERANDS][0], s, externs))  # noqa: E501
    elif (expr.matches(NodeType.EXPR) or expr.matches(NodeType.BUILTIN)
            and expr[Attr.NAME] in OPS):
        operands = (eval_expr(e, s, externs) for e in expr[Attr.OPERANDS])
        return reduce(OPS[expr[Attr.NAME]], operands)

    elif expr.matches(NodeType.COMPARISON) and expr[Attr.NAME] in CMP:
        operands = [eval_expr(e, s, externs) for e in expr[Attr.OPERANDS]]
        return reduce(CMP[expr[Attr.NAME]], operands)
    elif expr.matches(NodeType.IF):
        condition = eval_expr(expr[Attr.CONDITION], s, externs)
        if 1 in condition and 0 in condition:
            return (
                eval_expr(expr[Attr.THEN], s, externs) |
                eval_expr(expr[Attr.ELSE], s, externs))
        elif 1 in condition:
            return eval_expr(expr[Attr.THEN], s, externs)
        elif 0 in condition:
            return eval_expr(expr[Attr.ELSE], s, externs)
        else:
            raise ValueError(expr.as_labs())
    elif expr.matches(NodeType.QFORMULA):
        # TODO can we recover some information?
        return S(0, 1)
    else:
        raise NotImplementedError(expr.as_labs())


def apply_guard(guards, stmt, s0, externs, State):
    g = guards.get(stmt)
    if g is None:
        return s0
    new_guard = Expr("", "", "", {})
    new_guard[Attr.SYNTHETIC] = True
    new_guard[Attr.NAME] = "and"
    new_guard[Attr.OPERANDS] = g
    eval_whole = eval_expr(new_guard, s0, externs)
    if 1 in eval_whole and 0 not in eval_whole:
        # Guard always holds
        return s0
    elif 0 in eval_whole and 1 not in eval_whole:
        # Guard never holds
        return None
    # If we are here we must filter s0
    # TODO: do recursive bisection rather than enumeration
    s1 = None
    for s in enumerate(s0, State):
        if 1 in eval_expr(new_guard, s, externs):
            s1 = s if s1 is None else merge(s, s1, State)
    return s1


def apply_assignment(asgn, s0, externs, guards, State):
    # If asgn is guarded, reduce s0 to the states where the guard holds
    s0 = apply_guard(guards, asgn, s0, externs, State)
    # The guard did not hold anywhere, so we cannot interpret asgn
    if s0 is None:
        return None
    s1 = {k: getattr(s0, k) for k in s0._fields}
    for lhs, rhs in zip(asgn[Attr.LHS], asgn[Attr.RHS]):
        s1[lhs[Attr.NAME]] = eval_expr(rhs, s0, externs)
    return State(**s1)


def apply_block(blk, s0, externs, guards, State):
    # If blk is guarded, reduce s0 to the states where the guard holds
    s0 = apply_guard(guards, blk, s0, externs, State)
    # The guard did not hold anywhere, so we cannot interpret blk
    if s0 is None:
        return None
    for asgn in blk[Attr.BODY]:
        s1 = apply_assignment(asgn, s0, externs, guards, State)
        s0 = s1
    return s1


def value_analysis(cli, info):
    externs = {
        "id": S(0, info.spawn.num_agents() - 1)
    }
    for ext in cli[Args.VALUES]:
        name, value = ext.split("=")
        externs["_" + name] = S(int(value))
    ast = parse_to_dict(cli.file)

    # Extract all assignment, blocks, and guards from specification.
    # (That are reachable from the agents' behaviour)
    assignments = []
    blocks = []
    guards = []
    for a in ast.agents:
        behavior = [
            p for p in a[Attr.PROCDEFS] if p[Attr.NAME] == "Behavior"][0]
        visited_calls = set(("Behavior", ))
        frontier = [behavior]
        while frontier:
            node = frontier.pop()
            assignments.extend(
                n for n in node.walk([NodeType.BLOCK])
                if n.matches(NodeType.ASSIGN))
            blocks.extend(n for n in node.walk() if n.matches(NodeType.BLOCK))
            guards.extend(
                (a, n) for n in node.walk()
                if n.matches(NodeType.GUARDED))
            calls = (
                n[Attr.NAME] for n in node.walk()
                if n.matches(NodeType.CALL)
                and n[Attr.NAME] not in visited_calls)
            for c in calls:
                visited_calls.add(c)
                p = a.try_lookup(c) or ast["system"].try_lookup(c)
                if p is None:
                    raise KeyError(c)
                frontier.append(p)

    # Map assignments/blocks to their guards
    def get_guarded_assignments(node, agent):
        if node == "Skip":
            return set()
        elif node.matches(NodeType.COMPOSITION):
            if node[Attr.NAME] == "seq":
                return get_guarded_assignments(node[Attr.OPERANDS][0], agent)
            else:
                return set.union(*(
                    get_guarded_assignments(n, agent)
                    for n in node[Attr.OPERANDS]))
        elif node.matches(NodeType.ASSIGN) or node.matches(NodeType.BLOCK):
            return set((node, ))
        elif node.matches(NodeType.GUARDED):
            return get_guarded_assignments(node[Attr.BODY], agent)
        elif node.matches(NodeType.CALL):
            name = node[Attr.NAME]
            p = agent.try_lookup(name) or ast["system"].try_lookup(name)
            if p is None:
                raise KeyError(name)
            return get_guarded_assignments(p[Attr.BODY], agent)
        else:
            # for debug
            raise ValueError(node.AS_NODETYPE)

    guard_map = defaultdict(list)
    for (agent, g) in guards:
        for x in get_guarded_assignments(g[Attr.BODY], agent):
            guard_map[x].append(g[Attr.CONDITION])

    # Retrieve local variable names and build initial state
    local_names = [
        lhs[Attr.NAME]
        for blk in blocks
        for n in blk[Attr.BODY]
        for lhs in n[Attr.LHS]
        if n[Attr.TYPE] == "local"]
    State, s0 = make_init(info, local_names)

    def entailed_by(s1, s2):
        if s1 == s2:
            return False
        return all(
            getattr(s1, var).is_within(getattr(s2, var))
            for var in s1._fields)

    def parallel_find_entailed(set1, set2, exc):
        def find_entailed_1(s, states):
            for s1 in states:
                if entailed_by(s1, s):
                    return s1
            return None
        futures = [exc.submit(lambda: find_entailed_1(s, set2)) for s in set1]
        for f in as_completed(futures):
            s = f.result()
            if s is not None:
                yield s

    # We use a chaos automaton of all assignments/blocks
    # to overapproximate the range of feasible values
    fixpoint = False
    old_states = set([s0])
    # TODO make analysis bound configurable

    with ThreadPoolExecutor() as exc:
        for i in range(20):
            # Prune away old states entailed by others
            old_states -= set(parallel_find_entailed(old_states, old_states, exc))  # noqa: E501

            futures = []
            common_args = (externs, guard_map, State)
            futures = [
                exc.submit(apply_assignment, a, s, *common_args)
                for a, s in product(assignments, old_states)]
            futures.extend(
                exc.submit(apply_block, blk, s, *common_args)
                for blk, s in product(blocks, old_states))

            new_states = (f.result() for f in as_completed(futures))
            new_states = set(x for x in new_states if x is not None)
            new_states -= set(parallel_find_entailed(new_states, new_states, exc))  # noqa: E501

            if new_states <= old_states:
                fixpoint = True
                break
            else:
                old_states |= new_states

    def mergeStates(s0, s1):
        return merge(s0, s1, State)

    # print(*old_states, sep="\n")
    s1 = reduce(mergeStates, old_states)
    s1 = State(**{
        x: getattr(s1, x).join_adjacent()
        for x in s1._fields
    })
    return s1, fixpoint


if __name__ == "__main__":
    pass
