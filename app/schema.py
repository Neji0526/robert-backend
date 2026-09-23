"""Apply the SQL files in db/.

Statements are split on semicolons. The migration files do not use functions
or semicolons inside string literals, so that split is safe.
"""

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parents[1]
MIGRATION_FILES = [
    ROOT / "db" / "001_base_schema.sql",
    ROOT / "db" / "002_payments.sql",
    ROOT / "db" / "003_demo_payment_method.sql",
]


def statements_in(path: Path) -> list[str]:
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("--"):
            continue
        lines.append(line)
    return [part.strip() for part in "\n".join(lines).split(";") if part.strip()]


def apply_script(engine: Engine, path: Path) -> None:
    with engine.begin() as connection:
        for statement in statements_in(path):
            connection.execute(text(statement))


def rebuild_schema(engine: Engine) -> None:
    database = (engine.url.database or "").lower()
    if "test" not in database:
        raise RuntimeError(f"Refusing to rebuild the schema of database {engine.url.database!r}.")
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    for path in MIGRATION_FILES:
        apply_script(engine, path)


def main() -> None:
    from app import create_app
    from app.extensions import db

    application = create_app()
    with application.app_context():
        for path in MIGRATION_FILES:
            apply_script(db.engine, path)
        print(f"Applied schema files to {db.engine.url.database}.")


if __name__ == "__main__":
    main()
