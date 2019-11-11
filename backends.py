#!/usr/bin/env python3
import os
import platform
from enum import Enum
from pathlib import Path
from subprocess import check_output, CalledProcessError, DEVNULL
from sys import stderr
from cex import translateCPROVER


class Language(Enum):
    C = "c"
    LNT = "lnt"


class ExitStatus(Enum):
    SUCCESS = 0
    BACKEND_ERROR = 1
    FAILED = 10
    TIMEOUT = 124
    KILLED = 130

    @staticmethod
    def format(code) -> str:
        return {
            ExitStatus.SUCCESS: "Verification succesful.",
            ExitStatus.BACKEND_ERROR: "Backend failed.",
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
        try:
            os.remove(fname)
        except FileNotFoundError:
            pass

    def filename_argument(self, fname):
        """Returns a CLI argument for the input file.
        """
        return [fname]

    def preprocess(self, code, fname):
        return code

    def run(self, fname, info):
        args = self.debug_args if self.kwargs["debug"] else self.args
        cmd = [self.command, *self.filename_argument(fname), *args]
        if self.kwargs.get("timeout", 0) > 0:
            cmd = [self.timeout_cmd, str(self.kwargs["timeout"]), *cmd]
        try:
            if self.kwargs.get("verbose"):
                print("Backend call:", " ".join(cmd), file=stderr)
            out = check_output(cmd, stderr=DEVNULL, cwd=self.cwd)
            return self.handle_success(out)
        except CalledProcessError as err:
            if self.kwargs["verbose"]:
                print("------Backend output:------")
                print(err.output.decode())
                print("---------------------------")
            return self.handle_error(err, fname, info)

    def handle_success(self, out) -> ExitStatus:
        print(out.decode(), file=stderr)
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
        super().cleanup(fname)
        path = Path(fname)
        for suffix in (".c", ".c.map", ".cbmc-assumptions.log"):
            try:
                os.remove(str(path.parent / ("_cs_" + path.stem + suffix)))
            except FileNotFoundError:
                pass

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
        self.args = ["evaluator", "-diag", "fairly.mcl"]
        self.debug_args = ["evaluator", "-verbose", "-diag", "fairly.mcl"]
        self.language = Language.LNT

    def preprocess(self, code, fname):
        base_name = Path(fname).stem.upper()
        return code.replace("module HEADER is", f"module {base_name} is")

    def handle_success(self, out) -> ExitStatus:
        out_str = out.decode()
        if "\nFALSE\n" in out_str:
            print(out_str)  # Todo: actual cex translation
            return ExitStatus.FAILED
        else:
            return super().handle_success(self, out)


ALL_BACKENDS = {clz.__name__.lower(): clz for clz in (Cbmc, Cseq, Esbmc, Cadp)}
