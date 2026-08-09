"""Tokenization help for Python programs.

tokenize(readline) is a generator that breaks a stream of bytes into
Python tokens.  It decodes the bytes according to PEP-0263 for
determining source file encoding.

It accepts a readline-like method which is called repeatedly to get the
next line of input (or b"" for EOF).  It generates 5-tuples with these
members:

    the token type (see token.py)
    the token (a string)
    the starting (row, column) indices of the token (a 2-tuple of ints)
    the ending (row, column) indices of the token (a 2-tuple of ints)
    the original line (string)

It is designed to match the working of the Python tokenizer exactly, except
that it produces COMMENT tokens for comments and gives type OP for all
operators.  Additionally, all token lists start with an ENCODING token
which tells you which encoding was used to decode the bytes stream.
"""

__author__ = 'Ka-Ping Yee <ping@lfw.org>'
__credits__ = ('GvR, ESR, Tim Peters, Thomas Wouters, Fred Drake, '
               'Skip Montanaro, Raymond Hettinger, Trent Nelson, '
               'Michael Foord')
from builtins import open as _builtin_open
from codecs import lookup, BOM_UTF8
import collections
import functools
from io import TextIOWrapper
import itertools as _itertools
import re
import sys
from token import *
from token import EXACT_TOKEN_TYPES
try:
    import _tokenize
    _HAS_C_TOKENIZER = True
except ImportError:
    _HAS_C_TOKENIZER = False

cookie_re = re.compile(r'^[ \t\f]*#.*?coding[:=][ \t]*([-\w.]+)', re.ASCII)
blank_re = re.compile(br'^[ \t\f]*(?:[#\r\n]|$)', re.ASCII)

import token
__all__ = token.__all__ + ["tokenize", "generate_tokens", "detect_encoding",
                           "untokenize", "TokenInfo"]
del token

class TokenInfo(collections.namedtuple('TokenInfo', 'type string start end line')):
    def __repr__(self):
        annotated_type = '%d (%s)' % (self.type, tok_name[self.type])
        return ('TokenInfo(type=%s, string=%r, start=%r, end=%r, line=%r)' %
                self._replace(type=annotated_type))

    @property
    def exact_type(self):
        if self.type == OP and self.string in EXACT_TOKEN_TYPES:
            return EXACT_TOKEN_TYPES[self.string]
        else:
            return self.type

def group(*choices): return '(' + '|'.join(choices) + ')'
def any(*choices): return group(*choices) + '*'
def maybe(*choices): return group(*choices) + '?'

# Note: we use unicode matching for names ("\w") but ascii matching for
# number literals.
Whitespace = r'[ \f\t]*'
Comment = r'#[^\r\n]*'
Ignore = Whitespace + any(r'\\\r?\n' + Whitespace) + maybe(Comment)
Name = r'\w+'

Hexnumber = r'0[xX](?:_?[0-9a-fA-F])+'
Binnumber = r'0[bB](?:_?[01])+'
Octnumber = r'0[oO](?:_?[0-7])+'
# NB: the first branch takes any digits after a leading zero, not just
# more zeros.  '01234' and '007' are not valid literals, but 3.12's
# tokenizer still hands back one NUMBER and leaves the complaint to the
# parser; matching only '0' here split them into two tokens.  Each '_'
# must still be followed by a digit, so '0_' stops after the '0' --
# test_underscore_literals checks that it does not tokenize whole.
Decnumber = r'(?:0(?:_?[0-9])*|[1-9](?:_?[0-9])*)'
Intnumber = group(Hexnumber, Binnumber, Octnumber, Decnumber)
Exponent = r'[eE][-+]?[0-9](?:_?[0-9])*'
Pointfloat = group(r'[0-9](?:_?[0-9])*\.(?:[0-9](?:_?[0-9])*)?',
                   r'\.[0-9](?:_?[0-9])*') + maybe(Exponent)
Expfloat = r'[0-9](?:_?[0-9])*' + Exponent
Floatnumber = group(Pointfloat, Expfloat)
Imagnumber = group(r'[0-9](?:_?[0-9])*[jJ]', Floatnumber + r'[jJ]')
Number = group(Imagnumber, Floatnumber, Intnumber)

# Return the empty string, plus all of the valid string prefixes.
def _all_string_prefixes():
    # The valid string prefixes. Only contain the lower case versions,
    #  and don't contain any permutations (include 'fr', but not
    #  'rf'). The various permutations will be generated.
    _valid_string_prefixes = ['b', 'r', 'u', 'f', 'br', 'fr']
    # if we add binary f-strings, add: ['fb', 'fbr']
    result = {''}
    for prefix in _valid_string_prefixes:
        for t in _itertools.permutations(prefix):
            # create a list with upper and lower versions of each
            #  character
            for u in _itertools.product(*[(c, c.upper()) for c in t]):
                result.add(''.join(u))
    return result

@functools.lru_cache
def _compile(expr):
    return re.compile(expr, re.UNICODE)

# Note that since _all_string_prefixes includes the empty string,
#  StringPrefix can be the empty string (making it optional).
StringPrefix = group(*_all_string_prefixes())

