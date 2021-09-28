#!/usr/bin/env python3
import logging
import os
import platform
import re
from collections import namedtuple
from enum import Enum
from pathlib import Path
from subprocess import check_output, CalledProcessError, STDOUT

from info import raw_info
from cex import translateCPROVER, translate_cadp
from atlas.mcl import translate_property

LanguageInfo = namedtuple("LanguageInfo", ["extension", "encoding"])
log = logging.getLogger('backend')


class Language(Enum):
    C = LanguageInfo(extension="c", encoding="c")
    LNT = LanguageInfo(extension="lnt", encoding="lnt")
    LNT_MONITOR = LanguageInfo(extension="lnt", encoding="lnt-monitor")


class ExitStatus(Enum):
    SUCCESS = 0
    BACKEND_ERROR = 1
    INVALID_ARGS = 2
    PARSING_ERROR = 6
    FAILED = 10
    TIMEOUT = 124
    KILLED = 130

    @staticmethod
    def format(code, simulate=False) -> str:
        task = "Simulation" if simulate else "Verification"
        return {
            ExitStatus.SUCCESS:
                "Done." if simulate else "Verification successful.",
            ExitStatus.BACKEND_ERROR: "Backend failed.",
            ExitStatus.INVALID_ARGS: "Invalid arguments.",
            ExitStatus.PARSING_ERROR: "Could not parse input file.",
            ExitStatus.FAILED: f"{task} failed.",
            ExitStatus.TIMEOUT: f"{task} stopped (timeout).",
            ExitStatus.KILLED: f"\n{task} stopped (keyboard interrupt)."
        }.get(code, f"Unexpected exit code {code.value}")


class Backend:
    """Base class representing a generic analysis backend."""
    def __init__(self, cwd, **kwargs):
        if "Linux" in platform.system():
            self.timeout_cmd = "/usr/bin/timeout"
        else:
            self.timeout_cmd = "/usr/local/bin/gtimeout"
        self.cwd = cwd
        self.kwargs = kwargs
        self.temp_files = []
        self.modalities = tuple()

    def cleanup(self, fname):
        if self.kwargs.get("keep_files"):
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

    def check_property_support(self, info):
        for p in info.properties:
            modality = p.split()[0]
        if modality not in self.modalities:
            log.error(f"""Backend '{self.name}' does not support "{modality}" modality.""")  # noqa: E501
            return ExitStatus.BACKEND_ERROR
        return ExitStatus.SUCCESS

    def generate_code(self, file, simulate, show):
        bound, fair, sync = (
            str(self.kwargs["steps"]),
            self.kwargs["fair"],
            self.kwargs["sync"]
        )

        def make_filename():
            result = "_".join((
                # turn "file" into a valid identifier ([A-Za-z_][A-Za-z0-9_]+)
                re.sub(r'\W|^(?=\d)', '_', Path(file).stem),
                str(bound), ("fair" if fair else "unfair")))
            options = [o for o in (
                ("sync" if self.kwargs["sync"] else ""),
                "".join(v.replace("=", "") for v in values)) if o != ""]
            if options:
                result = f"{result}_{'_'.join(options)}"
            return f"{result}.{self.language.value.extension}"

        call = [
            self.cwd / "labs" / "LabsTranslate",
            "--file", file,
            "--bound", bound,
            "--enc", self.language.value.encoding]
        flags = [
            (fair, "--fair"),
            (simulate, "--simulation"),
            (not self.kwargs["bv"], "--no-bitvector"),
            (sync, "--sync"),
            (self.kwargs["property"], "--property"),
            (self.kwargs["property"], self.kwargs["property"]),
            (self.kwargs["no_properties"], "--no-properties")]
        call.extend(b for a, b in flags if a)

        values = self.kwargs.get("values")
        if values:
            call.extend(["--values", *values])
        try:
            out = check_output(call).decode("utf-8")
            fname = str(self.cwd / make_filename())
            out = self.preprocess(out, fname)
            if show:
                print(out)
                return fname, None
            else:
                with open(fname, 'w') as out_file:
                    out_file.write(out)
                self.temp_files.append(fname)
                return fname, raw_info(call)

        except CalledProcessError as e:
            raise e

    def filename_argument(self, fname):
        """Returns a CLI argument for the input file.
        """
        return [fname]

    def preprocess(self, code, fname):
        """Preprocesses code so that it is compatible with the backend.
        """
        return code

    def simulate(self, fname, info, simulate):
        """Returns random executions of the program at fname.
        """
        print("This backend does not support simulation.")
        return ExitStatus.BACKEND_ERROR

    def verify(self, fname, info):
        """Verifies the correctness of the program at fname.
        """
        args = self.debug_args if self.kwargs["debug"] else self.args
        cmd = [self.command, *self.filename_argument(fname), *args]
        if self.kwargs.get("timeout", 0) > 0:
            cmd = [self.timeout_cmd, str(self.kwargs["timeout"]), *cmd]
        try:
            log.debug(f"Executing {' '.join(cmd)}")
            out = check_output(cmd, stderr=STDOUT, cwd=self.cwd).decode()
            self.verbose_output(out, "Backend output")
            return self.handle_success(out, info)
        except CalledProcessError as err:
            self.verbose_output(err.output.decode(), "Backend output")
            return self.handle_error(err, fname, info)

    def verbose_output(self, output, decorate=None):
        if decorate:
            log.debug(f"""
------{decorate}:------
{output}
---------------------------""")
        else:
            log.debug(output)

    def handle_success(self, out, info) -> ExitStatus:
        return ExitStatus.SUCCESS

    def handle_error(self, err, fname, info) -> ExitStatus:
        if err.returncode == 124:
            return ExitStatus.TIMEOUT
        else:
            return ExitStatus.BACKEND_ERROR


