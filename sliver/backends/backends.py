#!/usr/bin/env python3
from .cadp import Cadp, CadpCompositional, CadpMonitor
from .cbmc import Cbmc
from .esbmc import Esbmc
from .nuxmv import NuXmv
from .common import Cseq

ALL_BACKENDS = {
    **{clz.__name__.lower(): clz for clz in (Cbmc, Cseq, Esbmc, Cadp, NuXmv)},
    "cadp-monitor": CadpMonitor,
    "cadp-comp": CadpCompositional
}
