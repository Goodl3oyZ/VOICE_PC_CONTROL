"""PC2 Windows agent.

Makes the shared `contracts/` package importable when the agent is started straight from the repo
(e.g. by Task Scheduler, where PYTHONPATH may not be set).
"""
import sys
from pathlib import Path

_contracts = Path(__file__).resolve().parent.parent.parent / "contracts"
if _contracts.is_dir() and str(_contracts) not in sys.path:
    sys.path.insert(0, str(_contracts))
