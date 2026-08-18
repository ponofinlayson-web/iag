"""Normalize CRLF -> LF for files that must be LF (shell scripts, env files)."""
import sys
from pathlib import Path

def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python fix_eol.py FILE [FILE...]", file=sys.stderr)
        return 2
    for arg in sys.argv[1:]:
        p = Path(arg)
        raw = p.read_bytes()
        fixed = raw.replace(b"\r\n", b"\n")
        if fixed != raw:
            p.write_bytes(fixed)
            print(f"[fix-eol] {p}: CRLF -> LF")
        else:
            print(f"[fix-eol] {p}: already LF")
    return 0

if __name__ == "__main__":
    sys.exit(main())
