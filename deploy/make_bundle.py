"""Package the files needed on the server into out/faibaplaning-deploy.tar.gz.

Usage:  .venv\\Scripts\\python deploy\\make_bundle.py
Shell scripts get Unix line endings and execute permission.
"""
import io
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INCLUDE = ["ftth", "planner", "planner_site", "deploy", "manage.py", "requirements.txt", "Dockerfile",
           "docker-entrypoint.sh", "docker-compose.yml", ".dockerignore", ".env.example", "DEPLOY.md"]
SKIP_PARTS = {"__pycache__", ".pytest_cache"}


def files():
    for name in INCLUDE:
        p = ROOT / name
        if p.is_file():
            yield p
        elif p.is_dir():
            yield from (f for f in sorted(p.rglob("*")) if f.is_file() and not SKIP_PARTS & set(f.parts))


def main():
    out = ROOT / "out" / "faibaplaning-deploy.tar.gz"
    out.parent.mkdir(exist_ok=True)
    with tarfile.open(out, "w:gz") as tar:
        for f in files():
            rel = f.relative_to(ROOT).as_posix()
            data = f.read_bytes()
            info = tarfile.TarInfo(f"faibaplaning/{rel}")
            if f.suffix == ".sh":
                data = data.replace(b"\r\n", b"\n")
                info.mode = 0o755
            else:
                info.mode = 0o644
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
