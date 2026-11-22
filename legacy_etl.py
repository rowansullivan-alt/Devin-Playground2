"""Load a CSV file of store sales and total revenue by region.

Python port of ``legacy_etl.java`` (class ``LegacyEtl``). stdout, stderr and
exit codes match the Java program run with UTF-8 and an en-US locale, byte
for byte; tests/test_legacy_etl.py checks this. Amounts are exact decimals
(``decimal.Decimal`` in place of ``java.math.BigDecimal``).

Expected CSV layout (first line is a header)::

    store_id,region,product,quantity,unit_price
    1001,North,Widget,3,4.50

Usage: python legacy_etl.py sales.csv
"""

import codecs
import re
import sys
import unicodedata
from decimal import MAX_EMAX, MAX_PREC, MIN_EMIN, ROUND_HALF_UP, Context, Decimal

COL_STORE_ID = 0
COL_REGION = 1
COL_PRODUCT = 2
COL_QUANTITY = 3
COL_UNIT_PRICE = 4
NUM_COLUMNS = 5

INT_MIN = -(2**31)
INT_MAX = 2**31 - 1

# Integer.parseInt: optional sign, then Unicode decimal digits (Character.digit).
# Supplementary-plane digits are rejected: Java reads them as two surrogates.
_JAVA_INT = re.compile(r"[+-]?(?:(?![\U00010000-\U0010FFFF])\d)+\Z")

# new BigDecimal(String): optional sign, Unicode decimal digits with at most
# one '.', optional exponent. No whitespace, NaN, Infinity, hex or suffixes.
_JAVA_BIGDECIMAL = re.compile(
    r"(?P<sign>[+-]?)(?P<int>\d*)(?:\.(?P<frac>\d*))?(?:[eE](?P<esign>[+-]?)(?P<exp>\d+))?\Z"
)
_SUPPLEMENTARY = re.compile(r"[\U00010000-\U0010FFFF]")

# Big enough that every + and * below is exact, like BigDecimal's.
_EXACT = Context(prec=MAX_PREC, Emax=MAX_EMAX, Emin=MIN_EMIN)
_CENTS = Decimal("0.01")


def _java_utf8_replace(error):
    """Decode errors the way Java's UTF-8 decoder does (one U+FFFD each).

    Matches Python's "replace" handler except for encoded surrogates
    (ED A0..BF [80..BF]), which Java replaces with a single U+FFFD.
    """
    data, start = error.object, error.start
    if (
        isinstance(error, UnicodeDecodeError)
        and data[start] == 0xED
        and start + 1 < len(data)
        and 0xA0 <= data[start + 1] <= 0xBF
    ):
        end = start + 2
        if end < len(data) and 0x80 <= data[end] <= 0xBF:
            end += 1
        return "\ufffd", end
    return codecs.replace_errors(error)


codecs.register_error("java_utf8_replace", _java_utf8_replace)


def java_trim(s):
    """String.trim(): strip leading/trailing chars <= U+0020."""
    start, end = 0, len(s)
    while start < end and s[start] <= " ":
        start += 1
    while end > start and s[end - 1] <= " ":
        end -= 1
    return s[start:end]


def parse_java_int(s):
    """Integer.parseInt(s); raises ValueError like NumberFormatException."""
    if not _JAVA_INT.match(s):
        raise ValueError(s)
    value = int(s)
    if value < INT_MIN or value > INT_MAX:
        raise ValueError(s)
    return value


def parse_java_bigdecimal(s):
    """new BigDecimal(s); raises ValueError like NumberFormatException."""
    m = _JAVA_BIGDECIMAL.match(s)
    if not m or _SUPPLEMENTARY.search(s):
        raise ValueError(s)
    int_digits, frac_digits = m.group("int"), m.group("frac") or ""
    if not int_digits and not frac_digits:
        raise ValueError(s)
    exponent = 0
    if m.group("exp") is not None:
        exp_digits = m.group("exp")
        # parseExp: at most 10 digits once redundant leading zeros are dropped.
        if len(exp_digits) > 10 and int(exp_digits[:-10]) != 0:
            raise ValueError(s)
        exponent = int(exp_digits) * (-1 if m.group("esign") == "-" else 1)
        if not INT_MIN <= exponent <= INT_MAX:
            raise ValueError(s)
    scale = len(frac_digits) - exponent
    if not INT_MIN <= scale <= INT_MAX:
        raise ValueError(s)
    digits = tuple(unicodedata.decimal(c) for c in int_digits + frac_digits)
    return Decimal((1 if m.group("sign") == "-" else 0, digits, -scale))


