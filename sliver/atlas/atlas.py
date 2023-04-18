#! /usr/bin/env python3

from collections import namedtuple

from pyparsing import (Combine, Forward, Group, Keyword, Optional,
                       ParserElement, Suppress, Word, alphanums, alphas,
                       delimitedList, infixNotation, oneOf, opAssoc)
from pyparsing import pyparsing_common as ppc

ParserElement.enablePackrat()

LPAR, RPAR, LBRAK, RBRAK, COMMA = map(Suppress, "()[],")
kws = oneOf("and or not id true false forall exists")
BUILTIN = oneOf("abs max min not")
VARNAME = Word(alphas.lower(), alphanums + "_").ignore(kws).ignore(BUILTIN)
TYPENAME = Word(alphas.upper(), alphanums + "_").ignore(kws).ignore(BUILTIN)
EXTERN = Combine(Suppress("_") + VARNAME).setParseAction(lambda toks: toks[0])

# AST nodes for ATLAS properties
EnvNode = namedtuple("Env", ["var", "offset"])
OfNode = namedtuple("Of", ["var", "offset", "agent"])
BinOp = namedtuple("BinOp", ["e1", "op", "e2"])
BuiltIn = namedtuple("BuiltIn", ["fn", "args"])
Nary = namedtuple("Nary", ["fn", "args"])
Quant = namedtuple("Quant", ["quantifier", "typename", "varname", "inner"])
Prop = namedtuple("Prop", ["modality", "quant"])


def pprint(node):
    if isinstance(node, EnvNode):
        return f"{node.var}"
    if isinstance(node, OfNode):
        return f"{node.var} of {node.agent}"
    if isinstance(node, BinOp):
        return f"({pprint(node.e1)} {node.op} {pprint(node.e2)})"
    elif isinstance(node, BuiltIn):
        return f"{node.fn}({', '.join(pprint(a) for a in node.args)})"
    elif isinstance(node, Nary):
        return "({})".format(f" {node.fn} ".join(pprint(a) for a in node.args))
    else:
        return node


EXPR = Forward()
BEXPR = Forward()
OFFSET = LBRAK + EXPR + RBRAK

EXPRATOM = (
    ppc.signed_integer |
    EXTERN |
    (VARNAME + Optional(OFFSET, default=None) + Keyword("of").suppress() + VARNAME).setParseAction(lambda toks: OfNode(*toks)) |  # noqa: E501
    (Combine(BUILTIN + LPAR) + Group(delimitedList(EXPR)) + RPAR).setParseAction(lambda toks: BuiltIn(*toks)) |  # noqa: E501
    (VARNAME + Optional(OFFSET, default=None)).setParseAction(lambda toks: EnvNode(*toks))  # noqa: E501
)

EXPR <<= infixNotation(EXPRATOM, [
    ("%", 2, opAssoc.LEFT, lambda x:BinOp(*x[0])),
    (oneOf("* /"), 2, opAssoc.LEFT, lambda x:BinOp(*x[0])),
    (oneOf("+ - "), 2, opAssoc.LEFT, lambda x:BinOp(*x[0])),
    (oneOf("> < = >= <= !="), 2, opAssoc.LEFT, lambda x:BinOp(*x[0]))
])


def makeBinOp(args):
    if len(args) <= 3:
        return BinOp(*args)
    elif args[3] in ("and", "or"):
        return Nary(args[3], [x for x in args if x != args[3]])
    else:
        return makeBinOp([makeBinOp(args[:3]), *args[3:]])


BEXPR <<= infixNotation(EXPR, [
    # Note: "not" is implemented as a BuiltIn
    # (oneOf("and or"), 2, opAssoc.LEFT, lambda x:BinOp(*x[0]))
    (Keyword("and"), 2, opAssoc.LEFT, lambda x:makeBinOp(x[0])),
    (Keyword("or"), 2, opAssoc.LEFT, lambda x:makeBinOp(x[0]))
])

QUANT = Forward()
QUANT <<= (
    (Keyword("forall") + TYPENAME + VARNAME + COMMA + QUANT).setParseAction(lambda toks: Quant(*toks)) |  # noqa: E501
    (Keyword("exists") + TYPENAME + VARNAME + COMMA + QUANT).setParseAction(lambda toks: Quant(*toks)) |  # noqa: E501
    BEXPR
)

