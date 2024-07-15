from pyparsing import (Forward, Group, Keyword, ParserElement, Suppress, Word,
                       ZeroOrMore, alphanums, dblQuotedString, delimitedList)
from pyparsing import pyparsing_common as ppc
from pyparsing import removeQuotes, replaceWith


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
            agent = info.pprint_agent(step[1])
            yield f"{step.asList()}"
            yield f"{agent}:\t{info.pprint_assign(*step[:3])}\n"
        elif step[0] == "ATTR":
            agent = info.pprint_agent(step[1])
            yield f"{agent}:\t{info.pprint_assign('I', *step[2:4])}\n"
        elif step[0] == "L":
            agent = info.pprint_agent(step[1])
            if len(step) > 4:
                # This was a stigmergic message sent from another agent
                yield f"{agent}:\t{info.pprint_assign('L', *step[2:4])}\t(from {info.pprint_agent(step[4])})\n"  # noqa: E501
            else:
                # This was an assignment from the agent itself
                yield f"{agent}:\t{info.pprint_assign('L', *step[2:4])}\n"
        else:
            yield f"<could not parse: {step}>\n"
