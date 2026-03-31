import io
from shutil import which
from subprocess import PIPE, CalledProcessError, Popen

import pcpp


from ..absentee.absentee import absentee
from ..app.cli import Args, ExitStatus
from .common import Backend, Language


class Kratos(Backend):
    def __init__(self, cwd, cli):
        cli[Args.BV] = False  # Force-disable CPROVER bitvectors
        super().__init__(cwd, cli)
        self.name = "esbmc"
        self.modalities = ("always", "finally")
        self.language = Language.C

    def get_cmdline(self, fname, _):
        kratos = which("kratos")
        if kratos is None:
            raise RuntimeError("kratos not found in PATH")
        return [
            kratos, "-stage=mc",
            fname, '-cex_type=patheval']

    def preprocess(self, code, _):
        code = ("extern int __CPROVER_nondet_int();\n"
                "extern int __CPROVER_nondet();\n"
                "extern void __CPROVER_assume(int);\n"
                "void __CPROVER_assert(int cond, const char *msg) {\n"
                "    if (!cond) { __CPROVER_error(); }\n"
                "}") + code

        preproc = pcpp.Preprocessor()
        preproc.parse(code)
        f = io.StringIO("")
        preproc.write(oh=f)
        f.seek(0)
        code = absentee.parse_and_execute(f.read(), "(without-bitwise)")
        c2kratos = which("c2kratos")
        if c2kratos is None:
            raise RuntimeError("c2kratos not found in PATH")
        cmd = [
            c2kratos,
            "--builtin-error", "__CPROVER_error",
            "--builtin-assume", "__CPROVER_assume",
            "--nondet-prefix", "__CPROVER_nondet",
            # "--blast-static-arrays", "9999",
            "--cpp", "cpp-11"  # TODO: make this configurable
        ]
        proc = Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE, text=True)
        stdout, stderr = proc.communicate(code)
        if proc.returncode != 0:
            raise RuntimeError(
                f"c2kratos failed with code {proc.returncode}:\n"
                f"{stderr}")
        return stdout

    def handle_error(self, err: CalledProcessError, fname, info):
        if err.returncode == 20:
            out = err.output.decode("utf-8")
            start = out.find("Counterexample trace:")
            end = out.find("Model checker statistics:")
            end = end if end != -1 else len(out)
            out = out[max(start, 0):end].strip()
            for line in out.splitlines():
                line_stripped = line.strip()
                if line_stripped.startswith("(assign"):
                    if (
                        "$tmp" not in line_stripped
                        and "var |x| int" not in line_stripped
                        and "$temp." not in line_stripped
                        and ".return" not in line_stripped
                    ):
                        print(line_stripped)
            return ExitStatus.FAILED
        else:
            return super().handle_error(err, fname, info)
