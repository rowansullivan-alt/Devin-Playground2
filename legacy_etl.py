"""Load a CSV file of store sales and total revenue by region.

Python port of ``legacy_etl.java`` (class ``LegacyEtl``). stdout, stderr and
exit codes match the Java program run on JDK 17 with UTF-8 and an en-US
locale, byte for byte; tests/test_legacy_etl.py checks this.

Expected CSV layout (first line is a header)::

    store_id,region,product,quantity,unit_price
    1001,North,Widget,3,4.50

Usage: python legacy_etl.py sales.csv
"""

import codecs
import math
import re
import struct
import sys

COL_STORE_ID = 0
COL_REGION = 1
COL_PRODUCT = 2
COL_QUANTITY = 3
COL_UNIT_PRICE = 4
NUM_COLUMNS = 5

INT_MIN = -(2**31)
INT_MAX = 2**31 - 1

# Integer.parseInt: optional sign, then Unicode decimal digits (Character.digit).
_JAVA_INT = re.compile(r"[+-]?\d+\Z")

# Double.parseDouble (FloatingDecimal.readJavaFormatString) grammar.
_JAVA_DOUBLE = re.compile(
    r"(?P<sign>[+-]?)(?:"
    r"(?P<special>NaN|Infinity)"
    r"|(?P<hex>0[xX](?:[0-9a-fA-F]+\.?[0-9a-fA-F]*|\.[0-9a-fA-F]+)[pP][+-]?[0-9]+)[fFdD]?"
    r"|(?P<dec>(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)[fFdD]?"
    r")\Z"
)


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


def parse_java_double(s):
    """Double.parseDouble(s); raises ValueError like NumberFormatException."""
    m = _JAVA_DOUBLE.match(java_trim(s))
    if not m:
        raise ValueError(s)
    negative = m.group("sign") == "-"
    if m.group("special") == "NaN":
        return float("nan")
    if m.group("special") == "Infinity":
        return float("-inf") if negative else float("inf")
    if m.group("hex"):
        try:
            value = float.fromhex(m.group("hex"))
        except OverflowError:
            value = float("inf")
    else:
        value = float(m.group("dec"))
    return -value if negative else value


def split_line(line):
    """StringTokenizer(line, ","): empty tokens are dropped, not kept."""
    fields = [token for token in line.split(",") if token]
    if len(fields) != NUM_COLUMNS:
        return None
    return fields


# --- DecimalFormat("#,##0.00").format(double), as implemented by JDK 17 ---
#
# DecimalFormat does not round the exact binary value: it first converts the
# double to decimal digits with jdk.internal.math.FloatingDecimal (the same
# digits Double.toString used before JDK 19), then rounds those digits
# HALF_EVEN in java.text.DigitList, consulting two flags from the conversion
# for ties. Those digits are usually, but not always, Python's shortest
# ``repr`` digits (e.g. integral doubles >= 2**53 keep extra digits), so the
# algorithm is ported here verbatim.

_SIGNIF_BIT_MASK = (1 << 52) - 1
_FRACT_HOB = 1 << 52
_EXP_ONE = 1023 << 52
# FloatingDecimal.N_5_BITS[i] == (5**i).bit_length()
_N_5_BITS = tuple((5**i).bit_length() for i in range(27))
_INSIGNIFICANT_DIGITS = (
    0, 0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 5, 5, 5, 6, 6, 6, 6, 7, 7, 7,
    8, 8, 8, 9, 9, 9, 9, 10, 10, 10, 11, 11, 11, 12, 12, 12, 12, 13, 13, 13, 14, 14, 14,
    15, 15, 15, 15, 16, 16, 16, 17, 17, 17, 18, 18, 18, 19,
)


def _double_bits(x):
    return struct.unpack("<Q", struct.pack("<d", x))[0]


def _wrap(value, width):
    """Two's-complement overflow of a Java int (32) or long (64)."""
    value &= (1 << width) - 1
    return value - (1 << width) if value >> (width - 1) else value


def _estimate_dec_exp(fract_bits, bin_exp):
    d2 = struct.unpack("<d", struct.pack("<Q", _EXP_ONE | (fract_bits & _SIGNIF_BIT_MASK)))[0]
    d = (d2 - 1.5) * 0.289529654 + 0.176091259 + float(bin_exp) * 0.301029995663981
    d_bits = _double_bits(d)
    exponent = ((d_bits >> 52) & 0x7FF) - 1023
    negative = d_bits >> 63 != 0
    if 0 <= exponent < 52:
        mask = _SIGNIF_BIT_MASK >> exponent
        r = ((d_bits & _SIGNIF_BIT_MASK) | _FRACT_HOB) >> (52 - exponent)
        if negative:
            return -r if (mask & d_bits) == 0 else -r - 1
        return r
    if exponent < 0:
        return 0 if (d_bits & ~(1 << 63)) == 0 else (-1 if negative else 0)
    return int(d)


