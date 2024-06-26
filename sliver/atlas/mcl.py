#! /usr/bin/env python3

from itertools import repeat

from sliver.atlas.atlas import get_property, vars_to_strings
from sliver.labsparse.labsparse.labs_ast import Attr, Node, NodeType
from sliver.labsparse.labsparse.utils import (eliminate_quantifiers,
                                              replace_externs)


def sprint_predicate(params, body):
    return f"""
macro Predicate({", ".join(params)}) =
    {body}
end_macro
"""


def BOX(s):
    return f"[{s}]"


def DIAMOND(s):
    return f"<{s}>"


def LABEL(store):
    return {
        "i": "ATTR", "lstig": "L", "e": "E"
    }[store]


def sprint_assign(varname, info, binds_to="v"):
    var, agent_id = varname.rsplit("_", 1)
    if var == "id":
        return ""
    var_info = info.lookup_var(var)
    label = LABEL(var_info.store)
    return f"""{{{label} !{agent_id} !{var_info.index} ?{binds_to}:Int ...}}"""


def irrelevant(var, varnames):
    return " and ".join(f"""({var} <> "{v}")""" for v in varnames)


def preprocess(params, prefix, info):
    sort_params = sorted(params)
    varnames = set(p.rsplit("_", 1)[0] for p in sort_params)
    prefix = f"{prefix}_" if prefix else ""
    inits = [sprint_assign(p, info, f"{prefix}{p}") for p in sort_params]
    nu_params = [f"{p}:Int:={prefix}{p}" for p in sort_params]
    return varnames, inits, nu_params


def update_clauses(params, info, fn, box_or_diamond):
    def params_replace(params, index, repl):
        return [p if i != index else repl for i, p in enumerate(params)]
    return (
        f"({box_or_diamond(sprint_assign(p, info))}"
        f"{fn}({', '.join(params_replace(params, i, 'v'))}))"
        for i, p in enumerate(params))


def _id(x):
    return x


def sprint_irrelevant(names, info, fn, box_or_diamond=_id, not_spurious=True):
    """Print a clause matching "irrelevant" transitions
    (i.e., those that do not affect satisfaction of Predicate).
    """
    def filter_(vs):
        return " and ".join(f"""(x <> {v.index})""" for v in vs)

    var_infos = [info.lookup_var(v) for v in names if v != "id"]
    labels = set(LABEL(v.store) for v in var_infos)
    other_actions = ["""(not "SPURIOUS")"""] if not_spurious else []
    other_actions.extend(f"(not {{{lbl} ...}})" for lbl in labels)

    other_actions = " and ".join(other_actions)
    other_actions = f"({other_actions})"
    attrs = {
        s: [v for v in var_infos if v.store == s]
        for s in ("i", "lstig", "e")}
    result = ""
    if labels:
        result += other_actions
    if attrs["i"]:
        result += f" or {{ATTR ?any ?x:Nat ... where ({filter_(attrs['i'])})}}"  # noqa: E501
    if attrs["lstig"]:
        result += f" or {{L ?any ?x:Nat ... where ({filter_(attrs['lstig'])})}}"  # noqa: E501
    if attrs["e"]:
        result += f" or {{E ?any ?x:Nat ... where ({filter_(attrs['e'])})}}"  # noqa: E501
    if labels:
        return f"({box_or_diamond(result)} {fn})"


def sprint_reach(params, info):
    varnames, _, args = preprocess(params, "args", info)
    macro_params = (f"args_{p}" for p in params)

    mcl_or = "\n    or\n    "

    return f"""
macro Reach({", ".join(macro_params)}) =
mu R ({", ".join(args)}) . (
    Predicate({", ".join(params)})
    or
    ((<"SPURIOUS"> true) and ([not "SPURIOUS"] false))
    or
    {sprint_irrelevant(varnames, info, f"R({', '.join(params)})", DIAMOND)}
    or
    {mcl_or.join(update_clauses(params, info, "R", DIAMOND))})
end_macro
"""


def sprint_finally(params, info):
    names, inits, args = preprocess(params, "", info)
    irrelevants = f"{sprint_irrelevant(names, info, '', not_spurious=False)}*"
    inits = [x for y in zip(repeat(irrelevants), inits) for x in y]
    mcl_and = "\n    and\n    "
    return f"""
[{" . ".join(inits)}]
mu R ({", ".join(args)}) . (
    (Predicate({", ".join(params)})
    or
    ((<"SPURIOUS"> true) and ([not "SPURIOUS"] false)))
    or
    ({sprint_irrelevant(names, info, f"R({', '.join(params)})", BOX)}
    and
    {mcl_and.join(update_clauses(params, info, "R", BOX))}))
"""


def sprint_invariant(params, info, name="Predicate", short_circuit=None):
    names, inits, nu_params = preprocess(params, "init", info)
    # We must capture irrelevant initializations,
    # otherwise we will get a vacuous pass
    irrelevants = f"{sprint_irrelevant(names, info, '', not_spurious=False)}*"  # noqa: E501
    inits = [x for y in zip(repeat(irrelevants), inits) for x in y]
    mcl_and = "\n    and\n    "

    short_circuit = (
        f"""{short_circuit}({", ".join(params)}) or """
        if short_circuit
        else "")

    return f"""
[{" . ".join(inits)}]
nu Inv ({", ".join(nu_params)}) . (
    {name}({", ".join(params)})
    and
    {short_circuit}{"(" if short_circuit else ""}
    {sprint_irrelevant(names, info, f"Inv({', '.join(params)})", BOX)}
    and
    {mcl_and.join(update_clauses(params, info, "Inv", BOX))}
{")" if short_circuit else ""})
"""


def pprint_mcl(node):
    if not isinstance(node, Node):
        return node
    if node(NodeType.BUILTIN):
        return f"{node[Attr.NAME]}({', '.join(pprint_mcl(a) for a in node[Attr.OPERANDS])})"  # noqa: E501
    elif Attr.OPERANDS in node:
        op = {
            "%": "mod",
            "!=": "<>"
        }.get(node[Attr.NAME], node[Attr.NAME])
        return "({})".format(f" {op} ".join(pprint_mcl(a) for a in node[Attr.OPERANDS]))  # noqa: E501
    else:
        return node.as_labs()


def translate_property(info, externs, parsed=None):
    """Retrieve the first property in info.properties
    and translate it into MCL.
    """

    prop = get_property(info)
    qformula = eliminate_quantifiers(prop[Attr.CONDITION], info)
    qformula = replace_externs(qformula, externs)
    new_vars = vars_to_strings(qformula, info)

    def key_of(v):
        name, agent_id = v.rsplit("_", 1)
        idx = info.lookup_var(name).index
        return int(agent_id), idx

    new_vars = sorted(list(new_vars), key=key_of)

    result = sprint_predicate(new_vars, pprint_mcl(qformula))
    if prop.modality == "always":
        result += sprint_invariant(new_vars, info)
    elif prop.modality in ("eventually", "finally"):
        result += sprint_finally(new_vars, info)
    elif prop.modality == "fairly":
        result += sprint_reach(new_vars, info)
        result += sprint_invariant(new_vars, info, "Reach", short_circuit="Predicate")  # noqa: E501
    elif prop.modality == "fairly_inf":
        result += sprint_reach(new_vars, info)
        result += sprint_invariant(new_vars, info, "Reach")  # noqa: E501
    else:
        raise Exception(f"Unrecognized modality {prop.modality}")

    return result
