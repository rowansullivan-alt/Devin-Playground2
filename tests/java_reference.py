"""Helpers for running the original ``legacy_etl.java`` and the Python port."""

import os
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
JAVA_SOURCE = os.path.join(REPO_ROOT, "legacy_etl.java")
PYTHON_PORT = os.path.join(REPO_ROOT, "legacy_etl.py")

# Pin the environment-dependent bits of the JVM (default charset, locale used
# by DecimalFormat) to what the Python port hard-codes: UTF-8 and en-US.
JAVA_FLAGS = [
    "-Dfile.encoding=UTF-8",
    "-Dstdout.encoding=UTF-8",
    "-Dstderr.encoding=UTF-8",
    "-Duser.language=en",
    "-Duser.country=US",
]


def clean_env():
    env = dict(os.environ)
    # These make the JVM print "Picked up ..." on stderr.
    for name in ("JDK_JAVA_OPTIONS", "JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS"):
        env.pop(name, None)
    env["LANG"] = "C.UTF-8"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def java_available():
    return shutil.which("javac") is not None and shutil.which("java") is not None


def compile_java():
    """Compile legacy_etl.java; return the classpath directory."""
    out_dir = tempfile.mkdtemp(prefix="legacy_etl_java_")
    subprocess.run(
        ["javac", "-nowarn", "-d", out_dir, JAVA_SOURCE],
        check=True,
        capture_output=True,
        env=clean_env(),
    )
    return out_dir


def run_java(classpath, args):
    proc = subprocess.run(
        ["java"] + JAVA_FLAGS + ["-cp", classpath, "LegacyEtl"] + list(args),
        capture_output=True,
        env=clean_env(),
    )
    return proc.returncode, proc.stdout, proc.stderr


def run_python(args):
    proc = subprocess.run(
        [sys.executable, PYTHON_PORT] + list(args),
        capture_output=True,
        env=clean_env(),
    )
    return proc.returncode, proc.stdout, proc.stderr
