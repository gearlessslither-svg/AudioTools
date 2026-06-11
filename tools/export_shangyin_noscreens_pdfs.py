from __future__ import annotations

from pathlib import Path
import sys

TOOLS = Path(__file__).resolve().parent.parent / "course_design" / "tools"
sys.path.insert(0, str(TOOLS))

import export_pdfs_pil as base


WORKSPACE = Path(r"G:\AI\Material\Wwise")
base.ROOT = WORKSPACE / "course_design_shangyin_noscreens"
base.OUT = WORKSPACE / "course_design_shangyin_noscreens_pdf"
base.PDF_DIR = base.OUT / "pdf"
base.COMBINED_DIR = base.OUT / "combined"


if __name__ == "__main__":
    base.main()
