
import io
import os
from importlib import resources
import re
from shutil import which
from subprocess import CalledProcessError

import pcpp

from sliver.analysis.domains import Stripes, Sign

from ..absentee.absentee import absentee
from ..app.cex import translateCPROVER54
from ..app.cli import Args, ExitStatus, SliverError
from ..analysis.value_analysis import value_analysis
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
            esbmc = os.environ.get("SLIVER_ESBMC") or esbmc or which("esbmc")
            if esbmc is None:
                raise SliverError(ExitStatus.BACKEND_ERROR, "esbmc not found")
            # SLIVER_ESBMC_ARGS completely overrides CLI arguments
            env_args = os.environ.get("SLIVER_ESBMC_ARGS")
            if env_args:
                return [esbmc, fname, *env_args.split()]
            cmd = [
                esbmc, fname,
                "--no-align-check", "--no-pointer-check", "--no-library",
                "--no-unwinding-assertions", "--no-pointer-relation-check"]

            cmd.extend([
                "--k-induction", "--bidirectional", "--unlimited-k-steps",
                "--quiet", "--z3", "--ir"
            ] if self.cli[Args.STEPS] == 0 else ["--bv", "--32"])

            if not self.cli[Args.DEBUG]:
                cmd.extend(("--no-bounds-check", "--no-div-by-zero-check"))
            return cmd

    def translate_cex(self, cex, info):
        return translateCPROVER54(cex, info)

    def preprocess(self, code, _):
        # Get info and pc invariants
        info = self.get_info(parsed=True)
        info.scan_pcmap(code)

        # preprocess the generated C code
        preproc = pcpp.Preprocessor()
        preproc.parse(code)
        f = io.StringIO("")
        preproc.write(oh=f)
        f.seek(0)
        code = f.read()

        ranges, fix, depends, wont_change = value_analysis(self.cli, info, Stripes)  # noqa: E501
        self.verbose_output(
            f"Value analysis: {ranges=}, {fix=}, {depends=}, {wont_change=}")

        s_analysis, s_fix, *_ = value_analysis(self.cli, info, Sign)
        self.verbose_output(f"Sign analysis: {s_analysis=}, {s_fix=}")

        rename = {"i": "I", "e": "E", "l": "Lvalue"}

        def fmt_var(var, stripes, tid=None):
            loc = rename[var.store]

            def fmt_one(index):
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

        wont_change = ranges._fields if fix else wont_change

        loop_assumptions = []
        # Shared variables
        for f in wont_change:
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
            for f in wont_change:
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

        # Consider sign analysis as a last resort
        # TODO refactor common logic here & above
        def fmt_sign(var, sign, tid=None):
            loc = rename[var.store]

            def fmt_one(index):
                if var.store == "e":
                    return (
                        f"{loc}[{index}] > 0" if sign.plus and not sign.zero and not sign.minus else  # noqa: E501
                        f"{loc}[{index}] >= 0" if sign.plus and sign.zero and not sign.minus else  # noqa: E501
                        f"{loc}[{index}] != 0" if sign.plus and not sign.zero and sign.minus else  # noqa: E501
                        f"{loc}[{index}] == 0" if not sign.plus and sign.zero and not sign.minus else  # noqa: E501
                        f"{loc}[{index}] <= 0" if not sign.plus and sign.zero and sign.minus else  # noqa: E501
                        f"{loc}[{index}] < 0" if not sign.plus and not sign.zero and sign.minus else None)  # noqa: E501
                else:
                    return (
                        f"{loc}[{tid}][{index}] > 0" if sign.plus and not sign.zero and not sign.minus else  # noqa: E501
                        f"{loc}[{tid}][{index}] >= 0" if sign.plus and sign.zero and not sign.minus else  # noqa: E501
                        f"{loc}[{tid}][{index}] != 0" if sign.plus and not sign.zero and sign.minus else  # noqa: E501
                        f"{loc}[{tid}][{index}] == 0" if not sign.plus and sign.zero and not sign.minus else  # noqa: E501
                        f"{loc}[{tid}][{index}] <= 0" if not sign.plus and sign.zero and sign.minus else  # noqa: E501
                        f"{loc}[{tid}][{index}] < 0" if not sign.plus and not sign.zero and sign.minus else None)  # noqa: E501
            if not var.is_array:
                yield fmt_one(var.index)
            else:
                yield from (
                    fmt_one(i)
                    for i in range(var.index, var.index + var.size))

        for f in (f for f in s_analysis._fields if f not in wont_change):
            if f == "id":
                continue
            try:
                var = info.lookup_var(f)
                sign = getattr(s_analysis, f)
                if var.store == "e":
                    loop_assumptions.extend(
                        f"__CPROVER_assume({x});"
                        for x in fmt_sign(var, sign) if x is not None)
            except KeyError:
                # Local variable
                continue

        # Agent variables
        for tid in range(info.spawn.num_agents()):
            agent = info.spawn[tid]
            for f in (f for f in s_analysis._fields if f not in wont_change):
                if f == "id":
                    continue
                try:
                    var = info.lookup_var(f)
                    sign = getattr(s_analysis, f)
                    if var.store == "e" or (var.index not in agent.iface and var.index not in agent.lstig):  # noqa: E501
                        continue
                    loop_assumptions.extend((
                        f"__CPROVER_assume({x});"
                        for x in fmt_sign(var, sign, tid) if x is not None))
                except KeyError:
                    # Local variable
                    continue

        loop_assumptions = "\n    ".join(loop_assumptions) + "\n    "
        loop_assumptions += "\n    ".join(
            f"__CPROVER_assume({x});" for x in info.get_pc_invariants())

        loop_assumptions = f"void __invariants(void) {{\n{loop_assumptions}\n}}"  # noqa: E501
        code = code.replace(
            """void __invariants(void) { }""",
            loop_assumptions)

        head_of_loop = re.compile(r'while\s*\(1\)\s*{')
        code = head_of_loop.sub("while (1) {\n __invariants();", code)

        esbmc_conf = """
        (without-bitwise)
        (replace-calls
            (__CPROVER_nondet nondet_int)
            (__CPROVER_assert __ESBMC_assert)
            (__CPROVER_assume __ESBMC_assume)
        )
        """
        # {"(without-arrays)" if self.cli[Args.STEPS] == 0 else ""}
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
