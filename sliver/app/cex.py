import re

from pyparsing import (Forward, Group, Keyword, ParserElement, Suppress, Word,
                       ZeroOrMore, alphanums, dblQuotedString, delimitedList)
from pyparsing import pyparsing_common as ppc
from pyparsing import removeQuotes, replaceWith


def pprint_agent(info, tid):
    return f"{info.spawn[int(tid)]} {tid}"


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
    LSTIG = re.compile(r"lstig\[([0-9]+)l?\]\[([0-9]+)l?\]")

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
