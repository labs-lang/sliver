#!/usr/bin/env python3
from .cadp import Cadp, CadpCompositional, CadpMonitor
from .cbmc import Cbmc
from .esbmc import Esbmc
from .common import Cseq

ALL_BACKENDS = {
    **{clz.__name__.lower(): clz for clz in (Cbmc, Cseq, Esbmc, Cadp)},
    "cadp-monitor": CadpMonitor,
    "cadp-comp": CadpCompositional
}