def _java_dtoa(magnitude):
    """FloatingDecimal.getBinaryToASCIIConverter(magnitude) for finite > 0.

    Returns (digits, dec_exponent, rounded_up, exact): the value is
    0.<digits> * 10**dec_exponent.
    """
    bits = _double_bits(magnitude)
    fract_bits = bits & _SIGNIF_BIT_MASK
    bin_exp = (bits >> 52) & 0x7FF
    if bin_exp == 0:
        leading_zeros = 64 - fract_bits.bit_length()
        shift = leading_zeros - (63 - 52)
        fract_bits <<= shift
        bin_exp = 1 - shift
        n_significant_bits = 64 - leading_zeros
    else:
        fract_bits |= _FRACT_HOB
        n_significant_bits = 53
    bin_exp -= 1023

    tail_zeros = (fract_bits & -fract_bits).bit_length() - 1
    n_fract_bits = 53 - tail_zeros
    n_tiny_bits = max(0, n_fract_bits - bin_exp - 1)

    if -21 <= bin_exp <= 62 and n_tiny_bits == 0:
        # Integral value: developLongDigits.
        p2 = bin_exp - n_significant_bits - 1
        insignificant = _INSIGNIFICANT_DIGITS[p2] if bin_exp > n_significant_bits and 1 < p2 < len(_INSIGNIFICANT_DIGITS) else 0
        lvalue = fract_bits << (bin_exp - 52) if bin_exp >= 52 else fract_bits >> (52 - bin_exp)
        if insignificant:
            pow10 = 10**insignificant
            lvalue, residue = divmod(lvalue, pow10)
            if residue >= pow10 >> 1:
                lvalue += 1
        text = str(lvalue)
        return [int(c) for c in text.rstrip("0")], len(text) + insignificant, False, False

    dec_exp = _estimate_dec_exp(fract_bits, bin_exp)
    b5 = max(0, -dec_exp)
    b2 = b5 + n_tiny_bits + bin_exp
    s5 = max(0, dec_exp)
    s2 = s5 + n_tiny_bits
    m5 = b5
    m2 = b2 - n_significant_bits
    fract_bits >>= tail_zeros
    b2 -= n_fract_bits - 1
    common2 = min(b2, s2)
    b2 -= common2
    s2 -= common2
    m2 -= common2
    if n_fract_bits == 1:
        m2 -= 1
    if m2 < 0:
        b2 -= m2
        s2 -= m2
        m2 = 0

    b_bits = n_fract_bits + b2 + (_N_5_BITS[b5] if b5 < len(_N_5_BITS) else b5 * 3)
    ten_s_bits = s2 + 1 + (_N_5_BITS[s5 + 1] if s5 + 1 < len(_N_5_BITS) else (s5 + 1) * 3)
    digits = []

    if b_bits < 64 and ten_s_bits < 64:
        width = 32 if (b_bits < 32 and ten_s_bits < 32) else 64
        b = _wrap((fract_bits * 5**b5) << b2, width)
        s = _wrap(5**s5 << s2, width)
        m = _wrap(5**m5 << m2, width)
        tens = _wrap(s * 10, width)
        q = b // s
        b = _wrap(10 * (b % s), width)
        m = _wrap(m * 10, width)
        low = b < m
        high = _wrap(b + m, width) > tens
        if q == 0 and not high:
            dec_exp -= 1
        else:
            digits.append(q)
        if dec_exp < -3 or dec_exp >= 8:
            high = low = False
        while not low and not high:
            q = b // s
            b = _wrap(10 * (b % s), width)
            m = _wrap(m * 10, width)
            if m > 0:
                low = b < m
                high = _wrap(b + m, width) > tens
            else:
                low = high = True
            digits.append(q)
        low_digit_difference = _wrap(_wrap(b << 1, width) - tens, width)
        exact = b == 0
    else:
        s_val = 5**s5 << s2
        b_val = (fract_bits * 5**b5) << b2
        m_val = 5 ** (m5 + 1) << (m2 + 1)
        ten_s_val = 5 ** (s5 + 1) << (s2 + 1)
        q, b_val = divmod(b_val, s_val)
        b_val *= 10
        low = b_val < m_val
        high = ten_s_val <= b_val + m_val
        if q == 0 and not high:
            dec_exp -= 1
        else:
            digits.append(q)
        if dec_exp < -3 or dec_exp >= 8:
            high = low = False
        while not low and not high:
            q, b_val = divmod(b_val, s_val)
            b_val *= 10
            m_val *= 10
            low = b_val < m_val
            high = ten_s_val <= b_val + m_val
            digits.append(q)
        if high and low:
            b_val <<= 1
            low_digit_difference = (b_val > ten_s_val) - (b_val < ten_s_val)
        else:
            low_digit_difference = 0
        exact = b_val == 0

    dec_exponent = dec_exp + 1
    rounded_up = False
    if high and (not low or low_digit_difference > 0 or (low_digit_difference == 0 and digits[-1] % 2)):
        # roundup()
        i = len(digits) - 1
        while digits[i] == 9 and i > 0:
            digits[i] = 0
            i -= 1
        if digits[i] == 9:
            dec_exponent += 1
            digits[0] = 1
        else:
            digits[i] += 1
            rounded_up = True
    return digits, dec_exponent, rounded_up, exact


