#!/usr/bin/env python3
import logging
from pathlib import Path
from subprocess import STDOUT, CalledProcessError, TimeoutExpired, check_output

from ..atlas.atlas import get_quant_formula, get_state_vars
from ..atlas.mcl import translate_property
from ..atlas.svl import svl
from ..app.cex import translate_cadp
from ..app.cli import Args, ExitStatus, SliverError
from ..app.info import get_var
from ..analysis.value_analysis import value_analysis
from ..analysis.domains import Stripes

from .common import Backend, Language, log_call

log = logging.getLogger('backend')


class CadpMonitor(Backend):
    """The CADP-based workflow presented in the paper
    "Combining SLiVER with CADP to Analyze Multi-agent Systems"
    (COORDINATION, 2020).
    """
    def __init__(self, cwd, cli):
        super().__init__(cwd, cli)
        self.name = "cadp-monitor"
        self.modalities = ("always", "eventually", "finally")
        self.language = Language.LNT_MONITOR

    def check_cadp(self):
        try:
            cmd = ["cadp_lib", "caesar"]
            check_output(cmd, stderr=STDOUT, cwd=self.cwd)
            return True
        except (CalledProcessError, FileNotFoundError):
            raise SliverError(
                status=ExitStatus.BACKEND_ERROR,
                error_message=(
                    "CADP not found or invalid license file. "
                    "Please, visit https://cadp.inria.fr "
                    "to obtain a valid license."))

    def get_cmdline(self, fname, info):
        cmd = ["lnt.open", fname, "evaluator", "-diag"]
        if self.cli[Args.DEBUG]:
            cmd.append("-verbose")
        modality = info.properties[0].split()[0]
        mcl = "fairly.mcl" if modality == "finally" else "never.mcl"
        mcl = str(Path("backends") / "cadp" / mcl)
        cmd.append(mcl)
        return cmd

    def translate_cex(self, cex, info):
        return translate_cadp(cex, info)

    def simulate(self, fname, info):
        if not self.check_cadp():
            return ExitStatus.BACKEND_ERROR
        cmd = [
            "lnt.open", fname, "executor",
            str(self.cli[Args.STEPS]), "2"]
        if self.cli[Args.TIMEOUT]:
            cmd = [self.timeout_cmd, str(self.cli[Args.TIMEOUT]), *cmd]

        try:
            for i in range(self.cli[Args.SIMULATE]):
                log_call(cmd)
                out = check_output(cmd, stderr=STDOUT, cwd=self.cwd).decode()
                self.verbose_output(out, "Backend output")
                header = f"====== Trace #{i+1} ======"
                print(header)
                for ln in self.translate_cex(out, info):
                    print(ln, sep="", end="")
                print(f'{"" :=<{len(header)}}')
            return ExitStatus.SUCCESS
        except CalledProcessError as err:
            self.verbose_output(err.output.decode(), "Backend output")
            return ExitStatus.BACKEND_ERROR

    def cleanup(self, fname):
        self.temp_files.append("evaluator.bcg")
        aux = (Path(self.cwd) / f for f in
               ("evaluator", "executor", "evaluator@1.o"))
        aux2 = (Path(self.cwd) / f"{Path(fname).stem}.{suffix}" for suffix in
                ("err", "f", "h", "h.BAK", "lotos", "o", "t"))
        self._safe_remove(aux)
        self._safe_remove(aux2)
        super().cleanup(fname)

    def preprocess(self, code, fname):
        base_name = Path(fname).stem.upper()
        return code.replace("module HEADER is", f"module {base_name} is")

    def handle_success(self, out, info) -> ExitStatus:
        if "\nFALSE\n" in out or "\nFAIL\n" in out:
            if "evaluator.bcg" in out and "<initial state>" not in out:
                cex = self.extract_trace()
                if cex:
                    print("Counterexample prefix:")
                    print(*self.translate_cex(cex, info), sep="", end="")
            else:
                print(*self.translate_cex(out, info), sep="", end="")
            return ExitStatus.FAILED
        else:
            return super().handle_success(out, info)

    def extract_trace(self):
        cmd = ["bcg_open", "evaluator.bcg", "executor", "100", "2"]
        log_call(cmd)
        try:
            out = check_output(
                cmd, stderr=STDOUT, cwd=self.cwd, timeout=180).decode()
            self.verbose_output(out, "Trace from counterexample BCG")
            return out
        except TimeoutExpired:
            log.info("Could not extract a counterexample.")
            return ""


