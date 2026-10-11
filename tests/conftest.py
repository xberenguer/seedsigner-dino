"""Import runtime modules from a fresh checkout without installing signer code."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "payload/opt/dino"))