PROP = (oneOf("always fairly fairly_inf finally") + QUANT).setParseAction(lambda toks: Prop(*toks))  # noqa: E501


def get_state_vars(formula):
    if isinstance(formula, OfNode) or isinstance(formula, EnvNode):
        return set((formula.var, )) if formula.var != "id" else set()
    elif isinstance(formula, Quant):
        return get_state_vars(formula.inner)
    elif isinstance(formula, BinOp):
        return get_state_vars(formula.e1) | get_state_vars(formula.e2)
    elif isinstance(formula, BuiltIn) or isinstance(formula, Nary):
        sets = [get_state_vars(f) for f in formula.args]
        result = set().union(*sets)
        return result
    else:
        return set()


def contains(formula, var):
    """Return True iff formula contains variable var.
    """
    if isinstance(formula, OfNode):
        return formula.agent == var
    elif isinstance(formula, BinOp):
        return contains(formula.e1, var) or contains(formula.e2, var)
    elif isinstance(formula, BuiltIn) or isinstance(formula, Nary):
        return any(contains(f, var) for f in formula.args)
    else:
        return False


def replace_with_string(f, agent):
    # TODO extend to arrays (check f.offset)
    return f"{f.var}_{agent}"


def remove_quant(formula, quant, var, agents, fn=replace_with_string):
    """Remove the given quantified variable from formula.
    """

    map_quant = {"forall": "and", "exists": "or"}
    new_vars = set()

    def replace_with(f, agent):
        nonlocal new_vars
        if isinstance(f, OfNode) and f.agent == var:
            if f.var == "id":
                return agent
            v = fn(f, agent)
            new_vars.add(v)
            return v
        elif isinstance(f, BinOp):
            return BinOp(replace_with(f.e1, agent), f.op, replace_with(f.e2, agent))  # noqa: E501
        elif isinstance(f, BuiltIn):
            return BuiltIn(f.fn, [replace_with(f, agent) for f in f.args])
        elif isinstance(f, Nary):
            return Nary(f.fn, [replace_with(f, agent) for f in f.args])
        else:
            return f
    return (
        Nary(map_quant[quant], [replace_with(formula, a) for a in agents]),
        new_vars)


def replace_externs(f, externs):
    def recurse(f):
        return replace_externs(f, externs)
    if isinstance(f, str) and f in externs:
        return externs[f]
    elif isinstance(f, BinOp):
        return BinOp(recurse(f.e1), f.op, recurse(f.e2))  # noqa: E501
    elif isinstance(f, BuiltIn):
        return BuiltIn(f.fn, [recurse(f) for f in f.args])
    elif isinstance(f, Nary):
        return Nary(f.fn, [recurse(f) for f in f.args])
    elif isinstance(f, Quant):
        return Quant(f.quantifier, f.typename, f.varname, recurse(f.inner))
    else:
        return f


def make_dict(formula):
    """Return a dictionary mapping quantified variable names
    to their quantifier and the type of agent being ranged over.
    """
    if isinstance(formula, Quant):
        inner_dict, inner_formula = make_dict(formula.inner)
        if formula.varname in inner_dict:
            raise Exception(
                f"Multiple definitions for variable {formula.varname}")
        inner_dict[formula.varname] = (formula.quantifier, formula.typename)  # noqa: E501
        return inner_dict, inner_formula
    else:
        return {}, formula


def get_quant_formula(info, prop=None):
    if not prop:
        prop = info.properties[0]
    return PROP.parseString(prop)


def get_formula(info, externs, prop=None, parsed=None):
    """Extract the 1st property in info.properties and
    turn it into a propositional formula (via quantifier elimination.)

    Return: the propositional formula, the set of variables introduced
    by quantifier elimination, and the property's temporal modality.
    """
    if parsed is None:
        parsed = get_quant_formula(info, prop)

    d, formula = make_dict(parsed[0].quant)

    # remove quantifiers
    # and collect variables created by quantifier elimination
    new_vars = set()
    for var in d:
        quant, agent_type = d[var]
        if contains(formula, var):
            formula, nv = remove_quant(formula, quant, var, info.spawn.tids(agent_type))  # noqa: E501
            new_vars = new_vars.union(nv)

    formula = replace_externs(formula, externs)

    return formula, new_vars, parsed[0].modality
