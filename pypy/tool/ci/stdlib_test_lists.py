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
    # CPython implementation details
    "test_capi",             # CPython C API internals
    "test_clinic",           # CPython Argument Clinic tool
    "test_compile",          # CPython compiler internals
    "test_dis",              # CPython bytecode details
    "test_dict_version",     # CPython implementation detail
    "test_embed",            # CPython embedding API
    "test_frozen",           # CPython frozen modules
    "test_gc",               # CPython GC implementation
    "test_gdb",              # CPython GDB hooks
    "test_getpath",          # CPython internal details
    "test_monitoring",       # CPython sys.monitoring (PEP 669)
    "test_peepholer",        # CPython bytecode optimizer
    "test_perf_profiler",    # CPython perf profiler support
    "test_stable_abi_ctypes", # needs ctypes.pythonapi
    "test_symtable",         # CPython symbol table details
    "test_tools",            # CPython internal tools
    "test_xxlimited",        # CPython C extension test
    "test_xxlimited_35",     # CPython C extension test
    "test_xxtestfuzz",       # CPython fuzzing
    "test_xxsubtype",        # CPython C extension test

    # Display/GUI required
    "test_idle",             # needs display (IDLE)
    "test_tix",              # needs display
    "test_tk",               # needs display
    "test_tkinter",          # needs display
    "test_ttk_guionly",      # needs display
    "test_ttk_textonly",     # needs Tk libraries
    "test_turtle",           # needs display

    # Platform-specific (Windows)
    "test_msilib",           # Windows only
    "test_startfile",        # Windows only
    "test_winreg",           # Windows only
    "test_winsound",         # Windows only
    "test_wmi",              # Windows only

    # Hardware/resource requirements
    "test_ossaudiodev",      # needs audio hardware
    "test_zipfile64",        # requires too many resources

    # Known to hang or be extremely slow
    "test_socketserver",     # can hang in CI
]

# Tests expected to fail on PyPy. These represent known behavioral
# differences between PyPy and CPython that don't affect normal usage.
EXPECTED_FAILURES = [
    "test_call",          # CPython-specific call protocol details
    "test_exceptions",    # minor exception message differences
    "test_generators",    # generator implementation details
    "test_grammar",       # parser differences
    "test_iter",          # iterator protocol details
    "test_list",          # implementation-specific behavior
    "test_re",            # buffer handling and error message differences
    "test_print",         # minor output differences
    "test_property",      # descriptor protocol differences
    "test_range",         # range implementation details
    "test_sort",          # sort stability/implementation details
    "test_types",         # type system differences
    "test_weakref",       # weakref implementation differences
]
