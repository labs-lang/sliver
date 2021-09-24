#!/usr/bin/env python3
import sys
from subprocess import CalledProcessError
from pathlib import Path

import click

from info import Info
from cli import DEFAULTS
from backends import ALL_BACKENDS, ExitStatus
from __about__ import __title__, __version__

__DIR = Path(__file__).parent.resolve()


@click.command()
@click.version_option(__version__, prog_name=__title__.lower())
@click.argument('file', required=True, type=click.Path(exists=True))
@click.argument('values', nargs=-1)
@click.option('--backend', "backend_arg",
              type=click.Choice(tuple(ALL_BACKENDS.keys())),
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
@click.option('--no-properties', **DEFAULTS("no-properties", default=False, is_flag=True))  # noqa: E501
@click.option('--property', **DEFAULTS("property"))  # noqa: E501
def main(file, backend_arg, simulate, show, **kwargs):
    """\b
* * *  The SLiVER LAbS VERification tool. v2.0-PREVIEW (September 2021) * * *

FILE -- path of LABS file to analyze

VALUES -- assign values for parameterised specification (key=value)
"""
    if simulate and kwargs.get("steps", 0) == 0:
        print("Must specify the length of simulation traces (--steps)")
        sys.exit(ExitStatus.INVALID_ARGS.value)

    print("Encoding...", file=sys.stderr)
    print(kwargs)
    backend = ALL_BACKENDS[backend_arg](__DIR, **kwargs)
    try:
        fname, info = backend.generate_code(file, simulate, show)
    except CalledProcessError as e:
        if kwargs.get("debug"):
            print(e, file=sys.stderr)
        print(ExitStatus.format(ExitStatus.PARSING_ERROR, simulate))
        sys.exit(ExitStatus.PARSING_ERROR.value)
    if fname and show:
        sys.exit(0)
    info = info.decode().replace("\n", "|")[:-1]
    if kwargs.get("debug"):
        print("[DEBUG]", info, file=sys.stderr)
    info = Info.parse(info)
    if fname:
        try:
            status = None
            sim_or_verify = "Running simulation" if simulate else "Verifying"
            print(
                f"{sim_or_verify} with backend {backend_arg}...",
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
                    print(ExitStatus.format(status, simulate))
                sys.exit(status.value)


if __name__ == "__main__":
    main()
