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
      "install": ["."],             # pip install args, run in the checkout --
                                    #   local extras like ".[test]" go HERE
      "test_deps": ["trustme"],     # extra PyPI deps needed only to run the
                                    #   suite; runs with a neutral cwd, so no
                                    #   relative paths / local extras here
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
        # [dev] is upstream's own test-deps extra (attrs, hypothesis, xmlschema,
        # requests, ...); testing/test_assertion.py imports attr unconditionally
        "install": [".[dev]"],
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
        # repo-root test-requirements.txt; setuptools<60 intentionally
        # downgrades the bootstrap's newer setuptools for ext-module builds
        "test_deps": ["numpy<2", "coverage", "pycodestyle", "setuptools<60"],
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
        # [test] is upstream's full test extra (jaraco.*, filelock, virtualenv,
        # build[virtualenv], ini2toml, pytest-subprocess, ...)
        "install": [".[test]"],
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
        # filelock: unconditional import in tests/test_integration.py (the
        # network-hitting tests themselves are gated behind --run-integration)
        "test_deps": ["pytest-mock", "pytest-rerunfailures", "wheel", "filelock"],
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
        # mirrors pip's own tests/requirements.txt; scripttest is imported by
        # tests/lib/__init__.py so nearly all of tests/unit needs it
        "test_deps": ["cryptography", "freezegun", "installer", "pytest-cov",
                      "pytest-rerunfailures", "pytest-xdist", "scripttest",
                      "virtualenv", "werkzeug", "tomli-w", "proxy.py"],
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
        # sdist, NOT a git clone: the harness clones --depth 1 without
        # submodules, and numpy@v1.26.4 hard-requires its vendored-meson /
        # x86-simd-sort / svml submodules to configure. The PyPI sdist bundles
        # all three, so build from it instead.
        "source": {"kind": "pyargs"},
        "install": ["--no-binary", ":all:", "numpy==1.26.4"],
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
        # cssselect un-skips test_css.py (import-guarded)
        "test_deps": ["cssselect"],
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
        # at 6.0.2 the suite lives in legacy_tests/ (tests/lib is gone); its
        # conftest drives a bespoke collector over legacy_tests/data/*
        "test_cmd": ["-m", "pytest", "legacy_tests", "-q"],
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
        "status": "skip",
        "note": "Structurally cannot run on PyPy: upstream setup.py skips the "
                "_greenlet C ext on PyPy but __init__.py imports it "
                "unconditionally, and PyPy's own lib_pypy/greenlet.py shim "
                "(over _continuation) shadows the install anyway -- 100% "
                "collection failure, not xfailable subtests. Parity is covered "
                "by extra_tests/test_greenlet_*.py instead.",
    },
    {
        "name": "psycopg2",
        "tier": 2, "kind": "cext",
        # dot-separated tags from 2.9.6 on (underscore style ended at 2_9_5)
        "source": {"kind": "git", "url": "https://github.com/psycopg/psycopg2",
                   "ref": "2.9.10"},
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
        # pytest-benchmark is load-bearing: pyproject addopts pass --benchmark-*
        # flags, so without the plugin pytest dies before collecting anything;
        # jsonschema/pytz are module-scope imports in conftest.py / test files
        "test_deps": ["dirty-equals", "pytest-mock", "email-validator",
                      "pytest-examples", "pytest-benchmark", "jsonschema",
                      "pytz"],
        "test_cmd": ["-m", "pytest", "tests", "-q"],
        "status": "expected_fail",
        "note": "Pulls pydantic-core 2.27.2 (PyO3 0.22); PyPy wheels exist only "
                "for pp39/pp310, no pp312 -> builds the sdist with stable Rust. "
                "Calibrate.",
    },
    {
        "name": "cryptography",
        "tier": 3, "kind": "rust",
        "source": {"kind": "git", "url": "https://github.com/pyca/cryptography",
                   "ref": "44.0.0"},
        # ./vectors installs the in-repo cryptography_vectors at the exact
        # matching version (upstream pins ==44.0.0; PyPI's latest is far newer)
        "install": [".", "./vectors"],
        "test_deps": ["pretend", "pytest-xdist", "pytest-benchmark", "certifi"],
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
        # psutil/faker un-skip test_memory.py/test_fake.py (guarded imports)
        "test_deps": ["numpy", "python-dateutil", "pytz", "psutil", "faker"],
        "test_cmd": ["-m", "pytest", "test", "-q"],
        "status": "expected_fail",
        "note": "Rust + maturin. Official wheels use nightly for opt-in SIMD "
                "features, but default features build on stable Rust (>=1.72), "
                "just without those fast paths. Calibrate.",
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
        # parallel=4 to fit the CI timeout; serial exceeded 1h
        "test_cmd": ["tests/runtests.py", "--parallel=4", "--verbosity=1"],
        "timeout": 5400,
        "status": "expected_pass",
        "note": "Own runner (tests/runtests.py); defaults to the sqlite backend. "
                "Feature-gated tests skip cleanly without the optional deps in "
                "tests/requirements/py3.txt (Pillow, argon2, redis, ...) -- "
                "expect skips, not failures, for those. Calibrate.",
    },
    {
        "name": "requests",
        "tier": 4, "kind": "pure",
        "source": {"kind": "git", "url": "https://github.com/psf/requests",
                   "ref": "v2.32.3"},
        "install": ["."],
        # pytest-httpbin pinned ==2.0.0 to match upstream setup.py exactly;
        # PySocks gates the SOCKS proxy tests
        "test_deps": ["pytest-httpbin==2.0.0", "httpbin", "trustme",
                      "pytest-mock", "pytest-xdist", "PySocks"],
        "test_cmd": ["-m", "pytest", "tests", "-q"],
        "deselect": ["tests/test_requests.py::TestPreparingURLs::"
                     "test_different_connection_pool_for_mtls_settings"],
        "status": "expected_pass",
        "note": "589/590 green on first calibrated run; the deselected test "
                "needs a live mTLS pool.",
    },
    {
        "name": "urllib3",
        "tier": 4, "kind": "pure",
        "source": {"kind": "git", "url": "https://github.com/urllib3/urllib3",
                   "ref": "2.3.0"},
        "install": ["."],
        # 2.3.0's dummyserver is hypercorn/trio/quart-based (tornado is gone);
        # upstream dev-requirements pins git forks of Quart/hypercorn -- the
        # PyPI versions below may need deselects for some with_dummyserver tests
        "test_deps": ["trustme", "pytest-timeout", "pytest-socket", "h2",
                      "pyOpenSSL", "cryptography", "trio", "quart", "quart-trio",
                      "hypercorn", "httpx"],
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
        "note": "C accelerator is disabled on PyPy (pure core). pytest config "
                "auto-loads from pyproject.toml [tool.pytest.ini_options] at "
                "the checkout root. Calibrate.",
    },
    {
        "name": "flask",
        "tier": 4, "kind": "pure",
        "source": {"kind": "git", "url": "https://github.com/pallets/flask",
                   "ref": "3.1.0"},
        "install": ["."],
        "test_deps": ["asgiref", "python-dotenv"],
        "test_cmd": ["-m", "pytest", "tests", "-q"],
        "status": "expected_pass",
    },
    {
        "name": "jinja2",
        "tier": 4, "kind": "pure",
        "source": {"kind": "git", "url": "https://github.com/pallets/jinja",
                   "ref": "3.1.5"},
        "install": ["."],
        "test_deps": ["trio"],
        "test_cmd": ["-m", "pytest", "tests", "-q"],
        "status": "expected_pass",
    },
    {
        "name": "werkzeug",
        "tier": 4, "kind": "pure",
        "source": {"kind": "git", "url": "https://github.com/pallets/werkzeug",
                   "ref": "3.1.3"},
        "install": ["."],
        "test_deps": ["watchdog", "cryptography", "ephemeral-port-reserve",
                      "pytest-timeout"],
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
        # the project's own "tests" extra covers hypothesis/cloudpickle/pympler/
        # pytest-xdist
        "install": [".[tests]"],
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
        # src-layout at this tag: tests live in top-level tests/, not inside
        # the package
        "test_cmd": ["-m", "pytest", "tests", "-q"],
        "status": "expected_pass",
    },
    {
        "name": "hypothesis",
        "tier": 4, "kind": "pure",
        "source": {"kind": "git", "url": "https://github.com/HypothesisWorks/hypothesis",
                   "ref": "hypothesis-python-6.122.3"},
        "install": ["./hypothesis-python"],
        "test_deps": ["pytest-xdist", "pexpect"],
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
        # uv workspace monorepo: the repo root has no [project] table, so
        # "pip install ." fails; the installable packages live in src/. Install
        # httpcore2 first so httpx2's workspace dep resolves locally.
        "install": ["./src/httpcore2", "./src/httpx2[http2]"],
        "test_deps": ["trio", "pytest-trio", "trustme", "uvicorn", "werkzeug",
                      "pytest-httpbin", "cryptography"],
        "test_cmd": ["-m", "pytest", "tests", "-q"],
        "status": "expected_pass",
        "note": "httpx successor stewarded by Pydantic Services (Tom Christie, "
                "author). [http2] extra pulls h2 to exercise the HTTP/2 path. "
                "Async tests run on trio (upstream dev group), not asyncio.",
    },
    {
        "name": "fastapi",
        "tier": 4, "kind": "pure",
        "source": {"kind": "git", "url": "https://github.com/fastapi/fastapi",
                   "ref": "0.115.6"},
        # [all] matches upstream CI (jinja2, orjson, ujson, uvicorn,
        # python-multipart, email-validator, ...); test_deps adds the direct
        # pins from their requirements-tests.txt not covered by the extra
        "install": [".[all]"],
        "test_deps": ["httpx", "trustme", "dirty-equals==0.6.0", "sqlmodel",
                      "flask", "anyio[trio]", "PyJWT==2.8.0", "passlib[bcrypt]",
                      "inline-snapshot==0.13.0"],
        "test_cmd": ["-m", "pytest", "tests", "-q"],
        "status": "expected_fail",
        "note": "Depends on pydantic (Rust core) + starlette; gated on pydantic "
                "building. Heavy test-dep set. Calibrate.",
    },
    {
        "name": "spacy",
        "tier": 4, "kind": "cext",
        "source": {"kind": "git", "url": "https://github.com/explosion/spaCy",
                   "ref": "release-v3.8.3"},
        "install": ["."],
        "test_deps": ["pytest-timeout", "hypothesis", "mock"],
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
        # -k instead of --deselect: --pyargs nodeids embed the venv path
        "test_cmd": ["-m", "pytest", "--pyargs", "bs4", "-q",
                     "-k", "not test_unsupported_pseudoclass"],
        "status": "expected_pass",
        "note": "Tests ship in the wheel (bs4.tests); optional lxml/html5lib "
                "parsers -- lxml tests self-skip if lxml is absent.",
    },
]
