import re

from pyparsing import (Word, alphanums, delimitedList, OneOrMore,
                       Forward, Suppress, Group, ParserElement, Keyword,
                       replaceWith, dblQuotedString, removeQuotes,
                       SkipTo, LineEnd, printables, Optional, StringEnd)
from pyparsing import pyparsing_common as ppc

ATTR = re.compile(r"I\[([0-9]+)l?\]\[([0-9]+)l?\]")
LSTIG = re.compile(r"Lvalue\[([0-9]+)l?\]\[([0-9]+)l?\]")
LTSTAMP = re.compile(r"Ltstamp\[([0-9]+)l?\]\[([0-9]+)l?\]")
ENV = re.compile(r"E\[([0-9]+)l?\]")
STEP = re.compile(r"__LABS_step")

PROPAGATE = re.compile(r"propagate_or_confirm=TRUE")
CONFIRM = re.compile(r"propagate_or_confirm=FALSE")


UNDEF = "16960"


BOOLEAN = (
    Keyword("TRUE").setParseAction(replaceWith(True)) |
    Keyword("FALSE").setParseAction(replaceWith(False)))


def pprint_agent(info, tid):
    return f"{info.spawn[int(tid)]} {tid}"


def translateCPROVER(cex, fname, info, offset=-1):
    def pprint_assign(var, value, tid="", init=False):
        def fmt(match, store_name, tid):
            tid = match[1] if len(match.groups()) > 1 else tid
            k = match[2] if len(match.groups()) > 1 else match[1]
            agent = f"{pprint_agent(info, tid)}:" if tid else ""
            assign = info.pprint_assign(store_name, int(k), value)
            # endline = " " if not(init) and store_name == "L" else "\n"
            return f"\n{agent}\t{assign}"
        is_attr = ATTR.match(var)
        if is_attr and info.i:
            return fmt(is_attr, "I", tid)
        is_env = ENV.match(var)
        if is_env:
            return fmt(is_env, "E", tid)
        is_lstig = LSTIG.match(var)
        if is_lstig:
            return fmt(is_lstig, "L", tid)
        is_ltstamp = LTSTAMP.match(var)
        if is_ltstamp:
            return f" [{value}]"
        return None

    STATE, FILE, FN, LINE, THREAD = (
        Keyword(tk).suppress() for tk in
        ("State", "file", "function", "line", "thread"))
    LBRACE, RBRACE = map(Suppress, "{}")
    SEP = Keyword("----------------------------------------------------")
    STUFF = Word(printables)
    INFO = FILE + STUFF + FN + STUFF +\
        LINE + ppc.number() + THREAD + ppc.number()

    TRACE_INFO = STATE + ppc.number() + INFO
    VAR = Word(printables, excludeChars="=")
    RECORD = Forward()
    VAL = ((ppc.number() + Optional(Suppress("u"))) | BOOLEAN | Group(RECORD))
    RECORD <<= (LBRACE + delimitedList(VAL) + RBRACE)

    ASGN = VAR + Suppress("=") + VAL + SkipTo(LineEnd()).suppress()

    TRACE = OneOrMore(Group(Group(TRACE_INFO) + SEP.suppress() + Group(ASGN)))

    cex_start_pos = cex.find("Counterexample:") + 15
    cex_end_pos = cex.find("Violated property:")
    states = TRACE.parseString(cex[cex_start_pos:cex_end_pos])

    inits = (
        l[1] for l in states
        if l[0][2] == "init" and not(LTSTAMP.match(l[1][0])))
    others = [l[1] for l in states if l[0][2] != "init"]
    yield "<initialization>"
    for i in inits:
        pprint = pprint_assign(*i, init=True)
        if pprint:
            yield pprint
    yield "\n<end initialization>"

    agent = ""
    system = None
    for i, (var, value) in enumerate(others):
        if var == "__LABS_step":
            if system:
                yield f"\n<end {system}>"
                system = None
        elif var == "propagate_or_confirm":
            system = "propagate" if value else "confirm"
            yield f"\n<{pprint_agent(info, agent)}: {system} "
        elif var == "guessedkey":
            yield f"'{info.lstig[int(value)].name}'>"
        elif var == "firstAgent":
            agent = value
        else:
            if all((len(others) > i + 1, LSTIG.match(var),
                    LTSTAMP.match(others[i + 1][0]))):
                pprint = pprint_assign(var, value, agent, endline=" ")
            else:
                pprint = pprint_assign(var, value, agent)
            if pprint:
                yield pprint

    prova = cex[cex_end_pos + 18:]
    END_TRACE = INFO + Suppress(SkipTo(StringEnd()))
    P_NAME = Suppress(SkipTo(",", include=True)) + Word(alphanums) + \
        Suppress(SkipTo(StringEnd()))
    prop = END_TRACE.parseString(prova)
    with open(prop[0]) as f:
        c_program = f.readlines()
        prop = P_NAME.parseString(c_program[prop[2] - 1])
        yield f"\n<property violated: '{prop[0]}'>\n"


