from functools import reduce
import logging
import random
import re
import sys
import time

import sympy
from z3 import (And, Bool, If, Implies, Int, Or, Solver, Sum, sat, set_param,
                simplify)
from z3.z3 import Z3_OP_UNINTERPRETED, BoolVal, IntVector, IntNumRef

from sliver.analysis.value_analysis import json2z3
from sliver.atlas.atlas import qelim

from ..app.cli import Args, ExitStatus, SliverError

log = logging.getLogger('backend')
RND_SEED = int(time.time())


def make_regex(placeholder):
    p = re.escape(placeholder)
    return re.compile(f'(?<=// ___{p}___)(.*?)(?=// ___end {p}___)', re.DOTALL)


def symbolic_reduce(vs, fn):
    m = vs[0]
    for v in vs[1:]:
        m = If(fn(v, m), v, m)
    return m


def symMax(vs):
    return symbolic_reduce(vs, lambda x, y: x > y)


def symMin(vs):
    return symbolic_reduce(vs, lambda x, y: x < y)


def Count(boolvec):
    return Sum(*(If(i, 1, 0) for i in boolvec))


def to_sympy(z3_expr):
    if isinstance(z3_expr, IntNumRef):
        return sympy.sympify(z3_expr.as_long())
    if z3_expr.decl().kind() == Z3_OP_UNINTERPRETED and not z3_expr.children():
        return sympy.symbols(z3_expr.decl().name())
    elif z3_expr.decl().name() in ("true", "false"):
        return BoolVal(z3_expr.decl().name() == "true")
    elif z3_expr.decl().name() == "ite":
        _, _, true_branch, false_branch = z3_expr.children()
        return sympy.Or(to_sympy(true_branch), to_sympy(false_branch))
    children = [to_sympy(c) for c in z3_expr.children()]
    if z3_expr.decl().name() == "and":
        return sympy.And(*children)
    elif z3_expr.decl().name() == "or":
        return sympy.Or(*children)
    elif z3_expr.decl().name() == "+":
        return sympy.Add(*children)
    elif z3_expr.decl().name() == "-":
        return reduce(lambda x, y: x - y, children, 0)
    elif z3_expr.decl().name() == "*":
        return reduce(lambda x, y: x * y, children, 1)
    elif z3_expr.decl().name() == "not":
        return ~(children[0])
    elif z3_expr.decl().name() == "mod":
        return children[0] % children[1]
    elif z3_expr.decl().name() == "=":
        return sympy.Eq(*children)
    elif z3_expr.decl().name() == "!=":
        return sympy.Ne(*children)
    elif z3_expr.decl().name() == "<":
        return sympy.Lt(*children)
    elif z3_expr.decl().name() == "<=":
        return sympy.Le(*children)
    elif z3_expr.decl().name() == ">":
        return sympy.Gt(*children)
    elif z3_expr.decl().name() == ">=":
        return sympy.Ge(*children)
    else:
        raise NotImplementedError(f"Unsupported: {z3_expr.decl().name()}")


def overapprox(s: sympy.Set | sympy.Mod):
    if isinstance(s, sympy.Mod) and s.args[1].is_integer:
        return sympy.Range(0, s.args[1], 1)
    elif isinstance(s, sympy.Union) or isinstance(s, sympy.FiniteSet):
        return reduce(lambda s1, s2: s1 | s2, (overapprox(arg) for arg in s.args))  # noqa: E501
    elif isinstance(s, sympy.Intersection):
        return reduce(lambda s1, s2: s1 & s2, (overapprox(arg) for arg in s.args))  # noqa: E501
    elif isinstance(s, sympy.ConditionSet):
        return s.base_set
    else:
        return s


