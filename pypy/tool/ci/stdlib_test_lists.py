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
# testing CPython implementation details, or removed in 3.12)
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

    # Network-dependent (no network in CI)
    "test_smtpnet",          # needs network
    "test_urllib2net",        # needs network
    "test_urllibnet",        # needs network
    "test_xmlrpc_net",       # needs network

    # Missing deps/env in CI
    "test_curses",           # needs curses terminal
    "test_pyrepl",           # needs terminal
    "test_readline",         # needs readline
    "test_tcl",              # needs Tcl/Tk

    # Known to hang or be extremely slow
    "test_socketserver",     # can hang in CI
]

# Tests expected to fail on PyPy due to implementation differences.
# Each has only a few subtest failures (<=3) out of many.
EXPECTED_FAILURES = [
    "test_ast",              # AST positional-only arg tuple
    "test_c_locale_coercion", # locale encoding details
    "test_codecs",           # octal/non-ASCII escape warning format
    "test_coroutines",       # RuntimeWarning, coroutine docstring
    "test_cmd_line_script",  # null bytes in multiline string
    "test_code_module",      # traceback context in console
    "test_codeop",           # SyntaxWarning handling
    "test_concurrent_futures", # process pool edge cases
    "test_ctypes",           # struct format differences
    "test_dataclasses",      # docstring format, weakref slots
    "test_doctest",          # doctest finder details
    "test_enum",             # flag containment
    "test_exceptions",       # SyntaxError caret range
    "test_frame",            # frame tracing line numbers
    "test_fstring",          # f-string error messages
    "test_future_stmt",      # future statement handling
    "test_genericalias",     # generic alias detail
    "test_generators",       # generator finalizer edge cases
    "test_grammar",          # parser edge cases
    "test_inspect",          # signature stripping
    "test_iter",             # reentrant exhaustion, __reduce__
    "test_list",             # deep repr recursion
    "test_marshal",          # object identity in marshal
    "test_memoryio",         # buffer error on write
    "test_memoryview",       # released memory access
    "test_metaclass",        # metaclass doctest
    "test_mmap",             # closed mmap detection
    "test_multibytecodec",   # codec state handling
    "test_pdb",              # debugger details
    "test_pydoc",            # pydoc output differences
    "test_re",               # buffer handling, error messages
    "test_repl",             # REPL close_stdin behavior
    "test_rlcompleter",      # tab completion
    "test_source_encoding",  # encoding error message
    "test_string_literals",  # invalid escape DeprecationWarning
    "test_subprocess",       # flaky ResourceWarning in zombie test
    "test_support",          # RecursionError handling
    "test_sys",              # sys.flags, version_info
    "test_sys_settrace",     # trace event ordering differences
    "test_termios",          # crashes in CI without terminal
    "test_threading",        # main thread after fork
    "test_typing",           # doctest difference
    "test_unparse",          # AST unparse of f-strings
    "test_utf8_mode",        # UTF-8 mode behavior
    "test_venv",             # pip default behavior
    "test_weakref",          # repr failure edge case
]