def translate_cadp(cex, info):
    def pprint_init_agent(args):
        tid, iface = args[1], args[2][1:]
        agent = pprint_agent(info, tid)
        init = "".join(
            f"{agent}:\t{info.pprint_assign('I', int(k), v)}\n"
            for k, v in enumerate(iface))
        if len(args) == 4:
            return init

        lstig = args[3][1:]
        init += "".join(
            f"{agent}:\t{info.pprint_assign('L', int(k), v[1])},{v[2]}\n"
            for k, v in enumerate(lstig)
        )
        return init

    def pprint_init_env(args):
        return "".join(
            f"\t{info.pprint_assign('E', int(k), v)}\n"
            for k, v in enumerate(args[1:]))

    def good_line(l):
        if l.startswith("\"ACTION"):
            return l[9:-1]
        elif l.startswith("\"MONITOR"):
            return l[1:-1]
        else:
            return None

    lines = [good_line(l) for l in cex.split('\n') if good_line(l)]
    inits = sorted(l for l in lines if l.startswith("AGENT"))
    init_env = (l for l in lines if l.startswith("ENV"))
    others = (l for l in lines
              if not (l.startswith("AGENT") or l.startswith("ENV")))

    ParserElement.setDefaultWhitespaceChars(' \t\n\x01\x02')
    NAME = Word(alphanums)
    LPAR, RPAR = map(Suppress, "()")
    RECORD = Forward()
    OBJ = (ppc.number() | BOOLEAN | Group(RECORD))
    RECORD <<= (NAME + LPAR + delimitedList(OBJ) + RPAR)

    QUOTES = dblQuotedString.setParseAction(removeQuotes)
    ASGN = QUOTES + OneOrMore(Suppress("!") + OBJ)
    MONITOR = (Keyword("MONITOR") + Suppress("!") + (BOOLEAN | QUOTES))
    STEP = ppc.number() | ASGN | MONITOR

    yield "<initialization>\n"
    yield from (pprint_init_env(RECORD.parseString(l)) for l in init_env if l)
    yield from (pprint_init_agent(RECORD.parseString(l)) for l in inits if l)
    yield "<end initialization>\n"

    sys_step = re.compile(r"(?:end )?(?:confirm|propagate)")

    for l in others:
        step = STEP.parseString(l, parseAll=True)
        if step[0] == "MONITOR" and step[1] == "deadlock":
            yield "<deadlock>\n"
        elif step[0] == "MONITOR":
            yield f"""<property {"satisfied" if step[1] else "violated"}>\n"""
        elif step[0] == "E":
            agent = pprint_agent(info, step[1])
            yield f"{agent}:\t{info.pprint_assign(*step[:3])}\n"
        elif step[0] == "I":
            agent = pprint_agent(info, step[1])
            yield f"{agent}:\t{info.pprint_assign(step[0], *step[2:4])}\n"
        elif step[0] == "L":
            agent = pprint_agent(info, step[1])
            val = f"{step[3][1]},{step[3][2]}"
            yield f"{agent}:\t{info.pprint_assign(step[0], step[2], val)}\n"
        elif sys_step.match(step[0]):
            yield (
                f"<{pprint_agent(info, step[1])}: {step[0]} "
                f"'{info.pprint_var(info.lstig, step[2])}'>\n")
        else:
            yield f"<could not parse: {step}>\n"
