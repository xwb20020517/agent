from loguru import logger
from sqlalchemy import text

from app.db.base import Base
from app.db.session import engine
from app import models  # noqa: F401


FK_CASCADE_RULES = [
    ("conversations", "user_id", "users", "id"),
    ("messages", "conversation_id", "conversations", "id"),
    ("messages", "user_id", "users", "id"),
    ("llm_calls", "conversation_id", "conversations", "id"),
    ("llm_calls", "user_id", "users", "id"),
]


async def _ensure_on_delete_cascade(conn) -> None:
    for table_name, column_name, referenced_table, referenced_column in FK_CASCADE_RULES:
        result = await conn.execute(
            text(
                """
                select k.constraint_name as constraint_name, r.delete_rule as delete_rule
                from information_schema.key_column_usage k
                join information_schema.referential_constraints r
                  on k.constraint_schema = r.constraint_schema
                 and k.constraint_name = r.constraint_name
                 and k.table_name = r.table_name
                where k.table_schema = database()
                  and k.table_name = :table_name
                  and k.column_name = :column_name
                  and k.referenced_table_name = :referenced_table
                  and k.referenced_column_name = :referenced_column
                """
            ),
            {
                "table_name": table_name,
                "column_name": column_name,
                "referenced_table": referenced_table,
                "referenced_column": referenced_column,
            },
        )
        row = result.mappings().first()
        if row and row["delete_rule"] == "CASCADE":
            continue
        if row:
            await conn.execute(text(f"ALTER TABLE `{table_name}` DROP FOREIGN KEY `{row['constraint_name']}`"))

        constraint_name = f"fk_{table_name}_{column_name}"
        await conn.execute(
            text(
                f"""
                ALTER TABLE `{table_name}`
                ADD CONSTRAINT `{constraint_name}`
                FOREIGN KEY (`{column_name}`)
                REFERENCES `{referenced_table}` (`{referenced_column}`)
                ON DELETE CASCADE
                """
            )
        )


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("ALTER TABLE messages MODIFY content LONGTEXT NOT NULL"))
        await conn.execute(text("ALTER TABLE llm_calls MODIFY error_message LONGTEXT NULL"))
        await _ensure_on_delete_cascade(conn)
    logger.info("Database tables are ready")
