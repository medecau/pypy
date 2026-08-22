# NOT_RPYTHON
"""
The 'sys' module.
"""

from _structseq import structseqtype, structseqfield, structseq_new, SimpleNamespace
import sys
import _imp
from __pypy__.os import _get_multiarch

def excepthook(exctype, value, traceback):
    """Handle an exception by displaying it with a traceback on sys.stderr."""
    if not isinstance(value, BaseException):
        sys.stderr.write("TypeError: print_exception(): Exception expected for "
                         "value, {} found\n".format(type(value).__name__))
        return

    # NB: no sys.stdout.flush() here.  It looks tempting -- stdout and stderr
    # may be the same file -- but CPython's C hook never touches stdout, and
    # test_code_module checks that the first thing a replaced stdout sees is
    # the program's own write.  app_main flushes both streams on the way out.

    try:
        from traceback import TracebackException
        from _colorize import can_colorize
        limit = getattr(sys, 'tracebacklimit', None)
        format_exc_only = False

        if limit is not None:
            # ok, this is bizarre, but, the meaning of sys.tracebacklimit is
            # understood differently in the traceback module than in
            # PyTraceBack_Print in CPython, see
            # https://bugs.python.org/issue38197
            # one is counting from the top, the other from the bottom of the
            # stack. so reverse polarity here
            if limit > 0:
                if limit > sys.maxsize:
                    limit = sys.maxsize
                limit = -limit
            else:
                # the limit is 0 or negative. PyTraceBack_Print does not print
                # Traceback (most recent call last):
                # because there is indeed no traceback.
                # the traceback module don't care
                traceback = None
                limit = None
                format_exc_only = True

        tb_exc = TracebackException(
            exctype,
            value,
            traceback,
            limit=limit,
        )
        tb_exc._colorize = can_colorize()
        if format_exc_only:
            line_generator = tb_exc.format_exception_only()
        else:
            line_generator = tb_exc.format()
        for line in line_generator:
            print(line, file=sys.stderr, end="")
    except BaseException as e:
        if not excepthook_failsafe(exctype, value):
            raise

def excepthook_failsafe(exctype, value):
    # This version carefully tries to handle all bad cases (e.g. an
    # ImportError looking for traceback.py), but may still raise.
    # If it does, we get "Error calling sys.excepthook" from app_main.py.
    try:
        # first try to print the exception's class name
        stderr = sys.stderr
        stderr.write(str(getattr(exctype, '__name__', exctype)))
        # then attempt to get the str() of the exception
        try:
            s = str(value)
        except:
            s = '<failure of str() on the exception instance>'
        # then print it
        if s:
            stderr.write(': %s\n' % (s,))
        else:
            stderr.write('\n')
        return True     # successfully printed at least the class and value
    except:
        return False    # got an exception again... ignore, report the original

def breakpointhook(*args, **kwargs):
    """This hook function is called by built-in breakpoint()."""

    import importlib, os, warnings

    hookname = os.getenv('PYTHONBREAKPOINT')
    if hookname is None or len(hookname) == 0:
        hookname = 'pdb.set_trace'
    elif hookname == '0':
        return None
    modname, dot, funcname = hookname.rpartition('.')
    if dot == '':
        modname = 'builtins'

    try:
        module = importlib.import_module(modname)
        hook = getattr(module, funcname)
    except:
        warnings.warn(
            'Ignoring unimportable $PYTHONBREAKPOINT: "{}"'.format(hookname),
            RuntimeWarning)
        return None

    return hook(*args, **kwargs)

def exit(exitcode=None):
    """Exit the interpreter by raising SystemExit(exitcode).
If the exitcode is omitted or None, it defaults to zero (i.e., success).
If the exitcode is numeric, it will be used as the system exit status.
If it is another kind of object, it will be printed and the system
exit status will be one (i.e., failure)."""
    # note that we cannot simply use SystemExit(exitcode) here.
    # in the default branch, we use "raise SystemExit, exitcode",
    # which leads to an extra de-tupelizing
    # in normalize_exception, which is exactly like CPython's.
    if isinstance(exitcode, tuple):
        raise SystemExit(*exitcode)
    raise SystemExit(exitcode)

#import __builtin__

def callstats():
    """Not implemented."""
    return None

