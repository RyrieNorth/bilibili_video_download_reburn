import sys

import bilidl

print("bare import pulls requests:", "requests" in sys.modules)
print("bare import pulls rich:", "rich" in sys.modules)

from bilidl import main

print("main is:", main.__module__ + "." + main.__name__)
print("dir:", dir(bilidl))

outcomes = main("BV1Gg411L7zg", dry_run=True)
print("outcomes:", outcomes)