class Cbmc(Backend):
    def __init__(self, cwd, **kwargs):
        super().__init__(cwd, **kwargs)
        self.name = "cbmc"
        self.modalities = ("always", "finally")
        self.language = Language.C
        cmd = str(cwd / "cbmc-simulator") \
            if "Linux" in platform.system() \
            else "cbmc"
        self.command = os.environ.get("CBMC") or cmd
        self.args = []
        self.debug_args = ["--bounds-check", "--signed-overflow-check"]

        CBMC_V, *CBMC_SUBV = check_output(
            [self.command, "--version"],
            cwd=cwd).decode().strip().split(" ")[0].split(".")
        CBMC_SUBV = CBMC_SUBV[0]
        if not (int(CBMC_V) <= 5 and int(CBMC_SUBV) <= 4):
            additional_flags = ["--trace", "--stop-on-fail"]
            self.args.extend(additional_flags)
            self.debug_args.extend(additional_flags)

    def handle_error(self, err: CalledProcessError, fname, info):
        if err.returncode == 10:
            out = err.output.decode("utf-8")
            print(*translateCPROVER(out, fname, info), sep="", end="")
            return ExitStatus.FAILED
        elif err.returncode == 6:
            print("Backend failed with parsing error.")
            return ExitStatus.BACKEND_ERROR
        else:
            return super().handle_error(err, fname, info)


class Cseq(Backend):
    def __init__(self, cwd, **kwargs):
        super().__init__(cwd, **kwargs)
        self.name = "cseq"
        self.modalities = ("always", "finally")
        self.language = Language.C
        self.command = os.environ.get("CSEQ") or str(cwd / "cseq" / "cseq.py")
        self.args = ["-l", "labs_parallel"]

        for arg in ("steps", "cores", "from", "to"):
            if kwargs.get(arg) is not None:
                self.args.extend((f"--{arg}", str(kwargs[arg])))

        self.debug_args = self.args
        self.cwd /= "cseq"

    def verify(self, fname, info):
        # TODO change split according to info
        self.args += ["--split", "_I", "--info", info.raw]
        return super().verify(fname, info)

    def filename_argument(self, fname):
        return ["-i", str(self.cwd / fname)]

    def cleanup(self, fname):
        path = Path(fname)
        aux = (
            str(path.parent / f"_cs_{path.stem}.{suffix}")
            for suffix in ("c", "c.map", "cbmc-assumptions.log")
        )
        super()._safe_remove(aux)
        super().cleanup(fname)

    def handle_error(self, err: CalledProcessError, fname, info):
        if err.returncode in (1, 10):
            out = err.output.decode("utf-8")
            print(*translateCPROVER(out, fname, info, 19), sep="", end="")
            return ExitStatus.FAILED
        elif err.returncode == 6:
            log.info("Backend failed with parsing error.")
            return ExitStatus.BACKEND_ERROR
        else:
            return super().handle_error(err, fname, info)


class Esbmc(Backend):
    def __init__(self, cwd, **kwargs):
        super().__init__(cwd, **kwargs)
        self.name = "esbmc"
        self.modalities = ("always", "finally")
        self.language = Language.C
        self.command = os.environ.get("ESBMC") or "esbmc"
        self.args = [
            "--no-bounds-check", "--no-div-by-zero-check",
            "--no-pointer-check", "--no-align-check",
            "--no-unwinding-assertions", "--z3"]
        self.debug_args = [
            "--no-pointer-check", "--no-align-check",
            "--no-unwinding-assertions", "--z3"]


