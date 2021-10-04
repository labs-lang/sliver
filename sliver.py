#!/usr/bin/env python3
import logging
import sys
from subprocess import CalledProcessError
from pathlib import Path

import click

from info import Info
from cli import CLICK, Args, CliArgs
from backends import ALL_BACKENDS, ExitStatus
from __about__ import __title__, __version__

__DIR = Path(__file__).parent.resolve()
log = logging.getLogger("sliver")


@click.command()
@click.version_option(__version__, prog_name=__title__.lower())
@click.argument('file', required=True, type=click.Path(exists=True))
@click.argument('values', nargs=-1)
@click.option('--backend',
              type=click.Choice(tuple(ALL_BACKENDS.keys())),
              **CLICK(Args.BACKEND))
@click.option('--debug', **CLICK(Args.DEBUG, is_flag=True))
@click.option('--fair/--no-fair', **CLICK(Args.FAIR))
@click.option('--bv/--no-bv', **CLICK(Args.BV))
@click.option('--simulate', **CLICK(Args.SIMULATE, type=int))
@click.option('--show', **CLICK(Args.SHOW, is_flag=True))
@click.option('--steps', **CLICK(Args.STEPS, type=int))
@click.option('--sync/--no-sync', **CLICK(Args.SYNC))
@click.option('--timeout', **CLICK(Args.TIMEOUT, type=int))
@click.option('--cores', **CLICK(Args.CORES, type=int))
@click.option('--from', **CLICK(Args.CORES_FROM, type=int))
@click.option('--to', **CLICK(Args.CORES_TO, type=int))
@click.option('--verbose', **CLICK(Args.VERBOSE, is_flag=True))
@click.option('--no-properties', **CLICK(Args.NO_PROPERTIES, is_flag=True))
@click.option('--property', **CLICK(Args.PROPERTY))
@click.option('--keep-files', **CLICK(Args.KEEP_FILES, is_flag=True))
def main(file, **kwargs):
    """\b
* * *  The SLiVER LAbS VERification tool. v2.0 (October 2021) * * *

FILE -- path of LABS file to analyze

VALUES -- assign values for parameterised specification (key=value)
"""
    cli = CliArgs(kwargs)
    backend_arg, simulate, show = (
        cli[Args.BACKEND],
        cli[Args.SIMULATE],
        cli[Args.SHOW])

    logging.basicConfig(
        format="[%(levelname)s:%(name)s] %(message)s",
        level=logging.DEBUG if cli[Args.VERBOSE] else logging.INFO
    )

    if simulate and cli[Args.STEPS] == 0:
        log.error(ExitStatus.format(ExitStatus.INVALID_ARGS))
        print("Must specify the length of simulation traces (--steps)")
        sys.exit(ExitStatus.INVALID_ARGS.value)

    log.info("Encoding...")

    sprint_cli = ", ".join(f"{k}={v}" for k, v in cli.data.items())
    log.debug(f"CLI options: {file=}, {sprint_cli}")
    backend = ALL_BACKENDS[backend_arg](__DIR, cli)
    try:
        fname, info = backend.generate_code(file, simulate, show)
    except CalledProcessError as e:
        log.debug(e)
        err_msg = e.stderr.decode()
        log.error(err_msg)
        sliver_return = (
            ExitStatus.INVALID_ARGS if err_msg.startswith("Property")
            else ExitStatus.PARSING_ERROR)
        print(ExitStatus.format(sliver_return, simulate))
        sys.exit(sliver_return.value)
    if fname and show:
        sys.exit(ExitStatus.SUCCESS.value)
    info = info.replace("\n", "|")[:-1]
    log.debug(f"{info=}")
    info = Info.parse(info)
    status = None
    if fname:
        try:
            status = (
                ExitStatus.SUCCESS if simulate
                else backend.check_property_support(info))
            if status != ExitStatus.SUCCESS:
                sys.exit(status.value)

            status = None
            sim_or_verify = "Running simulation" if simulate else "Verifying"
            if not simulate and cli[Args.PROPERTY]:
                sim_or_verify += f""" '{cli[Args.PROPERTY]}'"""
            log.info(f"{sim_or_verify} with backend {backend_arg}...")
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