# Tail end of ' string.
Single = r"[^'\\]*(?:\\.[^'\\]*)*'"
# Tail end of " string.
Double = r'[^"\\]*(?:\\.[^"\\]*)*"'
# Tail end of ''' string.
Single3 = r"[^'\\]*(?:(?:\\.|'(?!''))[^'\\]*)*'''"
# Tail end of """ string.
Double3 = r'[^"\\]*(?:(?:\\.|"(?!""))[^"\\]*)*"""'
Triple = group(StringPrefix + "'''", StringPrefix + '"""')
# Single-line ' or " string.
String = group(StringPrefix + r"'[^\n'\\]*(?:\\.[^\n'\\]*)*'",
               StringPrefix + r'"[^\n"\\]*(?:\\.[^\n"\\]*)*"')

# Sorting in reverse order puts the long operators before their prefixes.
# Otherwise if = came before ==, == would get recognized as two instances
# of =.
Special = group(*map(re.escape, sorted(EXACT_TOKEN_TYPES, reverse=True)))
Funny = group(r'\r?\n', Special)

PlainToken = group(Number, Funny, String, Name)
Token = Ignore + PlainToken

# First (or only) line of ' or " string.
ContStr = group(StringPrefix + r"'[^\n'\\]*(?:\\.[^\n'\\]*)*" +
                group("'", r'\\\r?\n'),
                StringPrefix + r'"[^\n"\\]*(?:\\.[^\n"\\]*)*' +
                group('"', r'\\\r?\n'))
PseudoExtras = group(r'\\\r?\n|\Z', Comment, Triple)
PseudoToken = Whitespace + group(PseudoExtras, Number, Funny, ContStr, Name)

# For a given string prefix plus quotes, endpats maps it to a regex
#  to match the remainder of that string. _prefix can be empty, for
#  a normal single or triple quoted string (with no prefix).
endpats = {}
for _prefix in _all_string_prefixes():
    endpats[_prefix + "'"] = Single
    endpats[_prefix + '"'] = Double
    endpats[_prefix + "'''"] = Single3
    endpats[_prefix + '"""'] = Double3
del _prefix

# A set of all of the single and triple quoted string prefixes,
#  including the opening quotes.
single_quoted = set()
triple_quoted = set()
for t in _all_string_prefixes():
    for u in (t + '"', t + "'"):
        single_quoted.add(u)
    for u in (t + '"""', t + "'''"):
        triple_quoted.add(u)
del t, u

tabsize = 8

class TokenError(Exception): pass


class StopTokenizing(Exception): pass

class Untokenizer:

    def __init__(self):
        self.tokens = []
        self.prev_row = 1
        self.prev_col = 0
        self.prev_type = None
        self.prev_line = ""
        self.encoding = None

    def add_whitespace(self, start):
        row, col = start
        if row < self.prev_row or row == self.prev_row and col < self.prev_col:
            raise ValueError("start ({},{}) precedes previous end ({},{})"
                             .format(row, col, self.prev_row, self.prev_col))
        self.add_backslash_continuation(start)
        col_offset = col - self.prev_col
        if col_offset:
            self.tokens.append(" " * col_offset)

    def add_backslash_continuation(self, start):
        """Add backslash continuation characters if the row has increased
        without encountering a newline token.

        This also inserts the correct amount of whitespace before the backslash.
        """
        row = start[0]
        row_offset = row - self.prev_row
        if row_offset == 0:
            return

        newline = '\r\n' if self.prev_line.endswith('\r\n') else '\n'
        line = self.prev_line.rstrip('\\\r\n')
        ws = ''.join(_itertools.takewhile(str.isspace, reversed(line)))
        self.tokens.append(ws + f"\\{newline}" * row_offset)
        self.prev_col = 0

    def escape_brackets(self, token):
        characters = []
        consume_until_next_bracket = False
        for character in token:
            if character == "}":
                if consume_until_next_bracket:
                    consume_until_next_bracket = False
                else:
                    characters.append(character)
            if character == "{":
                n_backslashes = sum(
                    1 for char in _itertools.takewhile(
                        "\\".__eq__,
                        characters[-2::-1]
                    )
                )
                if n_backslashes % 2 == 0 or characters[-1] != "N":
                    characters.append(character)
                else:
                    consume_until_next_bracket = True
            characters.append(character)
        return "".join(characters)

    def untokenize(self, iterable):
        it = iter(iterable)
        indents = []
        startline = False
        for t in it:
            if len(t) == 2:
                self.compat(t, it)
                break
            tok_type, token, start, end, line = t
            if tok_type == ENCODING:
                self.encoding = token
                continue
            if tok_type == ENDMARKER:
                break
            if tok_type == INDENT:
                indents.append(token)
                continue
            elif tok_type == DEDENT:
                indents.pop()
                self.prev_row, self.prev_col = end
                continue
            elif tok_type in (NEWLINE, NL):
                startline = True
            elif startline and indents:
                indent = indents[-1]
                if start[1] >= len(indent):
                    self.tokens.append(indent)
                    self.prev_col = len(indent)
                startline = False
            elif tok_type == FSTRING_MIDDLE:
                if '{' in token or '}' in token:
                    token = self.escape_brackets(token)
                    last_line = token.splitlines()[-1]
                    end_line, end_col = end
                    extra_chars = last_line.count("{{") + last_line.count("}}")
                    end = (end_line, end_col + extra_chars)

            self.add_whitespace(start)
            self.tokens.append(token)
            self.prev_row, self.prev_col = end
            if tok_type in (NEWLINE, NL):
                self.prev_row += 1
                self.prev_col = 0
            self.prev_type = tok_type
            self.prev_line = line
        return "".join(self.tokens)

    def compat(self, token, iterable):
        indents = []
        toks_append = self.tokens.append
        startline = token[0] in (NEWLINE, NL)
        prevstring = False
        in_fstring = 0

        for tok in _itertools.chain([token], iterable):
            toknum, tokval = tok[:2]
            if toknum == ENCODING:
                self.encoding = tokval
                continue

            if toknum in (NAME, NUMBER):
                tokval += ' '

            # Insert a space between two consecutive strings
            if toknum == STRING:
                if prevstring:
                    tokval = ' ' + tokval
                prevstring = True
            else:
                prevstring = False

            if toknum == FSTRING_START:
                in_fstring += 1
            elif toknum == FSTRING_END:
                in_fstring -= 1
            if toknum == INDENT:
                indents.append(tokval)
                continue
            elif toknum == DEDENT:
                indents.pop()
                continue
            elif toknum in (NEWLINE, NL):
                startline = True
            elif startline and indents:
                toks_append(indents[-1])
                startline = False
            elif toknum == FSTRING_MIDDLE:
                tokval = self.escape_brackets(tokval)

            # Insert a space between two consecutive brackets if we are in an f-string
            if tokval in {"{", "}"} and self.tokens and self.tokens[-1] == tokval and in_fstring:
                tokval = ' ' + tokval

            # Insert a space between two consecutive f-strings
            if toknum in (STRING, FSTRING_START) and self.prev_type in (STRING, FSTRING_END):
                self.tokens.append(" ")

            toks_append(tokval)
            self.prev_type = toknum


