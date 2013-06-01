#!/usr/bin/env python

# Todo list to prepare a release:
#  - run unit tests
#  - update VERSION in _tracemalloc.c and setup.py
#  - set release date in the README.rst file
#  - git commit -a
#  - git tag -a pytracemalloc-VERSION
#  - git push --tags
#  - python setup.py register sdist upload
#
# After the release:
#  - set version to n+1
#  - add a new empty section in the changelog for version n+1
#  - git commit
#  - git push

from __future__ import with_statement
from distutils.core import setup, Extension
import ctypes
import os
import subprocess
import sys

VERSION = '0.9.1'

CLASSIFIERS = [
    'Development Status :: 3 - Alpha',
    'Intended Audience :: Developers',
    'License :: OSI Approved :: MIT License',
    'Natural Language :: English',
    'Operating System :: OS Independent',
    'Programming Language :: C',
    'Programming Language :: Python',
    'Topic :: Security',
    'Topic :: Software Development :: Debuggers',
    'Topic :: Software Development :: Libraries :: Python Modules',
]

def pkg_config(name, arg, strip_prefix=0):
    args = ['pkg-config', name, arg]
    process = subprocess.Popen(args,
                               stdout=subprocess.PIPE,
                               universal_newlines=True)
    stdout, stderr = process.communicate()
    exitcode = process.wait()
    if exitcode:
        sys.exit(exitcode)
    args = stdout.strip().split()
    if strip_prefix:
        args = [item[strip_prefix:] for item in args]
    return args

def main():
    pythonapi = ctypes.cdll.LoadLibrary(None)
    if not hasattr(pythonapi, 'Py_SetAllocators'):
        print("Py_SetAllocators: missing, %s has not been patched" % sys.executable)
        sys.exit(1)
    else:
        print("Py_SetAllocators: present")

    library_dirs = pkg_config("glib-2.0", "--libs-only-L", 2)
    libraries = pkg_config("glib-2.0", "--libs-only-l", 2)
    include_dirs = pkg_config("glib-2.0", "--cflags-only-I", 2)
    cflags = pkg_config("glib-2.0", "--cflags-only-other")
    cflags.append('-DNDEBUG')
    if hasattr(pythonapi, '_PyFreeList_SetAllocators'):
        print("_PyFreeList_SetAllocators: present, track free lists")
        cflags.append('-DWITH_FREE_LIST')
    elif hasattr(pythonapi, '_PySys_UseFreeList'):
        print("_PySys_UseFreeList: present, free lists are disabled")
    else:
        print("_PyFreeList_SetAllocators, _PySys_UseFreeList: missing, free lists are used but not tracked")

    with open('README.rst') as f:
        long_description = f.read().strip()

    ext = Extension(
        '_tracemalloc',
        ['_tracemalloc.c'],
        include_dirs=include_dirs,
        library_dirs=library_dirs,
        libraries=libraries,
        extra_compile_args = cflags)

    options = {
        'name': 'pytracemalloc',
        'version': VERSION,
        'license': 'MIT license',
        'description': 'Track memory allocations per Python file',
        'long_description': long_description,
        'url': 'http://www.wyplay.com/',
        'download_url': 'https://github.com/wyplay/pytracemalloc',
        'author': 'Victor Stinner',
        'author_email': 'vstinner@wyplay.com',
        'ext_modules': [ext],
        'classifiers': CLASSIFIERS,
        'py_modules': ["tracemalloc"],
    }
    setup(**options)

if __name__ == "__main__":
    main()

