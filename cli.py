#!/usr/bin/env python3

from enum import Enum
from __about__ import __date__, __summary__, __title__, __version__
from typing import Dict


class Args(Enum):
    BACKEND = "backend"
    BV = "bv"


def get(kwargs: Dict, arg: Args):
    return kwargs[arg.value]


LONGDESCR = """
* * * {} - {} v{} ({}) * * *

FILE -- path of LABS file to analyze

VALUES -- assign values for parameterised specification (key=value)
""".format(__title__.lower(), __summary__, __version__, __date__)

HELPMSG = {
    "backend": "Backend to use in verification mode.",

    "bitvector":
        "Enable bitvector optimization where supported",

    "cores": "Number of CPU cores for parallel analysis",

    "debug": "Enable additional checks in the backend.",

    "lang": "Target language for the code generator.",

    "fair": "Enforce fair interleaving of components.",

    "from": (
        "Parallel analysis: partition start"
    ),

    "show": "Print C encoding and exit.",

    "simulate": (
        "Number of simulation traces to generate. "
        "If 0, run in verification mode."),

    "steps": (
        "Number of system evolutions."
        "If 0, generate an unbounded system."),

    "sync": "Force synchronous stigmergy messages.",

    "timeout": (
        "Configure time limit (seconds)."
        "Set to 0 to disable timeout."),

    "to": (
        "Parallel analysis: partition end."
    ),

    "verbose": "Print additional messages from the backend."
}


def DEFAULTS(name, **kwargs):
    return {
        "help": HELPMSG[name],
        "show_default": True,
        **kwargs
    }
