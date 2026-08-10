""" PyFrame class implementation with the interpreter main loop.
"""

import sys
from rpython.rlib import jit, rweakref
from rpython.rlib.debug import make_sure_not_resized, check_nonneg
from rpython.rlib.debug import ll_assert_not_none
from rpython.rlib.jit import hint
from rpython.rlib.objectmodel import instantiate, specialize, we_are_translated
from rpython.rlib.objectmodel import not_rpython
from rpython.rlib.rarithmetic import intmask, r_uint
from rpython.tool.pairtype import extendabletype

from pypy.interpreter import pycode, pytraceback
from pypy.interpreter.argument import Arguments
from pypy.interpreter.astcompiler import consts
from pypy.interpreter.baseobjspace import W_Root
from pypy.interpreter.error import (
    OperationError, oefmt)
from pypy.interpreter.executioncontext import ExecutionContext
from pypy.interpreter.nestedscope import Cell
from pypy.tool import stdlib_opcode

# Define some opcodes used
for op in '''DUP_TOP POP_TOP SETUP_EXCEPT SETUP_FINALLY SETUP_WITH
SETUP_ASYNC_WITH POP_BLOCK YIELD_VALUE
NOP FOR_ITER EXTENDED_ARG END_ASYNC_FOR LOAD_CONST CALL_FUNCTION
JUMP_IF_FALSE_OR_POP JUMP_IF_TRUE_OR_POP POP_JUMP_IF_FALSE POP_JUMP_IF_TRUE
JUMP_IF_NOT_EXC_MATCH JUMP_ABSOLUTE JUMP_FORWARD GET_ITER GET_AITER
RETURN_VALUE RERAISE RAISE_VARARGS POP_EXCEPT
YIELD_FROM BEFORE_ASYNC_WITH LOAD_FAST_AND_CLEAR STORE_FAST_MAYBE_NULL
'''.split():
    globals()[op] = stdlib_opcode.opmap[op]

class FrameDebugData(object):
    """ A small object that holds debug data for tracing
    """
    w_f_trace                = None
    instr_prev_plus_one      = 0
    f_lineno                 = 0      # current lineno for tracing
    is_being_profiled        = False
    is_in_line_tracing       = False
    f_trace_lines            = True
    f_trace_opcodes          = False
    w_locals                 = None
    hidden_operationerr      = None
    jumped_from_suspension   = False    # a suspended frame whose f_lineno
                                        # was assigned; consumed on resume

    def __init__(self, pycode, init_lineno=-1):
        self.f_lineno = init_lineno
        self.w_globals = pycode.w_globals

