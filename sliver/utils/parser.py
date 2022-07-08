#!/usr/bin/env python3

import argparse
from pathlib import Path
from sys import exit, stderr

import pyparsing as pp
from pyparsing import (Combine, FollowedBy, Forward, Group, Keyword, Literal,
                       OneOrMore, Optional, ParserElement, ParseResults,
                       SkipTo, Suppress, Word, ZeroOrMore, alphanums, alphas,
                       delimitedList, infixNotation, oneOf, opAssoc,
                       printables)
from pyparsing import pyparsing_common as ppc
from pyparsing import pythonStyleComment, ungroup

ParserElement.enablePackrat()

LBRACE, \
    RBRACE, LBRACK, RBRACK, EQ, COLON,\
    SEMICOLON, COMMA, LPAR, RPAR, RAWPREFIX = map(Suppress, "{}[]=:;,()$")
NoWhite = pp.NotAny(pp.White())

kws = oneOf("and or not id true false")

VARNAME = Word(alphas.lower(), alphanums + "_").ignore(kws)
# TODO reserve keywords in IDENTIFIER
IDENTIFIER = Word(alphas.upper(), alphanums).ignore(Keyword("Skip"))
EXTERN = Combine(Literal("_") + VARNAME)


def konst(val):
    def f(*args, **kwargs):
        return val
    return f


def to_sexpr(name, add=None):
    def fn(toks):
        return [name, *toks, *add] if add else [name, *toks]
    return fn


def to_list(toks):
    if len(toks) > 1:
        return ["list", *toks]
    else:
        return toks


def combinator(name):
    def fn(toks):
        return [name, *toks] if len(toks) > 1 else toks[0]
    return fn


def named_list(name, thing, sep=SEMICOLON):
    return (
        Keyword(name).suppress() + EQ + delimitedList(thing, sep)
    ).setResultsName(name).setName(name)


def to_prefix(toks):
    t = "/=" if toks[1] == "!=" else toks[1]
    return [t, toks[0], *toks[2:]]


def to_prefix_expr(toks):
    return [[t[1], t[0], *t[2:]] for t in toks.asList()]


BUILTIN = (
    Keyword("abs") |
    Keyword("min") |
    Keyword("max")
)


def baseVarRefParser(pexpr):
    ARRAY_INDEX = Suppress("[") + pexpr + Suppress("]")
    return (VARNAME + Optional(NoWhite + ARRAY_INDEX)).setParseAction(
        lambda toks: toks if len(toks) == 1 else [["#array", *toks]])


def linkVarRefParser(pexpr):
    ARRAY_INDEX = Suppress("[") + pexpr + Suppress("]")
    return Group(
        VARNAME + Optional(NoWhite + ARRAY_INDEX)
        + Keyword("of").suppress() + (
            Keyword("1") | Keyword("2") | Keyword("c1") | Keyword("c2"))
    ).setParseAction(lambda t: [["#var-of", t[0][0], f"\"a{t[0][1][-1]}\""]])


def makeExprParsers(pvarrefMaker):
    EXPR = Forward()
    VARREF = pvarrefMaker(EXPR)

    FUNCTIONNAME = Word(alphas + "_", printables, excludeChars="#(")
    RAWCALL = (
        Combine(RAWPREFIX + FUNCTIONNAME + LPAR)
        + Optional(delimitedList(EXPR))
        + RPAR
    ).setParseAction(to_sexpr("#raw"))

    EXPRATOM = (
        ppc.signed_integer |
        Keyword("id").setParseAction(konst("#self")) |
        Group(RAWCALL) |
        Group(Combine(BUILTIN + LPAR) + delimitedList(EXPR) + RPAR) |
        (VARREF ^ VARNAME) |
        EXTERN)

    EXPR <<= infixNotation(EXPRATOM, [
        ("%", 2, opAssoc.LEFT, to_prefix_expr),
        (oneOf("* /"), 2, opAssoc.LEFT, to_prefix_expr),
        (oneOf("+ - "), 2, opAssoc.LEFT, to_prefix_expr)])

    BEXPR = Forward()

    def unwrap_tf(lst):
        return (
            lst[0][0]
            if all((
                len(lst) == 1,
                len(lst[0]) == 1,
                lst[0][0] in ("#t", "#f")))
            else lst)

    BEXPRATOM = (
        Keyword("true").setParseAction(konst("#t")) |
        Keyword("false").setParseAction(konst("#f")) |
        (EXPR + oneOf("> < = >= <= !=") + EXPR).setParseAction(to_prefix))

    BEXPR <<= infixNotation(Group(BEXPRATOM), [
        (Keyword("and"), 2, opAssoc.LEFT, to_prefix_expr),
        (Keyword("or"), 2, opAssoc.LEFT, to_prefix_expr)
        # TODO other operators
        ]).setParseAction(unwrap_tf)
    return Group(EXPR), BEXPR


