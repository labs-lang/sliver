#!/usr/bin/env python3
# Rudimentary value analysis for LAbS specifications

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache, reduce
from itertools import product

import jq
import sympy
from pyrsistent import pmap
from sympy.core.relational import Relational
import z3

from sliver.analysis.domains import Stripes

from ..app.cli import Args


def merge(s0, s1):
    result = {**s0}
    for k in s1:
        if result[k] is None:
            result[k] = s1[k]
        elif s1[k] is not None:
            result[k] |= s1[k]
    return pmap(result)


def entailed_by(s1, states):
    for s2 in states:
        if s1 == s2:
            continue
        if not set(s1.keys()) <= set(s2.keys()):
            continue
        if all(s1[var].is_within(s2[var]) for var in s1):
            return True
    return False


def json2sympy(sym, obj):
    if isinstance(obj, int) or isinstance(obj, bool):
        return obj
    if obj == "id":
        return sym["id"]
    if "IfElse" in obj:
        return sympy.Piecewise(
            (json2sympy(sym, obj["IfTrue"]), sympy.Or(json2sympy(sym, obj["IfElse"]))),  # noqa: E501
            (json2sympy(sym, obj["IfFalse"]), True))
    if "Op" in obj:
        terms = [json2sympy(sym, t) for t in obj["Terms"]]
        if obj["Op"] in ("and", "or"):
            if len(terms) == 1:
                return terms
            by_lhs = defaultdict(list)
            for t in terms:
                if isinstance(t, Relational):
                    by_lhs[t.lhs].append(t)
            for lhs in by_lhs:
                by_lhs[lhs] = reduce(
                    lambda x, y: x & y if obj["Op"] == "and" else x | y,
                    by_lhs[lhs])  # noqa: E501
                return list(by_lhs.values())
        elif obj["Op"] == "or":
            return reduce(lambda x, y: x | y, terms)
        elif obj["Op"] == "not":
            return ~terms[0]
        elif obj["Op"] == "+":
            return reduce(lambda x, y: x + y, terms)
        elif obj["Op"] == "-":
            return reduce(lambda x, y: x - y, terms)
        elif obj["Op"] == "*":
            return reduce(lambda x, y: x * y, terms)
        elif obj["Op"] in ("==", "!=", ">", "<", ">=", "<="):
            return Relational(terms[0], terms[1], obj["Op"])
    elif "Var" in obj:
        var = obj["Var"]
        while "Item1" in var:
            var = var["Item1"]
        offset = obj.get("Offset")
        offset = f"[][{offset}]" if offset is not None else ""
        of = obj["Var"].get("Item2")
        var = f"{var["Name"]}{offset}{f'@{of}' if of is not None else ''}"
        return sympy.symbols(var)
    else:
        raise NotImplementedError(f"sym2py {obj}")


