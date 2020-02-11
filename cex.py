import re

from pyparsing import (Word, alphanums, delimitedList, OneOrMore,
                       Forward, Suppress, Group, ParserElement, Keyword,
                       replaceWith, dblQuotedString, removeQuotes)
from pyparsing import pyparsing_common as ppc

from info import get_var


ATTR = re.compile(r"I\[([0-9]+)l?\]\[([0-9]+)l?\]")
LSTIG = re.compile(r"Lvalue\[([0-9]+)l?\]\[([0-9]+)l?\]")
LTSTAMP = re.compile(r"Ltstamp\[([0-9]+)l?\]\[([0-9]+)l?\]")
ENV = re.compile(r"E\[([0-9]+)l?\]")
STEP = re.compile(r"__LABS_step")

PROPAGATE = re.compile(r"propagate_or_confirm=TRUE")
CONFIRM = re.compile(r"propagate_or_confirm=FALSE")


UNDEF = "16960"


def pprint_agent(info, tid):
    return f"{info.spawn[int(tid)]} {tid}"


def pprint_assign(lst, key, arrow, value):
    v = get_var(lst, key)
    if v.is_array:
        return f"\t{v.name}[{key - v.index}] {arrow} {value}\n"
    else:
        return "\t{} {} {}\n".format(v.name, arrow, value)


def translateCPROVER(cex, fname, info, offset=-1):
    with open(fname) as f:
        c_program = f.readlines()
    translatedcex = ''
    lines = cex.split('\n')
    k = 0  # cex[:cex.find('Trace for')].count('\n') + 1 + 1
    separator = "----------------------------------------------------"

    for k, ln in enumerate(lines):
        # case 1: another transition to fetch
        if ln.startswith('State ') and lines[k + 1] == separator:
            A, B, C = ln, lines[k + 1], lines[k + 2]

            # the part below the separator might be
            # more than one line long..
            j = 1
            while (k + 2 + j < len(lines) and
                    not lines[k + 2 + j].startswith('State ') and
                    not lines[k + 2 + j].startswith('Violated property')):
                C += lines[k + 2 + j]
                j += 1

            translatedcex += _mapCPROVERstate(A, B, C, info)

        # case 2: final transation with property violation
        elif ln.startswith('Violated property'):
            Y = keys_of(lines[k + 1])
            prop = c_program[int(Y["line"]) + offset]
            try:
                _, prop = c_program[int(Y["line"]) + offset].split("//")
            except ValueError:
                pass
            translatedcex += """Violated property: {}\n""".format(prop)
            break  # Stop converting after the 1st property has been violated

        # case 3: violated property in simulation run
        elif ln.startswith(">>>") and "violated" in ln:
            translatedcex += ln + "\n"

    if len(translatedcex) > 0:
        translatedcex = "Counterexample:\n\n{}\n".format(translatedcex)

    return translatedcex


def keys_of(ln):
    tokens = ln.split()
    return {key: value for key, value in zip(tokens[0::2], tokens[1::2])}


last_return = ""
last_step = -1
last_sys = []
last_agent = -1