def untokenize(iterable):
    """Transform tokens back into Python source code.
    It returns a bytes object, encoded using the ENCODING
    token, which is the first token sequence output by tokenize.

    Each element returned by the iterable must be a token sequence
    with at least two elements, a token number and token value.  If
    only two tokens are passed, the resulting output is poor.

    The result is guaranteed to tokenize back to match the input so
    that the conversion is lossless and round-trips are assured.
    The guarantee applies only to the token type and token string as
    the spacing between tokens (column positions) may change.
    """
    ut = Untokenizer()
    out = ut.untokenize(iterable)
    if ut.encoding is not None:
        out = out.encode(ut.encoding)
    return out


def _get_normal_name(orig_enc):
    """Imitates get_normal_name in tokenizer.c."""
    # Only care about the first 12 characters.
    enc = orig_enc[:12].lower().replace("_", "-")
    if enc == "utf-8" or enc.startswith("utf-8-"):
        return "utf-8"
    if enc in ("latin-1", "iso-8859-1", "iso-latin-1") or \
       enc.startswith(("latin-1-", "iso-8859-1-", "iso-latin-1-")):
        return "iso-8859-1"
    return orig_enc

def detect_encoding(readline):
    """
    The detect_encoding() function is used to detect the encoding that should
    be used to decode a Python source file.  It requires one argument, readline,
    in the same way as the tokenize() generator.

    It will call readline a maximum of twice, and return the encoding used
    (as a string) and a list of any lines (left as bytes) it has read in.

    It detects the encoding from the presence of a utf-8 bom or an encoding
    cookie as specified in pep-0263.  If both a bom and a cookie are present,
    but disagree, a SyntaxError will be raised.  If the encoding cookie is an
    invalid charset, raise a SyntaxError.  Note that if a utf-8 bom is found,
    'utf-8-sig' is returned.

    If no encoding is specified, then the default of 'utf-8' will be returned.
    """
    try:
        filename = readline.__self__.name
    except AttributeError:
        filename = None
    bom_found = False
    encoding = None
    default = 'utf-8'
    def read_or_stop():
        try:
            return readline()
        except StopIteration:
            return b''

    def find_cookie(line):
        try:
            # Decode as UTF-8. Either the line is an encoding declaration,
            # in which case it should be pure ASCII, or it must be UTF-8
            # per default encoding.
            line_string = line.decode('utf-8')
        except UnicodeDecodeError:
            msg = "invalid or missing encoding declaration"
            if filename is not None:
                msg = '{} for {!r}'.format(msg, filename)
            raise SyntaxError(msg)

        match = cookie_re.match(line_string)
        if not match:
            return None
        encoding = _get_normal_name(match.group(1))
        try:
            codec = lookup(encoding)
        except LookupError:
            # This behaviour mimics the Python interpreter
            if filename is None:
                msg = "unknown encoding: " + encoding
            else:
                msg = "unknown encoding for {!r}: {}".format(filename,
                        encoding)
            raise SyntaxError(msg)

        if bom_found:
            if encoding != 'utf-8':
                # This behaviour mimics the Python interpreter
                if filename is None:
                    msg = 'encoding problem: utf-8'
                else:
                    msg = 'encoding problem for {!r}: utf-8'.format(filename)
                raise SyntaxError(msg)
            encoding += '-sig'
        return encoding

    first = read_or_stop()
    if first.startswith(BOM_UTF8):
        bom_found = True
        first = first[3:]
        default = 'utf-8-sig'
    if not first:
        return default, []

    encoding = find_cookie(first)
    if encoding:
        return encoding, [first]
    if not blank_re.match(first):
        return default, [first]

    second = read_or_stop()
    if not second:
        return default, [first]

    encoding = find_cookie(second)
    if encoding:
        return encoding, [first, second]

    return default, [first, second]