class Cadp(CadpMonitor):
    """The CADP-based workflow presented in the paper
    "Verifying temporal properties of stigmergic collective systems using CADP"
    (ISoLA, 2021).
    """
    def __init__(self, cwd, cli):
        super().__init__(cwd, cli)
        # Fall back to "monitor" encoding for simulation
        self.language = (
            Language.LNT_MONITOR
            if self.cli[Args.SIMULATE]
            else Language.LNT)
        self.name = "cadp"
        self.modalities = (
            "always", "eventually", "fairly", "fairly_inf", "finally")

    def get_cmdline(self, fname, _):
        cmd = ["bcg_open", f"{fname}.min.bcg", "evaluator4", "-diag"]
        if self.cli[Args.DEBUG]:
            cmd.append("-verbose")
        cmd.append(self._mcl_fname(fname))
        return cmd

    def _mcl_fname(self, fname):
        return f"{fname}.mcl"

    def verify(self, fname, info):
        mcl = translate_property(info, self.cli.externs)
        mcl_fname = self._mcl_fname(fname)
        log.debug(f"Writing MCL query to {mcl_fname}...")
        with open(mcl_fname, "w") as f:
            f.write(mcl)
        self.temp_files.append(mcl_fname)
        self.verbose_output(mcl, "MCL property")

        try:
            cmd = ["lnt.open", fname, "generator", f"{fname}.bcg"]
            log_call(cmd)
            out = check_output(cmd, stderr=STDOUT, cwd=self.cwd).decode()
            self.verbose_output(out, "BCG generation ourput:")
            # ###### WARNING ##########
            # Here we can use divbranching because the properties we support
            # so far are preserved by it. Extensions to the property language
            # may require sharp or strong reduction.
            cmd = [
                "bcg_min", "-divbranching", f"{fname}.bcg", f"{fname}.min.bcg"]
            log_call(cmd)
            check_output(cmd, stderr=STDOUT, cwd=self.cwd).decode()
            self.temp_files.append(f"{fname}.bcg")
            self.temp_files.append(f"{fname}.min.bcg")
            return Backend.verify(self, fname, info)
        except CalledProcessError as err:
            log.error(err.output.decode())
            return ExitStatus.BACKEND_ERROR

    def handle_success(self, out, info) -> ExitStatus:
        result = super().handle_success(out, info)
        if "\nFALSE\n" in out and "evaluator.bcg" not in out:
            print("<property violated>")
        return result

    def cleanup(self, fname):
        self._safe_remove((
            self.cwd / "evaluator4",
            self.cwd / f"{fname}@1.o",
            self.cwd / f"{fname}.min@1.o",
        ))
        super().cleanup(fname)


