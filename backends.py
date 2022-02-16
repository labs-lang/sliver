#!/usr/bin/env python3
import logging
import os
import platform
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from subprocess import (PIPE, STDOUT, CalledProcessError, TimeoutExpired,
                        check_output, run)

from atlas.atlas import get_quant_formula, get_state_vars
from atlas.concretizer import Concretizer
from atlas.mcl import translate_property
from atlas.svl import svl
from cex import (translate_cadp, translateCPROVER, translateCPROVER54,
                 translateCPROVERNEW)
from cli import Args, ExitStatus, SliverError
from info import Info, get_var
from utils.value_analysis import value_analysis

log = logging.getLogger('backend')


def log_call(cmd):
    log.debug(f"Executing {' '.join(str(x) for x in cmd)}")


@dataclass
class LanguageInfo:
    extension: str
    encoding: str


class Language(Enum):
    C = LanguageInfo(extension="c", encoding="c")
    LNT = LanguageInfo(extension="lnt", encoding="lnt")
    LNT_MONITOR = LanguageInfo(extension="lnt", encoding="lnt-monitor")
    LNT_PARALLEL = LanguageInfo(extension="lnt", encoding="lnt-parallel")


class Backend:
    """Base class representing a generic analysis backend."""

    _run_args = {"stdout": PIPE, "stderr": PIPE, "check": True}

    def __init__(self, base_dir, cli):
        if "Linux" in platform.system():
            self.timeout_cmd = "/usr/bin/timeout"
        else:
            self.timeout_cmd = "/usr/local/bin/gtimeout"
        self.cli = cli
        self.base_dir = base_dir
        self.cwd = base_dir
        self.temp_files = []
        self.modalities = tuple()

    def cleanup(self, _):
        if self.cli[Args.KEEP_FILES]:
            for f in self.temp_files:
                log.info(f"Keeping {f}")
        else:
            self._safe_remove(self.temp_files)

    def _safe_remove(self, files):
        for f in files:
            try:
                log.debug(f"Removing {f}...")
                os.remove(f)
            except FileNotFoundError:
                pass

    def check_cli(self):
        if not self.cli[Args.SIMULATE] and self.cli[Args.NO_PROPERTIES]:
            raise SliverError(
                status=ExitStatus.SUCCESS,
                info_message="No property to verify!"
            )
        if self.cli[Args.SIMULATE] and self.cli[Args.STEPS] == 0:
            raise SliverError(
                status=ExitStatus.INVALID_ARGS,
                error_message="--simulate requires --steps N (with N>0)."
            )

    def check_info(self, info):
        if not self.cli[Args.SIMULATE]:
            if self.cli[Args.NO_PROPERTIES] or not info.properties:
                log.info("No property to verify!")
                raise SliverError(status=ExitStatus.SUCCESS)
            self.check_property_support(info)

    def check_property_support(self, info):
        for p in info.properties:
            modality = p.split()[0]
            if modality not in self.modalities:
                raise SliverError(
                    status=ExitStatus.BACKEND_ERROR,
                    error_message=f"""Backend '{self.name}' does not support "{modality}" modality."""  # noqa: E501
                )
        return

    def make_slug(self):
        bound, fair, sync, values = (
            str(self.cli[Args.STEPS]),
            self.cli[Args.FAIR],
            self.cli[Args.SYNC],
            self.cli[Args.VALUES]
        )
        result = "_".join((
            # turn "file" into a valid identifier ([A-Za-z_][A-Za-z0-9_]+)
            re.sub(r'\W|^(?=\d)', '_', Path(self.cli.file).stem),
            str(bound), ("fair" if fair else "unfair")))
        options = [o for o in (
            ("sync" if sync else ""),
            "".join(v.replace("=", "") for v in values)) if o != ""]
        if options:
            result = f"{result}_{'_'.join(options)}"
        return f"{result}.{self.language.value.extension}"

    def _labs_cmdline(self):
        call = [
            self.base_dir / "labs" / "LabsTranslate",
            "--file", self.cli.file,
            "--bound", str(self.cli[Args.STEPS]),
            "--enc", self.language.value.encoding]
        flags = [
            (self.cli[Args.FAIR], "--fair"),
            (self.cli[Args.SIMULATE], "--simulation"),
            (not self.cli[Args.BV], "--no-bitvector"),
            (self.cli[Args.SYNC], "--sync"),
            (self.cli[Args.PROPERTY], "--property"),
            (self.cli[Args.PROPERTY], self.cli[Args.PROPERTY]),
            (self.cli[Args.NO_PROPERTIES], "--no-properties")]
        call.extend(b for a, b in flags if a)

        if self.cli[Args.VALUES]:
            call.extend(["--values", *self.cli[Args.VALUES]])
        return call

    def get_info(self, parsed=False):
        try:
            call_info = self._labs_cmdline() + ["--info"]
            log_call(call_info)
            info_call = run(call_info, **self._run_args)
            info = info_call.stdout.decode()
            if parsed:
                info = info.replace("\n", "|")[:-1]
                log.debug(f"{info=}")
                return Info.parse(info, self.cli[Args.VALUES])
            else:
                return info
        except CalledProcessError as e:
            log.error(e)
            msg = e.stderr.decode()
            status = (
                ExitStatus.INVALID_ARGS if msg.startswith("Property")
                else ExitStatus.PARSING_ERROR)
            raise SliverError(status=status, error_message=msg)

    def generate_code(self):
        call = self._labs_cmdline()
        try:
            log_call(call)
            cmd = run(call, **self._run_args)
            out = cmd.stdout.decode()
            fname = str(self.base_dir / self.make_slug())
            # Insert --include'd code
            included = "___includes___\n\n"
            for inc_fname in self.cli[Args.INCLUDE]:
                with open(inc_fname) as f:
                    included += f.read()
            out = out.replace("___includes___", included)
            out = self.preprocess(out, fname)

            if self.cli[Args.SHOW]:
                # TODO add concretize cli options
                if self.cli[Args.SIMULATE] and self.language == Language.C:
                    log.info(f"Gathering information on {self.cli.file}...")
                    info = self.get_info(parsed=True)
                    self.check_info(info)
                    c = Concretizer(info, self.cli, True)
                    out = c.concretize_program(out)
                print(out)
            else:
                log.debug(f"Writing emulation program to {fname}...")
                with open(fname, 'w') as out_file:
                    out_file.write(out)
                self.temp_files.append(fname)
            return fname
        except CalledProcessError as e:
            log.error(e)
            msg = e.stderr.decode()
            status = (
                ExitStatus.INVALID_ARGS if msg.startswith("Property")
                else ExitStatus.PARSING_ERROR)
            raise SliverError(status=status, error_message=msg)

    def preprocess(self, code, _):
        """Preprocesses code so that it is compatible with the backend.
        """
        return code

    def simulate(self, *args):
        """Returns random executions of the program at fname.
        """
        print("This backend does not support simulation.")
        return ExitStatus.BACKEND_ERROR

    def verify(self, fname, info):
        """Verifies the correctness of the program at fname.
        """

        cmd = self.get_cmdline(fname, info)
        if self.cli[Args.TIMEOUT] > 0:
            cmd = [self.timeout_cmd, str(self.cli[Args.TIMEOUT]), *cmd]
        try:
            log_call(cmd)
            out = check_output(cmd, stderr=STDOUT, cwd=self.cwd).decode()

            self.verbose_output(out, "Backend output")
            return self.handle_success(out, info)
        except CalledProcessError as err:
            log.debug(err)
            self.verbose_output(err.output.decode(), "Backend output")
            return self.handle_error(err, fname, info)

    def verbose_output(self, output, decorate=None):
        if decorate:
            log.debug(f"""
------{decorate}------
{output}
---------------------------""")
        else:
            log.debug(output)

    def handle_success(self, *args) -> ExitStatus:
        return ExitStatus.SUCCESS

    def handle_error(self, err, *args) -> ExitStatus:
        if err.returncode == 124:
            return ExitStatus.TIMEOUT
        else:
            return ExitStatus.BACKEND_ERROR


