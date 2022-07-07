#!/usr/bin/env python3
from backends.common import Cseq, Esbmc
from backends.cbmc import Cbmc
from backends.cadp import Cadp, CadpMonitor, CadpCompositional

ALL_BACKENDS = {
    **{clz.__name__.lower(): clz for clz in (Cbmc, Cseq, Esbmc, Cadp)},
    "cadp-monitor": CadpMonitor,
    "cadp-comp": CadpCompositional
}
