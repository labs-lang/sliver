#! /usr/bin/env python3

from copy import deepcopy

import jq


def get_state_vars(formula):
    print(formula)
    return set()
    # return set(x[Attr.NAME] for x in formula // (NodeType.REF, ))


def get_property(ast):
    properties = jq.compile(".Properties").input(ast).first()
    return next(iter(properties.values()))


def qelim(info, formula):
    if not formula["Quantifiers"]:
        return formula

    def replace(obj, qvar, replacement):
        def recurse(a):
            return replace(a, qvar, replacement)
        if isinstance(obj, str) or isinstance(obj, int) or isinstance(obj, bool):  # noqa: E501
            return obj
        if "IdOfAgent" in obj:
            new_obj = deepcopy(obj)
            if obj["IdOfAgent"] == qvar:
                new_obj["IdOfAgent"] = replacement
            return new_obj
        if "Terms" in obj:
            new_obj = deepcopy(obj)
            new_obj["Terms"] = [recurse(a) for a in obj["Terms"]]
            return new_obj
        if "IfElse" in obj:
            new_obj = deepcopy(obj)
            for field in ("IfElse", "IfTrue", "IfFalse"):
                new_obj[field] = [recurse(a) for a in obj[field]]
            return new_obj
        if obj.get("Var", {}).get("Item2") == qvar:
            new_obj = deepcopy(obj)
            new_obj["Var"]["Item2"] = replacement
            return new_obj
        return obj

    predicate = formula["Predicate"]
    for qvar, mapping in formula["Quantifiers"].items():
        typ, quant = mapping["Item1"], mapping["Item2"]
        formulas = [
            replace(deepcopy(predicate), qvar, tid)
            for tid in info.spawn.range_of(typ)]
        op = "or" if quant == "exists" else "and"
        predicate = {"Op": op, "Terms": formulas}
    return predicate


def vars_to_strings(formula, info):
    """Turns (var of x) references into string literals. IN-PLACE"""
    new_vars = set()

    def transform(node):
        if "Terms" in node:
            node["Terms"] = [transform(a) for a in node["Terms"]]
        if "IfElse" in node:
            for field in ("IfElse", "IfTrue", "IfFalse"):
                node[field] = [transform(a) for a in node[field]]
        if node.get("Var", {}).get("Item2") is not None:
            agent = node["Var"]["Item2"]
            var_name = node["Var"]["Item1"]["Item1"]["Name"]
            var = info.lookup_var(var_name)
            v = f"{var.name}_{agent}"
            new_vars.add(v)
            node["Var"]["Item1"]["Item1"]["Name"] = v
            node["Var"]["Item2"] = None

    transform(formula)
    return new_vars
