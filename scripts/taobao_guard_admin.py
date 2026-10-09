from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jd_taobao_mcp.config import load_settings
from jd_taobao_mcp.taobao_guard import TaobaoNavigationGuard


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"status", "resume"}:
        print("Usage: python scripts/taobao_guard_admin.py status|resume")
        return 2

    settings = load_settings(ROOT)
    state_path = (
        settings.profile_dir
        / "taobao"
        / "taobao-safety-state.json"
    )

    guard = TaobaoNavigationGuard(state_path)

    if sys.argv[1] == "status":
        print(f"Taobao automation paused: {guard.is_paused()}")
        print(f"State file: {state_path}")
        return 0

    if not guard.is_paused():
        print("Taobao automation is not paused.")
        return 0

    print("Complete official Taobao verification manually first.")
    print("Stop all MCP server instances before resuming.")
    try:
        answer = input("Type RESUME TAOBAO to confirm: ").strip()
    except EOFError:
        return 2

    if answer != "RESUME TAOBAO":
        print("Cancelled. State unchanged.")
        return 1

    guard.resume_after_manual_verification()
    print("Local pause cleared; navigation limits preserved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