def _mapCPROVERstate(A, B, C, info):

    global last_return, last_step, last_sys, last_agent
    '''
    'Violated property:'
    '  file _cs_lazy_unsafe.c line 318 function thread3_0'
    '  assertion 0 != 0'
    '  0 != 0'
    '''
    # Fetch values.
    try:
        # 1st line
        keys = keys_of(A)
        keys["lvalue"], rvalue = C.strip().split("=")
        keys["rvalue"] = rvalue.split(" ")[0]

        is_ltstamp = LTSTAMP.match(keys["lvalue"])
        if is_ltstamp and last_return == "lstig":
            last_return = "ltstamp"
            return "({})\n".format(keys["rvalue"])

        if PROPAGATE.match(C.strip()):
            last_sys.append("propagate ")
        elif CONFIRM.match(C.strip()):
            last_sys.append("confirm ")
        elif keys["lvalue"] == "guessedcomp":
            tid = int(keys["rvalue"])
            agent = f"from {pprint_agent(info, tid)}:"
            last_sys.append(agent)
        elif keys["lvalue"] == "guessedkey":
            last_sys.append(info.lstig[int(keys["rvalue"])].name)
            result = ("".join(last_sys) + "\n")
            last_sys = []
            return result

        try:
            is_attr = ATTR.match(keys["lvalue"])
            if is_attr and keys["rvalue"] != UNDEF:
                tid, k = is_attr.group(1), is_attr.group(2)
                agent = pprint_agent(info, tid)
                last_return = "attr"
                return "{}:{}".format(
                    agent,
                    pprint_assign(info.i, int(k), "<-", keys["rvalue"]))

            is_lstig = LSTIG.match(keys["lvalue"])
            if is_lstig and keys["rvalue"] != UNDEF:
                tid, k = is_lstig.group(1), is_lstig.group(2)
                agent = pprint_agent(info, tid)
                last_return = "lstig"
                last_agent = agent
                return "{}:{}".format(
                    agent,
                    pprint_assign(info.lstig, int(k), "<~", keys["rvalue"]))

            if (keys["lvalue"].startswith("__LABS_step") and
                    keys["rvalue"] != last_step):
                last_return = "step"
                last_step = keys["rvalue"].replace("u", "")
                return "--step {}--\n".format(last_step)

            is_env = ENV.match(keys["lvalue"])
            if is_env and keys["rvalue"] != UNDEF:
                k = is_env.group(1)
                last_return = "env"
                return pprint_assign(info.e, int(k), "<--", keys["rvalue"])
        except KeyError:
            return ""
        return ""

    except Exception as e:
            print('unable to parse state %s' % keys['State'])
            print(e)
            print(A, B, C, sep="\n")
            return ""


def translate_cadp(cex, info):
    def pprint_init_agent(args):
        tid = args[1][0]
        iface = args[2][1:]
        agent = pprint_agent(info, tid)
        init_iface = "".join(
            f"""{agent}:{pprint_assign(info.i, int(k), "<-", v[0])}"""
            for k, v in enumerate(iface))
        if len(args) == 5:
            return init_iface

        lstig = args[3][1:]
        init_iface += "".join(
            f"""{agent}:{pprint_assign(info.lstig, int(k), "<~", v[1][0])}"""
            for k, v in enumerate(lstig)
        )
        return init_iface

    def pprint_init_env(args):
        return "".join(
            pprint_assign(info.e, int(k), "<--", v)
            for k, v in enumerate(args[1:]))

    lines = [l[9:-1] for l in cex.split('\n') if l.startswith("\"ACTION")]
    inits = sorted(l for l in lines if l.startswith("AGENT"))
    init_env = (l for l in lines if l.startswith("ENV"))
    others = (l for l in lines
              if not (l.startswith("AGENT") or l.startswith("ENV")))

    ParserElement.setDefaultWhitespaceChars(' \t\n\x01\x02')
    BOOLEAN = (
        Keyword("TRUE").setParseAction(replaceWith(True)) |
        Keyword("FALSE").setParseAction(replaceWith(False)))
    NAME = Word(alphanums)
    LPAR, RPAR = map(Suppress, "()")
    RECORD = Forward()
    RECORD <<= (NAME + LPAR +
                delimitedList(Group(ppc.number() | BOOLEAN | RECORD)) + RPAR)

    BANGNUM = (Suppress("!") + ppc.number)
    ASGN = dblQuotedString.setParseAction(removeQuotes) + OneOrMore(BANGNUM)
    STEP = ppc.number() | ASGN

    result = [pprint_init_env(RECORD.parseString(l)) for l in init_env]
    result.extend(pprint_init_agent(RECORD.parseString(l)) for l in inits)

    agent = 0
    for l in others:
        step = STEP.parseString(l, parseAll=True)
        if len(step) == 1:
            agent = step[0]
        else:
            if step[0] == "E":
                result.append(
                    pprint_assign(info.e, int(step[1]), "<--", step[2]))
            else:
                ls, arrow = {
                    "I": (info.i, "<-"),
                    "L": (info.lstig, "<~")}[step[0]]
                result.append(
                    pprint_agent(info, agent) + ":" +
                    pprint_assign(ls, int(step[2]), arrow, step[3]))

    return "".join(l for l in result if l)

