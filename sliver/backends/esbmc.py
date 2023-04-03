
import io
import os
from importlib import resources
from shutil import which
from subprocess import CalledProcessError

import pcpp

from ..absentee import absentee
from ..app.cex import translateCPROVER54
from ..app.cli import Args, ExitStatus, SliverError
from ..utils.value_analysis import value_analysis
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
            cmd = [
                esbmc, fname,
                "--no-align-check", "--no-pointer-check", "--no-library",
                "--no-unwinding-assertions", "--no-pointer-relation-check",
                "--slice-assumes", "--bv", "--16", "--quiet"
            ]
            
            if self.cli[Args.STEPS] == 0:
                # Enable bidirectional k-induction, otherwise just do BMC
                cmd.extend([
                    "--k-induction", "--bidirectional", "--unlimited-k-steps"
                ])
            if not self.cli[Args.DEBUG]:
                cmd.extend(("--no-bounds-check", "--no-div-by-zero-check"))
            return cmd

    def translate_cex(self, cex, info):
        return translateCPROVER54(cex, info)

    def preprocess(self, code, _):
        # preprocess the generated C code
        preproc = pcpp.Preprocessor()
        preproc.parse(code)
        f = io.StringIO("")
        preproc.write(oh=f)
        f.seek(0)
        code = f.read()

        info = self.get_info(parsed=True)
        ranges, fixpoint, *etc = value_analysis(self.cli, info)
        self.verbose_output(
            f"Value analysis: {ranges=}, {fixpoint=}, {etc=}")

        def fmt_var(var, stripes, tid=None):
            rename = {"i": "I", "e": "E", "l": "Lvalue"}

            def fmt_one(index):
                loc = rename[var.store]
                if var.store == "e":
                    return " | ".join(
                        f"{loc}[{index}] == {i.min}"
                        if i.min == i.max
                        else f"({loc}[{index}] >= {i.min}) & ({loc}[{index}] <= {i.max})"  # noqa: E501
                        for i in stripes)
                else:
                    return " | ".join(
                        f"{loc}[{tid}][{index}] == {i.min}"
                        if i.min == i.max
                        else f"({loc}[{tid}][{index}] >= {i.min}) & ({loc}[{tid}][{index}] <= {i.max})"  # noqa: E501
                        for i in stripes)
            if not var.is_array:
                yield fmt_one(var.index)
            else:
                yield from (
                    fmt_one(i)
                    for i in range(var.index, var.index + var.size))

        if fixpoint:
            self.verbose_output((ranges, fixpoint, ))
            loop_assumptions = []
            # Shared variables
            for f in ranges._fields:
                try:
                    var = info.lookup_var(f)
                    if var.store == "e":
                        loop_assumptions.extend(
                            f"__CPROVER_assume({x});"
                            for x in fmt_var(var, getattr(ranges, f).stripes))  # noqa: E501
                except KeyError:
                    continue

            # Agent variables
            for tid in range(info.spawn.num_agents()):
                agent = info.spawn[tid]
                for f in ranges._fields:
                    try:
                        var = info.lookup_var(f)
                        if var.store == "e" or var.index not in agent.iface:
                            continue
                        loop_assumptions.extend((
                            f"__CPROVER_assume({x});"
                            for x in fmt_var(var, getattr(ranges, f).stripes, tid)))  # noqa: E501
                    except KeyError:
                        # Local variable
                        continue
            loop_assumptions = "\n    ".join(loop_assumptions)
            loop_assumptions = f"""
void loopAssumptions(void) {{
    {loop_assumptions}
}}"""
            code = code.replace(
                """void loopAssumptions(void) { return; }""",
                loop_assumptions)

        esbmc_conf = """
        (without-bitwise)
        (replace-calls
            (__CPROVER_nondet nondet_int)
            (__CPROVER_assert __ESBMC_assert)
            (__CPROVER_assume __ESBMC_assume)
        )
        (without-arrays)
        """
        return absentee.parse_and_execute(code, esbmc_conf)

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
