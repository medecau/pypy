"""Application-level part of the zlib module."""


class _ZlibDecompressor(object):
    """_ZlibDecompressor(wbits=15, zdict=b'')

    Create a decompressor object for decompressing data incrementally.

    Added in CPython 3.12, where it is implemented in C on top of the same
    zlib primitives as decompressobj().  gzip.py relies on it (through
    _compression.DecompressReader), so it has to exist.  The API is the one
    shared with BZ2Decompressor and LZMADecompressor: unlike decompressobj()
    it buffers unconsumed input itself and reports that through needs_input,
    and a negative max_length means 'no limit' while 0 really does mean
    'return nothing yet'.
    """

    def __init__(self, wbits=15, zdict=b''):
        import zlib
        if zdict:
            self._decompressor = zlib.decompressobj(wbits, zdict)
        else:
            # decompressobj() rejects a non-bytes zdict even when empty,
            # which is what makes _ZlibDecompressor(-15, "notbytes") a
            # TypeError as CPython requires
            self._decompressor = zlib.decompressobj(wbits, bytes(zdict))
        self._input = b''
        self._eof = False
        self._unused_data = b''
        self._needs_input = True

    @property
    def eof(self):
        """True if the end-of-stream marker has been reached."""
        return self._eof

    @property
    def unused_data(self):
        """Data found after the end of the compressed stream."""
        return self._unused_data

    @property
    def needs_input(self):
        """True if more input is needed before more decompressed data can be
        produced."""
        return self._needs_input

    def decompress(self, data, max_length=-1):
        """Decompress *data*, returning uncompressed data as bytes.

        If *max_length* is nonnegative, returns at most *max_length* bytes of
        decompressed data.  If this limit is reached and further output can be
        produced, *needs_input* will be set to False.  In this case, the next
        call to *decompress()* may provide *data* as b'' to obtain more of the
        output.
        """
        if self._eof:
            raise EOFError("End of stream already reached")
        data = bytes(data)
        if self._input:
            data = self._input + data
            self._input = b''
        if max_length == 0:
            # zlib's decompressobj() spells 'unlimited' as 0, so this case
            # can never be handed to it; just hold on to the input.
            self._input = data
            self._needs_input = not data
            return b''
        if max_length < 0:
            limit = 0            # unlimited, in decompressobj()'s spelling
        else:
            limit = max_length
        result = self._decompressor.decompress(data, limit)
        if self._decompressor.eof:
            self._eof = True
            self._unused_data = self._decompressor.unused_data
            self._input = b''
            self._needs_input = False
        else:
            self._input = self._decompressor.unconsumed_tail
            self._needs_input = not self._input
        return result

    def __reduce__(self):
        raise TypeError("cannot pickle %r object" % (type(self).__name__,))
