#!/usr/bin/env python3

"""Functions and classes to obtain and represent structured information
about a LAbS system
"""
import re
from ast import NodeVisitor, parse
from random import choice


class LabsExprVisitor(NodeVisitor):
    def __init__(self, _id):
        self.id = _id

    def visit_string(self, s):
        return self.visit(parse(s))

    def visit_Module(self, node):
        return self.visit(node.body[0])

    def visit_Expr(self, node):
        return self.visit(node.value)

    def visit_Num(self, node):
        return node.n

    def visit_Name(self, node):
        return self.id if node.id == "id" else None

    def visit_BinOp(self, node):
        lvalue, rvalue = self.visit(node.left), self.visit(node.right)
        return self.visit(node.op)(lvalue, rvalue)

    def visit_UnaryOp(self, node):
        return self.visit(node.op)(self.visit(node.operand))

    def visit_Mod(self, node):
        return lambda x, y: x % y

    def visit_Add(self, node):
        return lambda x, y: x + y

    def visit_Sub(self, node):
        return lambda x, y: x - y

    def visit_Mult(self, node):
        return lambda x, y: x * y

    def visit_Div(self, node):
        return lambda x, y: x // y

    def visit_USub(self, node):
        return lambda x: -x

    def visit_UAdd(self, node):
        return lambda x: +x

    def visit_Call(self, node):
        if node.func.id == "abs":
            return abs(self.visit(node.args[0]))
        else:
            raise ValueError


class Info(object):
    def __init__(self, spawn, e, props, assumes, raw, externs):
        self.spawn = spawn
        self.i = {}
        self.lstig = {}
        self.pcs_raw = []
        self.externs = externs
        self.properties = tuple(p for p in props.split(";") if p)
        self.assumes = tuple(p for p in assumes.split(";") if p)
        for c in spawn.values():
            self.i.update(c.iface)
            self.lstig.update(c.lstig)
        self.e = {i: v for i, v in enumerate(e)}
        self.raw = raw

    def scan_pcmap(self, code):
        self.pcs_raw = [ln.strip() for ln in code.splitlines() if "//PC//" in ln]  # noqa: E501

    def get_pc_invariants(self):
        pattern = re.compile(r"[^\/]*\/\/PC\/\/([^=]+)=(.+)")
        result = []
        for raw in self.pcs_raw:
            match = pattern.match(raw)
            agent, cond = match.group(1), match.group(2)
            result.extend(
                cond.replace("$tid$", str(tid))
                for tid in self.spawn.tids(agent))
        return result

    @staticmethod
    def parse(txt, externs=[]):
        if not txt:
            raise ValueError("empty info")
        """Deserialize system info
        """
        lines = txt.split("|")
        envs, comps, props, assumes, picks = (
            lines[0], lines[1:-2], lines[-3], lines[-2], lines[-1])
        parsed_extern = [ex.split("=") for ex in externs]
        return Info(
            spawn=Spawn.parse(comps, picks),
            e=[Variable(*v.split("=")) for v in envs.split(";") if v],
            props=props,
            assumes=assumes,
            externs={e[0]: e[1] for e in parsed_extern},
            raw=txt)

    @staticmethod
    def _max_of(v):
        if v.is_array:
            return v.index + v.size - 1
        else:
            return v.index

    def max_key_i(self):
        if not self.i:
            return -1
        return max(self._max_of(v) for v in self.i.values())

    def max_key_lstig(self):
        if not self.lstig:
            return -1
        return max(self._max_of(v) for v in self.lstig.values())

    def lookup_var(self, name):
        """Finds a variable by name"""
        def _lookup(store):
            match = [store[x] for x in store if store[x].name == name] or None
            return match[0] if match else None

        match = _lookup(self.e)
        if match:
            return match
        match = _lookup(self.i)
        if match:
            return match
        match = _lookup(self.lstig)
        if match:
            return match
        raise KeyError(name)

    def pprint_var(self, store, key):
        v = get_var(store, key)
        if v.is_array:
            return "{}[{}]".format(v.name, key - v.index)
        else:
            return v.name

    def pprint_agent(self, tid):
        return "{} {}".format(self.spawn[int(tid)], tid)

    def pprint_assign(self, where, key, value):
        store, arrow = {
            "E": (self.e, "<--"),
            "I": (self.i, "<-"),
            "L": (self.lstig, "<~")}[where]
        return "{} {} {}".format(self.pprint_var(store, key), arrow, value) \
               if store else ""

    def instrument(self):

        def fmt(location, var, offset=0):
            return [
                (TYPE, location, offset + var.index + i, var.rnd_value())
                for i in range(var.size)
            ]

        TYPE = "short"
        out = [fmt("E", x) for x in self.e.values()]
        for (low, up), agent in self.spawn.items():
            i_length = len(agent.iface)
            out.extend(
                fmt("I", x, n * i_length)
                for n in range(low, up)
                for x in agent.iface.values())
            out.extend(
                fmt("Lvalue", x, n * i_length)
                for n in range(low, up)
                for x in agent.lstig.values())
        # Return the flattened list
        return (x for lst in out for x in lst)