def pick_from(s: sympy.Set):
    if s.is_Union or s.is_FiniteSet:
        # Pick from one of the subsets
        return pick_from(random.choice(s.args))
    elif s.is_Intersection:
        apx = overapprox(s)
        if apx.is_Intersection:
            # Reduction did not work, we give up
            raise ValueError(f"Cannot approximate {s}")
        return pick_from(apx)
    elif isinstance(s, sympy.ConditionSet):
        # Pick from the base set, ignoring the condition
        return pick_from(s.base_set)
    elif isinstance(s, sympy.Range):
        inf, sup = s.inf, s.sup
        # Well okay, in this case we _under_approximate :)
        # If the range is infinite, we cap it to +- sys.maxsize
        # (Max value that a Py_ssize_t can hold in CPython)
        if inf.is_infinite:
            inf = sys.maxsize if inf > 0 else -sys.maxsize
        if sup.is_infinite:
            sup = sys.maxsize if sup > 0 else -sys.maxsize
        return random.randint(inf, sup)
    else:
        raise NotImplementedError(f"Unsupported set type: {type(s), s}")


class Concretizer:
    def __init__(self, info, cli, ast, randomize=True):
        self.info = info
        self.cli = cli
        self.ast = ast
        self.randomize = randomize
        self.agents = self.info.spawn.num_agents()
        self.attrs = [[] for _ in range(self.agents)]
        self.lstigs = [[] for _ in range(self.agents)]
        self.envs = []
        self.sched = None
        self.picks = {}
        self.softs = set()
        self.past_models = []

        self.s = Solver()
        self._setup_initial_state()
        self._setup_scheduler()

        if randomize:
            self.s.set(":auto_config", False)
            self.s.set(":smt.phase_selection", 5)
            self.s.set(":smt.arith.random_initial_value", True)

    def isAnAgent(self, var):
        return And(var >= 0, var < self.agents)

    def isOfType(self, var, typ):
        rng = self.info.spawn.range_of(typ)
        return And(var >= rng.start, var < rng.stop)

    def _set_random_seed(self):
        seed = self.cli.get_seed()
        set_param(":smt.random_seed", seed)
        set_param(":sat.random_seed", seed)
        set_param(":smt.arith.random_initial_value", True)
        # 5 = random phase selection
        self.s.set("phase_selection", 5)

        random.seed(seed)
        log.debug(f"Concretization: random seed is {seed}")

    def _add_soft_constraints(self):
        self.s.push()
        # Experimental: soft constraints on picks
        # (Does not seem necessary so far)
        for name in self.picks:
            p, size, typ = self.picks[name]
            for step in range(self.cli[Args.STEPS]):
                choices = list(
                    self.info.spawn.range_of(typ)
                    if typ
                    else range(self.agents))
                try:
                    choices.remove(self.sched[step])
                except ValueError:
                    pass
                for i in range(size):
                    random.shuffle(choices)
                    for i in range(size):
                        soft = Bool(f"pick_{name}_{step}_{i}_%%soft%%")
                        self.softs.add(soft)
                        self.s.add(Implies(soft, p[step][i] == choices.pop()))

        def my_solveset(expr, var):
            if isinstance(expr, sympy.Or) or isinstance(expr, sympy.And):
                sets = []
                for arg in expr.args:
                    if var in arg.free_symbols:
                        try:
                            new_set = my_solveset(arg, var)
                            sets.append(new_set)
                        except Exception:
                            continue
                return (
                    reduce(
                        lambda s1, s2: s1 | s2
                        if isinstance(expr, sympy.Or)
                        else s1 & s2, sets)
                ) if sets else sympy.S.EmptySet
            else:
                return sympy.solveset(expr, var, domain=sympy.S.Integers)

        sympy_assume = sympy.And(*[to_sympy(a) for a in self.s.assertions()])
        for x in sympy_assume.free_symbols:
            if x.name.startswith("sched__"):
                continue
            sol = None
            try:
                sol = my_solveset(sympy_assume, x)
                choice = pick_from(sol)
                soft = Bool(f"assume_{x}_{choice}_%%soft%%")
                self.softs.add(soft)
                self.s.add(Implies(soft, Int(x.name) == choice))
            except Exception:
                log.debug(
                    f"Could not pick a value for {x} "
                    f"(solveset: {sol}). Skipping.")
                continue

    def _reset_soft_constraints(self):
        # Remove previous soft constraints
        # And forces the exclusion of past models
        self.softs = set()
        self.s.pop(self.s.num_scopes())
        for m in self.past_models:
            self.s.add(m)

    def _setup_initial_state(self):
        for tid in range(self.agents):
            a = self.info.spawn[tid]
            for v in a.iface.values():
                attrs = ([
                    Int(f"I_{tid}_{i}")
                    for i in range(v.index, v.index + v.size)]
                    if v.is_array
                    else [Int(f"I_{tid}_{v.index}")])
                self.attrs[tid].extend(attrs)
            for v in a.lstig.values():
                lstigs = ([
                    Int(f"L_{tid}_{i}")
                    for i in range(v.index, v.index + v.size)]
                    if v.is_array
                    else [Int(f"L_{tid}_{v.index}")])
                self.lstigs[tid].extend(lstigs)

        for v in self.info.e.values():
            envs = ([
                Int(f"E_{i}")
                for i in range(v.index, v.index + v.size)]
                if v.is_array
                else [Int(f"E_{v.index}")])
            self.envs = envs

        for assume in self.ast["Assumes"].values():
            formula = qelim(self.info, assume["Def"]["QuantPredicate"])

            constraint = simplify(json2z3(formula, self.info))
            self.s.add(constraint)

    def _setup_scheduler(self):
        steps = self.cli[Args.STEPS]
        self.sched = IntVector("sched", steps)
        self.s.add(*(self.isAnAgent(x) for x in self.sched))
        # Round robin scheduler
        # TODO This does not work with stigmergic systems
        if self.cli[Args.FAIR] and len(self.info.lstig) == 0:
            self.s.add(self.sched[0] == 0)
            self.s.add(*(
                (self.sched[i] == (self.sched[i - 1] + 1) % self.agents)
                for i in range(1, steps)))

    def add_pick(self, name, size, typ, _):
        """Adds constraints for statement <name> := pick <size> <typ> <where>

        <typ> is optional. When omitted, pick from all agents.
        The last argument is the "where" clause and is currently ignored.
        """
        size = int(size)
        steps = self.cli[Args.STEPS]

        def can_pick(tid, name):
            for ag in self.info.spawn.values():
                if name in ag.picks:
                    return self.isOfType(tid, ag.name)

        p = [IntVector(f"{name}_{i}", size) for i in range(steps)]
        for step in range(steps):
            # if agent cannot actually use the pick, set to 0

            if_can_pick = [
                # Honor agent type,
                self.isOfType(x, typ) for x in p[step]
            ] if typ else [
                # If pick is untyped, x should still be a valid id
                self.isAnAgent(x) for x in p[step]
            ]
            # picks should be distinct
            if_can_pick.extend(
                p[step][i] != p[step][j]
                for j in range(size)
                for i in range(j)
            )
            # Agent cannot pick itself
            if_can_pick.extend(x != self.sched[step] for x in p[step])

            self.s.add(If(
                can_pick(self.sched[step], name),
                And(if_can_pick),
                And([x == 0 for x in p[step]])
            ))
        self.picks[name] = (p, size, typ)

    def _scan_picks(self, program):
        re_pick = re.compile(
            r'TYPEOFVALUES '
            r'([^\[\n]+)\[.+\]; \/\* Pick ([0-9]+)\s+(\S*)?\s*(where .+)?\*\/'
        )
        return re_pick.findall(program)

    def concretize_program(self, program):
        if self.cli[Args.CONCRETIZATION] == "none":
            return program
        re_globals = make_regex("concrete-globals")
        re_sched = make_regex("concrete-scheduler")
        re_sym_sched = make_regex("symbolic-scheduler")

        if self.cli[Args.CONCRETIZATION] == "sat":
            if not self.cli[Args.FAIR]:
                program = re_sym_sched.sub('\n', program)
                program = re_sched.sub('\nscheduled = sched[__LABS_step];\n', program)  # noqa: E501
                program = re.sub(
                    r"init\(\);",
                    """init();
    TYPEOFAGENTID sched[BOUND];
    for (unsigned i = 0; i < BOUND; ++i) {{
        sched[i] = __CPROVER_nondet_int();
        sched[i] = sched[i] < MAXCOMPONENTS ? sched[i] : 0;
    }}
""",
                    program)
            elif len(self.info.lstig) == 0:
                program = re_sym_sched.sub('\n', program)
                program = re_sched.sub('\nscheduled = sched[__LABS_step];\n', program)  # noqa: E501
                steps = self.cli[Args.STEPS]
                sched = ", ".join(str(i % self.agents) for i in range(steps))
                program = re_globals.sub(
                    f"\nTYPEOFAGENTID sched[{steps}] = {{ {sched} }};\n",
                    program)

        elif self.cli[Args.CONCRETIZATION] == "src":
            picks = self._scan_picks(program)
            for pick_name, *_ in picks:
                usages = re.compile(
                    f'(?<!TYPEOFVALUES ){re.escape(pick_name)}' +
                    r'\[')
                program = usages.sub(f"{pick_name}[__LABS_step][", program)

            globs, inits = self.concretization(program)

            re_init = make_regex("concrete-init")

            re_sym_pick = make_regex("symbolic-pick")

            program = re_sym_sched.sub('\n', program)
            program = re_sym_pick.sub('\n', program)
            program = re_globals.sub(f'\n{globs}\n', program, 1)
            program = re_init.sub(f'\n{inits}\n', program)
            program = re_sched.sub('\nscheduled = sched[__LABS_step];\n', program)  # noQA: E501

            re_sym_init = make_regex("symbolic-init")
            program = re_sym_init.sub('\n', program)

        return program

    def concretize_file(self, fname, dest=None):
        with open(fname) as file:
            program = file.read()
        program = self.concretize_program(program)
        with open(dest if dest is not None else fname, "w") as file:
            file.write(program)

    def get_concretization(self, program, return_model=False):
        def fmt_globals(m):
            STEPS = self.cli[Args.STEPS]

            def fmt_intvec(vec):
                return f"""{{ {",".join(str(m[x]) for x in vec)} }}"""

            def fmt_pick(p, name, size):
                rows = ", ".join(fmt_intvec(row) for row in p)
                return f"TYPEOFAGENTID {name}[{STEPS}][{size}] = {{ {rows} }};"

            picks = (fmt_pick(p, n, s) for n, (p, s, _) in self.picks.items())
            return (
                f"TYPEOFAGENTID sched[{STEPS}] = {fmt_intvec(self.sched)};"
                + "\n"
                + "\n".join(picks))

        def fmt_inits(m):
            def index(attr):
                return int(str(attr).split("_")[-1])
            return ("\n".join(
                f"I[{tid}][{index(attr)}] = {m[attr]};"
                for tid in range(self.agents)
                for attr in self.attrs[tid]
                # Skip values that would be initialized to zero
                if str(m[attr]) != "0")
                + "\n" + "\n".join(
                    f"Lvalue[{tid}][{index(attr)}] = {m[attr]};"
                    for tid in range(self.agents)
                    for attr in self.lstigs[tid]
                    # Skip values that would be initialized to zero
                    if str(m[attr]) != "0")
                + "\n" + "\n".join(
                    f"E[{index(attr)}] = {m[attr]};"
                    for attr in self.envs
                    # Skip values that would be initialized to zero
                    if str(m[attr]) != "0"))

        if self.randomize:
            self._reset_soft_constraints()
            self._add_soft_constraints()
            self._set_random_seed()
        for p in self._scan_picks(program):
            self.add_pick(*p)

        check = None
        softs = list(self.softs)

        # Randomize the order of soft sonstraints
        random.shuffle(softs)
        # ...But keep "pick" constraints at the beginning of the list
        # (so they will removed last)
        # softs.sort(key=lambda s: 0 if "pick_" in str(s) else 1)

        # Try solving. If the current problem is unsat,
        # remove a (random) soft constraint and try again
        while check != sat:
            check = self.s.check(*softs)
            if check != sat:
                if not softs:
                    break
                softs.pop()

        if check == sat:
            m = self.s.model()
            # Avoid getting the same model in future
            block = []
            for decl in m:
                const = decl()
                # Ignore variables used for soft constraints
                if "%%soft%%" not in str(const):
                    block.append(const != m[decl])
            if block:
                self.past_models.append(Or(block))

            return m if return_model else (fmt_globals(m), fmt_inits(m))
        else:
            log.debug(f"Unsat core is {self.s.unsat_core()}")
            raise SliverError(
                ExitStatus.BACKEND_ERROR,
                error_message="Could not find a valid concretization.")
