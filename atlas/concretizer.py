import re
from z3 import (
    Concat, Exists, Optimize, simplify,
    Solver, Int, IntSort, And, Or, Function, ForAll, Not, If,
    set_option, sat, unsat, Sum, BoolVector
    )
import time
import random

from z3.z3 import IntVector

from atlas.atlas import (
    OfNode, BinOp, Nary, BuiltIn, QUANT, make_dict, contains, remove_quant)
from cli import Args
from info import get_var


RND_SEED = time.time()


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
    if isinstance(node, OfNode):
        raise ValueError
    if isinstance(node, BinOp):
        ops = {
            "=": lambda x, y: x == y,
            "!=": lambda x, y: x != y,
            ">": lambda x, y: x > y,
            "<": lambda x, y: x < y,
            "or": lambda x, y: Or(x, y),
            "and": lambda x, y: And(x, y)
        }
        return ops[node.op](to_z3(node.e1), to_z3(node.e2))
    elif isinstance(node, BuiltIn):
        funs = {
            "abs": lambda x: abs(x[0]),
            "max": lambda x: symMax(x),
            "min": lambda x: symMin(x),
            "not": lambda x: Not(x[0])
        }
        args = [to_z3(a) for a in node.args]
        return funs[node.fn](args)
    elif isinstance(node, Nary):
        ops = {
            "and": lambda x: And(*x),
            "or": lambda x: Or(*x)
        }
        return ops[node.fn]([to_z3(a) for a in node.args])
    else:
        return node


def quant_to_z3(quant, info, attrs, lstigs):
    dict_, formula = make_dict(quant)

    def replace_with_attr(node, agent):
        # return f"{f.var}_{agent}"
        if node.var == "id":
            return agent
        else:
            var = info.lookup_var(node.var)
            idx = var.index + (node.offset or 0)
            if var.store == "i":
                return attrs[agent][idx]
            elif var.store == "lstig":
                return lstigs[agent][idx]
            else:
                raise NotImplementedError

    for var in dict_:
        quant, agent_type = dict_[var]
        if contains(formula, var):
            formula, _ = remove_quant(
                formula, quant, var, info.spawn.tids(agent_type),
                replace_with_attr
            )
    return simplify(to_z3(formula))


