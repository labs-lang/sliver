#!/usr/bin/env python3
import click
import platform
import sys
from subprocess import check_output, CalledProcessError
from os import remove
import uuid
from pathlib import Path

from info import raw_info
from cli import DEFAULTS, SHORTDESCR, Languages
from backends import ALL_BACKENDS
from __about__ import __version__

__DIR = Path(__file__).parent.resolve()


def parse_linux(file, values, bound, fair, simulate, bv, sync, lang):
    env = {"LD_LIBRARY_PATH": "labs/libunwind"} \
        if "Linux" in platform.system() \
        else {}
    call = [
        __DIR / Path("labs/LabsTranslate"),
        "--file", file,
        "--bound", str(bound),
        "--enc", lang]
    flags = [
        (fair, "--fair"), (simulate, "--simulation"),
        (not bv, "--no-bitvector"), (sync, "--sync")
    ]

    if values:
        call.extend(["--values"] + list(values))
    for a, b in flags:
        if a:
            call.append(b)
    try:
        out = check_output(call, env=env)
        fname = str(__DIR / make_filename(file, values, bound, fair, sync))
        with open(fname, 'wb') as out_file:
            out_file.write(out)
        return out.decode("utf-8"), fname, raw_info(call)
    except CalledProcessError as e:
        print(e, file=sys.stderr)
        return None, None, None


def make_filename(file, values, bound, fair, sync):
    result = "_".join((
        Path(file[:-5]).name,
        str(bound), ("fair" if fair else "unfair"),
        ("sync" if sync else ""),
        "".join(v.replace("=", "") for v in values),
        str(uuid.uuid4())[:6])) + ".c"
    return result.replace("__", "_")


def cleanup(fname, backend):
    try:
        remove(fname)
        if backend == "cseq":
            for suffix in ("", ".map", ".cbmc-assumptions.log"):
                remove("_cs_" + fname + suffix)
    except FileNotFoundError:
        pass


@click.command()
@click.version_option(__version__, prog_name=SHORTDESCR)
@click.argument('file', required=True, type=click.Path(exists=True))
@click.argument('values', nargs=-1)
@click.option(
    '--backend',
    type=click.Choice(b for b in ALL_BACKENDS.keys()),
    default="cbmc", **DEFAULTS("backend"))
@click.option('--debug', **DEFAULTS("debug", default=False, is_flag=True))
@click.option('--fair/--no-fair', **DEFAULTS("fair", default=False))
@click.option('--bv/--no-bv', **DEFAULTS("bitvector", default=True))
@click.option('--simulate', **DEFAULTS("simulate", default=0, type=int))
@click.option('--show', **DEFAULTS("show", default=False, is_flag=True))
@click.option('--steps', **DEFAULTS("steps", default=0, type=int))
@click.option('--sync/--no-sync', **DEFAULTS("sync", default=False))
@click.option('--timeout', **DEFAULTS("timeout", default=0, type=int))
@click.option('--cores', **DEFAULTS("cores", default=4, type=int))
@click.option('--from', **DEFAULTS("from", type=int))
@click.option('--to', **DEFAULTS("to", type=int))
@click.option(
    '--lang',
    type=click.Choice(l.value for l in Languages),
    default=Languages.C.value, **DEFAULTS("lang"))
def main(file, backend, fair, simulate, show, values, lang, **kwargs):
    """
* * *  SLiVER - Symbolic LAbS VERification. v1.3 (July 2019) * * *

FILE -- path of LABS file to analyze

VALUES -- assign values for parameterised specification (key=value)
"""

    print("Encoding...", file=sys.stderr)
    c_program, fname, info = parse_linux(
        file, values, kwargs["steps"], fair,
        simulate, kwargs["bv"], kwargs["sync"], lang)
    info = info.decode().replace("\n", "|")[:-1]
    if fname:
        if show:
            print(c_program)
            cleanup(fname, backend)
            return
        sim_or_verify = "Running simulation" if simulate else "Verifying"
        print(
            "{} with backend {}...".format(sim_or_verify, backend),
            file=sys.stderr)
        try:
            back = ALL_BACKENDS[backend](__DIR, fname, info, **kwargs)
            back.run()
        except KeyboardInterrupt:
            print("Verification stopped (keyboard interrupt)", file=sys.stderr)
        finally:
            cleanup(fname, backend)


if __name__ == "__main__":
    main()
