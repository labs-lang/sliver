#!/usr/bin/env python3
from hashlib import sha1
from subprocess import run, PIPE
import tempfile

from sliver.app.cli import ExitStatus
from ..app.cli import Args
from .common import Backend, Language, log_call
from ..app.cex import translate_nuxmv


class NuXmv(Backend):
    def __init__(self, cwd, cli):
        super().__init__(cwd, cli)
        self.name = "nuxmv"
        self.modalities = ("always", "finally", "eventually", "between")
        self.language = Language.NUXMV

    def get_cmdline(self, fname, _):
        SIM_SCRIPT = '\n'.join((
            "go_msat",
            "msat_pick_state",
            f"msat_simulate -k {self.cli[Args.STEPS]*2}",
            "show_traces",
            "quit"
            ))
        with tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8") as src_file:  # noqa: E501
            if self.cli[Args.SIMULATE]:
                src_file.write(SIM_SCRIPT)
            src_file.close()
            self.temp_files.append(src_file.name)

        return ["nuxmv", "-source", src_file.name, fname]

    def simulate(self, fname, info):
        # TODO randomize simulations (this requires interacting with nuxmv...)
        for i in range(self.cli[Args.SIMULATE]):
            cmd = self.get_cmdline(fname, info)
            log_call(cmd)
            result = run(
                cmd, cwd=self.cwd, check=True, stderr=PIPE, stdout=PIPE)
            out = result.stdout.decode()
            self.verbose_output(result.stderr.decode(), "Backend stderr")
            self.verbose_output(out, "Backend output")
            trace_hash = sha1()
            header = f"====== Trace #{i+1} ======"
            print(header)
            for x in self.translate_cex(out, info):
                trace_hash.update(x.encode())
                print(x, sep="", end="")
            # This just prints a line of '=' that is as long as header
            print(f'{"" :=<{len(header)}}')
            self.verbose_output(f"Digest of trace #{i+1}: {trace_hash.hexdigest()}")  # noqa: E501
        return ExitStatus.SUCCESS

    def handle_success(self, out: str, info) -> ExitStatus:
        print(*self.translate_cex(out, info), sep="", end="")

    def translate_cex(self, out, info):
        yield from translate_nuxmv(out, info)
