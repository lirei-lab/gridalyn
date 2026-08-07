# Runner image for the `sti-k8s` Actions Runner Controller scale set.
#
# WHY THIS EXISTS. The upstream `ghcr.io/actions/actions-runner` image is
# deliberately minimal and carries no OpenMP runtime. LightGBM's native library
# links against it, and lightgbm is a BASE dependency of this project -- not an
# optional extra -- so `import lightgbm` fails at collection time with
#
#     OSError: libgomp.so.1: cannot open shared object file
#
# and the whole suite errors out before a single test runs. Measured on
# 2026-08-07, the first CI run after moving to this runner.
#
# WHY NOT INSTALL IT IN THE JOB. The upstream image runs as the unprivileged
# `runner` user with no sudo, so `apt-get install` cannot work from a workflow
# step. Vendoring a copy out of another wheel (scikit-learn ships a mangled
# `libgomp-*.so.1.0.0`) does work, but couples this project's CI to another
# package's internal layout. The runtime a workload needs belongs in the image
# that runs it.
FROM ghcr.io/actions/actions-runner:latest

USER root

# libgomp1  -- OpenMP runtime, required by lightgbm (base dependency).
# git       -- present upstream, pinned here so a slimmer future base still works.
# curl/ca-certificates -- actions/setup-python downloads its interpreter, since
#             this image carries no tool cache.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgomp1 \
        git \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Back to the unprivileged user the controller expects. Leaving this as root
# would silently grant every workflow step on this runner more privilege than
# the upstream image intends.
USER runner
