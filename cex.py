import re
from pyparsing import (
    LineEnd, LineStart, Word, alphanums, delimitedList, OneOrMore, ZeroOrMore,
    Forward, Suppress, Group, ParserElement, Keyword, dblQuotedString,
    removeQuotes, SkipTo, StringEnd, Regex, printables, replaceWith)
from pyparsing import pyparsing_common as ppc


ATTR = re.compile(r"I\[([0-9]+)l?\]\[([0-9]+)l?\]")
LSTIG = re.compile(r"Lvalue\[([0-9]+)l?\]\[([0-9]+)l?\]")
LTSTAMP = re.compile(r"Ltstamp\[([0-9]+)l?\]\[([0-9]+)l?\]")
ENV = re.compile(r"E\[([0-9]+)l?\]")
STUFF = Word(printables)
STATE = Keyword("State").suppress()
SKIP = Regex(r'Assumption:|(SIMULATION)') + SkipTo(STATE)

######### OLD parser, kept for reference  # noqa: E266
# BOOLEAN = (
#     Keyword("TRUE").setParseAction(replaceWith(True)) |
#     Keyword("FALSE").setParseAction(replaceWith(False)))
# FILE, FN, LINE, THREAD, ASSUMPTION, SIMULATION = (
#     Keyword(tk).suppress() for tk in
#     ("file", "function", "line", "thread", "Assumption:", "(SIMULATION)"))
# LBRACE = Suppress("{")
# SKIP = (ASSUMPTION | SIMULATION) + SkipTo(STATE)
# INFO = (
#     Optional(STATE + ppc.number().setResultsName("state")) +
#     (FILE + STUFF.setResultsName("file")) +
#     (
#         # At some point they brilliantly swapped "line" and "function"...
#         (FN + STUFF.setResultsName("function")) &
#         (LINE + ppc.number().setResultsName("line"))) +
#     Optional(THREAD + ppc.number().setResultsName("thread"))
# )
# VAR = Word(printables, excludeChars="=")
# VAL = (
#     (ppc.number() + Optional(Suppress("u"))) |
#     BOOLEAN |
#     dblQuotedString |
#     (LBRACE + restOfLine))
# ASGN = VAR + Suppress("=") + VAL + SkipTo(LineEnd()).suppress()
# TRACE = OneOrMore(Group(Group(INFO) + SEP.suppress() + Group(ASGN)))
# PROP = Suppress(INFO) + STUFF + Suppress(SkipTo(StringEnd()))

HEADER = Regex(r'(?:State (?P<state>\d+) )?file (?P<file>[^\s]+) function (?P<function>[^\s]+) line (?P<line>\d+) (?:thread (?P<thread>\d+))?')  # noqa: E501
HEADER_OLD = Regex(r'(?:State (?P<state>\d+) )?file (?P<file>[^\s]+) line (?P<line>\d+) function (?P<function>[^\s]+) (?:thread (?P<thread>\d+))?')  # noqa: E501
SEP = Keyword("----------------------------------------------------")
ASGN = Regex(r'(?P<lhs>[^\s=]+)=(?P<rhs>.+)')
TRACE = OneOrMore(Group(Group(HEADER) + SEP.suppress() + Group(ASGN))).ignore(OneOrMore(SKIP))  # noqa: E501
TRACE_OLD = OneOrMore(Group(Group(HEADER_OLD) + SEP.suppress() + Group(ASGN))).ignore(OneOrMore(SKIP))  # noqa: E501
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

    def get_value(rhs):
        return rhs.rsplit("(", 1)[0].strip()

    cex_start_pos = cex.find("Counterexample:") + 15
    cex_end_pos = cex.rfind("Violated property:")
    # start = time.time()
    states = parser.parseString(cex[cex_start_pos:cex_end_pos], parseAll=True)
    # yield f"<parsing took {time.time()-start} s>\n"
    # tr_start = time.time()

    inits = (
        (s[1].lhs, get_value(s[1].rhs)) for s in states
        if s[0].function == "init" and not(LTSTAMP.match(s[1][0])))
    others = [
        (s[0].function, s[0].line, s[1].lhs, get_value(s[1].rhs))
        for s in states
        if s[0].function not in ("init", "__CPROVER_initialize")]
    yield "<initialization>"
    for i in inits:
        pprint = pprint_assign(*i, init=True)
        if pprint:
            yield pprint
    yield "\n<end initialization>"

    agent = ""
    system = None
    last_line = None
    for i, (func, line, var, value) in enumerate(others):
        if var == "__LABS_step":
            if system:
                yield f"\n<end {system}>"
                system = None
        elif var == "__sim_spurious" and value == "TRUE":
            yield f"\n<spurious>"
            break
        elif var == "guessedkey":
            system = func
            yield f"\n<{pprint_agent(info, agent)}: {func} '{info.lstig[int(value)].name}'>"  # noqa: E501
        elif var in ("firstAgent", "guessedcomp"):
            agent = value
        # simulation: printf messages
        elif var == "format" and value.startswith('"(SIMULATION)'):
            yield f"\n<{value[1:-1]}>"
        # If multiple assignments correspond to the same line, it's because
        # we assigned to an array and CBMC is printing out the whole thing
        elif last_line != line:
            pprint = pprint_assign(var, value, agent)
            last_line = line
            if pprint:
                yield pprint

    violation = cex[cex_end_pos + 18:]
    prop = PROP.parseString(violation)
    if prop[0] != "__sliver_simulation__":
        yield f"\n<property violated: '{prop[0]}'>"
    # yield f"\n<Translation took {time.time()-tr_start} s>"
    # yield f"\n<Full time is {time.time()-start} s>"
    yield "\n"


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