def open(filename):
    """Open a file in read only mode using the encoding detected by
    detect_encoding().
    """
    buffer = _builtin_open(filename, 'rb')
    try:
        encoding, lines = detect_encoding(buffer.readline)
        buffer.seek(0)
        text = TextIOWrapper(buffer, encoding, line_buffering=True)
        text.mode = 'r'
        return text
    except:
        buffer.close()
        raise

def tokenize(readline):
    """
    The tokenize() generator requires one argument, readline, which
    must be a callable object which provides the same interface as the
    readline() method of built-in file objects.  Each call to the function
    should return one line of input as bytes.  Alternatively, readline
    can be a callable function terminating with StopIteration:
        readline = open(myfile, 'rb').__next__  # Example of alternate readline

    The generator produces 5-tuples with these members: the token type; the
    token string; a 2-tuple (srow, scol) of ints specifying the row and
    column where the token begins in the source; a 2-tuple (erow, ecol) of
    ints specifying the row and column where the token ends in the source;
    and the line on which the token was found.  The line passed is the
    physical line.

    The first token sequence will always be an ENCODING token
    which tells you which encoding was used to decode the bytes stream.
    """
    encoding, consumed = detect_encoding(readline)
    rl_gen = _itertools.chain(consumed, iter(readline, b""))
    if encoding is not None:
        if encoding == "utf-8-sig":
            # BOM will already have been stripped.
            encoding = "utf-8"
        yield TokenInfo(ENCODING, encoding, (0, 0), (0, 0), '')
    yield from _generate_tokens_from_c_tokenizer(rl_gen.__next__, encoding, extra_tokens=True)

def generate_tokens(readline):
    """Tokenize a source reading Python code as unicode strings.

    This has the same API as tokenize(), except that it expects the *readline*
    callable to return str objects instead of bytes.
    """
    return _generate_tokens_from_c_tokenizer(readline, extra_tokens=True)

def main():
    import argparse

    # Helper error handling routines
    def perror(message):
        sys.stderr.write(message)
        sys.stderr.write('\n')

    def error(message, filename=None, location=None):
        if location:
            args = (filename,) + location + (message,)
            perror("%s:%d:%d: error: %s" % args)
        elif filename:
            perror("%s: error: %s" % (filename, message))
        else:
            perror("error: %s" % message)
        sys.exit(1)

    # Parse the arguments and options
    parser = argparse.ArgumentParser(prog='python -m tokenize')
    parser.add_argument(dest='filename', nargs='?',
                        metavar='filename.py',
                        help='the file to tokenize; defaults to stdin')
    parser.add_argument('-e', '--exact', dest='exact', action='store_true',
                        help='display token names using the exact type')
    args = parser.parse_args()

    try:
        # Tokenize the input
        if args.filename:
            filename = args.filename
            with _builtin_open(filename, 'rb') as f:
                tokens = list(tokenize(f.readline))
        else:
            filename = "<stdin>"
            tokens = _generate_tokens_from_c_tokenizer(
                sys.stdin.readline, extra_tokens=True)


        # Output the tokenization
        for token in tokens:
            token_type = token.type
            if args.exact:
                token_type = token.exact_type
            token_range = "%d,%d-%d,%d:" % (token.start + token.end)
            print("%-20s%-15s%-15r" %
                  (token_range, tok_name[token_type], token.string))
    except IndentationError as err:
        line, column = err.args[1][1:3]
        error(err.args[0], filename, (line, column))
    except TokenError as err:
        line, column = err.args[1]
        error(err.args[0], filename, (line, column))
    except SyntaxError as err:
        error(err, filename)
    except OSError as err:
        error(err)
    except KeyboardInterrupt:
        print("interrupted\n")
    except Exception as err:
        perror("unexpected error: %s" % err)
        raise

def _transform_msg(msg):
    """Transform error messages from the C tokenizer into the Python tokenize

    The C tokenizer is more picky than the Python one, so we need to massage
    the error messages a bit for backwards compatibility.
    """
    if "unterminated triple-quoted string literal" in msg:
        return "EOF in multi-line string"
    return msg