def json2z3(obj, info=None):
    def recurse(o):
        return json2z3(o, info)
    if isinstance(obj, int) or isinstance(obj, bool):
        return obj
    if obj == "id":
        return z3.Int("id")
    if "IdOfAgent" in obj:
        if isinstance(obj["IdOfAgent"], int):
            return z3.IntVal(obj["IdOfAgent"])
        return z3.Int(f"id@{obj['IdOfAgent']}")
    if "IfElse" in obj:
        return z3.If(
            recurse(obj["IfElse"]),
            recurse(obj["IfTrue"]),
            recurse(obj["IfFalse"]))  # noqa: E501
    if "Op" in obj:
        terms = [recurse(t) for t in obj["Terms"]]
        if obj["Op"] in ("and", "or"):
            if len(terms) == 0:
                return z3.BoolVal(obj["Op"] == "and")
            if len(terms) == 1:
                return terms[0]
            return z3.And(terms) if obj["Op"] == "and" else z3.Or(terms)
        elif obj["Op"] == "not":
            return ~terms[0]
        elif obj["Op"] == "+":
            return reduce(lambda x, y: x + y, terms)
        elif obj["Op"] == "-":
            return reduce(lambda x, y: x - y, terms)
        elif obj["Op"] == "*":
            return reduce(lambda x, y: x * y, terms)
        elif obj["Op"] == "==":
            return terms[0] == terms[1]
        elif obj["Op"] == "!=":
            return terms[0] != terms[1]
        elif obj["Op"] == ">":
            return terms[0] > terms[1]
        elif obj["Op"] == "<":
            return terms[0] < terms[1]
        elif obj["Op"] == ">=":
            return terms[0] >= terms[1]
        elif obj["Op"] == "<=":
            return terms[0] <= terms[1]
    elif "Var" in obj:
        var = obj["Var"]
        while "Item1" in var:
            var = var["Item1"]
        offset = obj.get("Offset")
        of = obj["Var"].get("Item2")
        if info is not None:
            var_info = info.lookup_var(var["Name"])
            if not isinstance(offset or 0, int):
                raise ValueError(f"Non-integer offset {offset} in {obj}")
            if not isinstance(of or 0, int):
                raise ValueError(f"Non-integer ofAgent {of} in {obj}")
            if var_info.store == "e":
                var = f"E_{var_info.index + (offset or 0)}"
            else:
                store_name = {"i": "I", "l": "Lvalue"}[var_info.store]
                var = f"{store_name}_{of}_{var_info.index + (offset or 0)}"
        else:
            offset = f"[][{offset}]" if offset is not None else ""
            var = f"{var["Name"]}{offset}{f'@{of}' if of is not None else ''}"
        return z3.Int(var)
    else:
        raise NotImplementedError(f"json2z3 {obj}")


def handle_assumes(info, var_names, ast):
    s0 = defaultdict(lambda: sympy.S.EmptySet)
    s0["id"] = sympy.Interval(0, info.spawn.num_agents() - 1)
    sym = {var: sympy.symbols(var) for var in var_names}
    sym["id"] = sympy.symbols("id")
    predicates = jq.compile(".Assumes | .. | objects | .Predicate | objects")
    for pred in predicates.input(ast).all():
        assume_sympy = json2sympy(sym, pred)
        if isinstance(assume_sympy, Relational):
            assume_sympy = [assume_sympy]
        for a in assume_sympy:
            try:
                a_set = a.as_set()
            except NotImplementedError:
                continue
            a_symbol = next(iter(a.free_symbols))
            s0[a_symbol.name] |= a_set

    # Merge @-suffixes to get all possible values of var
    for var in list(s0.keys()):
        if "@" in var:
            new_var = var.split("@")[0]
            s0[new_var] |= s0[var]

    s0 = pmap({k: Stripes.of_sympy(v) for k, v in s0.items()})
    return s0, sym


def domain_of(state):
    return type(state[next(iter(state.keys()))])