class Spawn:
    """Maps ids to agents in the system.
    """

    def __init__(self, d):
        self._dict = d

    def picks_of(self, agent_type):
        return self._picks[agent_type]

    def __getitem__(self, key):
        """spawn[tid] returns the agent definition for agent tid
        """
        for (a, b), v in self.items():
            if a <= key < b:
                return v
        raise KeyError

    def range_of(self, agent_type):
        """Returns the id range for the given type
        """
        for (a, b), v in self.items():
            if v.name == str(agent_type):
                return range(a, b)
        raise KeyError

    def tids(self, agent_type):
        """Returns all ids of agents of the given type
        """
        return tuple(self.range_of(agent_type))

    def num_agents(self):
        """Returns the total number of agents in the system
        """
        return max(self._dict.keys(), key=lambda x: x[1])[1]

    def values(self):
        """Exposes the values of the internal dictionary
        """
        return self._dict.values()

    def items(self):
        """Exposes the items of the internal dictionary
        """
        return self._dict.items()

    @staticmethod
    def parse(c, picks=""):
        result = {}
        picks = dict([x.split(" ", 1) for x in picks.split(";")])
        picks = {k: v.split("),(") for k, v in picks.items()}
        reg = re.compile(r'\(+([^,]+),')
        for k in picks:
            matches = [reg.match(x) for x in picks[k] if reg.match(x)]
            picks[k] = [m.group(1) for m in matches]

        for comp, iface, lstig in zip(c[::3], c[1::3], c[2::3]):
            name, rng = comp.split(" ")
            compmin, compmax = rng.split(",")
            result[(int(compmin), int(compmax))] = Agent(name, iface, lstig, picks[name])  # noqa: E501

        return Spawn(result)


class Variable:
    """Representation of a single variable
    """

    def __init__(self, index, name, init, store="e"):
        self.index = int(index)
        self.size = 1
        self.store = store
        self.init = init
        if "[" in name:
            self.name, size = name.split("[")
            self.size = int(size[:-1])
            self.is_array = True
        else:
            self.name = name
            self.is_array = False

    def values(self, id):
        visitor = LabsExprVisitor(id)
        if self.init[0] == "[":
            return [
                visitor.visit_string(v)
                for v in self.init[1:-1].split(",")]
        elif ".." in self.init:
            low, up = self.init.split("..")
            return range(
                visitor.visit_string(low),
                visitor.visit_string(up))
        elif self.init == "undef":
            return [-32767]  # UNDEF
        else:
            return [visitor.visit_string(self.init)]

    def rnd_value(self, id):
        """Returns a random, feasible initial value for the variable.
        """
        val = choice(self.values(id))
        return val


def get_var(lst, index):
    """Gets the (possibly array) variable for a given index.

    E.g. if lst contains an array X of size 3 and a scalar Y,
    get_var(lst, 2) returns X
    """
    if type(index) is not int:
        raise TypeError()

    if type(lst) is dict:
        lst = list(lst.values())
        lst.sort(key=lambda x: x.index)

    _len = sum(v.size for v in lst)
    if not (0 <= index < _len):
        raise KeyError("Out of bounds: "+lst+"["+index+"]")
    count = 0
    for v in lst:
        count += v.size
        if count > index:
            return v


class Agent:

    def __init__(self, name, iface, lstig, picks=[]):
        self.name = name
        self.iface = {}
        self.lstig = {}
        self.picks = picks

        if iface != "":
            for txt in iface.split(";"):
                splitted = txt.split("=")
                index, text = splitted[0], splitted[1:]
                self.iface[int(index)] = Variable(int(index), *text, store="i")

        if lstig != "":
            for txt in lstig.split(";"):
                splitted = txt.split("=")
                index, text = splitted[0], splitted[1:]
                self.lstig[int(index)] = Variable(int(index), *text, store="lstig")  # noqa: E501

    def __str__(self):
        return self.name