def _generate_tokens_from_c_tokenizer(source, encoding=None, extra_tokens=False):
    """Tokenize a source; uses C extension when available, pure-Python fallback otherwise."""
    if not _HAS_C_TOKENIZER:
        yield from _py_tokenize(source, encoding=encoding, extra_tokens=extra_tokens)
        return
    if encoding is None:
        it = _tokenize.TokenizerIter(source, extra_tokens=extra_tokens)
    else:
        it = _tokenize.TokenizerIter(source, encoding=encoding, extra_tokens=extra_tokens)
    try:
        for info in it:
            yield TokenInfo._make(info)
    except SyntaxError as e:
        if type(e) != SyntaxError:
            raise e from None
        msg = _transform_msg(e.msg)
        raise TokenError(msg, (e.lineno, e.offset)) from None


def _tab_error(lnum, line):
    """The TabError CPython's tokenizer raises for ambiguous indentation.

    tabnanny re-raises this one's .msg and .text verbatim, so both the
    wording and the newline-stripped line matter.
    """
    text = line.rstrip('\r\n')
    return TabError("inconsistent use of tabs and spaces in indentation",
                    ("<string>", lnum, len(text) + 1, text))


# PEP 701: an f-string start is recognised positionally, not from the token
# the pseudo-regex happened to produce -- that regex cannot know where an
# f-string ends (nested same-quote strings are legal), and for a string it
# cannot terminate it falls back to matching a bare NAME.
_FStringStart = r"([fFbBrRuU]*)(\'\'\'|\"\"\"|\'|\")"


