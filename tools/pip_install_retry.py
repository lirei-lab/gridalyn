#!/usr/bin/env python3
"""Run a pip install, retrying only the failures that are the network's fault.

WHY THIS EXISTS. On 2026-09-16 six CI jobs across five pull requests and
``main`` died in the dependency-install step, none of them on a red test:

    ERROR: Could not install packages due to an OSError:
    ('Connection broken: IncompleteRead(214027 bytes read, 3458 more expected)')

Every one went green on a rerun of the same commit. The byte counts are the
evidence for what it is: identical across the jobs of a single run (PR #57:
both failing jobs 214027/3458; PR #54: both 230547/273), different between
runs. One upstream response is being cut, and whichever jobs are installing at
that moment die together -- not independent per-job hiccups, and nothing a
change to this repository caused.

WHY pip's OWN RETRIES DO NOT COVER IT. Every call site already runs with pip's
defaults and with ``actions/setup-python``'s ``cache: pip`` enabled. Those
retries cover a connection that fails to open; a response body cut mid-download
surfaces from the install phase as ``OSError`` and takes the process down with
it. The unit that has to be retried is therefore the install, not the fetch.

WHY A TOOL RATHER THAN A SHELL LOOP IN THE YAML. Five call sites would mean
five copies of the same loop, and inline workflow logic cannot be tested --
this repository treats a gate that is not run as not a gate
(``tools/ci_main_status.mjs`` exists for the same reason; see ``tools/README.md``).
``tests/test_pip_install_retry.py`` drives every branch below on every pull
request, including the one that matters most: a genuine failure must NOT be
retried.

WHAT IT DELIBERATELY DOES NOT DO. It does not retry a resolution error, a
missing extra, or a build failure -- those are this repository's bugs and must
fail on the first attempt, loudly and in seconds. Only the measured transient
signatures below are retried, so a real break cannot hide behind three
attempts and a timeout.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time

#: Failure signatures that are the network's, not the tree's.
#:
#: Kept narrow on purpose: every entry is a transport-layer failure that says
#: nothing about whether the requested environment is installable. A resolver
#: message ("No matching distribution found", "Could not build wheels") is
#: absent by design -- retrying one wastes CI minutes to reach the same red.
TRANSIENT_MARKERS: tuple[str, ...] = (
    "IncompleteRead",
    "Connection broken",
    "Connection reset",
    "Connection aborted",
    "Read timed out",
    "Temporary failure in name resolution",
    "TLSV1_ALERT",
    "502 Server Error",
    "503 Server Error",
    "504 Server Error",
)

DEFAULT_ATTEMPTS = 3
DEFAULT_DELAY_SECONDS = 5.0


def is_transient_failure(output: str) -> bool:
    """Whether a failed install looks like the transport, not the tree.

    Args:
        output: The combined stdout/stderr of the failed attempt.

    Returns:
        True when the output carries one of :data:`TRANSIENT_MARKERS`.
    """
    return any(marker in output for marker in TRANSIENT_MARKERS)


def run_pip_install(
    arguments: list[str],
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    command: list[str] | None = None,
    sleep=time.sleep,
) -> int:
    """Install with ``arguments``, retrying only transient transport failures.

    Output is echoed line by line as it arrives, so a CI log reads the same as
    it did before this tool existed, and is accumulated so the failure can be
    classified once the attempt ends.

    Args:
        arguments: Arguments after ``pip install`` (e.g. ``['-e', '.[all]']``).
        attempts: Maximum attempts. One means no retry.
        delay_seconds: Seconds to wait between attempts.
        command: The install command to run, for tests. Defaults to
            ``[sys.executable, '-m', 'pip', 'install']``.
        sleep: Injected for tests; the real wait by default.

    Returns:
        The exit code of the last attempt; ``0`` when one of them succeeded.
    """
    install = list(command or [sys.executable, "-m", "pip", "install"])
    for attempt in range(1, max(1, attempts) + 1):
        print(
            f"[pip-install-retry] attempt {attempt}/{attempts}: "
            f"{' '.join(install + arguments)}",
            flush=True,
        )
        process = subprocess.Popen(
            install + arguments,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        captured: list[str] = []
        assert process.stdout is not None
        for line in process.stdout:
            captured.append(line)
            sys.stdout.write(line)
        sys.stdout.flush()
        code = process.wait()
        if code == 0:
            return 0
        output = "".join(captured)
        if not is_transient_failure(output):
            print(
                f"[pip-install-retry] attempt {attempt} failed with exit {code}, "
                "and the failure is not a transport error: not retrying.",
                flush=True,
            )
            return code
        if attempt == attempts:
            print(
                f"[pip-install-retry] transport error on the last of {attempts} "
                f"attempts; failing with exit {code}.",
                flush=True,
            )
            return code
        print(
            f"[pip-install-retry] transport error on attempt {attempt}; "
            f"retrying in {delay_seconds:.0f}s.",
            flush=True,
        )
        sleep(delay_seconds)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run the install.

    Args:
        argv: Argument list; defaults to ``sys.argv[1:]``. Everything after
            ``--`` is passed to ``pip install`` verbatim.

    Returns:
        The process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--attempts", type=int, default=DEFAULT_ATTEMPTS)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS)
    parser.add_argument(
        "pip_arguments",
        nargs=argparse.REMAINDER,
        help="Arguments for `pip install`, after a `--` separator.",
    )
    args = parser.parse_args(argv)
    arguments = [value for value in args.pip_arguments if value != "--"]
    if not arguments:
        parser.error("nothing to install: pass pip's arguments after `--`")
    return run_pip_install(arguments, attempts=args.attempts, delay_seconds=args.delay)


if __name__ == "__main__":
    raise SystemExit(main())
