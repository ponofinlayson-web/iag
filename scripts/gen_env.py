"""One-shot generator for the local stack .env. Refuses to overwrite."""
import secrets
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"

def rand_password(n: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits
    return "Iag-" + "".join(secrets.choice(alphabet) for _ in range(n)) + "!"

def main() -> int:
    if ENV.exists():
        print("[gen-env] .env already exists; refusing to overwrite", file=sys.stderr)
        return 1
    values = {
        "IAG_POSTGRES_PASSWORD": secrets.token_hex(16),
        "IAG_APP_DB_PASSWORD": secrets.token_hex(16),
        "IAG_SECRET_KEY": secrets.token_hex(32),
        "IAG_BOOTSTRAP_ADMIN_PASSWORD": rand_password(),
    }
    lines = [
        "# IAG local stack secrets -- GITIGNORED, never commit real values.",
        "# Regenerate (fresh stack only! see .env.example) with scripts/gen_env.py",
        "",
    ]
    lines += [f"{k}={v}" for k, v in values.items()]
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[gen-env] wrote {ENV} ({len(values)} secrets)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
