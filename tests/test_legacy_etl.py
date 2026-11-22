"""Prove legacy_etl.py produces the same output as legacy_etl.java.

* ``GoldenFixtureTest`` compares the Python port against stdout/stderr/exit
  codes captured from the Java program (``tests/fixtures``). Needs no JDK.
* ``DifferentialTest`` compiles and runs the Java program side by side with
  the port on the fixtures, on randomized CSVs and on error cases. Skipped
  when ``javac``/``java`` are not on PATH.

Run: python -m unittest discover -s tests -t . -v
"""

import glob
import os
import random
import shutil
import struct
import tempfile
import unittest

import legacy_etl
from tests.java_reference import FIXTURES, compile_java, java_available, run_java, run_python

FIXTURE_NAMES = sorted(
    os.path.basename(p)[: -len(".csv")] for p in glob.glob(os.path.join(FIXTURES, "*.csv"))
)


def _read(path, mode="rb"):
    with open(path, mode) as f:
        return f.read()


class GoldenFixtureTest(unittest.TestCase):
    def test_fixtures_exist(self):
        self.assertGreater(len(FIXTURE_NAMES), 0)

    def test_matches_java_golden_output(self):
        for name in FIXTURE_NAMES:
            with self.subTest(fixture=name):
                base = os.path.join(FIXTURES, name)
                cwd = os.getcwd()
                os.chdir(FIXTURES)
                try:
                    code, out, err = run_python([name + ".csv"])
                finally:
                    os.chdir(cwd)
                self.assertEqual(out, _read(base + ".expected_stdout"))
                self.assertEqual(err, _read(base + ".expected_stderr"))
                self.assertEqual(code, int(_read(base + ".expected_exit", "r")))


def _random_price(rng):
    kind = rng.randrange(12)
    if kind == 0:
        return "%d.%03d5" % (rng.randrange(1000), rng.randrange(1000))
    if kind == 1:
        return "%d.%02d5" % (rng.randrange(10**7), rng.randrange(100))
    if kind == 2:
        return repr(struct.unpack("<d", struct.pack("<Q", rng.getrandbits(64)))[0])
    if kind == 3:
        return "%.17g" % rng.uniform(-1e6, 1e6)
    if kind == 4:
        return "%se%+d" % (rng.choice(["1", "-2.5", "0.005", "9.995", ".5", "5."]), rng.randrange(-60, 60))
    if kind == 5:
        return rng.choice(["NaN", "Infinity", "-Infinity", "+1", ".5", "5.", "1e3", "1E-2", "-0",
                           "-0.004", "-0.005", "0x1p4", "4.5d", "4.5F", "inf", "nan", "1_0", "1,0",
                           " 2.5 ", "--1", "+-1", "", "0x10", "1e", "e5", ".", ".e1", "1.2.3",
                           "1e+", "1e1.5", "\u0663", "\u0661.\u0665", "1e\u0662", "\uff15",
                           "1e2147483647x", "1e2147483648", "1e-2147483648", "1e-2147483649",
                           "0.5e-2147483647", "1e00000000002", "1e10000000000",
                           "12345678901234567890.123456789012345678905", "\U0001D7D9"])
    if kind == 6:
        return "-%d.%02d" % (rng.randrange(10**4), rng.randrange(100))
    return "%d.%02d" % (rng.randrange(10**4), rng.randrange(100))


def _random_quantity(rng):
    kind = rng.randrange(10)
    if kind == 0:
        return rng.choice(["2147483647", "2147483648", "-2147483648", "-2147483649", "+7",
                           "-0", "007", "3.0", "1e2", "", " 4 ", "\u0661\u0662", "\uff11",
                           "0x10", "1_000", "abc", "\U0001D7D9"])
    if kind == 1:
        return str(rng.randrange(-(2**31), 2**31))
    return str(rng.randrange(0, 500))


def _random_region(rng):
    return rng.choice(["North", "South", "East", "West", "north", " North ", "Nord-Est",
                       "São Paulo", "東京", "\U0001F600Emoji", "e\u0301", "A" * 25, "", " ", "\tTab"])


def _random_line(rng):
    kind = rng.randrange(20)
    if kind == 0:
        return ""
    if kind == 1:
        return " \t "
    if kind == 2:
        return ",".join(["1", "North", "Widget", "3"])
    if kind == 3:
        return ",".join(["1", "North", "Widget", "3", "1.0", "extra"])
    fields = [str(rng.randrange(10000)), _random_region(rng), "Widget",
              _random_quantity(rng), _random_price(rng)]
    line = ",".join(fields)
    if kind == 4:
        line = line.replace(",", ",,")
    if kind == 5:
        line = "," + line + ","
    return line


def _random_csv(rng):
    newline = rng.choice(["\n", "\r\n", "\r"])
    lines = ["store_id,region,product,quantity,unit_price"]
    lines += [_random_line(rng) for _ in range(rng.randrange(0, 80))]
    text = newline.join(lines)
    if rng.random() < 0.7:
        text += newline
    return text.encode("utf-8")


