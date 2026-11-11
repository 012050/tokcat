#!/usr/bin/env python3
# One-shot: flip rotate 90 -> 270 in the mpi3501 custom overlay source.
import sys

path = "/home/runcater/mpi3501-kernel-6.12-driver/mpi3501-custom.dts"
s = open(path).read()
assert "rotate = <90>" in s, "rotate = <90> not found"
s = s.replace("rotate = <90>", "rotate = <270>")
open(path, "w").write(s)
print("OK: rotate = <270> written to", path)