copyright_str = """\
Copyright 2003 PyPy development team.
All Rights Reserved.
For further information, see <https://pypy.org>

Portions Copyright (c) 2001-2021 Python Software Foundation.
All Rights Reserved.

Portions Copyright (c) 2000 BeOpen.com.
All Rights Reserved.

Portions Copyright (c) 1995-2001 Corporation for National Research Initiatives.
All Rights Reserved.

Portions Copyright (c) 1991-1995 Stichting Mathematisch Centrum, Amsterdam.
All Rights Reserved.
"""

# Keep synchronized with pypy.interpreter.app_main.sys_flags and
# pypy.module.cpyext._flags

# This is tested in test_app_main.py
class sysflags(metaclass=structseqtype):
    name = "sys.flags"
    _forbid_instantiation = True

    debug = structseqfield(0)
    inspect = structseqfield(1)
    interactive = structseqfield(2)
    optimize = structseqfield(3)
    dont_write_bytecode = structseqfield(4)
    no_user_site = structseqfield(5)
    no_site = structseqfield(6)
    ignore_environment = structseqfield(7)
    verbose = structseqfield(8)
    bytes_warning = structseqfield(9)
    quiet = structseqfield(10)
    hash_randomization = structseqfield(11)
    isolated = structseqfield(12)
    dev_mode = structseqfield(13)
    utf8_mode = structseqfield(14)
    warn_default_encoding = structseqfield(15)
    int_max_str_digits = structseqfield(16)
    safe_path = structseqfield(17)

# The real flags are set in app_main, which is not used in untranslated tests.
# Set reasonable defaults for testing, in particular set utf8_mode to 1
# no clue why some have to be a bool, but CPython has tests
# for that. Also see default_otions in app_main
# int_max_str_digits carries the interpreter default (4300, see
# DEFAULT_MAX_STR_DIGITS in pypy/module/sys/system.py) rather than -1, which
# is what app_main now fills in when neither -X int_max_str_digits nor
# PYTHONINTMAXSTRDIGITS is given.
null_sysflags = structseq_new(sysflags, (0,)*13 + (False, 1, 0, 4300, False))
null__xoptions = {}

