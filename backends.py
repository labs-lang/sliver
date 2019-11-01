#!/usr/bin/env python3
from enum import Enum
import os
from subcommand import check_output, CalledProcessError, DEVNULL


class Backends(Enum):
    CBMC = "cbmc"
    ESBMC = "esbmc"
    CSeq = "cseq"


class Backend:
    def __init__(self, cwd):
        self.cwd = cwd

    def run(self, **kwargs):
        args = self.debug_args if kwargs["debug"] else self.args
        cmd = [self.command, *args]
        try:
            out = check_output(cmd, stderr=DEVNULL, cwd=self.cwd)
            return self.handle_success(out)
        except CalledProcessError as err:
            out = b""
            return self.handle_error(err)


class Cbmc(Backend):
    def __init__(self, cwd):
        self.cwd = cwd
        self.command = os.environ.get("CBMC") or "cbmc"
        self.args = []
        self.debug_args = ["--bounds-check", "--signed-overflow-check"]

        self.errorCodes = {
            10: False
        }

        CBMC_V, CBMC_SUBV = check_output(
            [self.command, "--version"],
            cwd=cwd).decode().strip().split(".")
        if not (int(CBMC_V) <= 5 and int(CBMC_SUBV) <= 4):
            additional_flags = ["--trace", "--stop-on-fail"]
            self.args.extend(additional_flags)
            self.debug_args.extend(additional_flags)
        super().__init__(cwd)

