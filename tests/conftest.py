import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["SHADOWCALL_MODE"] = "mock"
os.environ.pop("MUBIT_API_KEY", None)
sys.path.insert(0, str(Path(__file__).resolve().parent))
