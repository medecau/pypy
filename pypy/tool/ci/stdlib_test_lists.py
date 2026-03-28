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

    # Test helpers use asyncore/smtpd (removed)
    "test_ftplib",           # test code uses asyncore mock servers
    "test_logging",          # test code uses smtpd
    "test_poplib",           # test code uses asyncore mock servers
    "test_smtplib",          # test code uses asyncore/smtpd mock servers
    "test_ssl",              # test code uses asyncore mock servers

    # Known to hang or be extremely slow
    "test_socketserver",     # can hang in CI
]

# Tests expected to fail on PyPy due to implementation differences.
# Each has only a few subtest failures (<=3) out of many.
EXPECTED_FAILURES = [
    # Smoke test failures (13)
    "test_call",             # CPython-specific tp_flags
    "test_exceptions",       # SyntaxError caret range differences
    "test_generators",       # generator finalizer edge cases
    "test_grammar",          # parser edge cases
    "test_iter",             # reentrant exhaustion, __reduce__ edge cases
    "test_list",             # deep repr recursion handling
    "test_print",            # error message wording
    "test_property",         # error message wording
    "test_range",            # error message wording
    "test_re",               # buffer handling differences
    "test_sort",             # list mutation detection during sort
    "test_types",            # type parameter pickling
    "test_weakref",          # proxy behavior differences

    # Full suite failures (56)
    "test__opcode",          # CPython opcode details
    "test_ast",              # AST implementation details
    "test_c_locale_coercion", # locale coercion behavior
    "test_cmd_line",         # command line handling details
    "test_cmd_line_script",  # script execution details
    "test_code",             # code object differences
    "test_code_module",      # code module details
    "test_codecs",           # codec edge cases
    "test_codeop",           # code compilation details
    "test_concurrent_futures", # process pool edge cases
    "test_coroutines",       # coroutine implementation details
    "test_cprofile",         # profiler implementation details
    "test_ctypes",           # ctypes implementation differences
    "test_dataclasses",      # dataclass edge cases
    "test_doctest",          # doctest implementation details
    "test_enum",             # enum edge cases
    "test_extcall",          # extended call protocol details
    "test_frame",            # frame object differences
    "test_fstring",          # f-string edge cases
    "test_future_stmt",      # future statement handling
    "test_genericalias",     # generic alias details
    "test_inspect",          # inspect module differences
    "test_marshal",          # marshal implementation details
    "test_memoryio",         # memory IO details
    "test_memoryview",       # memoryview implementation
    "test_metaclass",        # metaclass edge cases
    "test_mmap",             # mmap implementation details
    "test_multibytecodec",   # multibyte codec details
    "test_opcache",          # opcode cache details
    "test_pdb",              # debugger implementation details
    "test_positional_only_arg", # error message wording
    "test_pyclbr",           # class browser differences
    "test_pydoc",            # pydoc output differences
    "test_regrtest",         # test framework internals
    "test_repl",             # REPL behavior differences
    "test_rlcompleter",      # completer implementation details
    "test_signal",           # signal handling edge cases
    "test_source_encoding",  # source encoding details
    "test_string_literals",  # string literal edge cases
    "test_structseq",        # struct sequence details
    "test_subprocess",       # subprocess edge cases
    "test_sundry",           # miscellaneous module imports
    "test_super",            # super() implementation details
    "test_support",          # test support module details
    "test_syntax",           # syntax error details
    "test_sys",              # sys module differences
    "test_sys_settrace",     # trace function details
    "test_termios",          # termios implementation
    "test_threading",        # threading edge cases
    "test_trace",            # trace module details
    "test_tty",              # tty implementation
    "test_typing",           # typing module differences
    "test_unpack_ex",        # unpacking edge cases
    "test_unparse",          # AST unparsing details
    "test_utf8_mode",        # UTF-8 mode details
    "test_venv",             # venv creation details
]