EXPR, BEXPR = makeExprParsers(baseVarRefParser)
VARREF = baseVarRefParser(EXPR)
_, LINKBEXPR = makeExprParsers(linkVarRefParser)

INITIALIZER = (
    LBRACK + delimitedList(ungroup(EXPR)) + RBRACK |
    Group((ungroup(EXPR) + Suppress("..") + ungroup(EXPR)).setParseAction(to_sexpr("#range"))) |  # noqa: E501
    ungroup(EXPR)
)

PROC = Forward()


def group_list(toks):
    x = to_list(toks)
    try:
        if x and x[0] == "list":
            return [x]
        else:
            return x
    except TypeError:
        return x


PROCBASE = (
    (
        FollowedBy(BEXPR) + BEXPR + Suppress("->") + Group(PROC)
    ).setParseAction(to_sexpr("#guard")).setName("guarded") |
    (Keyword("Skip").setParseAction(konst(["skip"]))) |
    IDENTIFIER.copy().setParseAction(to_sexpr("#call")).setName("call") |
    (
        delimitedList(VARREF).setParseAction(group_list) +
        Suppress("<--") +
        delimitedList(ungroup(EXPR)).setParseAction(group_list)
    ).setParseAction(to_sexpr("assign-env")).setName("assign-env") | (
        delimitedList(VARREF).setParseAction(group_list) +
        Suppress("<~") +
        delimitedList(ungroup(EXPR)).setParseAction(group_list)
    ).setParseAction(to_sexpr("assign-lstig")).setName("assign-lstig") | (
        delimitedList(VARREF).setParseAction(group_list) +
        Suppress("<-") +
        delimitedList(ungroup(EXPR)).setParseAction(group_list)
    ).setParseAction(to_sexpr("assign-attr")).setName("assign-attr")
)


PAREN = (LPAR + Group(PROC) + RPAR).setName("__paren__")
SEQ = (delimitedList(PAREN | Group(PROCBASE), SEMICOLON)).setParseAction(combinator("#seq"))  # noqa: E501
CHOICE = delimitedList(Group(SEQ), Literal("++")).setParseAction(combinator("#choice"))  # noqa: E501
PROC <<= delimitedList(Group(CHOICE), Literal("||")).setParseAction(combinator("#par"))  # noqa: E501

PROCDEF = (
    IDENTIFIER.copy().setName("def-head").setResultsName("name") + EQ +
    Group(PROC).setName("def-body").setResultsName("body")
)

SYSTEM = Group(Keyword("system").suppress() + LBRACE + (
        Optional(named_list("extern", EXTERN, COMMA)) &
        Optional(named_list("environment", Group(VARREF + COLON + INITIALIZER)))  # noqa: E501
    ) +
    named_list("spawn", Group(IDENTIFIER + COLON + ungroup(EXPR)), COMMA) +
    ZeroOrMore(Group(PROCDEF)).setResultsName("processes") +
    RBRACE)

TUPLEDEF = (
    Group(delimitedList(VARNAME)) + COLON +
    Group(delimitedList(INITIALIZER))
).setParseAction(lambda toks: list(zip(toks[0], toks[1])))

STIGMERGY = (
    Keyword("stigmergy").suppress() + IDENTIFIER.setResultsName("name") +
    LBRACE +
    Keyword("link").suppress() + EQ + LINKBEXPR.setResultsName("link") +
    ZeroOrMore(Group(TUPLEDEF)).setResultsName("tuples") +
    SkipTo(RBRACE).suppress() +
    RBRACE)

AGENT = (
    Keyword("agent").suppress() + IDENTIFIER.setResultsName("name") +
    LBRACE + (
        Optional(named_list("interface", Group(VARREF + COLON + INITIALIZER)))  # noqa: E501
        & Optional(named_list("stigmergies", IDENTIFIER))) +
    OneOrMore(Group(PROCDEF)).setResultsName("processes") +
    RBRACE)

ASSUME = (
    Keyword("assume").suppress() + LBRACE +
    SkipTo(RBRACE) +
    RBRACE)

CHECK = (
    Keyword("check").suppress() + LBRACE +
    SkipTo(RBRACE) +
    RBRACE)

FILE = (
    SYSTEM.setResultsName("system") +
    ZeroOrMore(Group(STIGMERGY)).setResultsName("stigmergies") +
    OneOrMore(Group(AGENT)).setResultsName("agents") +
    Optional(ASSUME.setResultsName("assume")) +
    CHECK.setResultsName("check")
).ignore(pythonStyleComment)


def walk_flat(lst):
    if type(lst) in (list, tuple, ParseResults):
        for x in lst:
            yield from walk_flat(x)
    else:
        yield lst


def walk_and_print(thing):
    if type(thing) in (str, int):
        print(thing, end=" ")
    elif type(thing) in (list, tuple, ParseResults):
        print("(", end=" ")
        for v in thing:
            walk_and_print(v)
        print(")", end=" ")


