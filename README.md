pytracemalloc
=============

Debug tool tracking Python memory allocations. Provides the following information:

* Allocated size and number of allocations per file, or optionally per file and line number
* Computes the average size of memory allocations
* Computes delta between two "snapshots"
* Source of a memory allocation: filename and line number

Example (compact)::

    2013-02-28 23:40:18: Top 5 allocations per file
    #1: .../Lib/test/regrtest.py: 3998 KB
    #2: .../Lib/unittest/case.py: 2343 KB
    #3: .../ctypes/test/__init__.py: 513 KB
    #4: .../Lib/encodings/__init__.py: 525 KB
    #5: .../Lib/compiler/transformer.py: 438 KB
    other: 32119 KB
    Total allocated size: 39939 KB

Another example (full)::

    2013-03-04 01:01:55: Top 10 allocations per file and line
    #1: .../2.7/Lib/linecache.py:128: size=408 KiB (+408 KiB), count=5379 (+5379), average=77 B
    #2: .../unittest/test/__init__.py:14: size=401 KiB (+401 KiB), count=6668 (+6668), average=61 B
    #3: .../2.7/Lib/doctest.py:506: size=319 KiB (+319 KiB), count=197 (+197), average=1 KiB
    #4: .../Lib/test/regrtest.py:918: size=429 KiB (+301 KiB), count=5806 (+3633), average=75 B
    #5: .../Lib/unittest/case.py:332: size=162 KiB (+136 KiB), count=452 (+380), average=367 B
    #6: .../Lib/test/test_doctest.py:8: size=105 KiB (+105 KiB), count=1125 (+1125), average=96 B
    #7: .../Lib/unittest/main.py:163: size=77 KiB (+77 KiB), count=1149 (+1149), average=69 B
    #8: .../Lib/test/test_types.py:7: size=75 KiB (+75 KiB), count=1644 (+1644), average=46 B
    #9: .../2.7/Lib/doctest.py:99: size=64 KiB (+64 KiB), count=1000 (+1000), average=66 B
    #10: .../Lib/test/test_exceptions.py:6: size=56 KiB (+56 KiB), count=932 (+932), average=61 B
    3023 more: size=1580 KiB (+1138 KiB), count=12635 (+7801), average=128 B
    Total: size=3682 KiB (+3086 KiB), count=36987 (+29908), average=101 B


Python module developed by Wyplay: http://www.wyplay.com/
