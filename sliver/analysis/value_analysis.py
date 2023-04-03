#!/usr/bin/env python3
# Rudimentary value analysis for LAbS specifications

from collections import defaultdict, namedtuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import reduce, lru_cache
from itertools import product

from ..app.cli import Args
from ..labsparse.labs_ast import Expr, QueryResult
from ..labsparse.labs_parser import Attr, NodeType, parse_to_dict


def merge(s0, s1, State):
    result = {k: getattr(s0, k) for k in s0._fields}
    for k in s1._fields:
        if result[k] is None:
            result[k] = getattr(s1, k)
        elif getattr(s1, k) is not None:
            result[k] |= getattr(s1, k)
    return State(**result)


def entailed_by(s1, states):
    for s2 in states:
        if s1 == s2:
            continue
        if all(getattr(s1, var).is_within(getattr(s2, var))
               for var in s1._fields):
            return True
    return False


def make_init(info, local_names, domain):
    """Get value analysis in the initial state"""
    stores = (info.lstig, info.e, *(a.iface for a in info.spawn.values()))
    s0 = {}
    for store in stores:
        for var in store.values():
            for id_ in range(info.spawn.num_agents()):
                vals = var.values(id_)
                abstract = (
                    domain.abstract_range(vals) if isinstance(vals, range)
                    else domain.abstract(*vals))
                # stripe = domain.abstract(*vals)
                # stripe = (
                #     S(min(vals), max(vals))
                #     if isinstance(vals, range)
                #     else Stripes(*(I(x) for x in vals)))
                if var.name in s0:
                    s0[var.name] |= abstract
                else:
                    s0[var.name] = abstract

    s0["id"] = domain.abstract(*range(0, info.spawn.num_agents() - 1))
    State = namedtuple("State", [*local_names, *s0.keys()])
    for x in local_names:
        s0[x] = domain.NO
    s0 = State(**s0)

    return State, s0


def domain_of(state):
    return type(getattr(state, next(iter(state._fields))))


def eval_expr(expr, s, externs, info):
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
        "=": lambda x, y: x.equality(y),
        "!=": lambda x, y: ~x.equality(y),
    }
    UNARY_OPS = {
        "unary-minus": lambda x: -x,
        "unary-not": lambda x: not x,
        "abs": abs
    }

    def recurse(e):
        return eval_expr(e, s, externs, info)

    domain = domain_of(s)
    if expr(NodeType.LITERAL):
        return domain.abstract(expr[Attr.VALUE])
    elif expr(NodeType.REF) and expr[Attr.NAME] in s._fields:
        return getattr(s, expr[Attr.NAME])
    elif expr(NodeType.REF) or expr(NodeType.REF_EXT):
        return externs[expr[Attr.NAME]]
    elif expr(NodeType.BUILTIN) and expr[Attr.NAME] in UNARY_OPS:
        return UNARY_OPS[expr[Attr.NAME]](recurse(expr[Attr.OPERANDS][0]))  # noqa: E501
    elif (expr(NodeType.EXPR) or expr(NodeType.BUILTIN)
            and expr[Attr.NAME] in OPS):
        operands = [recurse(e) for e in expr[Attr.OPERANDS]]
        return reduce(OPS[expr[Attr.NAME]], operands)
    elif expr(NodeType.COMPARISON) and expr[Attr.NAME] in CMP:
        operands = [recurse(e) for e in expr[Attr.OPERANDS]]
        return reduce(CMP[expr[Attr.NAME]], operands)
    elif expr(NodeType.IF):
        condition = recurse(expr[Attr.CONDITION])
        if 1 in condition and 0 in condition:
            return (
                recurse(expr[Attr.THEN]) |
                recurse(expr[Attr.ELSE]))
        elif 1 in condition:
            return recurse(expr[Attr.THEN])
        elif 0 in condition:
            return recurse(expr[Attr.ELSE])
        else:
            raise ValueError(expr.as_labs())
    elif expr(NodeType.QFORMULA):
        # TODO can we recover some information?
        return domain.MAYBE
    elif expr(NodeType.PICK):
        if expr[Attr.TYPE] is None:
            result = getattr(s, "id")
        else:
            rng = info.spawn.range_of(expr[Attr.TYPE])
            result = domain.abstract(*rng)
        print(f"{expr.as_labs()}\n{result}")
        return result
    else:
        raise NotImplementedError(expr.as_labs())


