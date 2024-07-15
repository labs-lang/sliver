import os
from importlib import resources
from pathlib import Path
from subprocess import CalledProcessError

from ..app.cli import Args, ExitStatus, SliverError
from .cbmc import translateCPROVER54, translateCPROVERNEW
from .common import Backend, Language


class Cseq(Backend):
    def __init__(self, cwd, cli):
        super().__init__(cwd, cli)
        self.name = "cseq"
        self.modalities = ("always", "finally", "eventually")
        self.language = Language.C
        try:
            executable = self.get_cmdline(fname="a.c", info=None)[0]
            self.cwd /= Path(executable).parent
        except ModuleNotFoundError:
            # CSeq is not available
            pass

    def get_cmdline(self, fname, info):
        with resources.path("sliver.cseq", "cseq.py") as cseq_exec:
            result = [
                os.environ.get("CSEQ") or cseq_exec,
                "-l", "labs_parallel",
                "-i", fname
            ]

        args = (
            ("--steps", self.cli[Args.STEPS]),
            ("--cores", self.cli[Args.CORES]),
            ("--from", self.cli[Args.CORES_FROM]),
            ("--to", self.cli[Args.CORES_TO])
        )
        args = ((a[0], str(a[1])) for a in args if a[1] is not None)
        for arg in args:
            if arg[1] is not None:
                result.extend(arg)
        # TODO change split according to info
        if info is not None:
            result += ["--split", "I", "--info", info.raw]
        return result

    def cleanup(self, fname):
        aux = (
            str(self.cwd / f"_cs_{Path(fname).stem}.{suffix}")
            for suffix in (
                "c", "c.map", "cbmc-assumptions.log", "c.cbmc-assumptions.log")
        )
        self._safe_remove(aux)
        super().cleanup(fname)

    def check_cli(self):
        super().check_cli()
        if not self.cli[Args.STEPS] and not self.cli[Args.SHOW]:
            raise SliverError(
                status=ExitStatus.INVALID_ARGS,
                error_message="Backend 'cseq' requires --steps N (with N>0).")

    def translate_cex(self, cex, info):
        try:
            return translateCPROVERNEW(cex, info)
        except Exception:
            return translateCPROVER54(cex, info)

    def handle_error(self, err: CalledProcessError, fname, info):
        if err.returncode in (1, 10):
            out = err.output.decode("utf-8")
            for ln in self.translate_cex(out, info):
                print(ln, sep="", end="")
            return ExitStatus.FAILED
        elif err.returncode == 6:
            self.logger.info("Backend failed with parsing error.")
            return ExitStatus.BACKEND_ERROR
        else:
            return super().handle_error(err, fname, info)