class Concretizer:
    def __init__(self, info, cli, randomize=True):
        self.info = info
        self.cli = cli
        self.randomize = randomize
        self.agents = self.info.spawn.num_agents()
        self.attrs = [[] for _ in range(self.agents)]
        self.lstigs = [[] for _ in range(self.agents)]
        self.sched = None
        self.picks = {}
        self.is_setup = False
        if randomize:
            self.s = Optimize()
            set_option(":auto_config", False)
            set_option(":smt.phase_selection", 5)
            set_option(":smt.random_seed", int(RND_SEED))
            random.seed(RND_SEED)
            # Force incremental solver
            self.s.push()
        else:
            self.s = Solver()

    def setup(self, picks):
        if not self.is_setup:
            self._concretize_initial_state()
            self._concretize_scheduler()
            for p in picks:
                self.add_pick(*p)

    def isAnAgent(self, var):
        return And(var >= 0, var < self.agents)

    def _add_soft_constraints(self):
        for tid in range(self.agents):
            a = self.info.spawn[tid]
            for i, attr in enumerate(self.attrs[tid]):
                v = get_var(a.iface, i)
                self.s.add_soft(attr == v.rnd_value())

    def _init_constraint(self, v, attrs):
        def c(attr):
            if isinstance(v.values, range):
                return And(attr >= v.values.start, attr < v.values.stop)
            elif isinstance(v.values, list):
                return Or(*(attr == int(x) for x in v.values))
            else:
                return (attr == int(v.values))
        self.s.add(*(c(a) for a in attrs))

    def _concretize_initial_state(self):
        for tid in range(self.agents):
            a = self.info.spawn[tid]
            for v in a.iface.values():
                attrs = ([
                    Int(f"I_{tid:0>2}_{i:0>2}")
                    for i in range(v.index, v.index + v.size)
                    ]
                    if v.is_array
                    else [Int(f"I_{tid:0>2}_{v.index:0>2}")])
                self._init_constraint(v, attrs)
                self.attrs[tid].extend(attrs)
            for v in a.lstig.values():
                lstigs = ([
                    Int(f"L_{tid:0>2}_{i:0>2}")
                    for i in range(v.index, v.index + v.size)
                    ]
                    if v.is_array
                    else [Int(f"L_{tid:0>2}_{v.index:0>2}")])
                self._init_constraint(v, lstigs)
                self.lstigs[tid].extend(lstigs)

        for assume in self.info.assumes:
            formula = QUANT.parseString(assume)[0]
            constraint = quant_to_z3(
                formula, self.info, self.attrs, self.lstigs)
            self.s.add(constraint)

    def _concretize_scheduler(self):
        steps = self.cli[Args.STEPS]
        self.sched = IntVector("sched", steps)
        self.s.add(*(self.isAnAgent(x) for x in self.sched))
        # Round robin scheduler
        if self.cli[Args.FAIR]:
            self.s.add(self.sched[0] == 0)
            self.s.add(*(
                (self.sched[i] == (self.sched[i - 1] + 1) % self.agents)
                for i in range(1, steps)))

    def add_pick(self, name, size):
        size = int(size)
        steps = self.cli[Args.STEPS]

        p = [IntVector(f"{name}_{i}", size) for i in range(steps)]
        for step in range(steps):
            # Picks are agent ids
            self.s.add(*(self.isAnAgent(x) for x in p[step]))
            # No agent picks itselfs as neighbor
            self.s.add(*(x != self.sched[step] for x in p[step]))
            # All picks are different
            self.s.add(*(
                p[step][i] != p[step][j]
                for j in range(size)
                for i in range(j)))
        self.picks[name] = (p, size)

    def concretize_program(self, program):

        def make_regex(placeholder):
            p = re.escape(placeholder)
            return re.compile(
                f'(?<=// ___{p}___)(.*?)(?=// ___end {p}___)',
                re.DOTALL)

        re_pick = re.compile(
            r'TYPEOFVALUES '
            r'([^\[\n]+)\[.+\]; \/\* Pick ([0-9]+) \*\/'
        )

        if self.randomize:
            self._add_soft_constraints()

        picks = re_pick.findall(program)
        for pick_name, _ in picks:
            usages = re.compile(
                f'(?<!TYPEOFVALUES ){re.escape(pick_name)}' +
                r'\[')
            program = usages.sub(f"{pick_name}[__LABS_step][", program)

        globs, inits = self.get_concretization(picks)

        re_globals = make_regex("concrete-globals")
        re_init = make_regex("concrete-init")
        re_sched = make_regex("concrete-scheduler")
        re_sym_sched = make_regex("symbolic-scheduler")
        re_sym_pick = make_regex("symbolic-pick")

        program = re_sym_pick.sub('\n', program)
        program = re_globals.sub(f'\n{globs}\n', program, 1)
        program = re_init.sub(f'\n{inits}\n', program)
        program = re_sched.sub('\nfirstAgent = sched[__LABS_step];\n', program)
        program = re_sym_sched.sub('\n', program)

        return program

    def concretize_file(self, fname):
        with open(fname) as file:
            program = file.read()
        program = self.concretize_program(program)
        with open(fname, "w") as file:
            file.write(program)

    def get_concretization(self, picks):
        
        def fmt_globals(m):
            STEPS = self.cli[Args.STEPS]

            def fmt_intvec(vec):
                return f"""{{ {",".join(str(m[x]) for x in vec)} }}"""

            def fmt_pick(p, name, size):
                rows = ", ".join(fmt_intvec(row) for row in p)
                return f"TYPEOFAGENTID {name}[{STEPS}][{size}] = {{ {rows} }};"

            picks = (fmt_pick(p, n, s) for n, (p, s) in self.picks.items())
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
                for attr in self.attrs[tid])
                + "\n" + "\n".join(
                f"Lvalue[{tid}][{index(attr)}] = {m[attr]};"
                for tid in range(self.agents)
                for attr in self.lstigs[tid]))

        self.setup(picks)

        if self.s.check() == sat:
            m = self.s.model()
            # Avoid getting the same model in future
            block = []
            for decl in m:
                const = decl()
                block.append(const != m[decl])
            if block:
                self.s.add(Or(block))

            return fmt_globals(m), fmt_inits(m)
        else:
            return None, None