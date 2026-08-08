"""PyPy's stand-in for CPython's C _typing accelerator.

CPython implements a few typing internals in C and typing.py imports them
from a module named _typing.  PyPy implements them in Python, in
_pypy_typing, so without this module typing.py fell back to defining
_idfunc itself and it reported __module__ == 'typing'.  test_typing's
TestModules.test_c_functions checks for '_typing' specifically.

The names are re-exported rather than redefined, so these are the very same
objects typing.py binds from _pypy_typing just below its import of this
module -- the duplicate import there is now redundant but harmless.
"""

from _pypy_typing import (
    TypeVar,
    ParamSpec,
    TypeVarTuple,
    ParamSpecArgs,
    ParamSpecKwargs,
    TypeAliasType,
    Generic,
)


def _idfunc(_, x):
    return x
