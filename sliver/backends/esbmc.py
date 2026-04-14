
import os
from importlib import resources
import re
from shutil import which
from subprocess import CalledProcessError

from ..app.cli import Args, ExitStatus, SliverError
from ..analysis.value_analysis import value_analysis
from .common import Backend, Language
from .cbmc import translateCPROVERcex


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
        return translateCPROVERcex(cex, info, start="start_esbmc")

    def generate_code(self, *_):
        filename = super().generate_code(
            True,
            "--no-bitwise",
            "--c-assume-fn", "__ESBMC_assume",
            "--c-assert-fn", "__ESBMC_assert",
            "--c-nondet-fn", "nondet_int")
        return filename

    def preprocess(self, code, _):
        info = self.get_info(parsed=True)
        ast = self.get_ast()
        ranges, fix, depends, wont_change = value_analysis(self.cli, info, ast)
        self.verbose_output(
            f"Value analysis: {ranges=}, {fix=}, {depends=}, {wont_change=}")

        # Inject invariants as assumptions at the head of the loop
        def fmt_var(var, stripes, tid=None):
            loc = {"i": "I", "e": "E", "l": "Lvalue"}[var.store]

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

        wont_change = ranges if fix else wont_change

        loop_assumptions = []
        # Shared variables
        for f in wont_change:
            try:
                var = info.lookup_var(f)
                if var.store == "e":
                    loop_assumptions.extend(
                        f"__ESBMC_assume({x});"
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
                        f"__ESBMC_assume({x});"
                        for x in fmt_var(var, getattr(ranges, f).stripes, tid)))  # noqa: E501
                except KeyError:
                    # Local variable
                    continue

        loop_assumptions = "\n    ".join(loop_assumptions) + "\n    "
        loop_assumptions += "\n    ".join(
            f"__ESBMC_assume({x});" for x in info.get_pc_invariants())

        signature = "void __invariants(void)"
        loop_assumptions = f"{signature} {{\n    {loop_assumptions}\n}}"
        code = code.replace(f"{signature} {{ }}", loop_assumptions)

        head_of_loop = re.compile(r'while\s*\(1\)\s*{')
        code = head_of_loop.sub("while (1) {\n    __invariants();", code)
        return code

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
