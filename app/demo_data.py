from sqlalchemy import text

from app.extensions import db
from app.schema import MIGRATION_FILES, statements_in


def reset_demo_data() -> None:
    """Replace shop rows with the sample cart and the declined demo card."""
    db.session.execute(
        text(
            """
            TRUNCATE TABLE
                payments,
                cart_items,
                carts,
                user_payment_methods,
                products,
                users
            RESTART IDENTITY CASCADE
            """
        )
    )
    for path in MIGRATION_FILES:
        for statement in statements_in(path):
            if statement.lstrip().upper().startswith("INSERT"):
                db.session.execute(text(statement))
    db.session.commit()
