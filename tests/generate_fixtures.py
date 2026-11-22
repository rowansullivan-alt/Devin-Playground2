"""Regenerate tests/fixtures/*.expected_* by running the original Java program.

Usage: python -m tests.generate_fixtures
"""

import glob
import os

from tests.java_reference import FIXTURES, compile_java, run_java


def main():
    classpath = compile_java()
    for csv_path in sorted(glob.glob(os.path.join(FIXTURES, "*.csv"))):
        code, out, err = run_java(classpath, [os.path.basename(csv_path)])
        base = csv_path[: -len(".csv")]
        with open(base + ".expected_stdout", "wb") as f:
            f.write(out)
        with open(base + ".expected_stderr", "wb") as f:
            f.write(err)
        with open(base + ".expected_exit", "w") as f:
            f.write("%d\n" % code)
        print("%s: exit %d" % (os.path.basename(csv_path), code))


if __name__ == "__main__":
    os.chdir(FIXTURES)
    main()
