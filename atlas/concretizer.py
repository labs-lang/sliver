import enum
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
        self._concretize_initial_state()
        self._concretize_scheduler()
        self.neigs = self._concretize_neigs()

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
        self.s.add(*(s >= 0 for s in self.sched))
        self.s.add(*(s < self.agents for s in self.sched))
        # Round robin scheduler
        if self.cli[Args.FAIR]:
            self.s.add(self.sched[0] == 0)
            self.s.add(*(
                (self.sched[i] == (self.sched[i - 1] + 1) % self.agents)
                for i in range(1, steps)))

    # TODO: generalize below to any nondet variable?
    def _concretize_neigs(self):
        NEIGS = self.info.externs["neigs"]
        steps = self.cli[Args.STEPS]
        neigs = [BoolVector(f"neigs_{i}", self.agents) for i in range(steps)]
        for step in range(steps):
            for a in range(self.agents):
                # No agent selects itselfs as neighbor
                self.s.add(Or(a != self.sched[step], Not(neigs[step][a])))
            # Number of neighbors equals NEIGS
            self.s.add(Count(neigs[step]) == NEIGS)
        return neigs

    def concretize_file(self, fname):
        if self.randomize:
            self._add_soft_constraints()

        globs, inits = self.get_concretization()
        places = {
            "// ___concrete-globals___": None,
            "// ___end concrete-globals___": None,
            "// ___concrete-init___": None,
            "// ___end concrete-init___": None,
            "// ___concrete-scheduler___": None,
            "// ___end concrete-scheduler___": None,
            "// ___symbolic-scheduler___": None,
            "// ___end symbolic-scheduler___": None
        }

        with open(fname) as file:
            lines = file.readlines()

        for i, line in enumerate(lines):
            for placeholder in places:
                if placeholder in line:
                    places[placeholder] = i

        with open(fname, "w") as file:
            file.writelines(lines[:places["// ___concrete-globals___"] + 1])
            file.write(globs)
            file.write("\n")
            file.writelines(lines[places["// ___end concrete-globals___"]:places["// ___concrete-init___"] + 1])
            file.write(inits)
            file.write("\n")
            file.writelines(lines[places["// ___end concrete-init___"]:places["// ___concrete-scheduler___"] + 1])
            file.write("firstAgent = sched[__LABS_step];\n")
            file.writelines(lines[places["// ___end concrete-scheduler___"]:places["// ___symbolic-scheduler___"] + 1])
            file.writelines(lines[places["// ___end symbolic-scheduler___"]:])


    def get_concretization(self):
        def fmt_globals(m, neigs):
            STEPS, AGENTS = self.cli[Args.STEPS], self.agents

            def fmt_step(row):
                return ", ".join("1" if m[x] else "0" for x in row)
            return (
                f"TYPEOFAGENTID sched[{STEPS}] = {{"
                + ",".join(str(m[x]) for x in self.sched)
                + "};\n"
                + f"_Bool is_neig[{STEPS}][{AGENTS}] = {{"
                + ", ".join(f"{{{ fmt_step(row) }}}"for row in neigs)
                + "};\n")

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

        if self.s.check() == sat:
            m = self.s.model()
            # Avoid getting the same model in future
            block = []
            for decl in m:
                const = decl()
                block.append(const != m[decl])
            if block:
                self.s.add(Or(block))

            return fmt_globals(m, self.neigs), fmt_inits(m)
        else:
            return None, None