def eval_expr(expr, s):
    OPS = {
        "+": lambda x, y: x+y,
        "-": lambda x, y: x-y,
        "*": lambda x, y: x*y,
        "/": lambda x, y: x//y,
        "%": lambda x, y: x % y,
        "min": lambda x, y: x.Min(y),
        "max": lambda x, y: x.Max(y),
        "and": lambda x, y: x.And(y),
        "or": lambda x, y: x.Or(y),
        "nondet-from-range": lambda x, y: x.Range(y)
    }
    CMP = {
        ">": lambda x, y: x > y,
        "<": lambda x, y: x < y,
        ">=": lambda x, y: x >= y,
        "<=": lambda x, y: x <= y,
        "==": lambda x, y: x.equality(y),
        "!=": lambda x, y: ~x.equality(y),
    }
    UNARY_OPS = {
        "unary-minus": lambda x: -x,
        "unary-not": lambda x: not x,
        "abs": abs
    }

    def recurse(e):
        return eval_expr(e, s)

    domain = domain_of(s)
    if isinstance(expr, int) or isinstance(expr, bool):
        return domain.abstract(int(expr))
    elif expr == "id":
        return s["id"]
    elif "Var" in expr:
        var = expr["Var"]
        while "Item1" in var:
            var = var["Item1"]
        name = var["Name"]
        if var["Location"].startswith("Pick"):
            # TODO refine by pick type, if available
            return s["id"]
        if expr.get("Offset") is not None:
            name += f"""[{expr["Offset"]}]"""
        if expr.get("OfAgent") is not None:
            # Consider all possible values across agents
            vals = (v for x, v in s.items() if x.startswith(name + "@"))
            return reduce(lambda x, y: x | y, vals, domain())
        # print("Variable:", name, "-->", s[name])
        return s[name]
    # elif expr(NodeType.REF) or expr(NodeType.REF_EXT):
    #     return externs[expr[Attr.NAME]]
    elif "Op" in expr:
        operands = [recurse(t) for t in expr["Terms"]]
        if expr["Op"] in OPS:
            return reduce(OPS[expr["Op"]], operands)
        elif expr["Op"] in CMP:

            return reduce(CMP[expr["Op"]], operands)
        elif expr["Op"] in UNARY_OPS:
            return UNARY_OPS[expr["Op"]](operands[0])
        else:
            raise NotImplementedError(expr)
    elif "IfElse" in expr:
        condition = recurse(expr["IfElse"])
        if 1 in condition and 0 in condition:
            return (recurse(expr["IfTrue"]) | recurse(expr["IfFalse"]))
        elif 1 in condition:
            return recurse(expr["IfTrue"])
        elif 0 in condition:
            return recurse(expr["IfFalse"])
        else:
            raise ValueError(expr)
    elif "Quantifiers" in expr:
        # TODO can we recover some information?
        return domain.MAYBE
    # elif expr(NodeType.PICK):
    #     if expr[Attr.TYPE] is None:
    #         result = getattr(s, "id")
    #     else:
    #         rng = info.spawn.range_of(expr[Attr.TYPE])
    #         result = domain.abstract(*rng)
    #     return result
    else:
        raise NotImplementedError(expr)


@lru_cache(maxsize=256)
def bisect_by(s0, var):
    if var not in s0:
        if "@" in var and var.split("@")[0] in s0:
            var = var.split("@")[0]
        else:
            return None, None
    s1 = {**s0}
    s2 = {**s0}
    var1, var2 = s0[var].bisect()
    if var1 is None:
        return None, None
    s1[var] = var1
    s2[var] = var2
    return pmap(s1), pmap(s2)


def apply_assignment(asgn, state: dict, sym):
    if state is None:
        return None
    if asgn["ActionType"].startswith("Pick"):
        return state

    s1 = {**state}
    for upd in asgn["Updates"]:
        lhs = sym[upd["Item1"]["Var"]["Item1"]["Name"]]
        s1[lhs.name] = eval_expr(upd["Item2"], state)

    return s1


def apply_block(blk, s0, sym):
    if s0 is None:
        return None
    guards = blk.get("Guard", [])
    sympy_guards = [json2sympy(sym, g) for g in guards]
    g_vars = set(s.name for g in sympy_guards for s in g.free_symbols)

    def apply_guard(s):
        """Filters s down to the abstract state where all guards always hold"""
        always_holds = True
        for g in guards:
            eval_g = eval_expr(g, s)
        if 0 in eval_g:
            always_holds = False
            if 1 not in eval_g:
                return None
        if always_holds:
            return s
        bisections = [x for v in g_vars for x in bisect_by(pmap(s), v)]
        bisections = [x for x in bisections if x is not None]
        if len(bisections) == 0:
            return s
        with ThreadPoolExecutor() as exc:
            recurse = exc.map(apply_guard, bisections)
        recurse = [x for x in recurse if x is not None]
        if len(recurse) == 1:
            return next(iter(recurse))
        elif len(recurse) > 1:
            return reduce(lambda x0, x1: merge(x0, x1), recurse)
        else:
            raise ValueError("This should be unreachable")

    s1 = {**s0}
    if guards:
        s1 = apply_guard(s1)
    if s1 is None:
        return None

    # Find pick variables, set them to the full range of agents
    pick_vars = set(
        jq.compile(""" .. | objects | select(.Location == "Local") | .Name""")
        .input(blk["Stmt"]).all())
    for p in pick_vars:
        s1[p] = s1["id"]

    # Find local variables, set them to 0
    # (they will be overwritten by first assignment)
    local_vars = set(
        jq.compile(""" .. | objects | select(.Location == "Local") | .Name""")
        .input(blk["Stmt"]).all())
    for loc in local_vars:
        s1[loc] = s1["id"].abstract(0)

    for asgn in blk["Stmt"]:
        s1 = apply_assignment(asgn, s1, sym)
    return pmap(s1)


