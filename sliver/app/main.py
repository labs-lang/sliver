#!/usr/bin/env python3
import inspect
import logging
import sys
from pathlib import Path

import click
from ..backends.backends import ALL_BACKENDS

from .__about__ import __date__, __title__, __version__
from .cli import CLICK, LONGDESCR, Args, CliArgs, ExitStatus, SliverError

if not hasattr(sys.modules[__name__], '__file__'):
    __file__ = inspect.getfile(inspect.currentframe())

__DIR = Path(__file__).parent.resolve()
backends_type = click.Choice(tuple(ALL_BACKENDS.keys()))

log = logging.getLogger("sliver")


@click.command(help=LONGDESCR)
@click.version_option(__version__, prog_name=__title__.lower())
@click.argument('file', required=True, type=click.Path(exists=True))
@click.argument('values', nargs=-1)
@click.option('--backend', **CLICK(Args.BACKEND, type=backends_type))
@click.option('--concretization', **CLICK(Args.CONCRETIZATION))
@click.option('--bv/--no-bv', **CLICK(Args.BV))
@click.option('--cores', **CLICK(Args.CORES))
@click.option('--debug', **CLICK(Args.DEBUG, is_flag=True))
@click.option('--fair/--no-fair', **CLICK(Args.FAIR))
@click.option('--from', **CLICK(Args.CORES_FROM))
@click.option('--keep-files', **CLICK(Args.KEEP_FILES, is_flag=True))
@click.option('--no-properties', **CLICK(Args.NO_PROPERTIES, is_flag=True))
@click.option('--property', **CLICK(Args.PROPERTY))
@click.option('--rnd-seed', **CLICK(Args.RND_SEED))
@click.option('--show', **CLICK(Args.SHOW, is_flag=True))
@click.option('--simulate', **CLICK(Args.SIMULATE))
@click.option('--steps', **CLICK(Args.STEPS))
@click.option('--sync/--no-sync', **CLICK(Args.SYNC))
@click.option('--timeout', **CLICK(Args.TIMEOUT))
@click.option('--to', **CLICK(Args.CORES_TO))
@click.option('--verbose', **CLICK(Args.VERBOSE, is_flag=True))
@click.option('--translate-cex', **CLICK(Args.TRANSLATE_CEX))
@click.option('--include', multiple=True, **CLICK(Args.INCLUDE))
def main(file, **kwargs):
    cli = CliArgs(file, kwargs)
    backend_arg, simulate, show = (
        cli[Args.BACKEND],
        cli[Args.SIMULATE],
        cli[Args.SHOW])

    logging.basicConfig(
        format="[%(levelname)s:%(name)s] %(message)s",
        level=logging.DEBUG if cli[Args.VERBOSE] else logging.INFO
    )

    sprint_cli = ", ".join(f"{k}={v}" for k, v in cli.items())
    log.debug(f"CLI options: {file=}, {sprint_cli}")
    backend = ALL_BACKENDS[backend_arg](__DIR, cli)
    try:
        backend.check_cli()
        if not cli[Args.TRANSLATE_CEX] or show:
            log.info("Encoding...")
            fname = backend.generate_code()
        else:
            fname = ""
    except SliverError as err:
        err.handle(log=log, quit=True)
    if fname and show:
        sys.exit(ExitStatus.SUCCESS.value)
    status = None

    try:
        log.info(f"Gathering information on {cli.file}...")
        info = backend.get_info(parsed=True)
        backend.check_info(info)

        sim_or_verify = "Running simulation" if simulate else "Verifying"

        if cli[Args.TRANSLATE_CEX]:
            cex_name = cli[Args.TRANSLATE_CEX]
            log.info(f"Translating counterexample {cex_name}...")
            with open(cex_name) as cex:
                out = cex.read()
                print(
                    *backend.translate_cex(out, "", info), sep="", end="")
            sys.exit(0)

        if not simulate and cli[Args.PROPERTY]:
            sim_or_verify += f""" '{cli[Args.PROPERTY]}'"""
        log.info(f"{sim_or_verify} with backend {backend_arg}...")
        status = (backend.simulate(fname, info) if simulate else
                  backend.verify(fname, info))
    except KeyboardInterrupt:
        status = ExitStatus.KILLED
    except SliverError as err:
        err.handle(quiet=True, quit=False)
        status = err.status
    finally:
        backend.cleanup(fname)
        if status:
            print(ExitStatus.format(status, simulate))
            print()
            sys.exit(status.value)


__all__ = [__title__, __version__, __date__, main]


if __name__ == "__main__":
    main()
