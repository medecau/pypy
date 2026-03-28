"""Test lists for CPython stdlib test suite runs against PyPy."""

# Core tests to run in smoke-test mode (~60 modules)
SMOKE_TESTS = [
    "test_abc",
    "test_argparse",
    "test_base64",
    "test_binascii",
    "test_bool",
    "test_bytes",
    "test_calendar",
    "test_call",
    "test_class",
    "test_collections",
    "test_compare",
    "test_complex",
    "test_contains",
    "test_copy",
    "test_csv",
    "test_datetime",
    "test_decimal",
    "test_decorators",
    "test_defaultdict",
    "test_deque",
    "test_dict",
    "test_dictcomps",
    "test_enumerate",
    "test_errno",
    "test_exceptions",
    "test_float",
    "test_format",
    "test_fractions",
    "test_functools",
    "test_generators",
    "test_genexps",
    "test_getopt",
    "test_glob",
    "test_grammar",
    "test_hash",
    "test_heapq",
    "test_int",
    "test_io",
    "test_isinstance",
    "test_iter",
    "test_itertools",
    "test_json",
    "test_keyword",
    "test_list",
    "test_listcomps",
    "test_long",
    "test_math",
    "test_operator",
    "test_ordered_dict",
    "test_pow",
    "test_print",
    "test_property",
    "test_range",
    "test_re",
    "test_set",
    "test_setcomps",
    "test_slice",
    "test_sort",
    "test_string",
    "test_struct",
    "test_tuple",
    "test_types",
    "test_unary",
    "test_unicode",
    "test_weakref",
    "test_zlib",
]

# Tests that should never be run (platform-specific, resource-intensive,
# or testing CPython implementation details irrelevant to PyPy)
SKIP_TESTS = [
    "test_dis",              # CPython bytecode details
    "test_dict_version",     # CPython implementation detail
    "test_frozen",           # CPython frozen modules
    "test_gc",               # CPython GC implementation
    "test_symtable",         # CPython symbol table details
    "test_tools",            # CPython internal tools
    "test_xxlimited",        # CPython C extension test
    "test_xxtestfuzz",       # CPython fuzzing
    "test_zipfile64",        # requires too many resources
    "test_tix",              # needs display
    "test_tk",               # needs display
    "test_ttk_guionly",      # needs display
    "test_winsound",         # Windows only
    "test_ossaudiodev",      # needs audio hardware
    "test_stable_abi_ctypes", # needs ctypes.pythonapi
    "test_getpath",          # CPython internal details
]

# Tests expected to fail on PyPy. Initially empty; populate after
# the first CI run based on actual results.
EXPECTED_FAILURES = [
]
