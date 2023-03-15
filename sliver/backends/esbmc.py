
import io
import os
import platform
from importlib import resources
from shutil import which
from subprocess import CalledProcessError

import pcpp

from ..absentee import absentee
from ..app.cex import translateCPROVER54
from ..app.cli import Args, ExitStatus, SliverError
from .common import Backend, Language


class Esbmc(Backend):
    def __init__(self, cwd, cli):
        cli[Args.BV] = False  # Force-disable CPROVER bitvectors
        super().__init__(cwd, cli)
        self.name = "esbmc"
        self.modalities = ("always", "finally", "eventually", "between")
        self.language = Language.C

    def get_cmdline(self, fname, _):
        with resources.path("sliver.esbmc", "esbmc") as esbmc:
            esbmc = esbmc if os.path.exists(esbmc) else None
            esbmc = os.environ.get("ESBMC") or esbmc or which("esbmc")
            if esbmc is None:
                raise SliverError(ExitStatus.BACKEND_ERROR, "esbmc not found")
            cmd = []
            if platform.processor() == "arm" and platform.system() == "Darwin":
                cmd.extend(["arch", "-x86_64"])
            cmd.extend([
                esbmc, fname,
                "--no-align-check", "--no-pointer-check",
                "--no-unwinding-assertions", "--bv"
            ])

            if self.cli[Args.STEPS] == 0:
                cmd.extend(["--k-induction", "--interval-analysis"])
            if not self.cli[Args.DEBUG]:
                cmd.extend(("--no-bounds-check", "--no-div-by-zero-check"))
            return cmd

    def translate_cex(self, cex, info):
        return translateCPROVER54(cex, info)

    def preprocess(self, code, _):
        preproc = pcpp.Preprocessor()
        preproc.parse(code)
        f = io.StringIO("")
        preproc.write(oh=f)
        f.seek(0)

        esbmc_conf = """
        (without-bitwise)
        (replace-calls 
            (__CPROVER_nondet nondet_int)
            (__CPROVER_assert __ESBMC_assert)
            (__CPROVER_assume __ESBMC_assume)
        )
        """
        return absentee.parse_and_execute(f.read(), esbmc_conf)

    def handle_success(self, out, info) -> ExitStatus:
        result = super().handle_success(out, info)
        if "VERIFICATION UNKNOWN" in out:
            return ExitStatus.INCONCLUSIVE
        return result

    def handle_error(self, err: CalledProcessError, fname, info):
        if err.returncode == 1:
            out = err.output.decode("utf-8")
            print(*self.translate_cex(out, info), sep="", end="")
            return ExitStatus.FAILED
        elif err.returncode == 6:
            print("Backend failed with parsing error.")
            return ExitStatus.BACKEND_ERROR
        else:
            return super().handle_error(err, fname, info)
