#!/usr/bin/env python3
import os
import platform
from importlib import resources
from subprocess import STDOUT, CalledProcessError, check_output

from ..atlas.concretizer import Concretizer
from ..sliver.cex import translateCPROVER54, translateCPROVERNEW
from ..sliver.cli import Args, ExitStatus, SliverError
from .common import Backend, Language, log_call


class Cbmc(Backend):
    def __init__(self, cwd, cli):
        super().__init__(cwd, cli)
        self.name = "cbmc"
        self.modalities = ("always", "finally", "eventually")
        self.language = Language.C

    def get_cbmc_version(self, cmd):
        CBMC_V, *CBMC_SUBV = check_output(
            [cmd[0], "--version"],
            cwd=self.cwd).decode().strip().split(" ")[0].split(".")
        CBMC_SUBV = CBMC_SUBV[0]
        return CBMC_V, CBMC_SUBV

    def get_cmdline(self, fname, _):
        cmd = [os.environ.get("CBMC") or (
            resources.path("sliver.cbmc", "cbmc-simulator")
            if "Linux" in platform.system()
            else "cbmc")]
        CBMC_V, CBMC_SUBV = self.get_cbmc_version(cmd)
        if not (int(CBMC_V) <= 5 and int(CBMC_SUBV) <= 4):
            cmd += ["--trace", "--stop-on-fail"]
        if self.cli[Args.DEBUG]:
            cmd += ["--bounds-check", "--signed-overflow-check"]
        cmd.append(fname)
        return cmd

    def simulate(self, fname, info):
        cmd = self.get_cmdline(fname, info)
        c = Concretizer(info, self.cli, True)
        for i in range(self.cli[Args.SIMULATE]):
            try:
                c.concretize_file(fname)  # Concretization step
                if self.cli[Args.TIMEOUT] > 0:
                    cmd = [self.timeout_cmd, str(self.cli[Args.TIMEOUT]), *cmd]
                log_call(cmd)
                out = check_output(cmd, stderr=STDOUT, cwd=self.cwd).decode()
                self.verbose_output(out, "Backend output")
            except CalledProcessError as err:
                out = err.output.decode("utf-8")
                self.verbose_output(out, "Backend output")
                try:
                    header = f"====== Trace #{i+1} ======"
                    print(header)
                    for x in self.translate_cex(out, info):
                        print(x, sep="", end="")
                    print(f'{"" :=<{len(header)}}')
                except Exception as e:
                    print(f"Counterexample translation failed: {e}")
        return ExitStatus.SUCCESS

    def check_cli(self):
        super().check_cli()
        if not self.cli[Args.STEPS] and not self.cli[Args.SHOW]:
            raise SliverError(
                status=ExitStatus.INVALID_ARGS,
                error_message="Backend 'cbmc' requires --steps N (with N>0)."
            )

    def translate_cex(self, cex, info):
        cmd = self.get_cmdline("", "")
        CBMC_V, CBMC_SUBV = self.get_cbmc_version(cmd)
        if not (int(CBMC_V) <= 5 and int(CBMC_SUBV) <= 4):
            return translateCPROVERNEW(cex, info)
        else:
            return translateCPROVER54(cex, info)

    def handle_error(self, err: CalledProcessError, fname, info):
        if err.returncode == 10:
            out = err.output.decode("utf-8")
            print(*self.translate_cex(out, info), sep="", end="")
            return ExitStatus.FAILED
        elif err.returncode == 6:
            print("Backend failed with parsing error.")
            return ExitStatus.BACKEND_ERROR
        else:
            return super().handle_error(err, fname, info)
