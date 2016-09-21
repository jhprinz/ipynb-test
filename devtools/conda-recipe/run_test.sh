#!/bin/sh
ipynbtest.py --eval "denom=0" --show-diff --timeout 2 --restart-if-fail 1 ../../examples/ipynbtest_tutorial.ipynb --tested-types "display_data.image/png, stream.stdout, execute_result.text/plain" --verbose --pylab