def split_line(line):
    """line.split(",", -1): empty fields are kept."""
    fields = line.split(",")
    if len(fields) != NUM_COLUMNS:
        return None
    return fields


def round_cents(amount):
    """amount.setScale(2, BigDecimal.ROUND_HALF_UP)."""
    return amount.quantize(_CENTS, rounding=ROUND_HALF_UP, context=_EXACT)


def format_money(amount):
    """DecimalFormat("#,##0.00").format(BigDecimal) in an en-US locale."""
    # BigDecimal has no negative zero: -0.004 rounds to "0.00", not "-0.00".
    if amount.is_zero():
        amount = abs(amount)
    return "{:,.2f}".format(amount)


def java_length(s):
    """String.length(): UTF-16 code units, so non-BMP chars count as 2."""
    return len(s.encode("utf-16-le")) // 2


def pad_right(s, width):
    return s + " " * max(0, width - java_length(s))


def print_report(totals, rows_loaded, rows_skipped, out):
    grand_total = Decimal(0)
    out.write("REVENUE BY REGION\n")
    out.write("=================\n")
    for region, amount in totals.items():
        grand_total = _EXACT.add(grand_total, amount)
        out.write(pad_right(region, 20) + format_money(round_cents(amount)) + "\n")
    out.write("-----------------\n")
    out.write(pad_right("TOTAL", 20) + format_money(round_cents(grand_total)) + "\n")
    out.write("\n")
    out.write("Rows loaded:  %d\n" % rows_loaded)
    out.write("Rows skipped: %d\n" % rows_skipped)


def run(file_name, out=sys.stdout, err=sys.stderr):
    """Process ``file_name``; return the process exit code."""
    totals = {}
    line_number = 0
    rows_loaded = 0
    rows_skipped = 0

    try:
        # newline=None splits on \n, \r and \r\n, like BufferedReader.readLine.
        with open(file_name, encoding="utf-8", errors="java_utf8_replace", newline=None) as reader:
            reader.readline()
            line_number += 1
            for line in reader:
                line_number += 1
                line = line.rstrip("\n")
                if len(java_trim(line)) == 0:
                    continue

                fields = split_line(line)
                if fields is None:
                    err.write("WARNING: line %d has wrong number of columns, skipped\n" % line_number)
                    rows_skipped += 1
                    continue

                region = java_trim(fields[COL_REGION])
                try:
                    quantity = parse_java_int(java_trim(fields[COL_QUANTITY]))
                    unit_price = parse_java_bigdecimal(java_trim(fields[COL_UNIT_PRICE]))
                except ValueError:
                    err.write("WARNING: line %d has bad number, skipped\n" % line_number)
                    rows_skipped += 1
                    continue

                revenue = _EXACT.multiply(unit_price, Decimal(quantity))
                totals[region] = _EXACT.add(totals.get(region, Decimal(0)), revenue)
                rows_loaded += 1
    except OSError as e:
        detail = "%s (%s)" % (file_name, e.strerror) if e.strerror else str(e)
        err.write("ERROR: could not read %s: %s\n" % (file_name, detail))
        return 2

    print_report(totals, rows_loaded, rows_skipped, out)
    return 0


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    # Always emit UTF-8 rather than depending on the locale.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    if len(args) < 1:
        sys.stderr.write("Usage: python legacy_etl.py <sales.csv>\n")
        return 1
    return run(args[0])


if __name__ == "__main__":
    sys.exit(main())
