#! /usr/bin/env python3

from collections import namedtuple
from copy import deepcopy

from ..labsparse.labsparse.labs_ast import NodeType, Attr
from ..labsparse.labsparse.labs_parser import BEXPR, MODALITY, QUANT


Prop = namedtuple("Prop", ["modality", "quant"])
PROP = (MODALITY + (QUANT | BEXPR)).setParseAction(lambda toks: Prop(*toks))  # noqa: E501


def get_state_vars(formula):
    return set(x[Attr.NAME] for x in formula // (NodeType.REF, ))


def contains(formula, var):
    """Return True iff formula contains variable var.
    """
    for x in formula // (NodeType.REF, ):
        if x[Attr.NAME] == var:
            return True
    return False


# def replace_with_string(f, agent):
#     # TODO extend to arrays (check f.offset)
#     return f"{f.var}_{agent}"



    # if isinstance(f, str) and f in externs:
    #     return externs[f]
    # elif isinstance(f, BinOp):
    #     return BinOp(recurse(f.e1), f.op, recurse(f.e2))  # noqa: E501
    # elif isinstance(f, BuiltIn):
    #     return BuiltIn(f.fn, [recurse(f) for f in f.args])
    # elif isinstance(f, Nary):
    #     return Nary(f.fn, [recurse(f) for f in f.args])
    # elif isinstance(f, Quant):
    #     return Quant(f.quantifier, f.typename, f.varname, recurse(f.inner))
    # else:
    #     return f


def make_dict(formula):
    """Return a dictionary mapping quantified variable names
    to their quantifier and the type of agent being ranged over.
    """

    if formula(NodeType.QFORMULA):
        return ({
            x[Attr.NAME]: (x[Attr.QUANTIFIER], x[Attr.TYPE])
            for x in formula[Attr.QVARS]
        }, deepcopy(formula[Attr.CONDITION]))
    else:
        return {}, deepcopy(formula)

    # if isinstance(formula, Quant):
    #     inner_dict, inner_formula = make_dict(formula[NodeType.BO])
    #     if formula.varname in inner_dict:
    #         raise Exception(
    #             f"Multiple definitions for variable {formula.varname}")
    #     inner_dict[formula.varname] = (formula.quantifier, formula.typename)  # noqa: E501
    #     return inner_dict, inner_formula
    # else:
    #     return {}, formula


def get_property(info, prop=None) -> Prop:
    if not prop:
        prop = info.properties[0]
    return PROP.parseString(prop)


def vars_to_strings(formula, info, attrs, lstigs, envs):
    """Turns (var of x) references into string literals"""
    for node, parent, attr, i in formula.walk_with_handle():
        if node(NodeType.REF) and node[Attr.OF] is not None:
            agent = node[Attr.OF][Attr.VALUE]
            node[Attr.OF] = None
            if node[Attr.NAME] == "id":
                parent.set(attr, agent, i)
            else:
                var = info.lookup_var(node[Attr.NAME])
                idx = var.index + (node[Attr.OFFSET] or 0)
                if var.store == "i":
                    parent.set(attr, attrs[agent][idx], i)
                elif var.store == "lstig":
                    parent.set(attr, lstigs[agent][idx], i)
                elif var.store == "e":
                    parent.set(attr, envs[idx], i)
                else:
                    raise NotImplementedError

# def get_formula(info, externs, prop=None, parsed=None):
#     pass
    # """Extract the 1st property in info.properties and
    # turn it into a propositional formula (via quantifier elimination.)

    # Return: the propositional formula, the set of variables introduced
    # by quantifier elimination, and the property's temporal modality.
    # """
    # if parsed is None:
    #     parsed = get_quant_formula(info, prop)

    # d, formula = make_dict(parsed[0].quant)

    # # remove quantifiers
    # # and collect variables created by quantifier elimination
    # new_vars = set()
    # for var in d:
    #     quant, agent_type = d[var]
    #     if contains(formula, var):
    #         formula, nv = remove_quant(formula, quant, var, info.spawn.tids(agent_type))  # noqa: E501
    #         new_vars = new_vars.union(nv)

    # formula = replace_externs(formula, externs)

    # return formula, new_vars, parsed[0].modality