class PyFrame(W_Root):
    """Represents a frame for a regular Python function
    that needs to be interpreted.

    Public fields:
     * 'space' is the object space this frame is running in
     * 'code' is the PyCode object this frame runs
     * 'w_locals' is the locals dictionary to use, if needed, stored on a
       debug object
     * 'w_globals' is the attached globals dictionary
     * 'builtin' is the attached built-in module
     * 'valuestack_w', 'blockstack', control the interpretation

    Cell Vars:
        my local variables that are exposed to my inner functions
    Free Vars:
        variables coming from a parent function in which i'm nested
    'closure' is a list of Cell instances: the received free vars.
    """

    __metaclass__ = extendabletype

    frame_finished_execution = False
    f_generator_wref         = rweakref.dead_ref  # for generators/coroutines
    f_generator_nowref       = None               # (only one of the two attrs)
    w_yielding_from = None
    last_instr               = -1
    f_backref                = jit.vref_None

    escaped                  = False  # see mark_as_escaped()
    debugdata                = None

    pycode = None # code object executed by that frame
    locals_cells_stack_w = None # the list of all locals, cells and the valuestack
    valuestackdepth = 0 # number of items on valuestack
    lastblock = None

    # other fields:

    # builtin - builtin cache, only if honor__builtins__ is True
    # defaults to False

    # there is also self.space which is removed by the annotator

    # additionally JIT uses vable_token field that is representing
    # frame current virtualizable state as seen by the JIT

    def __init__(self, space, code, w_globals, outer_func):
        self = hint(self, access_directly=True, fresh_virtualizable=True)
        assert isinstance(code, pycode.PyCode)
        self.space = space
        self.pycode = code
        if code.frame_stores_global(w_globals):
            self.getorcreatedebug().w_globals = w_globals
        ncellvars = len(code.co_cellvars)
        nfreevars = len(code.co_freevars)
        size = code.co_nlocals + ncellvars + nfreevars + code.co_stacksize
        # the layout of this list is as follows:
        # | local vars | cells | stack |
        self.locals_cells_stack_w = [None] * size
        self.valuestackdepth = code.co_nlocals + ncellvars + nfreevars
        make_sure_not_resized(self.locals_cells_stack_w)
        check_nonneg(self.valuestackdepth)
        #
        if space.config.objspace.honor__builtins__:
            self.builtin = space.builtin.pick_builtin(w_globals)
        # regular functions always have CO_OPTIMIZED and CO_NEWLOCALS.
        # class bodies only have CO_NEWLOCALS.
        self.initialize_frame_scopes(outer_func, code)

    def getdebug(self):
        return self.debugdata

    def getorcreatedebug(self, init_lineno=-1):
        if self.debugdata is None:
            self.debugdata = FrameDebugData(self.pycode, init_lineno)
        return self.debugdata

    def get_w_globals(self):
        debugdata = self.getdebug()
        if debugdata is not None:
            return debugdata.w_globals
        return jit.promote(self.pycode).w_globals

    def get_w_f_trace(self):
        d = self.getdebug()
        if d is None:
            return None
        return d.w_f_trace

    def get_is_being_profiled(self):
        d = self.getdebug()
        if d is None:
            return False
        return d.is_being_profiled

    def get_w_locals(self):
        d = self.getdebug()
        if d is None:
            return None
        return d.w_locals

    def get_f_trace_lines(self):
        d = self.getdebug()
        if d is None:
            return True
        return d.f_trace_lines

    def get_f_trace_opcodes(self):
        d = self.getdebug()
        if d is None:
            return False
        return d.f_trace_opcodes

    @not_rpython
    def __repr__(self):
        # useful in tracebacks
        return "<%s.%s executing %s at line %s" % (
            self.__class__.__module__, self.__class__.__name__,
            self.pycode, self.get_last_lineno())

    def _getcell(self, varindex):
        cell = self.locals_cells_stack_w[varindex + self.pycode.co_nlocals]
        assert isinstance(cell, Cell)
        return cell

    def mark_as_escaped(self):
        """
        Must be called on frames that are exposed to applevel, e.g. by
        sys._getframe().  This ensures that the virtualref holding the frame
        is properly forced by ec.leave(), and thus the frame will be still
        accessible even after the corresponding C stack died.
        """
        self.escaped = True

    def append_block(self, block):
        assert block.previous is self.lastblock
        self.lastblock = block

    def pop_block(self):
        block = self.lastblock
        self.lastblock = block.previous
        return block

    def blockstack_non_empty(self):
        return self.lastblock is not None

    def get_blocklist(self):
        """Returns a list containing all the blocks in the frame"""
        lst = []
        block = self.lastblock
        while block is not None:
            lst.append(block)
            block = block.previous
        return lst

    def set_blocklist(self, lst):
        self.lastblock = None
        i = len(lst) - 1
        while i >= 0:
            block = lst[i]
            i -= 1
            block.previous = self.lastblock
            self.lastblock = block

    def get_builtin(self):
        if self.space.config.objspace.honor__builtins__:
            return self.builtin
        else:
            return self.space.builtin

    @jit.unroll_safe
    def initialize_frame_scopes(self, outer_func, code):
        # regular functions always have CO_OPTIMIZED and CO_NEWLOCALS.
        # class bodies only have CO_NEWLOCALS.
        # CO_NEWLOCALS: make a locals dict unless optimized is also set
        # CO_OPTIMIZED: no locals dict needed at all
        flags = code.co_flags
        if not (flags & pycode.CO_OPTIMIZED):
            if flags & pycode.CO_NEWLOCALS:
                self.getorcreatedebug().w_locals = self.space.newdict(module=True)
            else:
                w_globals = self.get_w_globals()
                assert w_globals is not None
                self.getorcreatedebug().w_locals = w_globals

        ncellvars = len(code.co_cellvars)
        nfreevars = len(code.co_freevars)
        if not nfreevars:
            if not ncellvars:
                return            # no cells needed - fast path
        elif outer_func is None:
            space = self.space
            raise oefmt(space.w_TypeError,
                        "directly executed code object may not contain free "
                        "variables")
        if outer_func and outer_func.closure:
            closure_size = len(outer_func.closure)
        else:
            closure_size = 0
        if closure_size != nfreevars:
            raise ValueError("code object received a closure with "
                                 "an unexpected number of free variables")
        index = code.co_nlocals
        for i in range(ncellvars):
            self.locals_cells_stack_w[index] = Cell(
                    None, self.pycode.cell_families[i])
            index += 1
        for i in range(nfreevars):
            self.locals_cells_stack_w[index] = outer_func.closure[i]
            index += 1

    def _is_generator_or_coroutine(self):
        return (self.getcode().co_flags & (pycode.CO_COROUTINE |
                                           pycode.CO_GENERATOR |
                                           pycode.CO_ASYNC_GENERATOR)) != 0

    def run(self, name=None, qualname=None):
        """Start this frame's execution."""
        if self._is_generator_or_coroutine():
            return self.initialize_as_generator(name, qualname)
        else:
            return self.execute_frame()
    run._always_inline_ = True

    def initialize_as_generator(self, name, qualname):
        space = self.space
        flags = self.getcode().co_flags
        if flags & pycode.CO_COROUTINE:
            from pypy.interpreter.generator import Coroutine
            gen = Coroutine(self, name, qualname)
            ec = space.getexecutioncontext()
            gen.capture_origin(ec)
        elif flags & pycode.CO_ASYNC_GENERATOR:
            from pypy.interpreter.generator import AsyncGenerator
            gen = AsyncGenerator(self, name, qualname)
        elif flags & pycode.CO_GENERATOR:
            from pypy.interpreter.generator import GeneratorIterator
            gen = GeneratorIterator(self, name, qualname)
        else:
            raise AssertionError("bad co_flags")

        if space.config.translation.rweakref:
            self.f_generator_wref = rweakref.ref(gen)
        else:
            self.f_generator_nowref = gen
        w_gen = gen
        return w_gen

    def resume_execute_frame(self, w_arg_or_err):
        # Called from execute_frame() just before resuming the bytecode
        # interpretation.
        from pypy.interpreter.pyopcode import SApplicationException
        space = self.space
        w_yf = self.w_yielding_from
        if w_yf is not None:
            self.w_yielding_from = None
            try:
                self.next_yield_from(w_yf, w_arg_or_err)
            except OperationError as operr:
                operr.record_context(space, space.getexecutioncontext())
                return self.handle_generator_error(operr)
            # Normal case: the call above raises Yield.
            # We reach this point if the iterable is exhausted.
            last_instr = jit.promote(self.last_instr)
            assert last_instr & 1 == 0
            assert last_instr >= 0
            return r_uint(last_instr + 2)

        if isinstance(w_arg_or_err, SApplicationException):
            # An exception thrown into a generator suspended inside an
            # except block must chain to that frame's own active exception.
            # Use ec.sys_exc_operror directly (the generator's saved state,
            # swapped in by push_gen_or_coroutine): the sys_exc_info() walk
            # would escape into *outer* handlers' exceptions and corrupt
            # chains built later (test_contextlib's ExitStack test), and
            # record_context()'s _context_recorded flag must stay unset so
            # the normal raise machinery still records at the raise site.
            operr = w_arg_or_err.operr
            last = space.getexecutioncontext().sys_exc_operror
            if last is not None:
                operr.chain_exceptions(space, last)
            return self.handle_generator_error(operr)

        last_instr = jit.promote(self.last_instr)
        if last_instr != -1:
            assert last_instr & 1 == 0
            d = self.getdebug()
            if d is not None and d.jumped_from_suspension:
                # f_lineno was assigned while suspended: land exactly on
                # the jump target and discard the sent value, which the
                # target line's stack has no slot for
                d.jumped_from_suspension = False
                assert last_instr >= 0
                return r_uint(last_instr)
            self.pushvalue(w_arg_or_err)
            return r_uint(last_instr + 2)
        else:
            return r_uint(0)

    def execute_frame(self, w_arg_or_err=None):
        """Execute this frame.  Main entry point to the interpreter.
        'w_arg_or_err' is non-None iff we are starting or resuming
        a generator or coroutine frame; in that case, w_arg_or_err
        is the input argument -or- an SApplicationException instance.
        """
        from pypy.interpreter import pyopcode as pyopcode
        # the following 'assert' is an annotation hint: it hides from
        # the annotator all methods that are defined in PyFrame but
        # overridden in the {,Host}FrameClass subclasses of PyFrame.
        assert (isinstance(self, self.space.FrameClass) or
                not self.space.config.translating)
        executioncontext = self.space.getexecutioncontext()
        executioncontext.enter(self)
        got_exception = True
        w_exitvalue = self.space.w_None
        try:
            executioncontext.call_trace(self)
            #
            # Execution starts just after the last_instr.  Initially,
            # last_instr is -1.  After a generator suspends it points to
            # the YIELD_VALUE/YIELD_FROM instruction.
            try:
                try:
                    if w_arg_or_err is None:
                        assert self.last_instr == -1
                        next_instr = r_uint(0)
                    else:
                        next_instr = self.resume_execute_frame(w_arg_or_err)
                except pyopcode.Yield:
                    w_exitvalue = self.popvalue()
                else:
                    w_exitvalue = self.dispatch(self.pycode, next_instr,
                                                executioncontext)
            except OperationError:
                raise
            except Exception as e:      # general fall-back
                raise self._convert_unexpected_exception(e)
            finally:
                executioncontext.return_trace(self, w_exitvalue)
            got_exception = False
        finally:
            executioncontext.leave(self, w_exitvalue, got_exception)
        return w_exitvalue
    execute_frame.insert_stack_check_here = True

    # stack manipulation helpers
    def pushvalue(self, w_object):
        depth = self.valuestackdepth
        self.locals_cells_stack_w[depth] = ll_assert_not_none(w_object)
        self.valuestackdepth = depth + 1

    def pushvalue_none(self):
        depth = self.valuestackdepth
        # the entry is already None, and remains None
        assert self.locals_cells_stack_w[depth] is None
        self.valuestackdepth = depth + 1

    def pushvalue_maybe_none(self, w_object):
        depth = self.valuestackdepth
        self.locals_cells_stack_w[depth] = w_object
        self.valuestackdepth = depth + 1

    def assert_stack_index(self, index):
        if we_are_translated():
            return
        if not self._check_stack_index(index):
            #import pdb; pdb.set_trace()
            assert 0

    def _check_stack_index(self, index):
        code = self.pycode
        ncellvars = len(code.co_cellvars)
        nfreevars = len(code.co_freevars)
        stackstart = code.co_nlocals + ncellvars + nfreevars
        return index >= stackstart

    def popvalue(self):
        return ll_assert_not_none(self.popvalue_maybe_none())

    def popvalue_maybe_none(self):
        depth = self.valuestackdepth - 1
        self.assert_stack_index(depth)
        assert depth >= 0
        w_object = self.locals_cells_stack_w[depth]
        self.locals_cells_stack_w[depth] = None
        self.valuestackdepth = depth
        return w_object


    # we need two popvalues that return different data types:
    # one in case we want list another in case of tuple
    def _new_popvalues():
        @jit.unroll_safe
        def popvalues(self, n):
            values_w = [None] * n
            while True:
                n -= 1
                if n < 0:
                    break
                values_w[n] = self.popvalue()
            return values_w
        return popvalues
    popvalues = _new_popvalues()
    popvalues_mutable = _new_popvalues()
    del _new_popvalues

    @jit.unroll_safe
    def peekvalues(self, n):
        values_w = [None] * n
        base = self.valuestackdepth - n
        self.assert_stack_index(base)
        assert base >= 0
        while True:
            n -= 1
            if n < 0:
                break
            values_w[n] = self.locals_cells_stack_w[base+n]
        return values_w

    @jit.unroll_safe
    def dropvalues(self, n):
        n = hint(n, promote=True)
        finaldepth = self.valuestackdepth - n
        self.assert_stack_index(finaldepth)
        assert finaldepth >= 0
        while True:
            n -= 1
            if n < 0:
                break
            self.locals_cells_stack_w[finaldepth+n] = None
        self.valuestackdepth = finaldepth

    @jit.unroll_safe
    def pushrevvalues(self, n, values_w): # n should be len(values_w)
        make_sure_not_resized(values_w)
        while True:
            n -= 1
            if n < 0:
                break
            self.pushvalue(values_w[n])

    @jit.unroll_safe
    def dupvalues(self, n):
        delta = n-1
        while True:
            n -= 1
            if n < 0:
                break
            w_value = self.peekvalue(delta)
            self.pushvalue(w_value)

    def peekvalue(self, index_from_top=0):
        # NOTE: top of the stack is peekvalue(0).
        # Contrast this with CPython where it's PEEK(-1).
        return ll_assert_not_none(self.peekvalue_maybe_none(index_from_top))

    def peekvalue_maybe_none(self, index_from_top=0):
        index_from_top = hint(index_from_top, promote=True)
        index = self.valuestackdepth + ~index_from_top
        self.assert_stack_index(index)
        assert index >= 0
        return self.locals_cells_stack_w[index]

    def settopvalue(self, w_object, index_from_top=0):
        index_from_top = hint(index_from_top, promote=True)
        index = self.valuestackdepth + ~index_from_top
        self.assert_stack_index(index)
        assert index >= 0
        self.locals_cells_stack_w[index] = ll_assert_not_none(w_object)

    @jit.unroll_safe
    def dropvaluesuntil(self, finaldepth):
        depth = self.valuestackdepth - 1
        finaldepth = hint(finaldepth, promote=True)
        assert finaldepth >= 0
        while depth >= finaldepth:
            self.locals_cells_stack_w[depth] = None
            depth -= 1
        self.valuestackdepth = finaldepth

    def make_arguments(self, nargs, methodcall=False, w_function=None, fnname=None):
        if fnname:
            import pdb;pdb.set_trace()
        fnname_parens = self.space.guess_function_name_parens(w_function)
        return Arguments(
                self.space, self.peekvalues(nargs), methodcall=methodcall, fnname_parens=fnname_parens)

    def argument_factory(self, arguments, keyword_names_w, keywords_w, w_star, w_starstar, methodcall=False, w_function=None, fnname=None):
        if fnname:
            import pdb;pdb.set_trace()
        fnname_parens = self.space.guess_function_name_parens(w_function)
        return Arguments(
                self.space, arguments, keyword_names_w, keywords_w, w_star,
                w_starstar, methodcall=methodcall, fnname_parens=fnname_parens)

    def hide(self):
        return self.pycode.hidden_applevel

    def getcode(self):
        return hint(self.pycode, promote=True)

    @jit.look_inside_iff(lambda self, scope_w: jit.isvirtual(scope_w))
    def setfastscope(self, scope_w):
        """Initialize the fast locals from a list of values,
        where the order is according to self.pycode.signature()."""
        scope_len = len(scope_w)
        if scope_len > self.pycode.co_nlocals:
            raise ValueError("new fastscope is longer than the allocated area")
        # don't assign directly to 'locals_cells_stack_w[:scope_len]' to be
        # virtualizable-friendly
        for i in range(scope_len):
            self.locals_cells_stack_w[i] = scope_w[i]
        self.init_cells()

    def getdictscope(self):
        """
        Get the locals as a dictionary
        """
        self.fast2locals()
        return self.debugdata.w_locals

    def setdictscope(self, w_locals, skip_free_vars=False):
        """
        Initialize the locals from a dictionary.
        """
        self.getorcreatedebug().w_locals = w_locals
        self.locals2fast(skip_free_vars=skip_free_vars)

    @jit.unroll_safe
    def fast2locals(self):
        # Copy values from the fastlocals to self.w_locals
        d = self.getorcreatedebug()
        w_locals = d.w_locals
        write = False
        if w_locals is None:
            w_locals = self.space.newdict(instance=True)
            write = True
        varnames = self.getcode().getvarnames()
        for i in range(min(len(varnames), self.getcode().co_nlocals)):
            name = varnames[i]
            if len(name) > 1 and name[0] == '.' and name.find('.', 1) > 0:
                # a PEP 709 hidden slot ('.0.iter', '.0.save.x'): never
                # exposed in locals(), like CPython's CO_FAST_HIDDEN.  The
                # legacy '.0' argument of non-inlined comprehensions has no
                # second dot and keeps its historical visibility.
                continue
            w_value = self.locals_cells_stack_w[i]
            if w_value is not None:
                self.space.setitem_str(w_locals, name, w_value)
            else:
                w_name = self.space.newtext(name)
                try:
                    self.space.delitem(w_locals, w_name)
                except OperationError as e:
                    if not e.match(self.space, self.space.w_KeyError):
                        raise

        # cellvars are values exported to inner scopes
        # freevars are values coming from outer scopes
        # (see locals2fast for why CO_OPTIMIZED)
        freevarnames = self.pycode.co_cellvars
        if self.pycode.co_flags & consts.CO_OPTIMIZED:
            freevarnames = freevarnames + self.pycode.co_freevars
        for i in range(len(freevarnames)):
            name = freevarnames[i]
            cell = self._getcell(i)
            try:
                w_value = cell.get()
            except ValueError:
                w_name = self.space.newtext(name)
                try:
                    self.space.delitem(w_locals, w_name)
                except OperationError as e:
                    if not e.match(self.space, self.space.w_KeyError):
                        raise
            else:
                self.space.setitem_str(w_locals, name, w_value)
        if write:
            d.w_locals = w_locals


    @jit.unroll_safe
    def locals2fast(self, skip_free_vars=False):
        # Copy values from self.w_locals to the fastlocals
        w_locals = self.getorcreatedebug().w_locals
        assert w_locals is not None
        varnames = self.getcode().getvarnames()
        numlocals = self.getcode().co_nlocals

        new_fastlocals_w = [None] * numlocals

        for i in range(min(len(varnames), numlocals)):
            name = varnames[i]
            if len(name) > 1 and name[0] == '.' and name.find('.', 1) > 0:
                # hidden slots are absent from w_locals (see fast2locals);
                # keep their live values or a debugger writing f_locals
                # mid-comprehension would wipe the iterator
                new_fastlocals_w[i] = self.locals_cells_stack_w[i]
                continue
            w_value = self.space.finditem_str(w_locals, name)
            if w_value is not None:
                new_fastlocals_w[i] = w_value

        self.setfastscope(new_fastlocals_w)

        freevarnames = self.pycode.co_cellvars
        if self.pycode.co_flags & consts.CO_OPTIMIZED and not skip_free_vars:
            freevarnames = freevarnames + self.pycode.co_freevars
            # If the namespace is unoptimized, then one of the
            # following cases applies:
            # 1. It does not contain free variables, because it
            #    uses import * or is a top-level namespace.
            # 2. It is a class namespace.
            # We don't want to accidentally copy free variables
            # into the locals dict used by the class.
        for i in range(len(freevarnames)):
            name = freevarnames[i]
            cell = self._getcell(i)
            w_value = self.space.finditem_str(w_locals, name)
            if w_value is not None:
                cell.set(w_value)
            else:
                cell.set(None)

    @jit.unroll_safe
    def init_cells(self):
        """
        Initialize cellvars from self.locals_cells_stack_w.
        """
        args_to_copy = self.pycode._args_as_cellvars
        index = self.pycode.co_nlocals
        for i in range(len(args_to_copy)):
            argnum = args_to_copy[i]
            if argnum >= 0:
                cell = self.locals_cells_stack_w[index]
                assert isinstance(cell, Cell)
                cell.set(self.locals_cells_stack_w[argnum])
            index += 1

    def getclosure(self):
        return None

    def fget_code(self, space):
        return self.getcode()

    def fget_getdictscope(self, space):
        return self.getdictscope()

    def fget_w_globals(self, space):
        # bit silly, but GetSetProperty passes a space
        return self.get_w_globals()


    ### line numbers ###

    def fget_f_lineno(self, space):
        "Returns the line number of the instruction currently being executed."
        # Always derive f_lineno from the instruction pointer (matching
        # CPython 3.12), rather than from a cached FrameDebugData.f_lineno
        # that is only kept in sync while a *global* sys.settrace hook is
        # active (see executioncontext.run_trace_func). A frame whose
        # f_trace was set directly (without sys.settrace) would otherwise
        # see a stale line number on every read after the first.
        lineno = self.get_last_lineno()
        if lineno == -1:
            # PEP 626: instructions without line information (artificial
            # bytecodes) expose f_lineno as None, not -1
            return space.w_None
        return space.newint(lineno)

    def fset_f_lineno(self, space, w_new_lineno):
        "Change the line number of the instruction currently being executed."
        try:
            new_lineno = space.int_w(w_new_lineno)
        except OperationError:
            raise oefmt(space.w_ValueError, "lineno must be an integer")

        # You can only do this from within a trace function, not via
        # _getframe or similar hackery.
        if space.int_w(self.fget_f_lasti(space)) == -1:
            raise oefmt(space.w_ValueError,
                        "can't jump from the 'call' trace event of a new frame")
        if self.get_w_f_trace() is None:
            raise oefmt(space.w_ValueError,
                        "f_lineno can only be set by a trace function")

        code = self.pycode.co_code
        # A frame stopped on a YIELD_VALUE/YIELD_FROM is a suspended
        # generator or coroutine: 3.12 allows jumping it -- from the
        # yield's 'return' trace event (PY_YIELD in monitoring terms), or
        # pdb-style from another frame's event (test_jump_from_yield).
        # The value the resume will push is accounted for below.
        opcode_here = ord(code[self.last_instr])
        # YIELD_FROM suspensions are deliberately excluded: PyPy delegates
        # through w_yielding_from, and a jump would be silently deferred
        # until the sub-iterable is exhausted; no 3.12 test needs it.
        suspended_at_yield = opcode_here == YIELD_VALUE

        # Otherwise only allow jumps when we're tracing a line event.
        d = self.getorcreatedebug()
        if not suspended_at_yield and not d.is_in_line_tracing:
            raise oefmt(space.w_ValueError,
                        "can only jump from a 'line' trace event")

        line = self.pycode.co_firstlineno
        if new_lineno < line:
            raise oefmt(space.w_ValueError,
                        "line %d comes before the current code block", new_lineno)

        lines = self.pycode._marklines()
        x = first_line_not_before(lines, new_lineno)


        # If we didn't reach the requested line, return an error.
        if x == -1:
            raise oefmt(space.w_ValueError,
                        "line %d comes after the current code block", new_lineno)
        new_lineno = x

        stacks = mark_stacks(self.pycode)
        start = stacks[self.last_instr // 2]
        if start is None or start is _JUMP_CONFLICT:
            raise oefmt(space.w_ValueError, "can't jump from unreachable code")
        if suspended_at_yield and len(start) > 0:
            # the value the yield consumed; the resume will push the sent
            # value in its place (CPython models this as one abstract pop
            # for FRAME_SUSPENDED)
            end = len(start) - 1
            assert end >= 0
            start = start[:end]

        error = "cannot find bytecode for specified line"
        best_addr = -1
        best_state = None
        best_mode = 0
        for i in range(len(lines)):
            if lines[i] == new_lineno:
                target = stacks[i]
                if target is None or target is _JUMP_CONFLICT:
                    if error is not None:
                        error = ("can't jump into an exception handler, "
                                 "or code may be unreachable")
                    continue
                mode = _jump_compatible(start, target)
                if mode >= 0:
                    error = None
                    if best_state is None or len(target) > len(best_state):
                        best_state = target
                        best_addr = i * 2
                        best_mode = mode
                elif error is not None:
                    error = _jump_error_message(mode)
        if error is not None:
            raise OperationError(space.w_ValueError, space.newtext(error))
        assert best_state is not None

        # 3.12 binds every still-unbound local to None on a successful
        # jump, warning first -- an error-escalated warning aborts before
        # any frame mutation.
        unbound = 0
        for j in range(self.pycode.co_nlocals):
            if self.locals_cells_stack_w[j] is None:
                unbound += 1
        if unbound > 0:
            if unbound == 1:
                plural = ""
            else:
                plural = "s"
            space.warn(space.newtext("assigning None to %d unbound local%s"
                                     % (unbound, plural)),
                       space.w_RuntimeWarning)
            for j in range(self.pycode.co_nlocals):
                if self.locals_cells_stack_w[j] is None:
                    self.locals_cells_stack_w[j] = space.w_None

        stackbase = (self.pycode.co_nlocals +
                     len(self.pycode.co_cellvars) +
                     len(self.pycode.co_freevars))
        # Validate the whole planned mutation against the real frame BEFORE
        # warning, binding locals or popping anything: a refusal must leave
        # the frame untouched.
        from pypy.interpreter.pyopcode import SysExcInfoRestorer
        if best_mode == _JUMP_MODE_POP:
            block = self.lastblock
            k = len(start) - 1
            while k >= len(best_state):
                kind = start[k] & 7
                if (kind == JK_TRYBLOCK or kind == JK_WITHBLOCK or
                        kind == JK_EXCBLOCK):
                    if block is None:
                        raise oefmt(space.w_ValueError, "incompatible stacks")
                    if kind == JK_EXCBLOCK:
                        if not isinstance(block, SysExcInfoRestorer):
                            raise oefmt(space.w_ValueError,
                                        "incompatible stacks")
                    else:
                        if isinstance(block, SysExcInfoRestorer):
                            raise oefmt(space.w_ValueError,
                                        "incompatible stacks")
                    block = block.previous
                k -= 1
            if stackbase + _jump_n_values(best_state) > self.valuestackdepth:
                raise oefmt(space.w_ValueError, "incompatible stacks")

        if best_mode == _JUMP_MODE_POP:
            # leave abandoned regions: pop their runtime blocks top-down,
            # then cut the value stack to the target's depth in one go
            # (dropvaluesuntil only assigns slots, so possibly-unbound
            # PEP 709 entries are dropped safely)
            k = len(start) - 1
            while k >= len(best_state):
                kind = start[k] & 7
                if kind == JK_TRYBLOCK or kind == JK_WITHBLOCK:
                    if self.lastblock is None:
                        raise oefmt(space.w_ValueError, "incompatible stacks")
                    self.pop_block()
                elif kind == JK_EXCBLOCK:
                    if self.lastblock is None:
                        raise oefmt(space.w_ValueError, "incompatible stacks")
                    popped = self.pop_block()
                    if not isinstance(popped, SysExcInfoRestorer):
                        raise oefmt(space.w_ValueError, "incompatible stacks")
                    # restores sys.exc_info() of the abandoned handler,
                    # exactly like POP_EXCEPT
                    popped.cleanupstack(self)
                k -= 1
            newdepth = stackbase + _jump_n_values(best_state)
            if newdepth > self.valuestackdepth:
                raise oefmt(space.w_ValueError, "incompatible stacks")
            self.dropvaluesuntil(newdepth)
        elif best_mode == _JUMP_MODE_PUSH:
            # entering try bodies: synthesize the runtime blocks their
            # SETUP instructions would have pushed.  CPython needs nothing
            # here (its exception tables are positional), but PyPy's
            # handlers live on the frame's block stack.
            from pypy.interpreter.pyopcode import ExceptBlock, FinallyBlock
            for k in range(len(start), len(best_state)):
                entry = best_state[k]
                assert entry & 7 == JK_TRYBLOCK
                aux = entry >> 3
                handlerpos = aux >> 1
                # the annotator cannot see that packed entries are
                # non-negative, and FrameBlock.handlerposition is unsigned
                assert handlerpos >= 0
                depth = stackbase + _jump_n_values(best_state[:k])
                assert depth >= 0
                if aux & 1:
                    block = ExceptBlock(depth, handlerpos, self.lastblock)
                else:
                    block = FinallyBlock(depth, handlerpos, self.lastblock)
                self.lastblock = block

        d.f_lineno = new_lineno
        assert best_addr & 1 == 0
        if suspended_at_yield:
            # resume_execute_frame normally pushes the sent value and
            # continues at last_instr + 2; after a jump the target line
            # must execute in full with no stray value on the stack
            # (CPython 3.13 semantics -- 3.12 skidded one instruction
            # instead, which no test observes), so flag the frame and
            # let the resume path land exactly here, pushing nothing.
            d.jumped_from_suspension = True
        self.last_instr = best_addr

    def get_last_lineno(self):
        "Returns the line number of the instruction currently being executed."
        return pytraceback.offset2lineno(self.pycode, self.last_instr)

    def fget_f_builtins(self, space):
        return self.get_builtin().getdict(space)

    def get_f_back(self):
        return ExecutionContext.getnextframe_nohidden(self)

    def fget_f_back(self, space):
        return self.get_f_back()

    def fget_f_lasti(self, space):
        return self.space.newint(self.last_instr)

    def fget_f_trace(self, space):
        return self.get_w_f_trace()

    def fset_f_trace(self, space, w_trace):
        if space.is_w(w_trace, space.w_None):
            self.getorcreatedebug().w_f_trace = None
        else:
            d = self.getorcreatedebug()
            d.w_f_trace = w_trace
            d.f_lineno = self.get_last_lineno()

    def fdel_f_trace(self, space):
        self.getorcreatedebug().w_f_trace = None

    def fget_f_trace_lines(self, space):
        return space.newbool(self.get_f_trace_lines())

    def fset_f_trace_lines(self, space, w_trace):
        self.getorcreatedebug().f_trace_lines = space.is_true(w_trace)

    def fget_f_trace_opcodes(self, space):
        return space.newbool(self.get_f_trace_opcodes())

    def fset_f_trace_opcodes(self, space, w_trace):
        self.getorcreatedebug().f_trace_opcodes = space.is_true(w_trace)

    def get_generator(self):
        if self.space.config.translation.rweakref:
            return self.f_generator_wref()
        else:
            return self.f_generator_nowref

    def descr_clear(self, space):
        """F.clear(): clear most references held by the frame"""
        # Clears a random subset of the attributes: the local variables
        # and the w_locals.  Note that CPython doesn't clear f_locals
        # (which can create leaks) but it's hard to notice because
        # the next Python-level read of 'frame.f_locals' will clear it.
        if not self.frame_finished_execution:
            if not self._is_generator_or_coroutine():
                raise oefmt(space.w_RuntimeError,
                            "cannot clear an executing frame")
            gen = self.get_generator()
            if gen is not None:
                if gen.running:
                    raise oefmt(space.w_RuntimeError,
                                "cannot clear an executing frame")
                if (self.getcode().co_flags & pycode.CO_COROUTINE and
                        self.last_instr == -1):
                    # matches Coroutine._finalize_: a coroutine that was
                    # never started (never awaited) warns when closed.
                    w_mod = space.getbuiltinmodule("_warnings")
                    w_f = space.getattr(w_mod,
                            space.newtext("_warn_unawaited_coroutine"))
                    space.call_function(w_f, gen)
                gen.descr_close()

        debug = self.getdebug()
        if debug is not None:
            debug.w_f_trace = None
            if debug.w_locals is not None:
                debug.w_locals = space.newdict()

        # clear the locals, including the cell/free vars, and the stack
        for i in range(len(self.locals_cells_stack_w)):
            w_oldvalue = self.locals_cells_stack_w[i]
            if isinstance(w_oldvalue, Cell):
                # we can't mutate w_oldvalue here, because that could still be
                # shared by an inner/outer function
                w_newvalue = Cell(
                    None, w_oldvalue.family)
            else:
                w_newvalue = None
            self.locals_cells_stack_w[i] = w_newvalue
        self.valuestackdepth = 0
        self.lastblock = None    # the FrameBlock chained list

    def _convert_unexpected_exception(self, e):
        from pypy.interpreter import error

        operr = error.get_converted_unexpected_exception(self.space, e)
        pytraceback.record_application_traceback(
            self.space, operr, self, self.last_instr)
        raise operr

    def descr_repr(self, space):
        code = self.pycode
        moreinfo = ", file '%s', line %s, code %s" % (
            code.co_filename, self.get_last_lineno(), code.co_name)
        return self.getrepr(space, "frame", moreinfo)

# ____________________________________________________________

# Abstract-stack simulation for frame.f_lineno assignment, following
# CPython 3.12's frame_setlineno/mark_stacks.  Each instruction gets a
# state: a list of packed entries (kind in the low 3 bits, auxiliary data
# above), or None (never reached), or the _JUMP_CONFLICT sentinel (reached
# with disagreeing states -- not jumpable).  Value-carrying kinds occupy a
# slot on the frame's value stack; block kinds mirror the runtime block
# stack, which CPython no longer has but PyPy still does.
def first_line_not_before(lines, line):
    result = sys.maxint
    for l in lines:
        if l >= line and l < result:
            result = l
    if result == sys.maxint:
        return -1
    return result

JK_OBJ = 0        # plain value; aux = index of the pushing instruction --
                  # plain values are only compatible when pushed by the
                  # same instruction, which is what refuses jumps between
                  # unrelated mid-expression states (the null-on-stack
                  # tests) and into inlined comprehensions
JK_ITER = 1       # the iterator of a for loop (value)
JK_EXITFN = 2     # the __exit__/aexit callable kept below a with (value)
JK_UNROLLER = 3   # the unroller pushed at handler entry (value)
JK_EXCVALUE = 4   # the exception instance in an except handler (value)
JK_TRYBLOCK = 5   # runtime Except/FinallyBlock; aux = handlerpos<<1|is_except
JK_WITHBLOCK = 6  # runtime FinallyBlock of a with statement
JK_EXCBLOCK = 7   # runtime SysExcInfoRestorer of an entered handler

_JUMP_MODE_POP = 0    # target state is a prefix of the start state
_JUMP_MODE_PUSH = 1   # start is a prefix; the difference is all TRYBLOCKs

_JUMP_ERR_STACKS = -1
_JUMP_ERR_EXCEPT = -2
_JUMP_ERR_FORLOOP = -3

_JUMP_CONFLICT = [-1]

def _jump_error_message(mode):
    if mode == _JUMP_ERR_EXCEPT:
        return "can't jump into an 'except' block as there's no exception"
    if mode == _JUMP_ERR_FORLOOP:
        return "can't jump into the body of a for loop"
    return "incompatible stacks"

def _jump_is_value(kind):
    return kind <= JK_EXCVALUE

def _jump_n_values(state):
    n = 0
    for k in range(len(state)):
        if _jump_is_value(state[k] & 7):
            n += 1
    return n

def _jump_entries_match(a, b):
    ka = a & 7
    if ka != (b & 7):
        return False
    if ka == JK_OBJ:
        # a plain temporary is only known to hold the right value when
        # both paths pushed it with the same instruction
        return a == b
    # blocks and structured values are interchangeable across sibling
    # constructs: jumping from one with body into another keeps the first
    # __exit__, which is what CPython does too
    return True

def _jump_refusal(target, common):
    """Pick the refusal following CPython's top-of-target-stack rule: an
    exception-handler entry anywhere in the unmatched part wins, then a
    loop iterator, then the generic message."""
    for k in range(len(target) - 1, common - 1, -1):
        kind = target[k] & 7
        if kind == JK_EXCBLOCK:
            return _JUMP_ERR_EXCEPT
    for k in range(len(target) - 1, common - 1, -1):
        kind = target[k] & 7
        if kind == JK_ITER:
            return _JUMP_ERR_FORLOOP
    return _JUMP_ERR_STACKS

def _jump_compatible(start, target):
    """negative error code if the jump must be refused, else the mode."""
    common = 0
    nstart = len(start)
    ntarget = len(target)
    while (common < nstart and common < ntarget and
           _jump_entries_match(start[common], target[common])):
        common += 1
    if common == ntarget:
        return _JUMP_MODE_POP     # everything above gets popped
    # the target needs entries the start does not have: only runtime try
    # blocks can be synthesized out of thin air
    if common == nstart:
        for k in range(common, ntarget):
            if (target[k] & 7) != JK_TRYBLOCK:
                return _jump_refusal(target, common)
        return _JUMP_MODE_PUSH
    return _jump_refusal(target, common)

def _jump_states_eq(a, b):
    if len(a) != len(b):
        return False
    for k in range(len(a)):
        if a[k] != b[k]:
            return False
    return True

def _jump_full_arg(code, addr):
    """The instruction's oparg with any number of EXTENDED_ARG prefixes."""
    arg = ord(code[addr + 1])
    shift = 8
    j = addr - 2
    while j >= 0 and ord(code[j]) == EXTENDED_ARG:
        arg |= ord(code[j + 1]) << shift
        shift += 8
        j -= 2
    return arg

def _jump_pop_values(state, n):
    """Remove the topmost n value entries, leaving block entries where
    they are: a runtime value pop never touches the block stack, so e.g.
    an except handler's prologue popping the exception value must not
    erase the JK_EXCBLOCK that models the handler's SysExcInfoRestorer."""
    while n > 0:
        k = len(state) - 1
        while k >= 0 and not _jump_is_value(state[k] & 7):
            k -= 1
        if k < 0:
            return state
        assert k >= 0
        state = state[:k] + state[k + 1:]
        n -= 1
    return state

def _jump_pop_block_kind(state, kind1, kind2):
    """Remove the topmost entry whose kind is kind1 or kind2."""
    for k in range(len(state) - 1, -1, -1):
        kind = state[k] & 7
        if kind == kind1 or kind == kind2:
            assert k >= 0
            return state[:k] + state[k + 1:]
    return state

def _jump_propagate(stacks, j, state, i):
    """Merge `state` into stacks[j]; returns True if the fixpoint must
    rescan (a backward target became marked, or a merge changed a state
    other instructions may already have consumed)."""
    old = stacks[j]
    if old is None:
        stacks[j] = state
        return j < i
    if old is _JUMP_CONFLICT or _jump_states_eq(old, state):
        return False
    # A control-flow merge ('or'/'and'/ternary) joins the same shape with
    # different value provenance.  Poisoning it would make every line
    # below the merge un-jumpable, so canonicalize differing plain values
    # to the merge point instead; only genuine shape mismatches conflict.
    if len(old) == len(state):
        merged = None
        mergeable = True
        for k in range(len(old)):
            if old[k] == state[k]:
                continue
            if (old[k] & 7) == JK_OBJ and (state[k] & 7) == JK_OBJ:
                if merged is None:
                    merged = old[:]
                merged[k] = (j << 3) | JK_OBJ
            else:
                mergeable = False
                break
        if mergeable and merged is not None:
            if _jump_states_eq(old, merged):
                return False
            stacks[j] = merged
            return True
    stacks[j] = _JUMP_CONFLICT
    return j < i

def mark_stacks(pycode):
    from pypy.interpreter.astcompiler.assemble import _opcode_stack_effect
    code = pycode.co_code
    n = len(code) // 2
    stacks = [None] * (n + 1)
    stacks[0] = []
    todo = True
    while todo:
        todo = False
        i = 0
        while i < len(code):
            state = stacks[i // 2]
            if state is None or state is _JUMP_CONFLICT:
                i += 2
                continue
            opcode = ord(code[i])
            if opcode == EXTENDED_ARG:
                if _jump_propagate(stacks, i // 2 + 1, state, i // 2):
                    todo = True
                i += 2
                continue
            arg = _jump_full_arg(code, i)
            next_i = i // 2 + 1
            if (opcode == JUMP_IF_FALSE_OR_POP or
                    opcode == JUMP_IF_TRUE_OR_POP):
                j = arg * 2
                if _jump_propagate(stacks, j // 2, state, i // 2):
                    todo = True
                if _jump_propagate(stacks, next_i,
                                   _jump_pop_values(state, 1), i // 2):
                    todo = True
            elif (opcode == POP_JUMP_IF_FALSE or
                    opcode == POP_JUMP_IF_TRUE):
                popped = _jump_pop_values(state, 1)
                j = arg * 2
                if _jump_propagate(stacks, j // 2, popped, i // 2):
                    todo = True
                if _jump_propagate(stacks, next_i, popped, i // 2):
                    todo = True
            elif opcode == JUMP_IF_NOT_EXC_MATCH:
                popped = _jump_pop_values(state, 2)
                j = arg * 2
                if _jump_propagate(stacks, j // 2, popped, i // 2):
                    todo = True
                if _jump_propagate(stacks, next_i, popped, i // 2):
                    todo = True
            elif opcode == JUMP_ABSOLUTE:
                j = arg * 2
                if _jump_propagate(stacks, j // 2, state, i // 2):
                    todo = True
            elif opcode == JUMP_FORWARD:
                j = arg * 2 + i + 2
                if _jump_propagate(stacks, j // 2, state, i // 2):
                    todo = True
            elif opcode == GET_ITER or opcode == GET_AITER:
                # replaces the iterable with the iterator
                newstate = (_jump_pop_values(state, 1) +
                            [(i // 2) << 3 | JK_ITER])
                if _jump_propagate(stacks, next_i, newstate, i // 2):
                    todo = True
            elif opcode == FOR_ITER:
                # fallthrough pushes the next item; the exit edge pops the
                # iterator
                body = state + [(i // 2) << 3 | JK_OBJ]
                if _jump_propagate(stacks, next_i, body, i // 2):
                    todo = True
                j = arg * 2 + i + 2
                if _jump_propagate(stacks, j // 2,
                                   _jump_pop_values(state, 1), i // 2):
                    todo = True
            elif opcode == SETUP_EXCEPT or opcode == SETUP_FINALLY:
                handlerpos = arg * 2 + i + 2
                is_except = opcode == SETUP_EXCEPT
                aux = handlerpos << 1
                if is_except:
                    aux |= 1
                body = state + [aux << 3 | JK_TRYBLOCK]
                if _jump_propagate(stacks, next_i, body, i // 2):
                    todo = True
                handler = state + [(i // 2) << 3 | JK_UNROLLER]
                if is_except:
                    handler = handler + [(i // 2) << 3 | JK_EXCVALUE]
                handler = handler + [(i // 2) << 3 | JK_EXCBLOCK]
                if _jump_propagate(stacks, handlerpos // 2, handler, i // 2):
                    todo = True
            elif opcode == SETUP_WITH or opcode == SETUP_ASYNC_WITH:
                handlerpos = arg * 2 + i + 2
                if opcode == SETUP_WITH:
                    # replaces the manager with __exit__, pushes the block
                    # and the __enter__ result
                    below = _jump_pop_values(state, 1)
                    below = below + [(i // 2) << 3 | JK_EXITFN]
                else:
                    # the exit fn was pushed by BEFORE_ASYNC_WITH; TOS is
                    # the awaited __aenter__ result, popped and re-pushed
                    below = _jump_pop_values(state, 1)
                body = (below + [(handlerpos << 1) << 3 | JK_WITHBLOCK]
                        + [(i // 2) << 3 | JK_OBJ])
                if _jump_propagate(stacks, next_i, body, i // 2):
                    todo = True
                handler = (below + [(i // 2) << 3 | JK_UNROLLER]
                           + [(i // 2) << 3 | JK_EXCBLOCK])
                if _jump_propagate(stacks, handlerpos // 2, handler, i // 2):
                    todo = True
            elif opcode == BEFORE_ASYNC_WITH:
                # pops the manager, pushes __aexit__ then the __aenter__
                # coroutine
                newstate = (_jump_pop_values(state, 1) +
                            [(i // 2) << 3 | JK_EXITFN,
                             (i // 2) << 3 | JK_OBJ])
                if _jump_propagate(stacks, next_i, newstate, i // 2):
                    todo = True
            elif opcode == POP_BLOCK:
                newstate = _jump_pop_block_kind(state, JK_TRYBLOCK,
                                                JK_WITHBLOCK)
                if _jump_propagate(stacks, next_i, newstate, i // 2):
                    todo = True
            elif opcode == POP_EXCEPT:
                newstate = _jump_pop_block_kind(state, JK_EXCBLOCK,
                                                JK_EXCBLOCK)
                if _jump_propagate(stacks, next_i, newstate, i // 2):
                    todo = True
            elif opcode == END_ASYNC_FOR:
                # pops the handler block, the exception, the unroller and
                # the exhausted async iterator on its fallthrough path
                newstate = _jump_pop_block_kind(state, JK_EXCBLOCK,
                                                JK_EXCBLOCK)
                newstate = _jump_pop_values(newstate, 3)
                if _jump_propagate(stacks, next_i, newstate, i // 2):
                    todo = True
            elif (opcode == RETURN_VALUE or opcode == RAISE_VARARGS or
                    opcode == RERAISE):
                pass    # no successor
            else:
                try:
                    effect = _opcode_stack_effect(opcode, arg)
                except KeyError:
                    stacks[next_i] = _JUMP_CONFLICT
                    i += 2
                    continue
                if effect < 0:
                    newstate = _jump_pop_values(state, -effect)
                elif effect > 0:
                    newstate = state
                    for k in range(effect):
                        newstate = newstate + [(i // 2) << 3 | JK_OBJ]
                else:
                    newstate = state
                if _jump_propagate(stacks, next_i, newstate, i // 2):
                    todo = True
            i += 2
    return stacks
# ____________________________________________________________

def get_block_class(opname):
    # select the appropriate kind of block
    from pypy.interpreter.pyopcode import block_classes
    return block_classes[opname]

def unpickle_block(space, w_tup):
    w_opname, w_handlerposition, w_valuestackdepth = space.unpackiterable(w_tup)
    opname = space.text_w(w_opname)
    handlerposition = space.int_w(w_handlerposition)
    valuestackdepth = space.int_w(w_valuestackdepth)
    assert valuestackdepth >= 0
    assert handlerposition >= 0
    blk = instantiate(get_block_class(opname))
    blk.handlerposition = handlerposition
    blk.valuestackdepth = valuestackdepth
    return blk
