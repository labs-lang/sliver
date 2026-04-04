#!/usr/bin/env python3

from .cadp import Cadp, CadpCompositional, CadpMonitor
from .cbmc import Cbmc
from .cseq import Cseq
from .esbmc import Esbmc
from .kratos import Kratos
from .nuxmv import NuXmv

ALL_BACKENDS = {
    **{
        clz.__name__.lower(): clz
        for clz in (Cbmc, Cseq, Esbmc, Cadp, Kratos, NuXmv)},
    "cadp-monitor": CadpMonitor,
    "cadp-comp": CadpCompositional
}
