import os
import tempfile

# keep tests out of the user's settings, recent files and saved signatures (read when Qt and pdfdesk load)
_home = tempfile.mkdtemp(prefix="pdfdesk-tests-")
os.environ["XDG_CONFIG_HOME"] = os.path.join(_home, "config")
os.environ["XDG_DATA_HOME"] = os.path.join(_home, "data")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf  # noqa: E402
import pytest  # noqa: E402


def make_contract(path, v2: bool = False):
    """Six-page contract; v2 changes the payment term on page 2 and adds a clause on page 3."""
    d = pymupdf.open()
    for n in range(1, 7):
        p = d.new_page()
        p.insert_text((72, 72), f"Contract page {n}", fontsize=18)
        p.insert_text((72, 110), "Client: Acme Ltd", fontsize=11)
        p.insert_text((72, 140), "Payment due net 45 days." if (v2 and n == 2) else "Payment due net 30 days.", fontsize=11)
        p.insert_text((72, 170), "Contact: jane.doe@example.com, phone (415) 555-0142.", fontsize=11)
        if v2 and n == 3:
            p.insert_text((72, 200), "New clause inserted in version two.", fontsize=11)
    d.set_toc([[1, "Intro", 1], [1, "Terms", 3], [1, "Signatures", 6]])
    d.save(path)


@pytest.fixture
def v1_path(tmp_path):
    p = tmp_path / "v1.pdf"
    make_contract(p)
    return str(p)


@pytest.fixture
def v1(v1_path):
    return pymupdf.open(v1_path)
