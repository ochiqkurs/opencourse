#!/usr/bin/env python3
"""In-place apostrophe normalizer for konspekt content modules.

ASCII ' between letters -> U+2019, applied OUTSIDE ``` code fences only
(fences keep ASCII quotes for runnable code). Idempotent.

Usage: normalize.py konspekt_x.py [more files...]
"""
import re
import sys

APO = re.compile(r"(?<=[a-zA-Z])'(?=[a-zA-Z])")

for path in sys.argv[1:]:
    src = open(path).read()
    parts = src.split("```")
    for i in range(0, len(parts), 2):  # even indexes are outside fences
        parts[i] = APO.sub("’", parts[i])
    out = "```".join(parts)
    if out != src:
        open(path, "w").write(out)
        print(f"{path}: normalized")
    else:
        print(f"{path}: clean")
