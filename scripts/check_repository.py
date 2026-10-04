"""Check tracked artifacts without printing any file contents or secret values."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    tracked = result.stdout.decode().split("\0")
    for name in filter(None, tracked):
        path = Path(name)
        if (
            (path.name.startswith(".env") and path.name != ".env.example")
            or path.suffix in {".pem", ".key", ".db", ".sqlite", ".log", ".session"}
            or set(path.parts) & {"secrets", "data", "models", ".venv", "backups"}
        ):
            raise SystemExit("Forbidden runtime/secret artifact is tracked")
    for name in ("secrets/telegram_token", ".env", "data/tipnews.db", "backups/db.sqlite"):
        check = subprocess.run(
            ["git", "check-ignore", "--quiet", "--no-index", name],
            cwd=ROOT,
        )
        if check.returncode != 0:
            raise SystemExit("Required secret/data ignore rule is missing")
    rules = (ROOT / ".dockerignore").read_text().splitlines()
    effective = [line for line in rules if line and not line.startswith("#")]
    if not effective or effective[0] != "**":
        raise SystemExit("Docker context must deny files by default")
    print("Repository artifact boundary checks passed")


if __name__ == "__main__":
    main()