# Names of the modules PyPy ships as part of its standard library (built-in
# plus lib-python/3 plus lib_pypy). Unlike CPython, which generates this
# from a build-time Lib/ scan, this is a static snapshot -- good enough
# since nothing depends on exact membership, only that it's a frozenset
# of strings (see test_sys.py:test_module_names).
stdlib_module_names = frozenset([
    '__decimal', '__future__', '__hello__', '__phello__', '_abc',
    '_aix_support', '_ast', '_blake2', '_bootsubprocess', '_cffi_backend',
    '_cffi_ssl', '_codecs', '_codecs_cn', '_codecs_hk', '_codecs_iso2022',
    '_codecs_jp', '_codecs_kr', '_codecs_tw', '_collections',
    '_collections_abc', '_colorize', '_compat_pickle', '_compression',
    '_contextvars', '_crypt', '_csv', '_ctypes', '_curses', '_curses_panel',
    '_dbm', '_ffi', '_frozen_importlib', '_gdbm', '_hashlib',
    '_immutables_map', '_io', '_locale', '_lzma', '_markupbase', '_marshal',
    '_md5', '_multibytecodec', '_multiprocessing', '_opcode',
    '_osx_support', '_overlapped', '_posixshmem', '_posixsubprocess',
    '_py_abc', '_pydecimal', '_pyio', '_pypy_generic_alias',
    '_pypy_interact', '_pypy_irc_topic', '_pypy_remote_debug',
    '_pypy_testcapi', '_pypy_typing', '_pypy_util_cffi', '_pypy_wait',
    '_pypy_winbase_cffi', '_pypy_winbase_cffi64', '_random', '_scproxy',
    '_sha1', '_sha256', '_sha3', '_sha512', '_signal', '_sitebuiltins',
    '_socket', '_sqlite3', '_sre', '_ssl', '_string', '_strptime',
    '_structseq', '_sysconfigdata', '_testcapi', '_thread',
    '_threading_local', '_tkinter', '_warnings', '_weakref', '_weakrefset',
    '_winapi', 'abc', 'aifc', 'antigravity', 'argparse', 'array', 'ast',
    'asynchat', 'asyncio', 'asyncore', 'atexit', 'audioop', 'base64', 'bdb',
    'binascii', 'bisect', 'builtins', 'bz2', 'cProfile', 'calendar', 'cffi',
    'cgi', 'cgitb', 'chunk', 'cmath', 'cmd', 'code', 'codecs', 'codeop',
    'collections', 'colorsys', 'compileall', 'concurrent', 'configparser',
    'contextlib', 'contextvars', 'copy', 'copyreg', 'crypt', 'csv',
    'ctypes', 'ctypes_support', 'curses', 'dataclasses', 'datetime', 'dbm',
    'decimal', 'difflib', 'dis', 'doctest', 'email', 'encodings',
    'ensurepip', 'enum', 'errno', 'faulthandler', 'fcntl', 'filecmp',
    'fileinput', 'fnmatch', 'fractions', 'ftplib', 'functools',
    'future_builtins', 'gc', 'genericpath', 'getopt', 'getpass', 'gettext',
    'glob', 'graphlib', 'greenlet', 'grp', 'gzip', 'hashlib', 'heapq',
    'hmac', 'html', 'http', 'identity_dict', 'idlelib', 'imaplib', 'imghdr',
    'importlib', 'inspect', 'io', 'ipaddress', 'itertools', 'json',
    'keyword', 'lib2to3', 'linecache', 'locale', 'logging', 'lzma',
    'mailbox', 'mailcap', 'marshal', 'math', 'mimetypes', 'mmap',
    'modulefinder', 'msilib', 'msvcrt', 'multiprocessing', 'netrc',
    'nntplib', 'ntpath', 'nturl2path', 'numbers', 'opcode', 'operator',
    'optparse', 'os', 'pathlib', 'pdb', 'pickle', 'pickletools', 'pipes',
    'pkgutil', 'platform', 'plistlib', 'poplib', 'posix', 'posixpath',
    'pprint', 'profile', 'pstats', 'pty', 'pwd', 'py_compile', 'pyclbr',
    'pydoc', 'pydoc_data', 'pyexpat', 'pypy_tools', 'pyrepl', 'queue',
    'quopri', 'random', 're', 'readline', 'reprlib', 'resource',
    'rlcompleter', 'runpy', 'sched', 'secrets', 'select', 'selectors',
    'shelve', 'shlex', 'shutil', 'signal', 'site', 'smtpd', 'smtplib',
    'sndhdr', 'socket', 'socketserver', 'sqlite3', 'sre_compile',
    'sre_constants', 'sre_parse', 'ssl', 'stackless', 'stat', 'statistics',
    'string', 'stringprep', 'struct', 'subprocess', 'sunau', 'symtable',
    'sys', 'sysconfig', 'syslog', 'tabnanny', 'tarfile', 'telnetlib',
    'tempfile', 'termios', 'textwrap', 'this', 'threading', 'time',
    'timeit', 'tkinter', 'token', 'tokenize', 'tomllib', 'tputil', 'trace',
    'traceback', 'tracemalloc', 'tty', 'turtle', 'turtledemo', 'types',
    'typing', 'unicodedata', 'unittest', 'urllib', 'uu', 'uuid', 'venv',
    'warnings', 'wave', 'weakref', 'webbrowser', 'wsgiref', 'xdrlib', 'xml',
    'xmlrpc', 'zipapp', 'zipfile', 'zipimport', 'zlib', 'zoneinfo',
])

# copied from version.py
def tuple2hex(ver):
    levels = {'alpha':     0xA,
              'beta':      0xB,
              'candidate': 0xC,
              'final':     0xF,
              }
    subver = ver[4]
    if not (0 <= subver <= 9):
        subver = 0
    return (ver[0] << 24   |
            ver[1] << 16   |
            ver[2] << 8    |
            levels[ver[3]] << 4 |
            subver)

implementation_dict = {
    'name':       'pypy',
    'version':    sys.pypy_version_info,
    'hexversion': tuple2hex(sys.pypy_version_info),
    'cache_tag':  _imp.get_tag(),
}

multiarch = _get_multiarch()
if multiarch:
    implementation_dict['_multiarch'] = multiarch

implementation = SimpleNamespace(**implementation_dict)


def sys_stdout():
    import sys
    try:
        return sys.stdout
    except AttributeError:
        raise RuntimeError("lost sys.stdout")

def print_item_to(x, stream):
    # give to write() an argument which is either a string or a unicode
    # (and let it deals itself with unicode handling).  The check "is
    # unicode" should not use isinstance() at app-level, because that
    # could be fooled by strange objects, so it is done at interp-level.
    try:
        stream.write(x)
    except UnicodeEncodeError:
        print_unencodable_to(x, stream)

