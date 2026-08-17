"""Executable pipeline, plotting, and reporting code for the study.

SEAL-01 (BLAS thread cap): the pipeline stages run as ``{python} -m
projects.ev_hosting_flex.scripts.pipeline.<stage>`` from the repo root, so this
package ``__init__`` executes BEFORE the stage module (and before any import
that pulls numpy transitively). Capping the BLAS thread pools here keeps the
annual chain deterministic — the exact guarantee the per-stage
``os.environ.setdefault(...)`` boilerplate used to make at module top.
"""

import os

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