def _py_tokenize(source, encoding=None, extra_tokens=False):
    """Pure-Python tokenizer used on PyPy when the _tokenize C extension is unavailable.
    Implements the CPython 3.11 generate_tokens() algorithm using the regex patterns
    already defined in this module.
    """
    lnum = parenlev = continued = bs_continued = 0
    contstr = ''
    needcont = 0
    contline = None
    indents = [0]
    altindents = [0]
    strstart = endprog = None
    last_line = line = ''
    # PEP 701: stack of open f-strings.  Each entry tracks the quote, rawness,
    # a mode stack ('lit' at the bottom, then an 'expr'/'spec' entry per open
    # replacement field), and the FSTRING_MIDDLE accumulator.
    fstack = []

    while True:
        try:
            # capture the previous line before it is overwritten: readline
            # signals end of input with an empty string, so `line` itself is
            # always clobbered at the end of the loop.
            last_line = line
            line = source()
        except StopIteration:
            line = b'' if encoding else ''
        if encoding is not None and isinstance(line, bytes):
            line = line.decode(encoding, 'replace')
        lnum += 1
        pos, max_ = 0, len(line)

        if continued:                               # inside multi-line string
            if not line:
                raise TokenError("EOF in multi-line statement", (lnum, 0))
            endmatch = endprog.match(line, pos)
            if endmatch:
                pos = end = endmatch.end(0)
                yield TokenInfo(STRING, contstr + line[:end],
                       strstart, (lnum, end), contline + line)
                contstr = ''; needcont = 0; contline = None; continued = 0
            elif needcont and line[-2:] != '\\\n' and line[-3:] != '\\\r\n':
                yield TokenInfo(ERRORTOKEN, contstr + line,
                           strstart, (lnum, len(line)), contline)
                contstr = ''; contline = None; continued = 0
                continue
            else:
                contstr += line; contline += line
                continue
        elif parenlev == 0 and not bs_continued and not fstack:  # new logical statement
            if not line:
                break
            # 'altcolumn' measures the same indentation with a tab stop of 1.
            # CPython's tokenizer carries both and calls the indentation
            # ambiguous whenever the two disagree about how this line relates
            # to the enclosing block -- that is what raises TabError.
            column = altcolumn = 0
            while pos < max_:
                c = line[pos]
                if c == ' ':      column += 1; altcolumn += 1
                elif c == '\t':
                    column = (column // tabsize + 1) * tabsize
                    altcolumn += 1
                elif c == '\f':   column = altcolumn = 0
                else:             break
                pos += 1
            if pos == max_:
                # Only reachable for a final line that is all whitespace and
                # has no newline ('a\n '): a line ending in \n leaves pos on
                # the \n and is handled just below.  3.12 still reports the
                # implicit line ending, at the end of that whitespace, and
                # still counts the line, so ENDMARKER lands on the next one.
                yield TokenInfo(NL, '', (lnum, pos), (lnum, pos + 1), line)
                lnum += 1
                break
            if line[pos] in '#\r\n':
                if line[pos] == '#':
                    comment = line[pos:].rstrip('\r\n')
                    if extra_tokens:
                        yield TokenInfo(COMMENT, comment,
                               (lnum, pos), (lnum, pos + len(comment)), line)
                    pos += len(comment)
                # When the line has no trailing newline the NL is still a
                # one-column token, so do not let len(line) collapse it to
                # zero width.
                yield TokenInfo(NL, line[pos:], (lnum, pos),
                                (lnum, max(len(line), pos + 1)), line)
                continue
            if column > indents[-1]:
                if altcolumn <= altindents[-1]:
                    raise _tab_error(lnum, line)
                indents.append(column)
                altindents.append(altcolumn)
                yield TokenInfo(INDENT, line[:pos], (lnum, 0), (lnum, pos), line)
            while column < indents[-1]:
                if column not in indents:
                    # 3.12 raises this from the C tokenizer, which names the
                    # source "<string>" (tabnanny prints that verbatim),
                    # strips the newline from .text, and puts .offset one
                    # past the end of the stripped line.
                    _text = line.rstrip('\r\n')
                    raise IndentationError(
                        "unindent does not match any outer indentation level",
                        ("<string>", lnum, len(_text) + 1, _text))
                indents.pop()
                altindents.pop()
                yield TokenInfo(DEDENT, '', (lnum, pos), (lnum, pos), line)
            # Having settled on a block, the tab-1 measurement has to agree
            # that this line sits at that level too.
            if column == indents[-1] and altcolumn != altindents[-1]:
                raise _tab_error(lnum, line)
        else:
            if not line:
                raise TokenError("EOF in multi-line statement", (lnum, 0))

        bs_continued = 0
        while pos < max_:
            if fstack:
                ctx = fstack[-1]
                top = ctx['modes'][-1]
                if top['m'] != 'expr':
                    # -- scanning literal text (or a format spec, which only
                    #    differs in what terminates it and in always flushing
                    #    a MIDDLE, even an empty one, before the closing '}')
                    quote = ctx['quote']
                    in_spec = top['m'] == 'spec'
                    if ctx['bufstart'] is None:
                        ctx['bufstart'] = (lnum, pos)
                    sp = pos
                    terminated = False
                    while sp < max_:
                        c = line[sp]
                        if c == '\\':
                            # A backslash never terminates anything: it takes
                            # the next character along (keeping a quote from
                            # closing the string, raw mode included), and in
                            # non-raw strings \N{...} is a named escape whose
                            # braces are not replacement fields.
                            if not ctx['raw'] and line.startswith('\\N{', sp):
                                nend = line.find('}', sp + 3)
                                if nend >= 0:
                                    # the named escape's closing brace also
                                    # closes the MIDDLE: following text opens
                                    # a fresh one, exactly like after '{{'
                                    ctx['buf'] += line[sp:nend + 1]
                                    ln = (ctx['bufline'] + line
                                          if ctx['bufline'] is not None else line)
                                    yield TokenInfo(FSTRING_MIDDLE, ctx['buf'],
                                           ctx['bufstart'], (lnum, nend + 1), ln)
                                    ctx['buf'] = ''
                                    ctx['bufstart'] = (lnum, nend + 1)
                                    ctx['bufline'] = None
                                    sp = nend + 1
                                    continue
                            if sp + 1 < max_ and line[sp + 1] not in '{}':
                                ctx['buf'] += line[sp:sp + 2]
                                sp += 2
                            else:
                                # a brace is never escapable by backslash --
                                # that is what doubling is for -- so the
                                # backslash stands alone and the brace is
                                # processed normally on the next pass
                                ctx['buf'] += c
                                sp += 1
                            continue
                        if c == quote[0] and line.startswith(quote, sp):
                            if in_spec:
                                raise TokenError(
                                    "f-string: expecting '}'", (lnum, sp))
                            if ctx['buf'] or ctx['bufline'] is not None:
                                ln = (ctx['bufline'] + line
                                      if ctx['bufline'] is not None else line)
                                yield TokenInfo(FSTRING_MIDDLE, ctx['buf'],
                                       ctx['bufstart'], (lnum, sp), ln)
                            yield TokenInfo(FSTRING_END, quote,
                                   (lnum, sp), (lnum, sp + len(quote)), line)
                            pos = sp + len(quote)
                            fstack.pop()
                            if fstack:
                                pctx = fstack[-1]
                                pctx['buf'] = ''
                                pctx['bufstart'] = None
                                pctx['bufline'] = None
                            terminated = True
                            break
                        if c in '{}':
                            doubled = sp + 1 < max_ and line[sp + 1] == c
                            if doubled and not in_spec:
                                # doubled brace in literal text: one brace of
                                # text; the token ends after the first brace
                                # and the second is consumed silently.  Spec
                                # mode has NO doubling: there '}' always
                                # closes the field, and '{{' is a field open
                                # followed by a dict/set display.
                                ctx['buf'] += c
                                ln = (ctx['bufline'] + line
                                      if ctx['bufline'] is not None else line)
                                yield TokenInfo(FSTRING_MIDDLE, ctx['buf'],
                                       ctx['bufstart'], (lnum, sp + 1), ln)
                                ctx['buf'] = ''
                                ctx['bufstart'] = (lnum, sp + 2)
                                ctx['bufline'] = None
                                sp += 2
                                continue
                            if c == '{':
                                if (ctx['buf'] or ctx['bufline'] is not None
                                        or (in_spec and doubled)):
                                    ln = (ctx['bufline'] + line
                                          if ctx['bufline'] is not None else line)
                                    yield TokenInfo(FSTRING_MIDDLE, ctx['buf'],
                                           ctx['bufstart'], (lnum, sp), ln)
                                yield TokenInfo(OP, '{',
                                       (lnum, sp), (lnum, sp + 1), line)
                                ctx['modes'].append({'m': 'expr', 'd': 0})
                                ctx['buf'] = ''
                                ctx['bufstart'] = None
                                ctx['bufline'] = None
                                pos = sp + 1
                                terminated = True
                                break
                            # lone '}'
                            if in_spec:
                                # closes the replacement field; the spec
                                # always contributes a MIDDLE here, empty
                                # included -- except straight after a line
                                # break, where CPython emits none
                                if (ctx['buf'] or ctx['bufline'] is not None
                                        or not top.get('anl')):
                                    ln = (ctx['bufline'] + line
                                          if ctx['bufline'] is not None else line)
                                    yield TokenInfo(FSTRING_MIDDLE, ctx['buf'],
                                           ctx['bufstart'], (lnum, sp), ln)
                                ctx['modes'].pop()
                                yield TokenInfo(OP, '}',
                                       (lnum, sp), (lnum, sp + 1), line)
                                ctx['buf'] = ''
                                ctx['bufstart'] = None
                                ctx['bufline'] = None
                                pos = sp + 1
                                terminated = True
                                break
                            raise TokenError(
                                "f-string: single '}' is not allowed",
                                (lnum, sp))
                        if c in '\r\n' and len(quote) == 1:
                            if in_spec:
                                # 3.12 allows a single-quoted f-string's
                                # format spec to continue on the next line:
                                # the accumulated middle is flushed without
                                # the newline, which becomes an NL token.
                                # (3.13 forbids this; the 3.12 suite relies
                                # on it in test_tokenize's test_string.)
                                if ctx['buf']:
                                    yield TokenInfo(FSTRING_MIDDLE, ctx['buf'],
                                           ctx['bufstart'], (lnum, sp), line)
                                nl = line[sp:]
                                if extra_tokens:
                                    yield TokenInfo(NL, nl, (lnum, sp),
                                           (lnum, sp + len(nl)), line)
                                top['anl'] = True
                                ctx['buf'] = ''
                                ctx['bufstart'] = None
                                ctx['bufline'] = None
                                pos = max_
                                terminated = True
                                break
                            raise TokenError(
                                "unterminated f-string literal", (lnum, sp))
                        ctx['buf'] += c
                        sp += 1
                    if terminated:
                        continue
                    # line exhausted inside a (triple-quoted) f-string
                    ctx['bufline'] = (ctx['bufline'] + line
                                      if ctx['bufline'] is not None else line)
                    pos = max_
                    continue
                # -- inside a replacement field: ordinary tokens, plus the
                #    field bookkeeping for ':', '!' and '}' at depth 0
                wpos = pos
                while wpos < max_ and line[wpos] in ' \t\f':
                    wpos += 1
                c = line[wpos] if wpos < max_ else ''
                if top['d'] == 0 and c in '}:!':
                    if c == '}':
                        ctx['modes'].pop()
                        if ctx['modes'][-1]['m'] == 'spec':
                            # back inside the enclosing spec: a fresh segment
                            # begins, and the empty-middle-on-close rule is
                            # live again
                            ctx['modes'][-1]['anl'] = False
                        yield TokenInfo(OP, '}', (lnum, wpos), (lnum, wpos + 1), line)
                        ctx['buf'] = ''
                        ctx['bufstart'] = None
                        ctx['bufline'] = None
                        pos = wpos + 1
                        continue
                    if c == ':':
                        # the format spec of this same field begins
                        top['m'] = 'spec'
                        yield TokenInfo(OP, ':', (lnum, wpos), (lnum, wpos + 1), line)
                        ctx['buf'] = ''
                        ctx['bufstart'] = None
                        ctx['bufline'] = None
                        pos = wpos + 1
                        continue
                    if c == '!' and not line.startswith('!=', wpos):
                        yield TokenInfo(OP, '!', (lnum, wpos), (lnum, wpos + 1), line)
                        pos = wpos + 1
                        continue
                pseudomatch = _compile(PseudoToken).match(line, pos)
                if not pseudomatch:
                    yield TokenInfo(ERRORTOKEN, line[pos],
                           (lnum, pos), (lnum, pos + 1), line)
                    pos += 1
                    continue
                start, end = pseudomatch.span(1)
                spos, epos, pos = (lnum, start), (lnum, end), end
                if start == end:
                    continue
                token, initial = line[start:end], line[start]
                fsm = (_compile(_FStringStart).match(line, start)
                       if initial in 'fFrRbBuU\'\"' else None)
                if fsm is not None and ('f' in fsm.group(1)
                                        or 'F' in fsm.group(1)):
                    slen = fsm.end() - start
                    yield TokenInfo(FSTRING_START, fsm.group(),
                           spos, (lnum, start + slen), line)
                    fstack.append({'quote': fsm.group(2),
                                   'raw': 'r' in fsm.group(1) or 'R' in fsm.group(1),
                                   'modes': [{'m': 'lit'}],
                                   'buf': '', 'bufstart': None,
                                   'bufline': None})
                    pos = start + slen
                elif initial in '0123456789' or (
                        initial == '.' and token not in ('.', '...')):
                    yield TokenInfo(NUMBER, token, spos, epos, line)
                elif initial in '\r\n':
                    if extra_tokens:
                        yield TokenInfo(NL, token, spos, epos, line)
                elif initial == '#':
                    if extra_tokens:
                        yield TokenInfo(COMMENT, token, spos, epos, line)
                elif token in triple_quoted:
                    endprog = _compile(endpats[token])
                    endmatch = endprog.match(line, pos)
                    if endmatch:
                        pos = endmatch.end(0)
                        yield TokenInfo(STRING, line[start:pos],
                               spos, (lnum, pos), line)
                    else:
                        strstart = (lnum, start)
                        contstr = line[start:]
                        contline = line
                        continued = 1
                        break
                elif (initial in single_quoted or token[:2] in single_quoted
                      or token[:3] in single_quoted):
                    if token[-1] == '\n':
                        strstart = (lnum, start)
                        endprog = _compile(endpats.get(initial) or
                                           endpats.get(token[1]) or
                                           endpats.get(token[2]))
                        contstr = line[start:]
                        needcont = 1
                        contline = line
                        continued = 1
                        break
                    yield TokenInfo(STRING, token, spos, epos, line)
                elif initial.isidentifier():
                    yield TokenInfo(NAME, token, spos, epos, line)
                elif initial == '\\':
                    bs_continued = 1
                    break
                else:
                    if initial in '([{':
                        top['d'] += 1
                    elif initial in ')]}':
                        top['d'] = max(0, top['d'] - 1)
                    yield TokenInfo(OP, token, spos, epos, line)
                continue
            pseudomatch = _compile(PseudoToken).match(line, pos)
            if not pseudomatch:
                yield TokenInfo(ERRORTOKEN, line[pos], (lnum, pos), (lnum, pos+1), line)
                pos += 1
                continue
            start, end = pseudomatch.span(1)
            spos, epos, pos = (lnum, start), (lnum, end), end
            if start == end:
                continue
            token, initial = line[start:end], line[start]

            if initial in '0123456789' or (initial == '.' and token not in ('.', '...')):
                yield TokenInfo(NUMBER, token, spos, epos, line)
            elif initial in '\r\n':
                if parenlev > 0:
                    if extra_tokens:
                        yield TokenInfo(NL, token, spos, epos, line)
                else:
                    yield TokenInfo(NEWLINE, token, spos, epos, line)
            elif initial == '#':
                if extra_tokens:
                    yield TokenInfo(COMMENT, token, spos, epos, line)
            elif (initial in 'fFrRbBuU\'\"'
                  and (fsm := _compile(_FStringStart).match(line, start))
                  and ('f' in fsm.group(1) or 'F' in fsm.group(1))):
                # PEP 701: an f-string is not one STRING token; only its
                # prefix+quote is consumed here, and the fstring machinery
                # above takes over from the next character.  Whatever the
                # pseudo-regex matched (a STRING, or just a NAME when the
                # string does not terminate on this line) is discarded.
                _slen = fsm.end() - start
                yield TokenInfo(FSTRING_START, fsm.group(),
                       spos, (lnum, start + _slen), line)
                fstack.append({'quote': fsm.group(2),
                               'raw': 'r' in fsm.group(1) or 'R' in fsm.group(1),
                               'modes': [{'m': 'lit'}],
                               'buf': '', 'bufstart': None, 'bufline': None})
                pos = start + _slen
            elif token in triple_quoted:
                endprog = _compile(endpats[token])
                endmatch = endprog.match(line, pos)
                if endmatch:
                    pos = endmatch.end(0)
                    yield TokenInfo(STRING, line[start:pos], spos, (lnum, pos), line)
                else:
                    strstart = (lnum, start); contstr = line[start:]
                    contline = line; continued = 1; break
            elif (initial in single_quoted or token[:2] in single_quoted
                  or token[:3] in single_quoted):
                if token[-1] == '\n':
                    strstart = (lnum, start)
                    endprog = _compile(endpats.get(initial) or
                                       endpats.get(token[1]) or
                                       endpats.get(token[2]))
                    contstr = line[start:]; needcont = 1
                    contline = line; continued = 1; break
                else:
                    yield TokenInfo(STRING, token, spos, epos, line)
            elif initial.isidentifier():
                yield TokenInfo(NAME, token, spos, epos, line)
            elif initial == '\\':
                bs_continued = 1; break
            else:
                if initial in '([{':   parenlev += 1
                elif initial in ')]}':
                    # A closing bracket with nothing open is just an OP.
                    # Letting parenlev go negative made everything after it
                    # look bracketed, so '); x' died with TokenError("EOF in
                    # multi-line statement") instead of tokenizing.
                    parenlev = max(0, parenlev - 1)
                yield TokenInfo(OP, token, spos, epos, line)

    # Add an implicit NEWLINE if the input doesn't end in one
    if last_line and last_line[-1] not in '\r\n' and not last_line.strip().startswith("#"):
        # The implicit NEWLINE carries the line it was synthesised for, not ''.
        yield TokenInfo(NEWLINE, '', (lnum - 1, len(last_line)),
                        (lnum - 1, len(last_line) + 1), last_line)
    for _ in indents[1:]:
        yield TokenInfo(DEDENT, '', (lnum, 0), (lnum, 0), '')
    yield TokenInfo(ENDMARKER, '', (lnum, 0), (lnum, 0), '')


if __name__ == "__main__":
    main()