def fix_scope(process, agent):
    """Fixes all process constants within `process`

    If `process` contains a constant `K` and `agent` contains a local
    definition for `K`, we replace `K` with `<agent.name>_K`.

    This is needed because Masseur has no concept of local vs. global process
    definitions.
    """
    local_names = set(p.name for p in agent.processes)

    def walk(x):
        if type(x) is list:
            return [walk(y) for y in x]
        elif type(x) is str and x in local_names:
            return f"{agent.name}_{x}"
        else:
            return x
    return walk(process)


def add_stigmergy_vars(process, vars):
    """Adds stigmergy variables that must be confirmed to actions"""
    def walk(lst, vars_guards):
        if type(lst) is list and len(lst):
            if type(lst[0]) is str:
                if lst[0] == "#guard":
                    v = set(x for x in walk_flat(lst[1]) if x in vars)
                    return [lst[0], lst[1], *(walk(lst[2:], vars_guards | v))]
                elif lst[0] == "#seq":
                    return [lst[0], walk(lst[1], vars_guards), *(walk(lst[2:], set()))]  # noqa: E501
                elif lst[0] == "skip":
                    return [lst[0], to_list([["#index-of", x] for x in vars_guards])]  # noqa: E501

                elif lst[0].startswith("assign"):
                    found_vars = set(x for x in walk_flat(lst[2:]) if x in vars)  # noqa: E501
                    return [*lst, to_list([["#index-of", x] for x in (found_vars | vars_guards)])]  # noqa: E501
                else:
                    return [walk(x, vars_guards) for x in lst]
            else:
                return [walk(x, vars_guards) for x in lst]
        else:
            return lst
    return walk(process, set())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Translate LAbS to Masseur')
    parser.add_argument('file', type=Path, help='LAbS file to translate')

    args = parser.parse_args()
    # with open("../labs/labs-examples/formation-safety.labs") as f:
    with open(args.file) as f:
        # ast = FILE.setDebug().parseFile(f)
        ast = FILE.parseFile(f)

    stigmergy_vars = set(
        var[0]
        for lstig in ast.stigmergies
        for t in lstig.tuples
        for var in t)

    if "system" not in ast:
        print("missing 'system'", file=stderr)
        exit(1)

    # compute_ids(ast.system.spawn.asList())

    if "extern" in ast.system:
        walk_and_print(["#params", *ast.system.extern])
        print()

    if "environment" in ast.system:
        walk_and_print(["#shared-vars", *ast.system.environment.asList()])
        print()
    # We use a dictionary because we want to remember the insertion order
    repl = {var[0]: None for a in ast.agents for var in a.interface}
    # Add stigmergic variables (in order):
    repl.update({
        var[0]: None
        for lstig in ast.stigmergies
        for t in lstig.tuples
        for var in t})

    walk_and_print(["#replicated-vars", *repl.keys()])
    print()

    if stigmergy_vars:
        walk_and_print(["#system", *ast.system.spawn.asList(), ["#raw", "propagate"], ["#raw", "confirm"]])  # noqa: E501
    else:
        walk_and_print(["#system", *ast.system.spawn.asList()])  # noqa: E501
    print()

    for p in ast.system.processes:
        walk_and_print(["#def", p.name, p.body.asList()])

    for agent in ast.agents:
        # TODO fail if "Behavior" is not defined
        behavior = [p for p in agent.processes if p.name == "Behavior"][0]
        # If Behavior is in the form "Behavior = <other constant>", use
        # <other constant> directly as the behavior of the agent
        b = (
            behavior.body[1]
            if behavior.body[0] == "#call"
            else f"{agent.name}_Behavior")
        b = fix_scope(b, agent)

        agent_stigmergy_vars = [
            var for lstig in ast.stigmergies
            for t in lstig.tuples for var in t
            if lstig.name in agent.stigmergies.asList()]

        agent_masseur = [
            "#agent", agent.name, b,
            *agent.interface.asList(),
            *agent_stigmergy_vars]
        walk_and_print(agent_masseur)
        print()

        for p in agent.processes:
            new_p = fix_scope(p.body.asList(), agent)
            new_p = add_stigmergy_vars(new_p, stigmergy_vars)
            walk_and_print(["#def", agent.name+"_"+p.name, new_p])
            print()

    links = [
        ['"link"', v[0], lstig.link]
        for lstig in ast.stigmergies
        for t in lstig.tuples
        for v in t]

    try:
        maxTuple = max(len(t) for lstig in ast.stigmergies for t in lstig.tuples)  # noqa: E501
        labs_links_tuples = (
            "#template", "lstig",
            ['"maxTuple"', maxTuple],
            *[('"tuple"', *[v[0] for v in t]) for lstig in ast.stigmergies for t in lstig.tuples],  # noqa: E501
            *links)
        walk_and_print(labs_links_tuples)
        print()
    except ValueError:
        # max(x) raises ValueError when x is empty.
        # In such a case there are no stigmergies
        # and we don't need to print anything
        pass
