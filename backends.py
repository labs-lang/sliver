#!/usr/bin/env python3
import os
import platform
from enum import Enum
from pathlib import Path
from subprocess import check_output, CalledProcessError, STDOUT
from sys import stderr, stdout
from cex import translateCPROVER, translate_cadp


class Language(Enum):
    C = "c"
    LNT = "lnt"


class ExitStatus(Enum):
    SUCCESS = 0
    SIM_SUCCESS = 0
    BACKEND_ERROR = 1
    INVALID_ARGS = 2
    PARSING_ERROR = 6
    FAILED = 10
    TIMEOUT = 124
    KILLED = 130

    @staticmethod
    def format(code) -> str:
        return {
            ExitStatus.SUCCESS: "Verification succesful.",
            ExitStatus.SIM_SUCCESS: "Done.",
            ExitStatus.BACKEND_ERROR: "Backend failed.",
            ExitStatus.INVALID_ARGS: "Invalid arguments.",
            ExitStatus.PARSING_ERROR: "Could not parse input file.",
            ExitStatus.FAILED: "Verification failed.",
            ExitStatus.TIMEOUT: "Verification stopped (timeout).",
            ExitStatus.KILLED: "\nVerification stopped (keyboard interrupt)."
        }.get(code, f"Unexpected exit code {code.value}")


class Backend:
    def __init__(self, cwd, **kwargs):
        if "Linux" in platform.system():
            self.timeout_cmd = "/usr/bin/timeout"
        else:
            self.timeout_cmd = "/usr/local/bin/gtimeout"
        self.cwd = cwd
        self.kwargs = kwargs

    def cleanup(self, fname):
        self._safe_remove((fname, ))

    def _safe_remove(self, files):
        try:
            for f in files:
                os.remove(f)
        except FileNotFoundError:
            pass

    def filename_argument(self, fname):
        """Returns a CLI argument for the input file.
        """
        return [fname]

    def preprocess(self, code, fname):
        return code

    def verify(self, fname, info):
        args = self.debug_args if self.kwargs["debug"] else self.args
        cmd = [self.command, *self.filename_argument(fname), *args]
        if self.kwargs.get("timeout", 0) > 0:
            cmd = [self.timeout_cmd, str(self.kwargs["timeout"]), *cmd]
        try:
            self.verbose_output(f"Backend call: {' '.join(cmd)}", file=stderr)
            out = check_output(cmd, stderr=STDOUT, cwd=self.cwd).decode()
            self.verbose_output(out, "Backend output")
            return self.handle_success(out, info)
        except CalledProcessError as err:
            self.verbose_output(err.output.decode(), "Backend output")
            return self.handle_error(err, fname, info)

    def verbose_output(self, output, decorate=None, file=stdout):
        if self.kwargs.get("verbose"):
            if decorate:
                print(
                    f"------{decorate}:------",
                    output,
                    "---------------------------",
                    sep="\n", file=file)
            else:
                print(output, file=file)

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
        self.language = Language.C
        self.command = os.environ.get("CBMC") or "cbmc"
        self.args = []
        self.debug_args = ["--bounds-check", "--signed-overflow-check"]

        CBMC_V, CBMC_SUBV = check_output(
            [self.command, "--version"],
            cwd=cwd).decode().strip().split(".")
        if not (int(CBMC_V) <= 5 and int(CBMC_SUBV) <= 4):
            additional_flags = ["--trace", "--stop-on-fail"]
            self.args.extend(additional_flags)
            self.debug_args.extend(additional_flags)

    def handle_error(self, err: CalledProcessError, fname, info):
        if err.returncode == 10:
            out = err.output.decode("utf-8")
            print(translateCPROVER(out, fname, info))
            return ExitStatus.FAILED
        elif err.returncode == 6:
            print("Backend failed with parsing error.", file=stderr)
            return ExitStatus.BACKEND_ERROR
        else:
            return super().handle_error(err, fname, info)


