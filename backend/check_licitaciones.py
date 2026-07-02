from app.db.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    result = conn.execute(text(
        "SELECT id, titulo, status, user_id FROM licitaciones WHERE status = 'indexed'"
    ))
    for r in result.fetchall():
        m = r._mapping
        print(f"licitacion_id : {m['id']}")
        print(f"titulo        : {m['titulo']}")
        print(f"user_id       : {m['user_id']}")
        print()

    # Y los usuarios disponibles
    print("--- Usuarios ---")
    result2 = conn.execute(text("SELECT id, email FROM users"))
    for r in result2.fetchall():
        m = r._mapping
        print(f"  {m['email']} → {m['id']}")