class CadpCompositional(CadpMonitor):
    """The CADP-based workflow using parallel emulation programs.
    """
    def __init__(self, cwd, cli):
        super().__init__(cwd, cli)
        # Fall back to "monitor" encoding for simulation
        self.language = (
            Language.LNT_MONITOR
            if self.cli[Args.SIMULATE]
            else Language.LNT_PARALLEL)
        self.name = "cadp-comp"
        self.modalities = (
            "always", "eventually", "fairly", "fairly_inf", "finally")

    def get_cmdline(self, fname, _):
        return ["svl", self._svl_fname(fname)]

    def _svl_fname(self, fname):
        return f"SVL_{Path(fname).stem}.svl"

    def _mcl_fname(self, fname):
        return Path(fname).with_suffix(".mcl")

    def preprocess(self, code, fname):
        code = super().preprocess(code, fname)
        info = self.get_info(parsed=True)
        ranges, fixpoint, *_ = value_analysis(self.cli, info, Stripes)
        self.verbose_output(str(ranges), "Value analysis")
        if not fixpoint:
            raise SliverError(
                status=ExitStatus.BACKEND_ERROR,
                error_message=f"Value analysis of {fname} did not succeed.")

        all_args = (
            (info.i, "i", info.max_key_i() + 1),
            (info.lstig, "l", info.max_key_lstig() + 1),
        )

        def fmt(store, array_name, bound):
            def make_assignments():
                for idx in range(bound):
                    var = get_var(store, idx)
                    intervals = tuple(getattr(ranges, var.name).stripes)
                    if len(intervals) == 1 and intervals[0].min == intervals[0].max:  # noqa: E501
                        yield f"{array_name}[{idx}] := {intervals[0].min}"
                    else:
                        constraints = " or ".join(
                            f"(x == {i.min})" if i.min == i.max
                            else f"(x >= {i.min}) and (x <= {i.max})"
                            for i in intervals
                        )
                        yield f"    x := any Int where ({constraints});\n    {array_name}[{idx}] := x"  # noqa: E501
                return

            assigns = ";\n    ".join(make_assignments())
            return "\n".join((
                "var x: Int in",
                "    ",
                assigns,
                "end var;")) if assigns else ""

        good_i, good_l = fmt(*all_args[0]), fmt(*all_args[1])
        code = code.replace("(*GOODIFACE*)", good_i)
        code = code.replace("(*GOODLSTIG*)", good_l)
        return code

    def verify(self, fname, info):
        mcl = translate_property(info, self.cli.externs)
        mcl_fname = self._mcl_fname(fname)
        log.debug(f"Writing MCL query to {mcl_fname}...")
        with open(mcl_fname, "w") as f:
            f.write(mcl)
        self.temp_files.append(mcl_fname)
        self.verbose_output(mcl, "MCL property")

        atlas = get_quant_formula(info)
        atlas_vars = get_state_vars(atlas[0].quant)
        not_hidden = set()
        for x in atlas_vars:
            var = info.lookup_var(x)
            lnt_names = {"i": "ATTR", "lstig": "L"}
            n = lnt_names.get(var.store)
            if n:
                not_hidden.add(n)

        svl_script = svl(
            str(Path(fname).name),
            not_hidden,
            has_stigmergy=bool(info.lstig),
            has_env=bool(info.e),
            num_agents=info.spawn.num_agents(),
            cli=self.cli)
        svl_fname = self._svl_fname(fname)
        with open(svl_fname, "w") as f:
            f.write(svl_script)
        self.temp_files.append(svl_fname)
        svl_logfile = Path(svl_fname).with_suffix(".log")
        self.temp_files.append(svl_logfile)
        self.temp_files.append(f"{fname}.bcg")
        self.verbose_output(svl_script, "SVL script")
        result = Backend.verify(self, fname, info, suppress_output=True)
        with open(svl_logfile) as logfile:
            self.verbose_output(logfile.read(), "Backend output")
        return result

    def handle_success(self, out, info) -> ExitStatus:
        log_fname = (self.base_dir / self.make_slug())
        log_fname = log_fname.with_name(f"SVL_{log_fname.stem}.log")
        with open(log_fname) as f:
            out = f.read()
        result = super().handle_success(out, info)
        if "\nFALSE\n" in out:
            print("<property violated>")
        return result

    def cleanup(self, fname):
        svl_fname = self._svl_fname(fname)
        sweep = ["svl", "-sweep", svl_fname]
        clean = ["svl", "-clean", svl_fname]
        if not self.cli[Args.KEEP_FILES]:
            for cmd in (sweep, clean):
                try:
                    log_call(cmd)
                    cmd_out = check_output(cmd).decode()
                    log.debug(cmd_out)
                except CalledProcessError:
                    continue
        else:
            log.debug("Keeping SVL intermediate files. To remove them, use:")
            log.debug("    " + " ".join(sweep))
            log.debug("    " + " ".join(clean))
        self._safe_remove((
            self.cwd / f"{fname}@1.o",
            self.cwd / "svl001_composition_1.err#0",
        ))
        super().cleanup(fname)
