"""Build the synthetic test corpus (no Foxit files). Usage: python tests/corpus/build.py"""
from pathlib import Path

import pymupdf

OUT = Path(__file__).parent


def contract(path: Path, v2: bool):
    d = pymupdf.open()
    for n in range(1, 7):
        p = d.new_page()
        p.insert_text((72, 72), f"Contract page {n}", fontsize=18)
        p.insert_text((72, 110), "Client: Acme Ltd", fontsize=11)
        body = "Payment due net 45 days." if (v2 and n == 2) else "Payment due net 30 days."
        p.insert_text((72, 140), body, fontsize=11)
        p.insert_text((72, 170), "Contact: jane.doe@example.com, phone (415) 555-0142.", fontsize=11)
        if v2 and n == 3:
            p.insert_text((72, 200), "New clause inserted in version two.", fontsize=11)
    d.set_toc([[1, "Intro", 1], [1, "Terms", 3], [1, "Signatures", 6]])
    d.save(path)


if __name__ == "__main__":
    contract(OUT / "contract-v1.pdf", False)
    contract(OUT / "contract-v2.pdf", True)
    print("built", [p.name for p in OUT.glob("*.pdf")])
