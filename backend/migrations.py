"""Idempotent additive schema migrations for existing SQLite/PostgreSQL databases."""
from sqlalchemy import inspect, text

MIGRATIONS = {
    "historical_readings": {"baseline_power_kw": "FLOAT", "total_cost": "FLOAT", "fan_power_kw": "FLOAT"},
    "decision_records": {"requested_setpoints_json": "TEXT"},
}


async def migrate(connection):
    await connection.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)"))
    for table, additions in MIGRATIONS.items():
        columns = await connection.run_sync(lambda sync: {c["name"] for c in inspect(sync).get_columns(table)})
        for column, data_type in additions.items():
            if column not in columns:
                await connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {data_type}"))
    if not (await connection.execute(text("SELECT version FROM schema_migrations WHERE version=2"))).first():
        await connection.execute(text("INSERT INTO schema_migrations (version) VALUES (2)"))
    if not (await connection.execute(text("SELECT version FROM schema_migrations WHERE version=3"))).first():
        await connection.execute(text("INSERT INTO schema_migrations (version) VALUES (3)"))