@lru_cache(maxsize=256)
def bisect_by(s0, var, State):
    s1 = {k: getattr(s0, k) for k in s0._fields}
    s2 = {k: getattr(s0, k) for k in s0._fields}
    var1, var2 = getattr(s0, var).bisect()
    if var1 is None:
        return None, None
    s1[var] = var1
    s2[var] = var2
    return State(**s1), State(**s2)


def apply_guard(guards, stmt, s0, externs, info, State):
    """Filters s0 down to the abstract state where stmt's guard always holds"""
    g = guards.get(stmt)
    if g is None:
        return s0
    new_guard = Expr("", "", "", {})
    new_guard[Attr.SYNTHETIC] = True
    new_guard[Attr.NAME] = "and"
    new_guard[Attr.OPERANDS] = g
    g_vars = set(x[Attr.NAME] for x in (new_guard // (NodeType.REF, )))

    def recursive_apply(s):
        eval_whole = eval_expr(new_guard, s, externs, info)
        if 1 in eval_whole and 0 not in eval_whole:
            # Guard always holds
            return s
        elif 0 in eval_whole and 1 not in eval_whole:
            # Guard never holds
            return None
        bisections = [x for v in g_vars for x in bisect_by(s, v, State)]
        bisections = [x for x in bisections if x is not None]
        if len(bisections) == 0:
            raise ValueError(f"This should be unreachable {s}")

        with ThreadPoolExecutor() as exc:
            recurse = exc.map(recursive_apply, bisections)
        recurse = [x for x in recurse if x is not None]
        if len(recurse) == 1:
            return next(iter(recurse))
        elif len(recurse) > 1:
            return reduce(lambda x0, x1: merge(x0, x1, State), recurse)
        else:
            raise ValueError(f"This should be unreachable {s} {new_guard.as_labs()} {eval_whole}")  # noqa E501

    return recursive_apply(s0)


def lhs_of(stmt):
    if stmt(NodeType.ASSIGN):
        return set(n[Attr.NAME] for n in stmt[Attr.LHS])
    elif stmt(NodeType.BLOCK):
        return set().union(*(lhs_of(a) for a in (stmt // (NodeType.ASSIGN, ))))


def apply_assignment(asgn, s0, externs, guards, old, info, State):
    # If asgn is guarded, reduce s0 to the states where the guard holds
    s0 = apply_guard(guards, asgn, s0, externs, info, State)
    # The guard did not hold anywhere, so we cannot interpret asgn
    if s0 is None:
        return None
    s1 = {k: getattr(s0, k) for k in s0._fields}
    for lhs, rhs in zip(asgn[Attr.LHS], asgn[Attr.RHS]):
        s1[lhs[Attr.NAME]] = eval_expr(rhs, s0, externs, info)
    s1 = State(**s1)
    return None if old is not None and entailed_by(s1, old) else s1


def apply_block(blk, s0, externs, guards, old, info, State):
    # If blk is guarded, reduce s0 to the states where the guard holds
    s0 = apply_guard(guards, blk, s0, externs, info, State)
    # The guard did not hold anywhere, so we cannot interpret blk
    if s0 is None:
        return None
    for asgn in blk[Attr.BODY]:
        s1 = apply_assignment(asgn, s0, externs, guards, None, info, State)
        s0 = s1
    return None if old is not None and entailed_by(s1, old) else s1


def dependency_analysis(assignments, blocks):
    depends = defaultdict(set)

    def update_depends(assignment):
        for lhs, rhs in zip(assignment[Attr.LHS], assignment[Attr.RHS]):
            # # We skip conditions (on ifs), since they don't really
            # # affect the values
            rhs1 = QueryResult(rhs.walk(ignore_attrs=[Attr.CONDITION]))
            names = [x[Attr.NAME] for x in rhs1 // (NodeType.REF, )]
            depends[lhs[Attr.NAME]].update(names)

    for a in assignments:
        update_depends(a)
    for blk in blocks:
        for a in (blk // (NodeType.ASSIGN, )):
            update_depends(a)

    # Transitivity
    old_depends = None
    while old_depends != depends:
        old_depends = {**depends}
        for v, v_deps in old_depends.items():
            for w in frozenset(v_deps):
                depends[v].update(old_depends.get(w, []))
    return depends


def value_analysis(cli, info, domain):
    externs = {}
    for ext in cli[Args.VALUES]:
        name, value = ext.split("=")
        externs["_" + name] = domain.abstract(int(value))
    ast = parse_to_dict(cli.file)

    # Extract all assignment, blocks, and guards
    # (That are reachable from the agents' behaviour)
    assignments = set()
    blocks = set()
    guards = set()
    for a in ast.agents:
        behavior = [
            p for p in a[Attr.PROCDEFS] if p[Attr.NAME] == "Behavior"][0]
        visited_calls = set(("Behavior", "Skip"))
        frontier = [behavior]
        while frontier:
            node = frontier.pop()
            assignments.update(
                n for n in node.walk(ignore_types=[NodeType.BLOCK])
                if n(NodeType.ASSIGN))
            blocks.update(n for n in node.walk() if n(NodeType.BLOCK))
            guards.update(
                (a, n) for n in node.walk()
                if n(NodeType.GUARDED))
            calls = (
                n[Attr.NAME] for n in node.walk()
                if n(NodeType.CALL)
                and n[Attr.NAME] not in visited_calls)
            for c in calls:
                visited_calls.add(c)
                p = a.try_lookup(c) or ast["system"].try_lookup(c)
                if p is None:
                    raise KeyError(c)
                frontier.append(p)

    # Map assignments/blocks to their guards
    def get_guarded_assignments(node, agent):
        if node(NodeType.COMPOSITION):
            if node[Attr.NAME] == "seq":
                return get_guarded_assignments(node[Attr.OPERANDS][0], agent)
            else:
                return set.union(*(
                    get_guarded_assignments(n, agent)
                    for n in node[Attr.OPERANDS]))
        elif node(NodeType.ASSIGN) or node(NodeType.BLOCK):
            return set((node, ))
        elif node(NodeType.GUARDED):
            return get_guarded_assignments(node[Attr.BODY], agent)
        elif node(NodeType.CALL):
            name = node[Attr.NAME]
            if name == "Skip":
                return set()
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

    depends = dependency_analysis(assignments, blocks)

    # Retrieve local variable names and build initial state
    local_names = set(
        lhs[Attr.NAME]
        for blk in blocks
        for n in blk[Attr.BODY]
        for lhs in n[Attr.LHS]
        if n[Attr.TYPE] == "local")
    State, s0 = make_init(info, local_names, domain)

    # We use a chaos automaton of all assignments/blocks
    # to overapproximate the range of feasible values
    fixpoint = False
    old_states = set([s0])

    def mergeStates(s0, s1):
        return merge(s0, s1, State)

    wont_change = set()
    with ThreadPoolExecutor() as exc:
        # TODO make analysis bound configurable
        for i in range(10):
            # Prune away old states entailed by others
            old_merge = reduce(mergeStates, old_states)

            futures = []
            common_args = (externs, guard_map, old_states, info, State)
            futures = [
                exc.submit(apply_assignment, a, s, *common_args)
                for a, s in product(assignments, old_states)]
            futures.extend(
                exc.submit(apply_block, blk, s, *common_args)
                for blk, s in product(blocks, old_states))

            new_states = (f.result() for f in as_completed(futures))
            new_states = set(s for s in new_states if s is not None)

            if new_states <= old_states:
                fixpoint = True
                break
            old_states |= new_states

            # Detect which variables won't change anymore
            next_merge = reduce(mergeStates, old_states)
            common_args = (externs, {}, (next_merge, ), info, State)
            no_dep_vars = [v for v in depends if len(depends[v]) == 0]
            for v in no_dep_vars:
                futures = [
                    exc.submit(apply_assignment, a, s, *common_args)
                    for s in old_states
                    for a in assignments
                    if any(lhs == v for lhs in lhs_of(a))]
                futures.extend(
                    exc.submit(apply_block, b, s, *common_args)
                    for s in old_states
                    for b in blocks
                    if any(lhs == v for lhs in lhs_of(b)))
            result = (f.result() for f in as_completed(futures))
            result = [s for s in result if s is not None]
            next2_merge = (
                reduce(mergeStates, result)
                if len(result)
                else next_merge)
            new_wont_change = [
                v for v in no_dep_vars
                if getattr(next2_merge, v).is_within(getattr(next_merge, v))
                and getattr(next_merge, v).is_within(getattr(old_merge, v))
                and v not in wont_change]
            wont_change.update(new_wont_change)

    s1 = old_merge if fixpoint else reduce(mergeStates, old_states)
    s1 = State(**{
        x: getattr(s1, x).join_adjacent()
        for x in s1._fields
    })
    return s1, fixpoint, depends, wont_change


if __name__ == "__main__":
    pass