@unittest.skipUnless(java_available(), "javac/java not on PATH")
class DifferentialTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.classpath = compile_java()
        cls.workdir = tempfile.mkdtemp(prefix="legacy_etl_diff_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.classpath, ignore_errors=True)
        shutil.rmtree(cls.workdir, ignore_errors=True)

    def assertSameAsJava(self, args):
        java = run_java(self.classpath, args)
        python = run_python(args)
        self.assertEqual(python[1].decode("utf-8", "replace"), java[1].decode("utf-8", "replace"))
        self.assertEqual(python[2].decode("utf-8", "replace"), java[2].decode("utf-8", "replace"))
        self.assertEqual(python[0], java[0])

    def _write(self, name, data):
        path = os.path.join(self.workdir, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_fixtures(self):
        for name in FIXTURE_NAMES:
            with self.subTest(fixture=name):
                self.assertSameAsJava([os.path.join(FIXTURES, name + ".csv")])

    def test_randomized_csvs(self):
        rng = random.Random(20261122)
        for i in range(40):
            data = _random_csv(rng)
            with self.subTest(case=i, data=data):
                self.assertSameAsJava([self._write("random_%d.csv" % i, data)])

    def test_money_formatting_over_many_values(self):
        # One region per value so every value goes through DecimalFormat.
        rng = random.Random(7)
        lines = ["store_id,region,product,quantity,unit_price"]
        for i in range(4000):
            lines.append("%d,R%05d,p,1,%s" % (i, i, _random_price(rng).strip() or "0"))
        self.assertSameAsJava([self._write("money.csv", ("\n".join(lines) + "\n").encode())])

    def test_invalid_utf8_bytes(self):
        data = (b"h\n1,Bad\xff\xfe\xc3(,p,1,1\n1,Trunc\xe6\x9d,p,1,1\n"
                b"1,Over\xc0\xaf,p,1,1\n1,Surr\xed\xa0\x80,p,1,1\n")
        self.assertSameAsJava([self._write("bad_utf8.csv", data)])

    def test_random_invalid_utf8_bytes(self):
        rng = random.Random(3)
        alphabet = [0x41, 0x80, 0x9F, 0xA0, 0xBF, 0xC0, 0xC2, 0xE0, 0xED, 0xEF, 0xF0, 0xF4, 0xF5, 0xFF]
        lines = [b"h"]
        for i in range(500):
            junk = bytes(rng.choice(alphabet) for _ in range(rng.randrange(1, 6)))
            lines.append(b"1,R%03d" % i + junk + b"x,p,1,1")
        self.assertSameAsJava([self._write("random_utf8.csv", b"\n".join(lines) + b"\n")])

    def test_missing_file(self):
        self.assertSameAsJava([os.path.join(self.workdir, "does_not_exist.csv")])

    def test_directory_instead_of_file(self):
        self.assertSameAsJava([self.workdir])

    def test_extra_arguments_are_ignored(self):
        self.assertSameAsJava([os.path.join(FIXTURES, "basic.csv"), "ignored", "args"])

    def test_no_arguments_exit_code(self):
        # The usage text intentionally names the Python entry point; only the
        # exit code is expected to match.
        self.assertEqual(run_python([])[0], run_java(self.classpath, [])[0])


class HelperTest(unittest.TestCase):
    def test_java_trim_only_strips_control_and_space(self):
        self.assertEqual(legacy_etl.java_trim("\t\x00 a b \x1f"), "a b")
        self.assertEqual(legacy_etl.java_trim("\u00a0a\u2003"), "\u00a0a\u2003")

    def test_pad_right_counts_utf16_units(self):
        self.assertEqual(legacy_etl.pad_right("\U0001F600", 4), "\U0001F600  ")
        self.assertEqual(legacy_etl.pad_right("abcde", 3), "abcde")

    def test_split_line_keeps_empty_fields(self):
        self.assertEqual(legacy_etl.split_line("1,,p,3,"), ["1", "", "p", "3", ""])
        self.assertIsNone(legacy_etl.split_line(",a,b,c,d,e,"))
        self.assertIsNone(legacy_etl.split_line("a,b,c,d"))

    def test_parse_java_int(self):
        self.assertEqual(legacy_etl.parse_java_int("+7"), 7)
        self.assertEqual(legacy_etl.parse_java_int("-2147483648"), -(2**31))
        for bad in ["2147483648", "1_000", "", "+", "3.0", " 4", "\U0001D7D9"]:
            with self.assertRaises(ValueError):
                legacy_etl.parse_java_int(bad)

    def test_parse_java_bigdecimal(self):
        parse = legacy_etl.parse_java_bigdecimal
        self.assertEqual(str(parse("+4.50")), "4.50")
        self.assertEqual(str(parse("5.")), "5")
        self.assertEqual(str(parse("-.5E3")), "-5E+2")
        self.assertEqual(str(parse("\u0661.\u0665")), "1.5")
        self.assertEqual(str(parse("1e00000000002")), "1E+2")
        for bad in ["NaN", "Infinity", "4.5d", "0x10", "1_0", "", ".", "1e", "1e+", "e5",
                    "1.2.3", " 1", "+-1", "\U0001D7D9", "1.\U0001D7D9", "1e10000000000", "1e2147483648", "1e-2147483648"]:
            with self.assertRaises(ValueError, msg=bad):
                parse(bad)

    def test_round_and_format_money(self):
        cases = {
            "0.125": "0.13", "0.135": "0.14", "2.675": "2.68", "-2.675": "-2.68",
            "-0.004": "0.00", "-0.005": "-0.01", "1234567.5": "1,234,567.50",
            "1e20": "100,000,000,000,000,000,000.00",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                amount = legacy_etl.round_cents(legacy_etl.parse_java_bigdecimal(value))
                self.assertEqual(legacy_etl.format_money(amount), expected)


if __name__ == "__main__":
    unittest.main()
