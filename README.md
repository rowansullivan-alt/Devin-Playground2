# Devin-Playground2
Devin Playground for elementary testing

## legacy_etl

`legacy_etl.py` is a Python port of `legacy_etl.java` (revenue by region from a sales CSV):

```
python legacy_etl.py sales.csv
```

Parity tests compare it against the Java original (golden fixtures, plus side-by-side runs when a JDK is on PATH):

```
python -m unittest discover -s tests -t . -v
python -m tests.generate_fixtures   # regenerate golden output from the Java program
```
