#!/usr/bin/env python3

import logging
import sys
from dataclasses import dataclass
from enum import Enum

from .__about__ import __date__, __summary__, __version__

log = logging.getLogger('backend')


class Args(Enum):
    BACKEND = "backend"
    BV = "bv"
    CORES = "cores"
    DEBUG = "debug"
    FAIR = "fair"
    CORES_FROM = "from"
    KEEP_FILES = "keep_files"
    INCLUDE = "include"
    PROPERTY = "property"
    CONCRETIZATION = "concretization"
    NO_CONCRETIZE = "no_concretize"
    NO_PROPERTIES = "no_properties"
    SHOW = "show"
    SIMULATE = "simulate"
    STEPS = "steps"
    SYNC = "sync"
    TIMEOUT = "timeout"
    TRANSLATE_CEX = "translate_cex"
    CORES_TO = "to"
    VALUES = "values"
    VERBOSE = "verbose"


LONGDESCR = f"""
* * * {__summary__} v{__version__} ({__date__}) * * *

FILE -- path of LABS file to analyze

VALUES -- assign values for parameterised specification (key=value)
"""

HELPMSG = {
    Args.BACKEND: "Backend to use in verification mode.",

    Args.BV: "Enable bitvector optimization where supported.",

    Args.CONCRETIZATION: "Type of concretization (only for simulation).",

    Args.CORES: "Number of CPU cores for parallel analysis.",

    Args.DEBUG: "Enable additional checks in the backend.",

    Args.FAIR: "Enforce fair interleaving of components.",

    Args.CORES_FROM: "Parallel analysis: partition start.",

    Args.KEEP_FILES: "Do not remove intermediate files.",

    Args.INCLUDE: (
        "Add custom code to generated program "
        "(may be specified multiple times)."),

    Args.PROPERTY: "Property to consider, others will be ignored.",

    Args.NO_CONCRETIZE: "Disable concretization step (only for simulation).",

    Args.NO_PROPERTIES: "Ignore all properties.",

    Args.SHOW: "Print emulation program and exit.",

    Args.SIMULATE: (
        "Number of simulation traces to generate. "
        "If 0, run in verification mode."),

    Args.STEPS: (
        "Number of system evolutions. "
        "If 0, generate an unbounded system."),

    Args.SYNC: "Force synchronous stigmergy messages.",

    Args.TIMEOUT: (
        "Configure time limit (seconds). "
        "Set to 0 to disable timeout."),

    Args.TRANSLATE_CEX: (
        "Translate given counterexample to LAbS and exit."
    ),

    Args.CORES_TO: "Parallel analysis: partition end.",

    Args.VALUES: "assign values for parameterised specification (key=value)",

    Args.VERBOSE: "Print additional messages from the backend."
}

DEFAULTS = {
    Args.BACKEND: "cbmc",
    Args.BV: True,
    Args.CONCRETIZATION: "src",
    Args.CORES: 1,
    Args.DEBUG: False,
    Args.FAIR: False,
    Args.CORES_FROM: None,
    Args.INCLUDE: tuple(),
    Args.KEEP_FILES: False,
    Args.PROPERTY: None,
    Args.NO_CONCRETIZE: False,
    Args.NO_PROPERTIES: False,
    Args.SHOW: False,
    Args.SIMULATE: 0,
    Args.STEPS: 0,
    Args.SYNC: False,
    Args.TIMEOUT: 0,
    Args.TRANSLATE_CEX: None,
    Args.CORES_TO: None,
    Args.VALUES: tuple(),
    Args.VERBOSE: False
}


def CLICK(name, **kwargs):
    return {
        "help": HELPMSG[name],
        "show_default": name in DEFAULTS,
        **({} if DEFAULTS[name] is None else {"default": DEFAULTS[name]}),
        **kwargs
    }


class CliArgs(dict):
    def __init__(self, file, __dict) -> None:
        self.file = file
        self.update(__dict)
        self.externs = {}
        for x in self[Args.VALUES]:
            k, v = x.split("=")
            self.externs[k] = int(v)

    def __getitem__(self, key: Args):
        return self.get(key.value, DEFAULTS[key])

    def __setitem__(self, key: Args, value):
        if isinstance(key, Args):
            self[key.value] = value
        else:
            super().__setitem__(key, value)


class ExitStatus(Enum):
    SUCCESS = 0
    BACKEND_ERROR = 1
    INVALID_ARGS = 2
    PARSING_ERROR = 6
    FAILED = 10
    TIMEOUT = 124
    NOT_FOUND = 127
    KILLED = 130

    @staticmethod
    def format(code, simulate=False) -> str:
        task = "Simulation" if simulate else "Verification"
        return {
            ExitStatus.SUCCESS:
                "Done." if simulate else "Verification successful.",
            ExitStatus.BACKEND_ERROR: "Backend failed.",
            ExitStatus.INVALID_ARGS: "Invalid arguments.",
            ExitStatus.PARSING_ERROR: "Could not parse input file.",
            ExitStatus.FAILED: f"{task} failed.",
            ExitStatus.TIMEOUT: f"{task} stopped (timeout).",
            ExitStatus.KILLED: f"\n{task} stopped (keyboard interrupt)."
        }.get(code, f"Unexpected exit code {code.value}")


@dataclass
class SliverError(BaseException):
    status: ExitStatus
    stdout: str = ""
    error_message: str = ""
    info_message: str = ""

    def handle(self, log=log, quit=False, quiet=False, simulate=False):
        if self.info_message:
            log.info(self.info_message)
        if self.error_message:
            log.error(self.error_message)
        if self.stdout:
            print(self.stdout)
        if not quiet:
            print(ExitStatus.format(self.status, simulate))
        if quit:
            print()
            sys.exit(self.status.value)
