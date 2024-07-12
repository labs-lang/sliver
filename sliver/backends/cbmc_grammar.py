from dataclasses import dataclass
from lark import Lark, Transformer


grammar = r"""
%import common.INT
%import common.SIGNED_NUMBER
%import common.WS
%ignore WS
%ignore ASSUMPTION
%ignore SIM_ANNOTATION

ASSUMPTION: /Assumption:\n.*\n.*/m
SIM_ANNOTATION: /(SIMULATION):.*/

NAME: /[^-][^\s=]*/
BITS: /[01 ]+/

?rhs    : "TRUE"  -> true
        | "FALSE"  -> false
        | SIGNED_NUMBER ["u"]
        | "{" rhs ("," rhs)* "}"

integer : INT
_name : NAME

_rhs_bits    : BITS
            | "{" _rhs_bits ("," _rhs_bits)* "}"

header : \
    "State" integer "file" _name "function" _name \
    "line" integer "thread" integer

_asgn : _name "=" rhs "(" _rhs_bits ")"
state : header "----------------------------------------------------" _asgn

start : state*

"""


@dataclass
class State:
    state: int
    file: str
    function: str
    line: int
    lhs: str
    rhs: any


class Tr(Transformer):
    def integer(self, n):
        (n,) = n
        return int(n)

    def true(self, _):
        return True

    def false(self, _):
        return False

    def SIGNED_NUMBER(self, n):
        try:
            return int(n)
        except Exception:
            return float(n)

    def NAME(self, n):
        return str(n)

    def state(self, n):
        header, lhs, rhs, *_ = n
        state_id, file, function, line, _ = header.children
        return State(state_id, file, function, line, lhs, rhs)


parser = Lark(grammar, parser='lalr', transformer=Tr())