def _should_round_up(digits, count, max_digits, rounded_up, exact):
    """DigitList.shouldRoundUp for RoundingMode.HALF_EVEN."""
    if max_digits < count:
        digit = digits[max_digits]
        if digit > 5:
            return True
        if digit == 5:
            if max_digits == count - 1:
                if rounded_up:
                    return False
                if not exact:
                    return True
                return max_digits > 0 and digits[max_digits - 1] % 2 != 0
            return any(d != 0 for d in digits[max_digits + 1 : count])
    return False


def _round_to_cents(magnitude):
    """DigitList.set(isNegative, magnitude, 2); returns (digits, decimal_at)."""
    if magnitude == 0:
        return [], 0
    digits, decimal_at, rounded_up, exact = _java_dtoa(magnitude)
    count = len(digits)
    max_fraction = 2
    if -decimal_at > max_fraction:
        return [], decimal_at
    if -decimal_at == max_fraction:
        if _should_round_up(digits, count, 0, rounded_up, exact):
            return [1], decimal_at + 1
        return [], decimal_at
    while count > 1 and digits[count - 1] == 0:
        count -= 1
    max_digits = max_fraction + decimal_at
    if 0 <= max_digits < count:
        if _should_round_up(digits, count, max_digits, rounded_up, exact):
            while True:
                max_digits -= 1
                if max_digits < 0:
                    digits[0] = 1
                    decimal_at += 1
                    max_digits = 0
                    break
                digits[max_digits] += 1
                if digits[max_digits] <= 9:
                    break
            max_digits += 1
        count = max_digits
        while count > 1 and digits[count - 1] == 0:
            count -= 1
    return digits[:count], decimal_at


def format_money(value):
    """DecimalFormat("#,##0.00").format(value) in an en-US locale (JDK 17)."""
    if math.isnan(value):
        return "NaN"
    sign = "-" if math.copysign(1.0, value) < 0 else ""
    if math.isinf(value):
        return sign + "\u221e"
    digits, decimal_at = _round_to_cents(abs(value))

    def digit(i):
        return str(digits[i]) if 0 <= i < len(digits) else "0"

    integer = "".join(digit(i) for i in range(decimal_at)) or "0"
    fraction = digit(decimal_at) + digit(decimal_at + 1)
    return "%s%s.%s" % (sign, "{:,}".format(int(integer)), fraction)


def java_length(s):
    """String.length(): UTF-16 code units, so non-BMP chars count as 2."""
    return len(s.encode("utf-16-le")) // 2


def pad_right(s, width):
    return s + " " * max(0, width - java_length(s))


def print_report(totals, rows_loaded, rows_skipped, out):
    grand_total = 0.0
    out.write("REVENUE BY REGION\n")
    out.write("=================\n")
    for region, amount in totals.items():
        grand_total = grand_total + amount
        out.write(pad_right(region, 20) + format_money(amount) + "\n")
    out.write("-----------------\n")
    out.write(pad_right("TOTAL", 20) + format_money(grand_total) + "\n")
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
                    unit_price = parse_java_double(java_trim(fields[COL_UNIT_PRICE]))
                except ValueError:
                    err.write("WARNING: line %d has bad number, skipped\n" % line_number)
                    rows_skipped += 1
                    continue

                revenue = quantity * unit_price
                totals[region] = totals.get(region, 0.0) + revenue
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