def print_unencodable_to(x, stream):
    encoding = stream.encoding
    encoded = x.encode(encoding, 'backslashreplace')
    buffer = getattr(stream, 'buffer', None)
    if buffer is not None:
         buffer.write(encoded)
    else:
        escaped = encoded.decode(encoding, 'strict')
        stream.write(escaped)

def print_newline_to(stream):
    stream.write("\n")

def displayhook(obj):
    """Print an object to sys.stdout and also save it in builtins._"""
    import builtins
    if obj is not None:
        builtins._ = obj
        # NB. this is slightly more complicated in CPython,
        # see e.g. the difference with  >>> print 5,; 8
        print_item_to(repr(obj), sys_stdout())
        print_newline_to(sys_stdout())

__displayhook__ = displayhook  # this is exactly like in CPython


def _make_monitoring_module():
    # PEP 669 (sys.monitoring, new in 3.12): API-surface implementation.
    #
    # PyPy does not (yet) implement the underlying low-overhead bytecode
    # instrumentation, so no event is ever delivered.  Everything that does
    # not need instrumentation is implemented for real, in particular the
    # tool id registry (use_tool_id/free_tool_id/get_tool): _lsprof reserves
    # PROFILER_ID there for the lifetime of a profiler exactly like CPython
    # 3.12's cProfile does, and monitoring clients use the registry to
    # detect each other.  Asking for actual events (a non-empty event set
    # passed to set_events/set_local_events) raises NotImplementedError
    # rather than quietly delivering nothing, so that no client silently
    # gets zero events -- they can fall back to sys.settrace/sys.setprofile,
    # which work and give correct results on PyPy.
    #
    # NB: this runs while the sys module itself is being initialized, so it
    # must not import anything (importing types here can deadlock the
    # bootstrap, since types.py itself imports sys).  ModuleType is
    # reachable as type(sys): app.py already holds the in-progress module,
    # and CodeType as the type of any function's __code__.
    _ModuleType = type(sys)
    _CodeType = type(_make_monitoring_module.__code__)

    monitoring = _ModuleType(
        'sys.monitoring',
        "An implementation of PEP 669's API surface. The tool id registry is "
        "real, but PyPy does not implement the underlying instrumentation "
        "yet: no event is delivered, and asking for events raises "
        "NotImplementedError instead of silently doing nothing.")

    events = _ModuleType('sys.monitoring.events')
    _event_ids = [   # ids from CPython's pycore_instruments.h
        ('PY_START', 0), ('PY_RESUME', 1), ('PY_RETURN', 2), ('PY_YIELD', 3),
        ('CALL', 4), ('LINE', 5), ('INSTRUCTION', 6), ('JUMP', 7),
        ('BRANCH', 8), ('STOP_ITERATION', 9), ('RAISE', 10),
        ('EXCEPTION_HANDLED', 11), ('PY_UNWIND', 12), ('PY_THROW', 13),
        ('RERAISE', 14), ('C_RETURN', 15), ('C_RAISE', 16),
    ]
    events.NO_EVENTS = 0
    for _name, _id in _event_ids:
        setattr(events, _name, 1 << _id)
    monitoring.events = events
    _NUM_EVENTS = len(_event_ids)

    # Only ids 0..5 can be handed out: CPython reserves 6 and 7 for
    # sys.setprofile() and sys.settrace().
    _NUM_TOOL_IDS = 6
    monitoring.DEBUGGER_ID = 0
    monitoring.COVERAGE_ID = 1
    monitoring.PROFILER_ID = 2
    monitoring.OPTIMIZER_ID = 5

    # Every id except PROFILER_ID starts out taken.  The registry itself is
    # real, but there is no instrumentation behind it, so a client that got
    # an id would receive no events; reporting the ids as in use is what
    # makes hypothesis, coverage.py and debuggers fall back to
    # sys.settrace/sys.setprofile, which do work here.  PROFILER_ID is left
    # free because _lsprof claims it, the way CPython's cProfile does.
    _RESERVED = 'non-instrumenting sys.monitoring stub'
    _tool_names = [_RESERVED] * _NUM_TOOL_IDS
    _tool_names[monitoring.PROFILER_ID] = None
    _tool_events = [0] * _NUM_TOOL_IDS
    _tool_callbacks = [{} for _i in range(_NUM_TOOL_IDS)]

    class _Sentinel:
        def __init__(self, name):
            self._name = name
        def __repr__(self):
            return '<sys.monitoring.%s>' % self._name

    monitoring.DISABLE = _Sentinel('DISABLE')
    monitoring.MISSING = _Sentinel('MISSING')

    def _index(value):
        # CPython's argument clinic 'int' converter, spelled out: this
        # module must keep working without importing anything (see above).
        if not isinstance(value, int):
            try:
                index = type(value).__index__
            except AttributeError:
                raise TypeError(
                    "'%s' object cannot be interpreted as an integer"
                    % (type(value).__name__,)) from None
            value = index(value)
        if not -0x80000000 <= value <= 0x7fffffff:
            raise OverflowError("Python int too large to convert to C int")
        return value

    def _check_tool_id(tool_id):
        tool_id = _index(tool_id)
        if not 0 <= tool_id < _NUM_TOOL_IDS:
            raise ValueError("invalid tool %d (must be between 0 and %d)"
                             % (tool_id, _NUM_TOOL_IDS - 1))
        return tool_id

    def _check_event_set(event_set, what="event set"):
        event_set = _index(event_set)
        if not 0 <= event_set < (1 << _NUM_EVENTS):
            raise ValueError("invalid %s 0x%x"
                             % (what, event_set & 0xffffffff))
        return event_set

    def _check_in_use(tool_id):
        if _tool_names[tool_id] is None:
            raise ValueError("tool %d is not in use" % (tool_id,))

    def _check_code(code):
        if not isinstance(code, _CodeType):
            raise TypeError("code must be a code object")

    def _not_implemented():
        return NotImplementedError(
            "PyPy does not implement sys.monitoring instrumentation yet: "
            "no event can be delivered, use sys.settrace()/sys.setprofile() "
            "instead")

    def use_tool_id(tool_id, name):
        tool_id = _check_tool_id(tool_id)
        if not isinstance(name, str):
            raise ValueError("tool name must be a str")
        if _tool_names[tool_id] is not None:
            raise ValueError("tool %d is already in use" % (tool_id,))
        _tool_names[tool_id] = name

    def free_tool_id(tool_id):
        # CPython only drops the name here: the event set and the callbacks
        # registered for the id survive, a tool is expected to clean up
        # after itself.  Freeing an id that is not in use is not an error.
        tool_id = _check_tool_id(tool_id)
        _tool_names[tool_id] = None

    def get_tool(tool_id):
        tool_id = _check_tool_id(tool_id)
        return _tool_names[tool_id]

    def register_callback(tool_id, event, func):
        tool_id = _check_tool_id(tool_id)
        event = _index(event)
        if event <= 0 or event & (event - 1):
            raise ValueError(
                "The callback can only be set for one event at a time")
        if event >= (1 << _NUM_EVENTS):
            raise ValueError("invalid event %d" % (event,))
        sys.audit('sys.monitoring.register_callback', func)
        callbacks = _tool_callbacks[tool_id]
        previous = callbacks.get(event)
        if func is None:
            callbacks.pop(event, None)
        else:
            callbacks[event] = func
        return previous

    def get_events(tool_id):
        tool_id = _check_tool_id(tool_id)
        return _tool_events[tool_id]

    def set_events(tool_id, event_set):
        tool_id = _check_tool_id(tool_id)
        event_set = _check_event_set(event_set)
        _check_in_use(tool_id)
        if event_set != events.NO_EVENTS:
            raise _not_implemented()
        _tool_events[tool_id] = event_set

    def get_local_events(tool_id, code):
        _check_code(code)
        _check_tool_id(tool_id)
        return events.NO_EVENTS

    def set_local_events(tool_id, code, event_set):
        _check_code(code)
        tool_id = _check_tool_id(tool_id)
        event_set = _check_event_set(event_set, "local event set")
        _check_in_use(tool_id)
        if event_set != events.NO_EVENTS:
            raise _not_implemented()

    def restart_events():
        pass

    for _fn in (use_tool_id, free_tool_id, get_tool, register_callback,
                get_events, set_events, get_local_events, set_local_events,
                restart_events):
        setattr(monitoring, _fn.__name__, _fn)
    return monitoring

monitoring = _make_monitoring_module()
