import re

from pyparsing import (Word, alphanums, delimitedList, OneOrMore, ZeroOrMore,
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
            agent = f"{pprint_agent(info, tid)}:" if tid != "" else ""
            assign = info.pprint_assign(store_name, int(k), value)
            # endline = " " if not(init) and store_name == "L" else "\n"
            return f"\n{agent}\t{assign}"
        is_attr = ATTR.match(var)
        is_env = ENV.match(var)
        is_lstig = LSTIG.match(var)
        if is_attr and info.i:
            return fmt(is_attr, "I", tid)
        elif is_env:
            return fmt(is_env, "E", tid)
        elif is_lstig:
            return fmt(is_lstig, "L", tid)
        else:
            return ""

    STATE, FILE, FN, LINE, THREAD = (
        Keyword(tk).suppress() for tk in
        ("State", "file", "function", "line", "thread"))
    LBRACE, RBRACE = map(Suppress, "{}")
    SEP = Keyword("----------------------------------------------------")
    STUFF = Word(printables)
    ASSUMPTION = Keyword("Assumption:").suppress() + SkipTo(STATE)
    INFO = (
        Optional(STATE + ppc.number().setResultsName("state")) &
        (FILE + STUFF.setResultsName("file")) &
        (FN + STUFF.setResultsName("function")) &
        (LINE + ppc.number().setResultsName("line")) &
        Optional(THREAD + ppc.number().setResultsName("thread"))
    ).ignore(ASSUMPTION)

    VAR = Word(printables, excludeChars="=")
    RECORD = Forward()
    VAL = ((ppc.number() + Optional(Suppress("u"))) | BOOLEAN | Group(RECORD))
    RECORD <<= (LBRACE + delimitedList(VAL) + RBRACE)

    ASGN = VAR + Suppress("=") + VAL + SkipTo(LineEnd()).suppress()

    TRACE = OneOrMore(Group(Group(INFO) + SEP.suppress() + Group(ASGN)))

    cex_start_pos = cex.find("Counterexample:") + 15
    cex_end_pos = cex.find("Violated property:")
    states = TRACE.parseString(cex[cex_start_pos:cex_end_pos], parseAll=True)

    inits = (
        s[1] for s in states
        if s[0]["function"] == "init" and not(LTSTAMP.match(s[1][0])))
    others = [
        (s[0]["function"], *s[1]) for s in states
        if s[0]["function"] not in ("init", "__CPROVER_initialize")]
    yield "<initialization>"
    for i in inits:
        pprint = pprint_assign(*i, init=True)
        if pprint:
            yield pprint
    yield "\n<end initialization>"

    agent = ""
    system = None
    for i, (func, var, value) in enumerate(others):
        if var == "__LABS_step":
            if system:
                yield f"\n<end {system}>"
                system = None
        elif var == "guessedkey":
            system = func
            yield f"\n<{pprint_agent(info, agent)}: {func} '{info.lstig[int(value)].name}'>"  # noqa: E501
        elif var in ("firstAgent", "guessedcomp"):
            agent = value
        else:
            if (len(others) > i + 1 and LSTIG.match(var) and
                    LTSTAMP.match(others[i + 1][0])):
                pprint = pprint_assign(var, value, agent, endline=" ")
            else:
                pprint = pprint_assign(var, value, agent)
            if pprint:
                yield pprint

    prova = cex[cex_end_pos + 18:]
    PROP = Suppress(INFO) + STUFF + Suppress(SkipTo(StringEnd()))
    prop = PROP.parseString(prova)
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

    lines = cex.split('\n')
    first_line = [i+1 for i, l in enumerate(lines) if "<initial state>" in l][0]  # noqa: E501
    lines = [l[1:-1] for l in lines[first_line:] if l and l[0] == '"']  # noqa: E501, E741

    ParserElement.setDefaultWhitespaceChars(' \t\n\x01\x02')
    NAME = Word(alphanums)
    LPAR, RPAR = map(Suppress, "()")
    RECORD = Forward()
    OBJ = (ppc.number() | BOOLEAN | Group(RECORD))
    RECORD <<= (NAME + LPAR + delimitedList(OBJ) + RPAR)

    QUOTES = dblQuotedString.setParseAction(removeQuotes)
    ASGN = NAME + ZeroOrMore(Suppress("!") + OBJ)
    MONITOR = (Keyword("MONITOR") + Suppress("!") + (BOOLEAN | QUOTES))
    STEP = ppc.number() | ASGN | MONITOR

    yield "<initialization>\n"

    for l in lines:    # noqa: E741
        step = STEP.parseString(l, parseAll=True)
        if step[0] == "ENDINIT":
            yield "<end initialization>\n"
        elif step[0] == "MONITOR" and step[1] == "deadlock":
            yield "<deadlock>\n"
        elif step[0] == "MONITOR":
            yield f"""<property {"satisfied" if step[1] else "violated"}>\n"""
        elif step[0] == "E":
            agent = pprint_agent(info, step[1])
            yield f"{step.asList()}"
            yield f"{agent}:\t{info.pprint_assign(*step[:3])}\n"
        elif step[0] == "ATTR":
            agent = pprint_agent(info, step[1])
            yield f"{agent}:\t{info.pprint_assign('I', *step[2:4])}\n"
        elif step[0] == "L":
            agent = pprint_agent(info, step[1])
            if len(step) > 4:
                # This was a stigmergic message sent from another agent
                yield f"{agent}:\t{info.pprint_assign('L', *step[2:4])}\t(from {pprint_agent(info, step[4])})\n"  # noqa: E501
            else:
                # This was an assignment from the agent itself
                yield f"{agent}:\t{info.pprint_assign('L', *step[2:4])}\n"
        else:
            yield f"<could not parse: {step}>\n"
