#!/usr/bin/env python3
import os
import platform
from subprocess import check_output, CalledProcessError, DEVNULL
from sys import stderr, exit
from cex import translateCPROVER


class Language(Enum):
    C = "c"
    LNT = "lnt"


class Backend:
    def __init__(self, cwd, filename, info, **kwargs):
        if "Linux" in platform.system():
            self.timeout_cmd = "/usr/bin/timeout"
        else:
            self.timeout_cmd = "/usr/local/bin/gtimeout"
        self.cwd = cwd
        self.filename = filename
        self.info = info
        self.kwargs = kwargs

    def fname_arg(self):
        return [self.filename]

    def run(self):
        args = self.debug_args if self.kwargs["debug"] else self.args
        cmd = [self.command, *args, *self.fname_arg()]
        if self.kwargs.get("timeout", 0) > 0:
            cmd = [self.timeout_cmd, str(self.kwargs["timeout"]), *cmd]
        try:
            print(" ".join(cmd))
            out = check_output(cmd, stderr=DEVNULL, cwd=self.cwd)
            return self.handle_success(out)
        except CalledProcessError as err:
            out = b""
            return self.handle_error(err)

    def handle_success(self, out):
        print("No properties violated!", file=stderr)

    def handle_error(self, err):
        if err.returncode == 124:
            print(
                "Timed out after {} seconds"
                .format(self.kwargs["timeout"]), file=stderr)
            exit(124)
        else:
            print(
                f"Unexpected error (return code: {err.returncode})",
                file=stderr)
            print(err.output.decode(), file=stderr)


class Cbmc(Backend):
    def __init__(self, cwd, filename, info, **kwargs):
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

        super().__init__(cwd, filename, info, **kwargs)

    def handle_error(self, err: CalledProcessError):
        if err.returncode == 10:
            out = err.output.decode("utf-8")
            print(translateCPROVER(out, self.filename, self.info))
        elif err.returncode == 6:
            print("Backend failed with parsing error.", file=stderr)
        else:
            super().handle_error(err)


class Cseq(Backend):
    def __init__(self, cwd, filename, info, **kwargs):
        self.command = os.environ.get("CSEQ") or str(cwd / "cseq" / "cseq.py")
        self.args = ["-l", "labs_parallel", "--split", "_I"]
        self.debug_args = self.args
        super().__init__(cwd, filename, info, **kwargs)
        self.cwd /= "cseq"

    def fname_arg(self):
        print(["-i", self.cwd / self.filename])
        return ["-i", str(self.cwd / self.filename)]


class Esbmc(Backend):
    def __init__(self, cwd, filename, info, **kwargs):
        self.command = os.environ.get("ESBMC") or "esbmc"
        self.args = [
            "--no-bounds-check", "--no-div-by-zero-check",
            "--no-pointer-check", "--no-align-check",
            "--no-unwinding-assertions", "--z3"]
        self.debug_args = [
            "--no-pointer-check", "--no-align-check",
            "--no-unwinding-assertions", "--z3"]


ALL_BACKENDS = {clz.__name__.lower(): clz for clz in (Cbmc, Cseq, Esbmc)}
