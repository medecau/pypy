"""Package matrix for third-party test-suite runs against a translated PyPy.

Companion to ``run_thirdparty_tests.py`` -- the third-party analogue of
``stdlib_test_lists.py``.  Where the stdlib file holds three flat lists of
module names, this file holds one ``PACKAGES`` list of structured entries,
because third-party packages install and run their suites heterogeneously
(git clone at a tag vs. tests shipped in the wheel vs. a bespoke runner).

Entry schema (all keys optional except name/tier/kind/source/test_cmd)::

    {
      "name": "requests",           # unique key / display name
      "tier": 4,                    # 1..4, FFI risk tier (see --tiers filter)
      "kind": "pure",               # "pure" | "cext" | "rust" (informational)
      "source": {                   # how to obtain the suite:
          "kind": "git",            #   "git"    -> shallow clone url@ref
          "url": "https://github.com/psf/requests",
          "ref": "v2.32.3",         #   pinned tag/sha (never a moving branch)
      },                            #   "pyargs" -> tests ship in the wheel
      "install": ["."],             # pip install args, run in the checkout
      "test_deps": ["trustme"],     # extra PyPI deps needed only to run the suite
      "no_build_isolation": False,  # pass --no-build-isolation to the install
      "runner": "pytest",           # "pytest" (default) | "script" (own runner)
      "test_cmd": ["-m", "pytest", "tests"],   # argv after the venv python
      "deselect": [],               # pytest --deselect nodeids (per-subtest xfail)
      "ignore": [],                 # pytest --ignore paths
      "status": "expected_pass",    # "expected_pass" | "expected_fail" | "skip"
      "note": "",                   # rationale, esp. for expected_fail / skip
    }

``status`` collapses the stdlib file's three lists into one field:
``expected_pass`` must pass, ``expected_fail`` is tolerated (xfail),
``skip`` is never run.  Because we cannot edit third-party source the way we
add ``@impl_detail`` to stdlib tests, ``deselect``/``ignore`` are the
per-subtest equivalent -- a curated list that keeps a package
``expected_pass`` overall while documenting the specific gaps.

CALIBRATION NOTE: the pins, ``install``/``test_deps`` seeds, and ``status``
values below are best-effort starting points.  The first on-demand CI dispatch
is the calibration pass: triage ``thirdparty-results.json``, fix real bugs at
the correct level, record ``deselect``/``status`` for genuine divergences, and
promote heavy packages from ``expected_fail`` to ``expected_pass`` as they go
green.  Refs that do not resolve show up as ``error`` (clone failed).
"""

