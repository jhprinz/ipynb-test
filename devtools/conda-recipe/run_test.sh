#!/bin/sh
pwd
ls -ltra
ipynbtest.py --eval "denom=0" --show-diff --timeout 2 --restart-if-fail 1 ../work/examples/ipynbtest_tutorial.ipynb --tested-types "image/png, text/plain" --verbose --pylab