class CadpMonitor(Backend):
    """The CADP-based workflow presented in the paper
    "Combining SLiVER with CADP to Analyze Multi-agent Systems"
    (COORDINATION, 2020).
    """
    def __init__(self, cwd, **kwargs):
        super().__init__(cwd, **kwargs)
        self.name = "cadp-monitor"
        self.modalities = ("always", "finally")
        self.command = "lnt.open"
        self.args = ["evaluator", "-diag"]
        self.debug_args = ["evaluator", "-verbose", "-diag"]
        self.language = Language.LNT_MONITOR

    def check_cadp(self):
        try:
            cmd = ["cadp_lib", "caesar"]
            check_output(cmd, stderr=STDOUT, cwd=self.cwd).decode()
            return True
        except (CalledProcessError, FileNotFoundError):
            log.error(
                "CADP not found or invalid license file. "
                "Please, visit https://cadp.inria.fr "
                "to obtain a valid license.")
            return False

    def verify(self, fname, info):
        if not(self.check_cadp()):
            return ExitStatus.BACKEND_ERROR
        modality = info.properties[0].split()[0]
        mcl = "fairly.mcl" if modality == "finally" else "never.mcl"
        mcl = str(Path("cadp") / Path(mcl))
        self.args.append(mcl)
        self.debug_args.append(mcl)
        return super().verify(fname, info)

    def simulate(self, fname, info, simulate):
        if not(self.check_cadp()):
            return ExitStatus.BACKEND_ERROR
        cmd = [
            "lnt.open", fname, "executor",
            str(self.kwargs.get("steps", 1)), "2"]
        if self.kwargs.get("timeout", 0) > 0:
            cmd = [self.timeout_cmd, str(self.kwargs["timeout"]), *cmd]

        try:
            for i in range(simulate):
                self.verbose_output(f"Executing {' '.join(cmd)}")
                out = check_output(cmd, stderr=STDOUT, cwd=self.cwd).decode()
                self.verbose_output(out, "Backend output")
                header = f"====== Trace #{i+1} ======"
                print(header)
                print(*translate_cadp(out, info), sep="", end="")
                print(f'{"" :=<{len(header)}}')
            return ExitStatus.SUCCESS
        except CalledProcessError as err:
            self.verbose_output(err.output.decode(), "Backend output")
            return ExitStatus.BACKEND_ERROR

    def cleanup(self, fname):
        aux = (str(Path(self.cwd) / f) for f in
               ("evaluator", "executor", "evaluator@1.o", "evaluator.bcg"))
        path = Path(fname)
        aux2 = (str(path.parent / f"{path.stem}.{suffix}") for suffix in
                ("err", "f", "h", "h.BAK", "lotos", "o", "t"))
        super()._safe_remove(aux)
        super()._safe_remove(aux2)
        super().cleanup(fname)

    def preprocess(self, code, fname):
        base_name = Path(fname).stem.upper()
        return code.replace("module HEADER is", f"module {base_name} is")

    def handle_success(self, out, info) -> ExitStatus:
        if "\nFALSE\n" in out:
            if "evaluator.bcg" in out:
                cex = self.extract_trace()
                print("Counterexample prefix:")
                print(*translate_cadp(cex, info), sep="", end="")
            else:
                print(*translate_cadp(out, info), sep="", end="")
            return ExitStatus.FAILED
        else:
            return super().handle_success(out, info)

    def extract_trace(self):
        cmd = ["bcg_open", "evaluator.bcg", "executor", "100", "2"]
        return check_output(cmd, stderr=STDOUT, cwd=self.cwd).decode()


class Cadp(CadpMonitor):
    """The CADP-based workflow presented in the paper
    "Verifying temporal properties of stigmergic collective systems using CADP"
    (ISoLA, 2021).
    """
    def __init__(self, cwd, **kwargs):
        super().__init__(cwd, **kwargs)
        # Fall back to "monitor" ancoding for simulation
        self.language = (
            Language.LNT_MONITOR
            if kwargs.get("steps")
            else Language.LNT)
        self.name = "cadp"
        self.modalities = ("always", "fairly", "fairly_inf", "finally")
        self.args = ["evaluator4", "-diag"]
        self.debug_args = ["evaluator4", "-verbose", "-diag"]

    def _mcl_fname(self, fname):
        return f"{fname}.mcl"

    def verify(self, fname, info):
        if not(self.check_cadp()):
            return ExitStatus.BACKEND_ERROR
        mcl = translate_property(info)
        mcl_fname = self._mcl_fname(fname)
        with open(mcl_fname, "w") as f:
            f.write(mcl)
        self.temp_files.append(mcl_fname)
        self.args.append(mcl_fname)
        self.debug_args.append(mcl_fname)
        self.verbose_output(mcl, "MCL property")
        return Backend.verify(self, fname, info)

    def handle_success(self, out, info) -> ExitStatus:
        result = super().handle_success(out, info)
        if "\nFALSE\n" in out and "evaluator.bcg" not in out:
            print("<property violated>")
        return result

    def cleanup(self, fname):
        super().cleanup(fname)


ALL_BACKENDS = {
    **{clz.__name__.lower(): clz for clz in (Cbmc, Cseq, Esbmc, Cadp)},
    "cadp-monitor": CadpMonitor
}
