import re
from pyparsing import (
    LineEnd, LineStart, Word, alphanums, delimitedList, OneOrMore, ZeroOrMore,
    Forward, Suppress, Group, ParserElement, Keyword, dblQuotedString,
    removeQuotes, SkipTo, StringEnd, Regex, printables, replaceWith, Optional)
from pyparsing import pyparsing_common as ppc
from ..backends.cbmc_grammar import parser as lark_parser

ATTR = re.compile(r"I\[([0-9]+)l?\]\[([0-9]+)l?\]")
LSTIG = re.compile(r"Lvalue\[([0-9]+)l?\]\[([0-9]+)l?\]")
LTSTAMP = re.compile(r"Ltstamp\[([0-9]+)l?\]\[([0-9]+)l?\]")
ENV = re.compile(r"E\[([0-9]+)l?\]")
STUFF = Word(printables)
STATE = Keyword("State").suppress()
SKIP = Regex(r'Assumption:|(SIMULATION)') + SkipTo(STATE)


HEADER = Regex(r'(?:State (?P<state>\d+) )?file (?P<file>[^\s]+)( function (?P<function>[^\s]+))? line (?P<line>\d+) (?:thread (?P<thread>\d+))?')  # noqa: E501
HEADER_OLD = Regex(r'(?:State (?P<state>\d+) )?file (?P<file>[^\s]+) line (?P<line>\d+)( function (?P<function>[^\s]+))? (?:thread (?P<thread>\d+))?')  # noqa: E501
SEP = Keyword("----------------------------------------------------")
ASGN = Regex(r'(?P<lhs>[^\s=]+)\s?=\s?(?P<rhs>.+)')
TRACE = OneOrMore(Group(Group(HEADER) + SEP.suppress() + Optional(Group(ASGN)))).ignore(OneOrMore(SKIP))  # noqa: E501
TRACE_OLD = OneOrMore(Group(Group(HEADER_OLD) + SEP.suppress() + Group(ASGN))).ignore(OneOrMore(SKIP))  # noqa: E501
# TODO: fix property parser for "new" versions of CBMC
PROP = Suppress(SkipTo(LineEnd())) + Suppress(SkipTo(LineStart())) + STUFF + Suppress(SkipTo(StringEnd()))  # noqa: E501


def pprint_agent(info, tid):
    return f"{info.spawn[int(tid)]} {tid}"


def translateCPROVER54(cex, info):
    yield from translateCPROVER(cex, info, parser=TRACE_OLD)


def translateCPROVERNEW(cex, info):
    yield from translateCPROVER(cex, info, parser=TRACE)


def translateCPROVER(cex, info, parser=TRACE):
    def pprint_assign(var, value, tid="", init=False):
        def fmt(match, store_name, tid):
            tid = match[1] if len(match.groups()) > 1 else tid
            k = match[2] if len(match.groups()) > 1 else match[1]
            agent = f"{pprint_agent(info, tid)}:" if tid != "" else ""
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
        return ""

    cex_start_pos = cex.find("Counterexample:") + 15
    cex_end_pos = cex.rfind("Violated property:")
    states = lark_parser.parse(cex[cex_start_pos:cex_end_pos]).children

    inits = [
        (s.lhs, s.rhs) for s in states
        if s.function == "init" and not LTSTAMP.match(s.lhs)]
    # Hack to display variables which were initialized to 0
    for (store, loc) in ((info.e, "E"), (info.i, "I"), (info.lstig, "L")):
        for tid in range(info.spawn.num_agents()):
            for var in store.values():
                vals = var.values(tid)
                if len(vals) == 1 and vals[0] == 0:
                    size = var.size if var.is_array else 1
                    for off in range(0, size):
                        tid_fmt = f"[{tid}]" if loc != "E" else ""
                        inits.append((f"{loc}{tid_fmt}[{var.index + off}]", "0"))  # noqa: E501
            if store == info.e:
                break

    others = (
        s for s in states
        if s.function not in ("init", "__CPROVER_initialize"))
    yield "<initialization>"
    for i in inits:
        pprint = pprint_assign(*i, init=True)
        if pprint:
            yield pprint
    yield "\n<end initialization>"

    agent = ""
    system = None
    last_line = None
    for i, state in enumerate(others):
        if state.lhs == "__LABS_step":
            if system:
                yield f"\n<end {system}>"
                system = None
            yield f"""\n<step {state.rhs}>"""
        elif state.lhs == "__sim_spurious" and state.rhs is True:
            yield "\n<spurious>"
            break
        elif state.lhs == "guessedkey":
            system = state.function
            yield f"\n<{pprint_agent(info, agent)}: {state.function} '{info.lstig[int(state.rhs)].name}'>"  # noqa: E501
        elif state.lhs in ("firstAgent", "scheduled"):
            agent = state.rhs
        # simulation: printf messages
        elif state.lhs == "format" and state.rhs.startswith('"(SIMULATION)'):
            yield f"\n<{state.rhs[1:-1]}>"
        # If multiple assignments correspond to the same line, it's because
        # we assigned to an array and CBMC is printing out the whole thing
        elif last_line != state.line:
            pprint = pprint_assign(state.lhs, state.rhs, agent)
            last_line = state.line
            if pprint:
                yield pprint

    violation = cex[cex_end_pos + 18:]
    prop = PROP.parseString(violation)
    if prop[0] != "__sliver_simulation__":
        yield f"\n<property violated: '{prop[0]}'>"
    yield "\n"


def translate_cadp(cex, info):
    lines = cex.split('\n')
    first_line = next(
        i+1 for i, l in enumerate(lines)
        if "<initial state>" in l)
    last_line = next(
        i for i, l in enumerate(lines[first_line:], first_line)
        if "<goal state>" in l or "<deadlock>" in l)
    lines = [l[1:-1] for l in lines[first_line:last_line] if l and l[0] == '"']  # noqa: E501, E741

    ParserElement.setDefaultWhitespaceChars(' \t\n\x01\x02')
    BOOLEAN = (
        Keyword("TRUE").setParseAction(replaceWith(True)) |
        Keyword("FALSE").setParseAction(replaceWith(False)))
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
        if "invisible transition" in l:
            # skip internal moves
            continue
        elif "<deadlock>" in l:
            yield l
            continue
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


def translate_nuxmv(cex, info):
    ATTR = re.compile(r"i\[([0-9]+)l?\]\[([0-9]+)l?\]")
    ENV = re.compile(r"e\[([0-9]+)l?\]")

    def pprint_assign(var, value, tid="", init=False):
        def fmt(match, store_name, tid):
            tid = match[1] if len(match.groups()) > 1 else tid
            k = match[2] if len(match.groups()) > 1 else match[1]
            agent = f"{pprint_agent(info, tid)}:" if tid != "" else ""
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
        return ""

    tid = ""
    for i, state in enumerate(cex.split("->")[2:]):
        if i == 0:
            yield "<initialization>"
        elif i == 1:
            yield "\n<end initialization>"
        if i % 2 == 1:
            yield f"""\n<step {(i // 2)}>"""
        for asgn in state.split("<-")[1].split("\n"):
            asgn = asgn.strip()
            if asgn:
                lhs, rhs = asgn.split("=")
                if lhs == "tid":
                    tid = rhs.strip()
                    continue
                pprint = pprint_assign(lhs, rhs, tid, i > 0)
                if pprint:
                    yield pprint
    yield f"""\n<step {(i // 2)}>\n"""