PACKAGES = [

    # ------------------------------------------------------------------ #
    # Tier 1 -- meta-tools (unblock everything else; run these first)     #
    # ------------------------------------------------------------------ #
    {
        "name": "pytest",
        "tier": 1, "kind": "pure",
        "source": {"kind": "git", "url": "https://github.com/pytest-dev/pytest",
                   "ref": "8.3.4"},
        "install": ["."],
        "test_deps": ["hypothesis", "xmlschema", "requests"],
        "test_cmd": ["-m", "pytest", "testing", "-q"],
        "status": "expected_pass",
        "note": "The runner everything else uses.",
    },
    {
        "name": "coverage",
        "tier": 1, "kind": "cext",
        "source": {"kind": "git", "url": "https://github.com/nedbat/coveragepy",
                   "ref": "7.6.10"},
        "install": ["."],
        "test_deps": ["flaky", "hypothesis", "pytest-xdist"],
        "test_cmd": ["-m", "pytest", "tests", "-q"],
        "status": "expected_pass",
        "note": "Highest-value: on 3.12 coverage prefers sys.monitoring (PEP 669, "
                "which PyPy defers) and falls back to sys.settrace -- this "
                "validates the fallback the test_monitoring SKIP relies on.",
    },
    {
        "name": "cython",
        "tier": 1, "kind": "cext",
        "source": {"kind": "git", "url": "https://github.com/cython/cython",
                   "ref": "3.0.11"},
        "install": ["."],
        "runner": "script",
        "test_cmd": ["runtests.py", "-j4", "--no-cleanup"],
        "status": "expected_fail",
        "note": "Gatekeeper for the scientific stack; its own runtests.py suite is "
                "huge and slow. Calibrate/scope after first run.",
    },
    {
        "name": "setuptools",
        "tier": 1, "kind": "pure",
        "source": {"kind": "git", "url": "https://github.com/pypa/setuptools",
                   "ref": "v75.3.0"},
        "install": ["."],
        "test_deps": ["jaraco.test", "pytest-xdist", "pytest-timeout", "virtualenv"],
        "test_cmd": ["-m", "pytest", "setuptools/tests", "-q"],
        "status": "expected_pass",
        "note": "Build backend.",
    },
    {
        "name": "build",
        "tier": 1, "kind": "pure",
        "source": {"kind": "git", "url": "https://github.com/pypa/build",
                   "ref": "1.2.2"},
        "install": ["."],
        "test_deps": ["pytest-mock", "pytest-rerunfailures", "wheel"],
        "test_cmd": ["-m", "pytest", "tests", "-q"],
        "status": "expected_pass",
    },
    {
        "name": "wheel",
        "tier": 1, "kind": "pure",
        "source": {"kind": "git", "url": "https://github.com/pypa/wheel",
                   "ref": "0.45.1"},
        "install": ["."],
        "test_cmd": ["-m", "pytest", "tests", "-q"],
        "status": "expected_pass",
    },
    {
        "name": "pip",
        "tier": 1, "kind": "pure",
        "source": {"kind": "git", "url": "https://github.com/pypa/pip",
                   "ref": "24.3.1"},
        "install": ["."],
        "test_deps": ["pytest-xdist", "freezegun", "tomli-w", "werkzeug", "pretend",
                      "installer"],
        "test_cmd": ["-m", "pytest", "tests/unit", "-q"],
        "status": "expected_fail",
        "note": "Full suite needs network/vendoring fixtures; scoped to tests/unit. "
                "Calibrate deselects after first run.",
    },

    # ------------------------------------------------------------------ #
    # Tier 2 -- cpyext C extensions (historical battleground; no graphics)#
    # ------------------------------------------------------------------ #
    {
        "name": "numpy",
        "tier": 2, "kind": "cext",
        "source": {"kind": "git", "url": "https://github.com/numpy/numpy",
                   "ref": "v1.26.4"},
        "install": ["."],
        "test_deps": ["hypothesis", "pytest-xdist"],
        # --pyargs => import the *installed* numpy, not the source tree
        "test_cmd": ["-m", "pytest", "--pyargs", "numpy", "-q"],
        "status": "expected_fail",
        "note": "Canonical cpyext stress test; meson build. Calibrate.",
    },
    {
        "name": "lxml",
        "tier": 2, "kind": "cext",
        "source": {"kind": "git", "url": "https://github.com/lxml/lxml",
                   "ref": "lxml-5.3.0"},
        "install": ["."],
        "test_cmd": ["-m", "pytest", "src/lxml/tests", "-q"],
        "status": "expected_fail",
        "note": "Needs libxml2-dev/libxslt1-dev system headers. Calibrate.",
    },
    {
        "name": "pyyaml",
        "tier": 2, "kind": "cext",
        "source": {"kind": "git", "url": "https://github.com/yaml/pyyaml",
                   "ref": "6.0.2"},
        "install": ["."],
        "test_cmd": ["-m", "pytest", "tests/lib", "-q"],
        "status": "expected_pass",
        "note": "libyaml C path via libyaml-dev; pure-Python fallback otherwise.",
    },
    {
        "name": "markupsafe",
        "tier": 2, "kind": "cext",
        "source": {"kind": "git", "url": "https://github.com/pallets/markupsafe",
                   "ref": "3.0.2"},
        "install": ["."],
        "test_cmd": ["-m", "pytest", "tests", "-q"],
        "status": "expected_pass",
        "note": "C speedups are typically disabled on PyPy (pure path).",
    },
    {
        "name": "greenlet",
        "tier": 2, "kind": "cext",
        "source": {"kind": "git", "url": "https://github.com/python-greenlet/greenlet",
                   "ref": "3.1.1"},
        "install": ["."],
        "test_cmd": ["-m", "pytest", "--pyargs", "greenlet.tests", "-q"],
        "status": "expected_pass",
        "note": "PyPy provides greenlet natively via _continuation; confirm parity.",
    },
    {
        "name": "psycopg2",
        "tier": 2, "kind": "cext",
        "source": {"kind": "git", "url": "https://github.com/psycopg/psycopg2",
                   "ref": "2_9_10"},
        "install": ["."],
        "test_cmd": ["-m", "pytest", "tests", "-q"],
        "status": "expected_fail",
        "note": "Needs libpq-dev to build and a running postgres service for the "
                "suite (DSN via PSYCOPG2_TESTDB* env). Calibrate once service added.",
    },

    # ------------------------------------------------------------------ #
    # Tier 3 -- Rust / PyO3 (modern frontier; needs a Rust toolchain)     #
    # ------------------------------------------------------------------ #
    {
        "name": "pydantic",
        "tier": 3, "kind": "rust",
        "source": {"kind": "git", "url": "https://github.com/pydantic/pydantic",
                   "ref": "v2.10.4"},
        "install": ["."],
        "test_deps": ["dirty-equals", "hypothesis", "pytest-mock", "email-validator",
                      "pytest-examples"],
        "test_cmd": ["-m", "pytest", "tests", "-q"],
        "status": "expected_fail",
        "note": "Pulls pydantic-core (PyO3); no PyPy wheels -> builds from source "
                "via Rust. Calibrate.",
    },
    {
        "name": "cryptography",
        "tier": 3, "kind": "rust",
        "source": {"kind": "git", "url": "https://github.com/pyca/cryptography",
                   "ref": "44.0.0"},
        "install": ["."],
        "test_deps": ["cryptography_vectors", "pretend", "pytest-xdist",
                      "pytest-benchmark"],
        "test_cmd": ["-m", "pytest", "tests", "-q"],
        "status": "expected_fail",
        "note": "Rust + OpenSSL headers (libssl-dev). Calibrate.",
    },
    {
        "name": "bcrypt",
        "tier": 3, "kind": "rust",
        "source": {"kind": "git", "url": "https://github.com/pyca/bcrypt",
                   "ref": "4.2.1"},
        "install": ["."],
        "test_cmd": ["-m", "pytest", "tests", "-q"],
        "status": "expected_fail",
        "note": "Rust (PyO3). Calibrate.",
    },
    {
        "name": "orjson",
        "tier": 3, "kind": "rust",
        "source": {"kind": "git", "url": "https://github.com/ijl/orjson",
                   "ref": "3.10.12"},
        "install": ["."],
        "test_deps": ["numpy", "python-dateutil", "pytz", "pytest-random-order"],
        "test_cmd": ["-m", "pytest", "test", "-q"],
        "status": "expected_fail",
        "note": "Rust + maturin (historically needs a Rust nightly). Calibrate.",
    },

    # ------------------------------------------------------------------ #
    # Tier 4 -- big pure-Python suites + user additions                   #
    # ------------------------------------------------------------------ #
    {
        "name": "django",
        "tier": 4, "kind": "pure",
        "source": {"kind": "git", "url": "https://github.com/django/django",
                   "ref": "5.1.4"},
        "install": ["."],
        "runner": "script",
        "test_cmd": ["tests/runtests.py", "--parallel=1", "--verbosity=1"],
        "status": "expected_pass",
        "note": "Own runner (tests/runtests.py); defaults to the sqlite backend. "
                "Calibrate.",
    },
    {
        "name": "requests",
        "tier": 4, "kind": "pure",
        "source": {"kind": "git", "url": "https://github.com/psf/requests",
                   "ref": "v2.32.3"},
        "install": ["."],
        "test_deps": ["pytest-httpbin", "httpbin", "trustme"],
        "test_cmd": ["-m", "pytest", "tests", "-q"],
        "status": "expected_pass",
        "note": "Deselect network/httpbin-live tests during calibration.",
    },
    {
        "name": "urllib3",
        "tier": 4, "kind": "pure",
        "source": {"kind": "git", "url": "https://github.com/urllib3/urllib3",
                   "ref": "2.3.0"},
        "install": ["."],
        "test_deps": ["trustme", "tornado", "pytest-timeout", "pytest-socket"],
        "test_cmd": ["-m", "pytest", "test", "-q"],
        "status": "expected_pass",
        "note": "Spins up a local test server; deselect true-network tests.",
    },
    {
        "name": "sqlalchemy",
        "tier": 4, "kind": "pure",
        "source": {"kind": "git", "url": "https://github.com/sqlalchemy/sqlalchemy",
                   "ref": "rel_2_0_36"},
        "install": ["."],
        "test_deps": ["pytest-xdist"],
        "test_cmd": ["-m", "pytest", "test", "-q"],
        "status": "expected_pass",
        "note": "C accelerator is disabled on PyPy (pure core). Calibrate.",
    },
    {
        "name": "flask",
        "tier": 4, "kind": "pure",
        "source": {"kind": "git", "url": "https://github.com/pallets/flask",
                   "ref": "3.1.0"},
        "install": ["."],
        "test_deps": ["asgiref"],
        "test_cmd": ["-m", "pytest", "tests", "-q"],
        "status": "expected_pass",
    },
    {
        "name": "jinja2",
        "tier": 4, "kind": "pure",
        "source": {"kind": "git", "url": "https://github.com/pallets/jinja",
                   "ref": "3.1.5"},
        "install": ["."],
        "test_cmd": ["-m", "pytest", "tests", "-q"],
        "status": "expected_pass",
    },
    {
        "name": "werkzeug",
        "tier": 4, "kind": "pure",
        "source": {"kind": "git", "url": "https://github.com/pallets/werkzeug",
                   "ref": "3.1.3"},
        "install": ["."],
        "test_deps": ["watchdog", "cryptography", "ephemeral-port-reserve"],
        "test_cmd": ["-m", "pytest", "tests", "-q"],
        "status": "expected_pass",
    },
    {
        "name": "click",
        "tier": 4, "kind": "pure",
        "source": {"kind": "git", "url": "https://github.com/pallets/click",
                   "ref": "8.1.8"},
        "install": ["."],
        "test_cmd": ["-m", "pytest", "tests", "-q"],
        "status": "expected_pass",
    },
    {
        "name": "attrs",
        "tier": 4, "kind": "pure",
        "source": {"kind": "git", "url": "https://github.com/python-attrs/attrs",
                   "ref": "24.3.0"},
        "install": ["."],
        "test_deps": ["hypothesis", "cloudpickle"],
        "test_cmd": ["-m", "pytest", "tests", "-q"],
        "status": "expected_pass",
    },
    {
        "name": "rich",
        "tier": 4, "kind": "pure",
        "source": {"kind": "git", "url": "https://github.com/Textualize/rich",
                   "ref": "v13.9.4"},
        "install": ["."],
        "test_cmd": ["-m", "pytest", "tests", "-q"],
        "status": "expected_pass",
    },
    {
        "name": "python-dateutil",
        "tier": 4, "kind": "pure",
        "source": {"kind": "git", "url": "https://github.com/dateutil/dateutil",
                   "ref": "2.9.0.post0"},
        "install": ["."],
        "test_deps": ["hypothesis", "freezegun"],
        "test_cmd": ["-m", "pytest", "dateutil/test", "-q"],
        "status": "expected_pass",
    },
    {
        "name": "hypothesis",
        "tier": 4, "kind": "pure",
        "source": {"kind": "git", "url": "https://github.com/HypothesisWorks/hypothesis",
                   "ref": "hypothesis-python-6.122.3"},
        "install": ["./hypothesis-python"],
        "test_deps": ["pytest-xdist"],
        "test_cmd": ["-m", "pytest", "hypothesis-python/tests/cover", "-q"],
        "status": "expected_pass",
        "note": "Package + suite live in the hypothesis-python/ subdir; scoped to "
                "tests/cover.",
    },
    {
        "name": "httpx2",
        "tier": 4, "kind": "pure",
        "source": {"kind": "git", "url": "https://github.com/pydantic/httpx2",
                   "ref": "v2.5.0"},
        "install": [".[http2]"],
        "test_deps": ["pytest-asyncio", "trustme", "typing_extensions"],
        "test_cmd": ["-m", "pytest", "tests", "-q"],
        "status": "expected_pass",
        "note": "httpx successor stewarded by Pydantic Services (Tom Christie, "
                "author). [http2] extra pulls h2 to exercise the HTTP/2 path.",
    },
    {
        "name": "fastapi",
        "tier": 4, "kind": "pure",
        "source": {"kind": "git", "url": "https://github.com/fastapi/fastapi",
                   "ref": "0.115.6"},
        "install": ["."],
        "test_deps": ["pytest-asyncio", "httpx", "trustme", "dirty-equals",
                      "email-validator", "python-multipart", "sqlmodel",
                      "flask", "orjson", "ujson"],
        "test_cmd": ["-m", "pytest", "tests", "-q"],
        "status": "expected_fail",
        "note": "Depends on pydantic (Rust core) + starlette; gated on pydantic "
                "building. Heavy test-dep set. Calibrate.",
    },
    {
        "name": "spacy",
        "tier": 4, "kind": "cext",
        "source": {"kind": "git", "url": "https://github.com/explosion/spaCy",
                   "ref": "v3.8.3"},
        "install": ["."],
        "test_deps": ["pytest-timeout", "hypothesis"],
        "test_cmd": ["-m", "pytest", "spacy/tests", "-q"],
        "status": "expected_fail",
        "note": "Cython stack (thinc/blis/cymem/preshed/murmurhash/srsly) + numpy. "
                "Deselect model-download tests during calibration.",
    },
    {
        "name": "beautifulsoup4",
        "tier": 4, "kind": "pure",
        "source": {"kind": "pyargs"},
        "install": ["beautifulsoup4==4.12.3", "html5lib"],
        "test_cmd": ["-m", "pytest", "--pyargs", "bs4", "-q"],
        "status": "expected_pass",
        "note": "Tests ship in the wheel (bs4.tests); optional lxml/html5lib "
                "parsers -- lxml tests self-skip if lxml is absent.",
    },
]
