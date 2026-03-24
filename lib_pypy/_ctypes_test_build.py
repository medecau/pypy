"""
This will create the _ctypes_test c-extension module. Unlike _testcapi, the
extension cannot be wrapped with a _ctypes_test.py module since test.importlib
explicitly does a c-extension import
"""
import importlib.machinery
import importlib.util
import os
import sys

try:
    import cpyext
except ImportError:
    raise RuntimeError("must have cpyext")
import _pypy_testcapi
cfile = '_ctypes_test.c'
thisdir = os.path.dirname(__file__)
output_dir = _pypy_testcapi.get_hashed_dir(os.path.join(thisdir, cfile))
try:
    import _ctypes
except ImportError:
    pass    # obscure condition of _ctypes_test.py being imported by py.test
else:
    _ctypes.PyObj_FromPtr = None
    del _ctypes
    try:
        for suffix in importlib.machinery.EXTENSION_SUFFIXES:
            candidate = os.path.join(thisdir, '_ctypes_test' + suffix)
            if os.path.exists(candidate):
                spec = importlib.util.spec_from_file_location('_ctypes_test', candidate)
                mod = importlib.util.module_from_spec(spec)
                sys.modules['_ctypes_test'] = mod
                spec.loader.exec_module(mod)
                break
        else:
            raise ImportError('_ctypes_test not found in ' + thisdir)
    except ImportError:
        _pypy_testcapi.compile_shared('_ctypes_test.c', '_ctypes_test', thisdir)
