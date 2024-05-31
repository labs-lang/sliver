#!/usr/bin/env python3
import logging
import os
import re
import shutil
from dataclasses import dataclass
from enum import Enum
from functools import cached_property
from importlib import resources
from pathlib import Path
from subprocess import PIPE, STDOUT, CalledProcessError, check_output, run
from pyparsing import ParseException


from ..atlas.concretizer import Concretizer
from ..app.cex import translateCPROVER54, translateCPROVERNEW
from ..app.cli import Args, ExitStatus, SliverError
from ..app.info import Info


log = logging.getLogger('sliver')


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
    NUXMV = LanguageInfo(extension="smv", encoding="nuxmv")


class Backend:
    """Base class representing a generic analysis backend."""

    _run_args = {"stdout": PIPE, "stderr": PIPE, "check": True}

    def __init__(self, base_dir, cli):
        # if "Linux" in platform.system():
        #     self.timeout_cmd = "/usr/bin/timeout"
        # else:
        #     self.timeout_cmd = "/usr/local/bin/gtimeout"
        self.cli = cli
        self.base_dir = base_dir
        self.info = None
        self.cwd = base_dir
        self.temp_files = []
        self.modalities = tuple()
        self.logger = logging.getLogger('sliver')
        self.logger.setLevel(
            logging.DEBUG if cli[Args.VERBOSE] else logging.INFO)

    @cached_property
    def timeout_cmd(self):
        for name in ("timeout", "gtimeout"):
            path = shutil.which(name)
            if path is not None:
                return path
        raise SliverError(
            status=ExitStatus.FAILED,
            error_message="Cannot find timeout command."
        )

    def cleanup(self, _):
        if self.cli[Args.KEEP_FILES]:
            for f in self.temp_files:
                self.logger.info(f"Keeping {f}")
        else:
            self._safe_remove(self.temp_files)

    def _safe_remove(self, files):
        for f in files:
            try:
                self.logger.debug(f"Removing {f}...")
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
                self.logger.info("No property to verify!")
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
        with resources.path("sliver.labs", "LabsTranslate") as labs_exec:
            call = [
                labs_exec,
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
        if self.info is not None:
            return self.info
        log.info(f"Gathering information on {self.cli.file}...")
        try:
            call_info = self._labs_cmdline() + ["--info"]
            log_call(call_info)
            info_call = run(call_info, **self._run_args)
            info = info_call.stdout.decode()
            if parsed:
                info = info.replace("\n", "|")[:-1]
                self.logger.debug(f"{info=}")
                info = Info.parse(info, self.cli[Args.VALUES])
            self.check_info(info)
            self.info = info
            return info
        except CalledProcessError as e:
            self.logger.error(e)
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
                    self.logger.info(f"Gathering information on {self.cli.file}...")  # noQA: E501
                    info = self.get_info(parsed=True)
                    self.check_info(info)
                    c = Concretizer(info, self.cli, True)
                    if self.cli[Args.CONCRETIZATION] != "none":
                        out = c.concretize_program(out)
                print(out)
            else:
                self.logger.debug(f"Writing emulation program to {fname}...")
                with open(fname, 'w') as out_file:
                    out_file.write(out)
                self.temp_files.append(fname)
            return fname
        except CalledProcessError as e:
            self.logger.error(e)
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

    def verify(self, fname, info, suppress_output=False):
        """Verifies the correctness of the program at fname.
        """

        cmd = self.get_cmdline(fname, info)
        if self.cli[Args.TIMEOUT] > 0:
            cmd = [self.timeout_cmd, str(self.cli[Args.TIMEOUT]), *cmd]
        try:
            log_call(cmd)
            out = check_output(cmd, stderr=STDOUT, cwd=self.cwd).decode()
            if not suppress_output:
                self.verbose_output(out, "Backend output")
            return self.handle_success(out, info)
        except CalledProcessError as err:
            self.logger.debug(err)
            if not suppress_output:
                self.verbose_output(err.output.decode(), "Backend output")
            return self.handle_error(err, fname, info)

    def verbose_output(self, output, decorate=None):
        if output:
            if decorate:
                self.logger.debug(f"""
------{decorate}------
{output}
---------------------------""")
            else:
                self.logger.debug(output)

    def handle_success(self, *args) -> ExitStatus:
        return ExitStatus.SUCCESS

    def handle_error(self, err, *args) -> ExitStatus:
        if err.returncode == 124:
            return ExitStatus.TIMEOUT
        else:
            return ExitStatus.BACKEND_ERROR


class Cseq(Backend):
    def __init__(self, cwd, cli):
        super().__init__(cwd, cli)
        self.name = "cseq"
        self.modalities = ("always", "finally", "eventually")
        self.language = Language.C
        try:
            executable = self.get_cmdline(fname="a.c", info=None)[0]
            self.cwd /= Path(executable).parent
        except ModuleNotFoundError:
            # CSeq is not available
            pass

    def get_cmdline(self, fname, info):
        with resources.path("sliver.cseq", "cseq.py") as cseq_exec:
            result = [
                os.environ.get("CSEQ") or cseq_exec,
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
        if info is not None:
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
        try:
            return translateCPROVERNEW(cex, info)
        except ParseException:
            return translateCPROVER54(cex, info)

    def handle_error(self, err: CalledProcessError, fname, info):
        if err.returncode in (1, 10):
            out = err.output.decode("utf-8")
            for ln in self.translate_cex(out, info):
                print(ln, sep="", end="")
            return ExitStatus.FAILED
        elif err.returncode == 6:
            self.logger.info("Backend failed with parsing error.")
            return ExitStatus.BACKEND_ERROR
        else:
            return super().handle_error(err, fname, info)
