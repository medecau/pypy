import sys, os
from .error import VerificationError


LIST_OF_FILE_NAMES = ['sources', 'include_dirs', 'library_dirs',
                      'extra_objects', 'depends']

class _Extension:
    """Minimal C extension descriptor (no distutils/setuptools required)."""
    def __init__(self, name, sources, **kwds):
        self.name = name
        self.sources = list(sources)
        self.include_dirs = list(kwds.get('include_dirs') or [])
        self.library_dirs = list(kwds.get('library_dirs') or [])
        self.libraries = list(kwds.get('libraries') or [])
        self.extra_compile_args = list(kwds.get('extra_compile_args') or [])
        self.extra_link_args = list(kwds.get('extra_link_args') or [])
        self.extra_objects = list(kwds.get('extra_objects') or [])
        self.define_macros = list(kwds.get('define_macros') or [])
        self.depends = list(kwds.get('depends') or [])


def get_extension(srcfilename, modname, sources=(), **kwds):
    allsources = [srcfilename]
    for src in sources:
        allsources.append(os.path.normpath(src))
    return _Extension(name=modname, sources=allsources, **kwds)

def compile(tmpdir, ext, compiler_verbose=0, debug=None):
    """Compile a C extension module using subprocess and sysconfig."""

    saved_environ = os.environ.copy()
    try:
        outputfilename = _build(tmpdir, ext, compiler_verbose, debug)
        outputfilename = os.path.abspath(outputfilename)
    finally:
        for key, value in saved_environ.items():
            if os.environ.get(key) != value:
                os.environ[key] = value
    return outputfilename

def _build(tmpdir, ext, compiler_verbose=0, debug=None):
    import subprocess
    import sysconfig as _sc

    cc = (_sc.get_config_var('CC') or 'gcc').split()
    cflags = (_sc.get_config_var('CFLAGS') or '').split()
    ldshared = (_sc.get_config_var('LDSHARED') or 'gcc -shared').split()
    ext_suffix = _sc.get_config_var('EXT_SUFFIX')
    include_dir = _sc.get_path('include')

    if debug is None:
        debug = sys.flags.debug

    oldir = os.getcwd()
    os.chdir(tmpdir)
    ext.sources = [os.path.relpath(os.path.join(oldir, x)) for x in ext.sources]
    try:
        obj_files = []
        for i, src in enumerate(ext.sources):
            obj = 'tmp_%d_%s.o' % (i, ext.name.replace('.', '_'))
            compile_cmd = (
                cc + cflags +
                ['-fPIC', '-I', include_dir] +
                ['-I' + d for d in ext.include_dirs] +
                ext.extra_compile_args +
                (['-g'] if debug else []) +
                ['-D' + (n if v is None else '%s=%s' % (n, v))
                 for n, v in ext.define_macros] +
                ['-c', src, '-o', obj]
            )
            if compiler_verbose:
                print(' '.join(compile_cmd))
            ret = subprocess.call(compile_cmd)
            if ret != 0:
                raise VerificationError(
                    'Compilation failed: %s (exit status %d)' % (src, ret))
            obj_files.append(obj)

        soname = ext.name.split('.')[-1] + ext_suffix
        link_cmd = (
            ldshared +
            obj_files +
            ext.extra_objects +
            ['-L' + d for d in ext.library_dirs] +
            ['-l' + l for l in ext.libraries] +
            ext.extra_link_args +
            ['-o', soname]
        )
        if compiler_verbose:
            print(' '.join(link_cmd))
        ret = subprocess.call(link_cmd)
        if ret != 0:
            raise VerificationError(
                'Linking failed: %s (exit status %d)' % (soname, ret))

        return os.path.join(tmpdir, soname)
    finally:
        os.chdir(oldir)


try:
    from os.path import samefile
except ImportError:
    def samefile(f1, f2):
        return os.path.abspath(f1) == os.path.abspath(f2)

def maybe_relative_path(path):
    if not os.path.isabs(path):
        return path      # already relative
    dir = path
    names = []
    while True:
        prevdir = dir
        dir, name = os.path.split(prevdir)
        if dir == prevdir or not dir:
            return path     # failed to make it relative
        names.append(name)
        try:
            if samefile(dir, os.curdir):
                names.reverse()
                return os.path.join(*names)
        except OSError:
            pass

# ____________________________________________________________

try:
    int_or_long = (int, long)
    import cStringIO
except NameError:
    int_or_long = int      # Python 3
    import io as cStringIO

def _flatten(x, f):
    if isinstance(x, str):
        f.write('%ds%s' % (len(x), x))
    elif isinstance(x, dict):
        keys = sorted(x.keys())
        f.write('%dd' % len(keys))
        for key in keys:
            _flatten(key, f)
            _flatten(x[key], f)
    elif isinstance(x, (list, tuple)):
        f.write('%dl' % len(x))
        for value in x:
            _flatten(value, f)
    elif isinstance(x, int_or_long):
        f.write('%di' % (x,))
    else:
        raise TypeError(
            "the keywords to verify() contains unsupported object %r" % (x,))

def flatten(x):
    f = cStringIO.StringIO()
    _flatten(x, f)
    return f.getvalue()
