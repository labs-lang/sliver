#!/usr/bin/env python3
from hashlib import sha1
from subprocess import run, PIPE
import tempfile
import re

from sliver.app.cli import ExitStatus
from ..app.cli import Args
from .common import Backend, Language, log_call


def translate_nuxmv(cex, info):
    ATTR = re.compile(r"i\[([0-9]+)l?\]\[([0-9]+)l?\]")
    ENV = re.compile(r"e\[([0-9]+)l?\]")
    LSTIG = re.compile(r"lstig\[([0-9]+)l?\]\[([0-9]+)l?\]")

    def pprint_assign(var, value, tid="", init=False):
        def fmt(match, store_name, tid):
            tid = match[1] if len(match.groups()) > 1 else tid
            k = match[2] if len(match.groups()) > 1 else match[1]
            agent = f"{info.pprint_agent(tid)}:" if tid != "" else ""
            assign = info.pprint_assign(store_name, int(k), value)
            return f"\n{agent}\t{assign}"
        is_attr = ATTR.match(var)
        if is_attr and info.i:
            return fmt(is_attr, "I", tid)
        is_env = ENV.match(var)
        if is_env:
            return fmt(is_env, "E", tid)
        is_lstig = LSTIG.match(var)
        if is_lstig:
            return fmt(is_lstig, "L", tid)
        return ""

    tid = ""
    for i, state in enumerate(cex.split("->")[2:]):
        if i == 0:
            yield "<initialization>"
        elif i == 1:
            yield "\n<end initialization>"
        if i % 2 == 1:
            yield f"""\n<step {(i // 2)}>"""
        for asgn in state.split("<-")[1].split("\n"):
            asgn = asgn.strip()
            if asgn:
                lhs, rhs = asgn.split("=")
                if lhs == "tid":
                    tid = rhs.strip()
                    continue
                pprint = pprint_assign(lhs, rhs, tid, i > 0)
                if pprint:
                    yield pprint
    yield f"""\n<step {(i // 2)}>\n"""


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