class Cseq(Backend):
    def __init__(self, cwd, **kwargs):
        super().__init__(cwd, **kwargs)
        self.language = Language.C
        self.command = os.environ.get("CSEQ") or str(cwd / "cseq" / "cseq.py")
        # TODO change split
        self.args = ["-l", "labs_parallel", "--split", "_I"]

        for arg in ("steps", "cores", "from", "to"):
            if kwargs.get(arg) is not None:
                self.args.extend((f"--{arg}", str(kwargs[arg])))

        self.debug_args = self.args
        self.cwd /= "cseq"

    def filename_argument(self, fname):
        return ["-i", str(self.cwd / fname)]

    def cleanup(self, fname):
        path = Path(fname)
        aux = (
            str(path.parent / ("_cs_" + path.stem + suffix))
            for suffix in (".c", ".c.map", ".cbmc-assumptions.log")
        )
        super()._safe_remove(aux)
        super().cleanup(fname)

    def handle_error(self, err: CalledProcessError, fname, info):
        if err.returncode in (1, 10):
            out = err.output.decode("utf-8")
            print(translateCPROVER(out, fname, info, 19))
            return ExitStatus.FAILED
        elif err.returncode == 6:
            print("Backend failed with parsing error.", file=stderr)
            return ExitStatus.BACKEND_ERROR
        else:
            return super().handle_error(err, fname, info)


class Esbmc(Backend):
    def __init__(self, cwd, **kwargs):
        super().__init__(cwd, **kwargs)
        self.language = Language.C
        self.command = os.environ.get("ESBMC") or "esbmc"
        self.args = [
            "--no-bounds-check", "--no-div-by-zero-check",
            "--no-pointer-check", "--no-align-check",
            "--no-unwinding-assertions", "--z3"]
        self.debug_args = [
            "--no-pointer-check", "--no-align-check",
            "--no-unwinding-assertions", "--z3"]


class Cadp(Backend):
    def __init__(self, cwd, **kwargs):
        super().__init__(cwd, **kwargs)
        self.command = "lnt.open"
        self.args = ["evaluator", "-diag"]
        self.debug_args = ["evaluator", "-verbose", "-diag"]
        self.language = Language.LNT

    def verify(self, fname, info):
        mcl = "fairly.mcl" if info.properties[0] == "finally" else "never.mcl"
        mcl = str(Path("cadp") / Path(mcl))
        self.args.append(mcl)
        self.debug_args.append(mcl)
        return super().verify(fname, info)

    def simulate(self, fname, info, simulate):
        cmd = [
            "lnt.open", fname, "executor",
            str(self.kwargs.get("steps", 1)), "2"]
        if self.kwargs.get("timeout", 0) > 0:
            cmd = [self.timeout_cmd, str(self.kwargs["timeout"]), *cmd]

        try:
            for i in range(simulate):
                self.verbose_output(
                    f"Backend call: {' '.join(cmd)}", file=stderr)
                out = check_output(cmd, stderr=STDOUT, cwd=self.cwd).decode()
                self.verbose_output(out, "Backend output")
                print(f"====== Trace #{i+1} ======")
                print(translate_cadp(out, info))
                print(f"========================")
            return ExitStatus.SIM_SUCCESS
        except CalledProcessError as err:
            self.verbose_output(err.output.decode(), "Backend output")
            return ExitStatus.BACKEND_ERROR

    def cleanup(self, fname):
        aux = (str(Path(self.cwd) / f) for f in
               ("evaluator", "executor", "evaluator@1.o", "evaluator.bcg"))
        super().cleanup(fname)
        super()._safe_remove(aux)

    def preprocess(self, code, fname):
        base_name = Path(fname).stem.upper()
        return code.replace("module HEADER is", f"module {base_name} is")

    def handle_success(self, out, info) -> ExitStatus:
        if "\nFALSE\n" in out:
            if "evaluator.bcg" in out:
                cex = self.extract_trace()
                print("Counterexample prefix:")
                print(translate_cadp(cex, info))
            else:
                print(translate_cadp(out, info))
            return ExitStatus.FAILED
        else:
            return super().handle_success(out, info)

    def extract_trace(self):
        cmd = ["bcg_open", "evaluator.bcg", "executor", "100", "2"]
        return check_output(cmd, stderr=STDOUT, cwd=self.cwd).decode()


ALL_BACKENDS = {clz.__name__.lower(): clz for clz in (Cbmc, Cseq, Esbmc, Cadp)}
