#! /usr/bin/env python3

from itertools import repeat
from atlas.atlas import get_formula, OfNode, BinOp, Nary, BuiltIn


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


def sprint_assign(varname, info, binds_to="v"):
    var, agent_id = varname.rsplit("_", 1)
    var_info = info.lookup_var(var)
    label = {
        "i": "ATTR", "lstig": "L", "e": "E"
    }[var_info.store]
    return f"""{{{label} !{agent_id} !{var_info.index} ?{binds_to}:Int ...}}"""


def irrelevant(var, varnames):
    return " and ".join(f"""({var} <> "{v}")""" for v in varnames)


def preprocess(params, prefix, info):
    varnames = set(p.rsplit("_", 1)[0] for p in params)
    inits = [sprint_assign(p, info, f"{prefix}_{p}") for p in params]
    nu_params = [f"{p}:Int:={prefix}_{p}" for p in params]
    return varnames, inits, nu_params


def update_clauses(params, info, fn, box_or_diamond):
    def params_replace(params, index, repl):
        return [p if i != index else repl for i, p in enumerate(params)]
    return (
        f"({box_or_diamond(sprint_assign(p, info))}"
        f"{fn}({', '.join(params_replace(params, i, 'v'))}))"
        for i, p in enumerate(params))


def sprint_irrelevant(varnames, info, fn, box_or_diamond):
    """Print a clause matching "irrelevant" transitions
    (i.e., those that do not affect satisfaction of Predicate).
    """
    def filter_(vs):
        return " and ".join(f"""(x <> {v.index})""" for v in vs)

    var_infos = [info.lookup_var(v) for v in varnames]
    labels = set("attr" if v.store == "i" else v.store for v in var_infos)
    other_actions = " and ".join(f"(not {{{lbl} ...}})" for lbl in labels)
    attrs = {
        s: [v for v in var_infos if v.store == s]
        for s in ("i", "lstig", "e")}
    result = ""
    if labels:
        result += other_actions
    if attrs["i"]:
        result += f" or {{attr ?any ?x:Nat ... where ({filter_(attrs['i'])})}}"  # noqa: E501
    if attrs["lstig"]:
        result += f" or {{lstig ?any ?x:Nat ... where ({filter_(attrs['lstig'])})}}"  # noqa: E501
    if attrs["e"]:
        result += f" or {{e ?any ?x:Nat ... where ({filter_(attrs['e'])})}}"  # noqa: E501
    if labels:
        return f"({box_or_diamond(result)} {fn})"


def sprint_reach(params, info):
    varnames, args_list, args = preprocess(params, "args", info)

    mcl_or = "\n    or\n    "

    return f"""
macro Reach({", ".join(args_list)}) =
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


def sprint_call(params, info, name):
    _, inits, _ = preprocess(params, "init", info)
    return f"""
[{" . ".join(inits)}]
{name}({", ".join(params)})
"""


def sprint_invariant(params, info, name="Predicate", short_circuit=None):
    varnames, inits, nu_params = preprocess(params, "init", info)
    # We must capture irrelevant initializations,
    # otherwise we will get a vacuous pass
    irrelevants = f"{sprint_irrelevant(varnames,info, '', lambda x: x)}*"  # noqa: E501
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
    {sprint_irrelevant(varnames, info, f"Inv({', '.join(params)})", BOX)}
    and
    {mcl_and.join(update_clauses(params, info, "Inv", BOX))}
{")" if short_circuit else ""})
"""


def pprint_mcl(node):
    if isinstance(node, OfNode):
        # Should never happen, since node should be the result
        # of get_formula() and thus have no quantified variables.
        raise Exception(f"Unexpected {node}")
    if isinstance(node, BinOp):
        op = {
            "%": "mod",
            "!=": "<>"
        }.get(node.op) or node.op
        return f"({pprint_mcl(node.e1)} {op} {pprint_mcl(node.e2)})"
    elif isinstance(node, BuiltIn):
        return f"{node.fn}({', '.join(pprint_mcl(a) for a in node.args)})"
    elif isinstance(node, Nary):
        return "({})".format(f" {node.fn} ".join(pprint_mcl(a) for a in node.args))  # noqa: E501
    else:
        return node


def translate_property(info):
    """Retrieve the first property in info.properties
    and translate it into MCL.
    """
    formula, new_vars, modality = get_formula(info)
    result = sprint_predicate(sorted(new_vars), pprint_mcl(formula))
    if modality == "always":
        result += sprint_invariant(sorted(new_vars), info)
    elif modality == "finally":
        result += sprint_reach(sorted(new_vars), info)
        result += sprint_call(sorted(new_vars), info, "Reach")
    elif modality == "fairly":
        result += sprint_reach(sorted(new_vars), info)
        result += sprint_invariant(sorted(new_vars), info, "Reach", short_circuit="Predicate")  # noqa: E501
    elif modality == "fairly_inf":
        result += sprint_reach(sorted(new_vars), info)
        result += sprint_invariant(sorted(new_vars), info, "Reach")  # noqa: E501
    else:
        raise Exception(f"Unrecognized modality {modality}")

    return result
