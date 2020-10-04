#!/usr/bin/env python3
import platform
import sys
import re
from subprocess import check_output, CalledProcessError
from pathlib import Path

import click

from info import raw_info, Info
from cli import DEFAULTS
from backends import ALL_BACKENDS, ExitStatus
from __about__ import __title__, __version__

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
        raise e


def make_filename(file, values, bound, fair, sync, language):
    result = "_".join((
        # turn "file" into a valid identifier ([A-Za-z_][A-Za-z0-9_]+)
        re.sub(r'\W|^(?=\d)', '_', Path(file).stem),
        str(bound), ("fair" if fair else "unfair")))
    options = [o for o in (
        ("sync" if sync else ""),
        "".join(v.replace("=", "") for v in values)) if o != ""]
    if options:
        result = f"{result}_{'_'.join(options)}"
    return f"{result}.{language.value}"


@click.command()
@click.version_option(__version__, prog_name=__title__.lower())
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
* * *  SLiVER - Symbolic LAbS VERification. v1.5 (October 2020) * * *

FILE -- path of LABS file to analyze

VALUES -- assign values for parameterised specification (key=value)
"""
    if simulate and kwargs.get("steps", 0) == 0:
        print("Must specify the length of simulation traces (--steps)")
        sys.exit(ExitStatus.INVALID_ARGS.value)

    print("Encoding...", file=sys.stderr)
    backend = ALL_BACKENDS[backend_arg](__DIR, **kwargs)
    try:
        code, fname, info = generate_code(
            file, values, kwargs["steps"], fair,
            simulate, kwargs["bv"], kwargs["sync"], backend)
    except CalledProcessError as e:
        if kwargs.get("debug"):
            print(e, file=sys.stderr)
        print(ExitStatus.format(ExitStatus.PARSING_ERROR))
        sys.exit(ExitStatus.PARSING_ERROR.value)
    info = info.decode().replace("\n", "|")[:-1]
    if kwargs.get("debug"):
        print("[DEBUG]", info, file=sys.stderr)
    info = Info.parse(info)
    if fname:
        if show:
            print(code)
            sys.exit(0)
        else:
            with open(fname, 'w') as out_file:
                out_file.write(code)
        try:
            status = None
            sim_or_verify = "Running simulation" if simulate else "Verifying"
            print(
                "{} with backend {}...".format(sim_or_verify, backend_arg),
                file=sys.stderr)
            status = (backend.simulate(fname, info, simulate) if simulate else
                      backend.verify(fname, info))
        except KeyboardInterrupt:
            status = ExitStatus.KILLED
        finally:
            backend.cleanup(fname)
            if status:
                if status == ExitStatus.SUCCESS and simulate:
                    print("Done.")
                else:
                    print(ExitStatus.format(status))
                sys.exit(status.value)


if __name__ == "__main__":
    main()
