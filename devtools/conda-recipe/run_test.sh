#!/bin/sh
ipynbtest.py --eval "denom=0" --timeout 2 --restart-if-fail 1 ../../examples/ipynbtest_tutorial.ipynb
