#! /usr/bin/env python3

from atlas.atlas import get_formula, pprint


def sprint_predicate(params, body):
    return f"""
macro Predicate({", ".join(params)}) =
    {body}
end_macro
"""


def sprint_assign(varname, binds_to="v"):
    var, agent_id = varname.rsplit("_", 1)
    return f"""{{assign !{agent_id} !"{var}" ?{binds_to}:Int ...}}"""


def irrelevant(var, varnames):
    return " and ".join(f"""({var} <> "{v}")""" for v in varnames)


def preprocess(params, prefix):
    varnames = set(p.rsplit("_", 1)[0] for p in params)
    inits = [sprint_assign(p, f"{prefix}_{p}") for p in params]
    nu_params = [f"{p}:Int={prefix}_{p}" for p in params]
    return varnames, inits, nu_params


def update_clauses(params, fn, box_or_diamond):
    def params_replace(params, index, repl):
        return [p if i != index else repl for i, p in enumerate(params)]
    left = box_or_diamond
    right = {"[": "]", "<": ">"}[left]
    return (
        f"{left}{sprint_assign(p)}{right} "
        f"{fn}({', '.join(params_replace(params, i, 'v'))})"
        for i, p in enumerate(params))


def sprint_reach(params):
    varnames, args_list, args = preprocess(params, "args")

    mcl_or = "\n    or\n    "

    return f"""
macro Reach({", ".join(args_list)}) =
mu R ({", ".join(args)}) . (
    Predicate({", ".join(params)})
    or
    ((<"SPURIOUS"> true) and ([not "SPURIOUS"] false))
    or
    <not {{assign ...}} or {{assign ?any ?x:string ... where ({irrelevant("x", varnames)})}}> R({", ".join(params)}) 
    or
    {mcl_or.join(update_clauses(params, "R", "<"))})
end_macro
"""


def sprint_invariant(params, name="Predicate", short_circuit=None):
    varnames, inits, nu_params = preprocess(params, "init")

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
    (
    {short_circuit}
    ([not {{assign ...}} or {{assign ?any ?x:string ... where ({irrelevant("x", varnames)})}}] Inv({", ".join(params)})
    and
    {mcl_and.join(update_clauses(params, "Inv", "["))}))
)
"""


def translate_property(info):
    """Retrieve the first property in info.properties
    and translate it into MCL.
    """
    formula, new_vars, modality = get_formula(info)
    result = sprint_predicate(sorted(new_vars), pprint(formula))
    if modality == "always":
        result += sprint_invariant(sorted(new_vars))
    elif modality in ("finally", "fairly"):
        result += sprint_reach(sorted(new_vars))
        result += sprint_invariant(sorted(new_vars), "Reach", short_circuit="Predicate")  # noqa: E501
    elif modality in ("fairly_inf"):
        result += sprint_reach(sorted(new_vars))
        result += sprint_invariant(sorted(new_vars), "Reach")  # noqa: E501
    else:
        raise Exception(f"Unrecognized modality {modality}")

    return result
