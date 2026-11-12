"""The translation tables and the interface must not drift apart: every string passed to tr() has a German, a
French and an Arabic entry, and the tables carry no entries for strings the interface no longer shows. The
interface is the desktop window (pdfdesk/) and the browser and phone apps (web/src)."""
import ast
import pathlib
import re

from pdfdesk.lang import ar, de, fr

SRC = pathlib.Path(__file__).resolve().parents[1] / "pdfdesk"
WEB = SRC.parent / "web" / "src"                      # the browser and phone apps use the same tables
TS_STRING = re.compile(r'"((?:[^"\\\n]|\\.)*)"')
# keys built at run time rather than written as one literal: f"Paste {what} Here" with what from clipboard.describe()
DYNAMIC = re.compile(r"^Paste (Comment|Object|Image|Text) Here$")


def _strings():
    literals, keys = set(), set()
    for p in SRC.rglob("*.py"):
        if p.parent.name == "lang":
            continue
        for n in ast.walk(ast.parse(p.read_text())):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                literals.add(n.value)
            elif isinstance(n, ast.Call) and getattr(n.func, "id", None) == "tr" and n.args \
                    and isinstance(n.args[0], ast.Constant):
                keys.add(n.args[0].value)
    for p in WEB.glob("*.ts"):
        text = p.read_text()
        literals |= set(TS_STRING.findall(text))
        keys |= set(re.findall(r'\btr\("((?:[^"\\\n]|\\.)*)"', text))
    return literals, keys


def test_every_translated_string_is_in_both_tables():
    _literals, keys = _strings()
    assert sorted(k for k in keys if k not in de.STRINGS) == []
    assert sorted(k for k in keys if k not in fr.STRINGS) == []
    assert sorted(k for k in keys if k not in ar.STRINGS) == []
    assert set(de.STRINGS) == set(fr.STRINGS) == set(ar.STRINGS)


def test_tables_hold_no_strings_the_interface_no_longer_shows():
    literals, _keys = _strings()
    stale = [k for k in de.STRINGS if k not in literals and not DYNAMIC.match(k)]
    assert stale == []