class Cbmc(Backend):
    def __init__(self, cwd, cli):
        super().__init__(cwd, cli)
        self.name = "cbmc"
        self.modalities = ("always", "finally")
        self.language = Language.C

    def get_cbmc_version(self, cmd):
        CBMC_V, *CBMC_SUBV = check_output(
            [cmd[0], "--version"],
            cwd=self.cwd).decode().strip().split(" ")[0].split(".")
        CBMC_SUBV = CBMC_SUBV[0]
        return CBMC_V, CBMC_SUBV

    def get_cmdline(self, fname, _):
        cmd = [os.environ.get("CBMC") or (
            str(self.cwd / "backends" / "cbmc" / "cbmc-simulator")
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


class Cseq(Backend):
    def __init__(self, cwd, cli):
        super().__init__(cwd, cli)
        self.name = "cseq"
        self.modalities = ("always", "finally")
        self.language = Language.C
        self.cwd /= Path("backends") / "cseq"

    def get_cmdline(self, fname, info):
        result = [
            os.environ.get("CSEQ") or str(self.cwd / "cseq.py"),
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
                error_message="Backend 'cseq' requires --steps N (with N>0)."
            )

    def translate_cex(self, cex, info):
        return translateCPROVER(cex, info)

    def handle_error(self, err: CalledProcessError, fname, info):
        if err.returncode in (1, 10):
            out = err.output.decode("utf-8")
            for ln in self.translate_cex(out, info):
                print(ln, sep="", end="")
            return ExitStatus.FAILED
        elif err.returncode == 6:
            log.info("Backend failed with parsing error.")
            return ExitStatus.BACKEND_ERROR
        else:
            return super().handle_error(err, fname, info)


class Esbmc(Backend):
    def __init__(self, cwd, cli):
        super().__init__(cwd, cli)
        self.name = "esbmc"
        self.modalities = ("always", "finally")
        self.language = Language.C

    def get_cmdline(self, fname, _):
        cmd = [
            os.environ.get("ESBMC") or "esbmc", fname,
            "--no-pointer-check", "--no-align-check",
            "--no-unwinding-assertions", "--z3"
        ]
        if not self.cli[Args.DEBUG]:
            cmd.extend(("--no-bounds-check", "--no-div-by-zero-check"))
        return cmd


class CadpMonitor(Backend):
    """The CADP-based workflow presented in the paper
    "Combining SLiVER with CADP to Analyze Multi-agent Systems"
    (COORDINATION, 2020).
    """
    def __init__(self, cwd, cli):
        super().__init__(cwd, cli)
        self.name = "cadp-monitor"
        self.modalities = ("always", "finally")
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
        if not(self.check_cadp()):
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
        if "\nFALSE\n" in out:
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
        self.modalities = ("always", "fairly", "fairly_inf", "finally")

    def get_cmdline(self, fname, _):
        cmd = ["lnt.open", fname, "evaluator4", "-diag"]
        if self.cli[Args.DEBUG]:
            cmd.append("-verbose")
        cmd.append(self._mcl_fname(fname))
        return cmd

    def _mcl_fname(self, fname):
        return f"{fname}.mcl"

    def verify(self, fname, info):
        mcl = translate_property(info)
        mcl_fname = self._mcl_fname(fname)
        log.debug(f"Writing MCL query to {mcl_fname}...")
        with open(mcl_fname, "w") as f:
            f.write(mcl)
        self.temp_files.append(mcl_fname)
        self.verbose_output(mcl, "MCL property")
        return Backend.verify(self, fname, info)

    def handle_success(self, out, info) -> ExitStatus:
        result = super().handle_success(out, info)
        if "\nFALSE\n" in out and "evaluator.bcg" not in out:
            print("<property violated>")
        return result

    def cleanup(self, fname):
        self._safe_remove((self.cwd / "evaluator4", ))
        super().cleanup(fname)


class CadpCompositional(CadpMonitor):
    """The CADP-based workflow using parallel emulation programs
    """
    def __init__(self, cwd, cli):
        super().__init__(cwd, cli)
        # Fall back to "monitor" encoding for simulation
        self.language = (
            Language.LNT_MONITOR
            if self.cli[Args.SIMULATE]
            else Language.LNT_PARALLEL)
        self.name = "cadp-comp"
        self.modalities = ("always", "fairly", "fairly_inf", "finally")

    def get_cmdline(self, fname, _):
        return ["svl", self._svl_fname(fname)]

    def _svl_fname(self, fname):
        return f"SVL_{Path(fname).stem}.svl"

    def _mcl_fname(self, fname):
        return Path(fname).with_suffix(".mcl")

    def preprocess(self, code, fname):
        code = super().preprocess(code, fname)
        info = self.get_info(parsed=True)
        ranges, fixpoint = value_analysis(self.cli, info)
        self.verbose_output(str(ranges), "Value analysis")
        if not fixpoint:
            log.critical(f"Value analysis of {fname} did not succeed.")
            return ExitStatus.BACKEND_ERROR

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
        mcl = translate_property(info)
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

        svl_script = svl(str(Path(fname).name), not_hidden)
        svl_fname = self._svl_fname(fname)
        with open(svl_fname, "w") as f:
            f.write(svl_script)
        self.temp_files.append(svl_fname)
        self.temp_files.append(Path(svl_fname).with_suffix(".log"))
        self.temp_files.append(f"{fname}.bcg")
        self.verbose_output(svl_script, "SVL script")
        return Backend.verify(self, fname, info)

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
        if not(self.cli[Args.KEEP_FILES]):
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


ALL_BACKENDS = {
    **{clz.__name__.lower(): clz for clz in (Cbmc, Cseq, Esbmc, Cadp)},
    "cadp-monitor": CadpMonitor,
    "cadp-comp": CadpCompositional
}