def dependency_analysis(blocks):
    depends = defaultdict(set)
    # We ignore ifElse conditions since they don't really affect the values
    finder = jq.compile(
        """
        walk(if type == "object" then del(.pred) else . end)
        | .. | objects | select(has("Vartype")) | .Name
        """)

    def update_depends(assignment):
        for upd in assignment["Updates"]:
            lhs = set(finder.input(upd["Item1"]).all())
            rhs = set(finder.input(upd["Item2"]).all())
            lhs.discard("id")  # id is guaranteed not to depend on anything
            for x in lhs:
                depends[x].update(rhs)
    for blk in blocks:
        for a in blk["Stmt"]:
            update_depends(a)

    # Transitivity
    old_depends = None
    while old_depends != depends:
        old_depends = {**depends}
        for v, v_deps in old_depends.items():
            for w in frozenset(v_deps):
                depends[v].update(old_depends.get(w, []))
    # id never depends on anything
    depends["id"] = set()
    return depends


def value_analysis(cli, info, ast):
    externs = {}
    for ext in cli[Args.VALUES]:
        name, value = ext.split("=")
        externs["_" + name] = sympy.Interval(int(value), int(value))

    blocks = [
        t["Action"]
        for agent in ast["Agents"].values()
        for t in agent["Sts"]]

    depends = dependency_analysis(blocks)

    vars_ = set(
        jq.compile(
            """.Agents | map(.Sts) | .. | objects
            | select(has("Location")) | .Name""")
        .input(ast).all())

    s0, sym = handle_assumes(info, vars_, ast)

    # We use a chaos automaton of all assignments/blocks
    # to overapproximate the range of feasible values
    def mergeStates(s0, s1):
        if s0 is None:
            return s1
        elif s1 is None:
            return s0
        return merge(s0, s1)

    def parallel_merge(states):
        if not states:
            return None
        elif len(states) == 1:
            return next(iter(states))
        else:
            st_list = list(states)
            mid = len(st_list) // 2
            with ThreadPoolExecutor() as exc:
                rec_left = exc.submit(parallel_merge, st_list[:mid])
                rec_right = exc.submit(parallel_merge, st_list[mid:])
                return mergeStates(rec_left.result(), rec_right.result())

    def loop(bound, s0):
        visited_states = set()
        frontier = set((s0, ))
        fixpoint = False
        with ThreadPoolExecutor(max_workers=1) as exc:
            for _ in range(bound):
                futures = []
                # common_args = (externs, State)
                futures = [
                    exc.submit(apply_block, blk, s, sym)
                    for blk, s in product(blocks, frontier)]

                new_states = set(f.result() for f in as_completed(futures))
                new_states.discard(None)

                if new_states <= visited_states:
                    fixpoint = True
                    break
                visited_states |= frontier
                frontier = new_states

        visited_states |= frontier
        s1 = reduce(mergeStates, visited_states)
        s1 = pmap({x: s1[x].join_adjacent() for x in s1})
        return s1, fixpoint

    s1, fixpoint = loop(20, s0)
    if not fixpoint:
        # Lookahead to find out (an underapproximation of)
        # the set of variables that won't change anymore
        s2, _ = loop(1, s1)
        wont_change = set(("id", ))  # id is guaranteed not to change
        while True:
            new_wont_change = set(
                v for v in depends
                if (all(dep in wont_change or dep == v) for dep in depends[v])
                and s2[v].is_within(s1[v]))
            if new_wont_change <= wont_change:
                break
            else:
                wont_change |= new_wont_change
    else:
        wont_change = set(depends.keys())

    return s1, fixpoint, depends, wont_change


if __name__ == "__main__":
    pass
