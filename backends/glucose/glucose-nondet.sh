#!/bin/bash
BASEDIR=$(dirname "$0")

$BASEDIR/glucose -model \
  -rnd-init -rnd-freq=1 -rnd-seed=$RANDOM.$RANDOM \
  -ccmin-mode=0 \
  -no-elim \
  $1
