import logging
import random
import re
import time

from z3 import (And, Bool, If, Implies, Int, Not, Or, Solver, Sum, sat,
                set_option, simplify)
from z3.z3 import IntVector

from sliver.atlas.atlas import vars_to_strings
from sliver.labsparse.labsparse.labs_ast import Attr, Node, NodeType
from sliver.labsparse.labsparse.labs_parser import BEXPR, QUANT
from sliver.labsparse.labsparse.utils import (eliminate_quantifiers,
                                              replace_externs)

from ..app.cli import Args, ExitStatus, SliverError
from ..app.info import get_var


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


def to_z3(node):
    """Translate a (quantifier-free) ATLAS property to a Z3 constraint
    """
    # if isinstance(node, OfNode):
    #     raise ValueError
    if not isinstance(node, Node):
        return node
    if Attr.OPERANDS in node:
        ops = {
            "+": lambda x, y: Sum(x, y),
            "-": lambda x, y: Sum(x, -y),
            "*": lambda x, y: x * y,
            "/": lambda x, y: x / y,
            "=": lambda x, y: x == y,
            "!=": lambda x, y: x != y,
            ">": lambda x, y: x > y,
            ">=": lambda x, y: x >= y,
            "<": lambda x, y: x < y,
            "<=": lambda x, y: x <= y,
            "%": lambda x, y: x % y,
            "and": lambda *x: And(x),
            "or": lambda *x: Or(x),
            "abs": lambda x: abs(x[0]),
            "max": lambda x: symMax(x),
            "min": lambda x: symMin(x),
            "not": lambda x: Not(x[0])
        }
        args = [to_z3(a) for a in node[Attr.OPERANDS]]
        try:
            return ops[node[Attr.NAME]](*args)
        except TypeError:
            raise TypeError(node[Attr.NAME], args)

    elif node(NodeType.LITERAL):
        return int(node[Attr.VALUE])
    else:
        return node
    # elif isinstance(node, BuiltIn):
    #     funs = {
    #         "abs": lambda x: abs(x[0]),
    #         "max": lambda x: symMax(x),
    #         "min": lambda x: symMin(x),
    #         "not": lambda x: Not(x[0])
    #     }
    #     return funs[node.fn])([to_z3(a) for a in node[Attr.OPERANDS]])
    # elif isinstance(node, Nary):
    #     ops = {
    #         "and": lambda x: And(*x),
    #         "or": lambda x: Or(*x)
    #     }
    #     return ops[node.fn]([to_z3(a) for a in node.args])
    # else:
    #     try:
    #         parse_int = int(node)
    #         return parse_int
    #     except (ValueError, TypeError):
    #         return node


def quant_to_z3(formula, info, attrs, lstigs, envs):
    vars_to_strings(formula, info, attrs, lstigs, envs)
    return simplify(to_z3(formula))


class Concretizer:
    def __init__(self, info, cli, randomize=True):
        self.info = info
        self.cli = cli
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
        self._setup_initial_state(self.info.externs)
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
        set_option(":smt.random_seed", seed)
        random.seed(seed)
        log.debug(f"Concretization: random seed is {seed}")

    def _add_soft_constraints(self):
        self.s.push()
        for tid in range(self.agents):
            a = self.info.spawn[tid]
            for i, attr in enumerate(self.attrs[tid]):
                v = get_var(a.iface, i)
                if len(v.values(tid)) == 1:
                    # var is deterministic, no need for additional constraints
                    continue
                fresh_bool = Bool(f"{v.store}_{tid}_{v.index}_%%soft%%")
                self.softs.add(fresh_bool)
                rnd = v.rnd_value(tid)
                self.s.add(Implies(fresh_bool, attr == rnd))

        for i, env_var in enumerate(self.envs):
            v = get_var(self.info.e, i)
            if len(v.values(0)) == 1:
                # var is deterministic, no need for additional constraints
                continue
            fresh_bool = Bool(f"{v.store}_{v.index}_%%soft%%")
            self.softs.add(fresh_bool)
            self.s.add(Implies(fresh_bool, attr == v.rnd_value(tid)))

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
                        self.s.add(Implies(soft, p[step][i] == choices.pop()))  # noQA: E501

    def _reset_soft_constraints(self):
        # Remove previous soft constraints
        # And forces the exclusion of past models
        self.softs = set()
        self.s.pop(self.s.num_scopes())
        for m in self.past_models:
            self.s.add(m)

    def _init_constraint(self, v, attrs, id):
        def c(attr):
            values = v.values(id)
            if isinstance(values, range):
                return And(attr >= values.start, attr < values.stop)
            elif isinstance(values, list):
                return Or(*(attr == int(x) for x in values))
            else:
                return (attr == int(values))
        self.s.add(*(c(a) for a in attrs))

    def _setup_initial_state(self, externs):
        for tid in range(self.agents):
            a = self.info.spawn[tid]
            for v in a.iface.values():
                attrs = ([
                    Int(f"I_{tid:0>2}_{i:0>2}")
                    for i in range(v.index, v.index + v.size)]
                    if v.is_array
                    else [Int(f"I_{tid:0>2}_{v.index:0>2}")])
                self._init_constraint(v, attrs, tid)
                self.attrs[tid].extend(attrs)
            for v in a.lstig.values():
                lstigs = ([
                    Int(f"L_{tid:0>2}_{i:0>2}")
                    for i in range(v.index, v.index + v.size)]
                    if v.is_array
                    else [Int(f"L_{tid:0>2}_{v.index:0>2}")])
                self._init_constraint(v, lstigs, tid)
                self.lstigs[tid].extend(lstigs)

        for v in self.info.e.values():
            envs = ([
                Int(f"E_{i:0>2}")
                for i in range(v.index, v.index + v.size)]
                if v.is_array
                else [Int(f"E_{v.index:0>2}")])
            self._init_constraint(v, envs, 0)
            self.envs = envs

        for assume in self.info.assumes:
            formula = (QUANT | BEXPR).parseString(assume)[0]
            formula = eliminate_quantifiers(formula, self.info)
            formula = replace_externs(formula, externs)

            constraint = quant_to_z3(
                formula, self.info, self.attrs, self.lstigs, self.envs)
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

            globs, inits = self.get_concretization(program)

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
