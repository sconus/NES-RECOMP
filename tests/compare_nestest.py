#!/usr/bin/env python3
"""Compare a recompiled program's --trace output with nestest.log.

Usage: python3 compare_nestest.py nestest.log trace.txt
Checks PC, A, X, Y, P, SP and the cycle counter on every line.
"""
import re
import sys

ref = []
for line in open(sys.argv[1]):
    m = re.match(r"(\w{4}).*?(A:\w\w X:\w\w Y:\w\w P:\w\w SP:\w\w).*CYC:(\d+)",
                 line)
    ref.append("%s %s CYC:%s" % (m[1], m[2], m[3]))
got = [line.strip() for line in open(sys.argv[2])]

for i, (r, g) in enumerate(zip(ref, got)):
    if r != g:
        print("MISMATCH at line %d" % (i + 1))
        print("  expected: %s" % r)
        print("  got:      %s" % g)
        sys.exit(1)
if len(got) < len(ref):
    print("trace ended early: %d of %d lines matched" % (len(got), len(ref)))
    sys.exit(1)
print("PASS: all %d instructions match the reference log" % len(ref))
