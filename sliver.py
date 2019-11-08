#!/usr/bin/env python3
import click
import platform
import sys
from subprocess import check_output, CalledProcessError
from os import remove
import uuid
from pathlib import Path

from info import raw_info
from backends import ALL_BACKENDS
from cli import DEFAULTS, SHORTDESCR
from __about__ import __version__

__DIR = Path(__file__).parent.resolve()


def generate_code(file, values, bound, fair, simulate, bv, sync, backend):
    env = {"LD_LIBRARY_PATH": "labs/libunwind"} \
        if "Linux" in platform.system() \
        else {}
    call = [
        __DIR / Path("labs/LabsTranslate"),
        "--file", file,
        "--bound", str(bound),
        "--enc", backend.language.value]
    flags = [
        (fair, "--fair"), (simulate, "--simulation"),
        (not bv, "--no-bitvector"), (sync, "--sync")
    ]
    call.extend(b for a, b in flags if a)

    if values:
        call.extend(["--values", *values])

    try:
        out = check_output(call, env=env).decode("utf-8")
        fname = str(__DIR / make_filename(
            file, values, bound, fair, sync, backend.language))
        out = backend.preprocess(out, fname)
        return out, fname, raw_info(call)
    except CalledProcessError as e:
        print(e, file=sys.stderr)
        return None, None, None


def make_filename(file, values, bound, fair, sync, language):
    result = "_".join((
        Path(file).stem,
        str(bound), ("fair" if fair else "unfair"),
        ("sync" if sync else ""),
        "".join(v.replace("=", "") for v in values))) + "." + language.value
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
    '--backend', "backend_arg",
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
@click.option('--verbose', **DEFAULTS("verbose", default=False, is_flag=True))
def main(file, backend_arg, fair, simulate, show, values, **kwargs):
    """
* * *  SLiVER - Symbolic LAbS VERification. v1.3 (July 2019) * * *

FILE -- path of LABS file to analyze

VALUES -- assign values for parameterised specification (key=value)
"""

    print("Encoding...", file=sys.stderr)
    backend = ALL_BACKENDS[backend_arg](__DIR, **kwargs)
    code, fname, info = generate_code(
        file, values, kwargs["steps"], fair,
        simulate, kwargs["bv"], kwargs["sync"], backend)
    info = info.decode().replace("\n", "|")[:-1]
    if fname:
        if show:
            print(code)
            sys.exit(0)
        else:
            with open(fname, 'w') as out_file:
                out_file.write(code)
        try:
            sim_or_verify = "Running simulation" if simulate else "Verifying"
            print(
                "{} with backend {}...".format(sim_or_verify, backend_arg),
                file=sys.stderr)
            status = backend.run(fname, info)
        except KeyboardInterrupt:
            print("Verification stopped (keyboard interrupt)", file=sys.stderr)
        finally:
            cleanup(fname, backend)


if __name__ == "__main__":
    main()
