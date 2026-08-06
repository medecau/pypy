"""_sha2 compatibility module.

CPython 3.12 merged the _sha256 and _sha512 C accelerator modules into a
single _sha2 module (gh-101148), and hashlib.py/random.py import it by that
name.  PyPy keeps its pure-Python implementations in _sha256.py/_sha512.py;
re-export them under the 3.12 module layout.
"""

from _sha256 import sha224, sha256
from _sha512 import sha384, sha512

__all__ = ["sha224", "sha256", "sha384", "sha512"]
