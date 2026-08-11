from pypy.interpreter.astcompiler import ast

from rpython.rlib.objectmodel import specialize, we_are_translated

@specialize.arg(0)
def build(cls, *args):
    token = args[-1]
    newargs = args[:-1] + (token.lineno, token.column,
        token.end_lineno, token.end_column)
    return cls(*newargs)

def add_constant_string(astbuilder, joined_pieces, constant):
    space = astbuilder.space
    is_unicode = space.isinstance_w(constant.value, space.w_unicode)
    # Implement implicit string concatenation.
    if joined_pieces:
        prev = joined_pieces[-1]
        if isinstance(prev, ast.Constant):
            if is_unicode is space.isinstance_w(prev.value, space.w_unicode):
                w_string = space.add(prev.value, constant.value)
                start_lineno = joined_pieces[-1].lineno
                start_column = joined_pieces[-1].col_offset
                joined_pieces[-1] = ast.Constant(w_string, constant.kind,
                    start_lineno, start_column, constant.end_lineno, constant.end_col_offset)
                return
    joined_pieces.append(constant)

def _debug_check_fstring_pieces(space, joined_pieces):
    # TODO: Remove this
    for piece in joined_pieces:
        assert not isinstance(piece, ast.Constant) or space.is_true(piece.value)

def concatenate_strings(astbuilder, nodes):
    space = astbuilder.space
    # encoding = astbuilder.compile_info.encoding
    joined_pieces = []
    fmode = False
    for i in range(len(nodes)):
        node = nodes[i]
        if isinstance(node, ast.Constant):
            add_constant_string(astbuilder, joined_pieces, node)
        else:
            assert isinstance(node, ast.JoinedStr)
            fmode = True
            for piece in node.values:
                if isinstance(piece, ast.Constant):
                    add_constant_string(astbuilder, joined_pieces, piece)
                elif isinstance(piece, ast.FormattedValue):
                    joined_pieces.append(piece)
                else:
                    raise AssertionError("unexpected node type %s" % (type(piece),))


    if not fmode and len(joined_pieces) == 1:   # <= the common path
        return joined_pieces[0]   # ast.Constant or FormattedValue

    if fmode:
        # An f-string's JoinedStr carries no empty pieces: "f'{1}' ''" is
        # just the formatted value, as is "'' f'{1}'".  add_constant_string
        # above can only merge an empty literal into a neighbouring
        # Constant, so drop what it had to append instead.  Only str
        # constants: an empty bytes literal still has to reach the
        # bytes-and-nonbytes check below.
        pieces = []
        for node in joined_pieces:
            if (isinstance(node, ast.Constant) and
                    space.isinstance_w(node.value, space.w_unicode) and
                    not space.is_true(node.value)):
                continue
            pieces.append(node)
        joined_pieces = pieces

    # with more than one piece, it is a combination of ast.Constant[str]
    # and FormattedValue pieces --- if there is a bytes value, then we got
    # an invalid mixture of bytes and unicode literals
    for node in joined_pieces:
        if isinstance(node, ast.Constant) and space.isinstance_w(node.value, space.w_bytes):
            astbuilder.raise_syntax_error_known_location(
                "cannot mix bytes and nonbytes literals",
                node)
    assert fmode
    if not we_are_translated():
        _debug_check_fstring_pieces(space, joined_pieces)
    result = ast.JoinedStr(
        joined_pieces,
        lineno=nodes[0].lineno,
        col_offset=nodes[0].col_offset,
        end_lineno=nodes[-1].end_lineno,
        end_col_offset=nodes[-1].end_col_offset,
    )
    # NB: no check_version here.  CPython does not gate f-strings on
    # feature_version -- ast.parse('f"{a}"', feature_version=(3, 4)) is
    # accepted there -- while it does gate underscored numeric literals,
    # which baserpypeg still checks.  We gated both, so test_type_comments'
    # test_fstring failed: it parses an f-string at every feature_version
    # from the lowest upwards and expects all of them to succeed.
    return result
