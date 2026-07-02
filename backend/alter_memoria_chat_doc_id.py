"""
Añade la columna `doc_id` a `memoria_chat_messages` para vincular cada turno
de chat a la versión del documento (`memoria_documents.id`).

Idempotente: no toca la columna si ya existe. Los turnos antiguos quedan con
`doc_id = NULL` y no se mostrarán al filtrar por documento.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text

from app.db.database import engine


def main():
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                IF NOT EXISTS (
                    SELECT 1
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_NAME = 'memoria_chat_messages' AND COLUMN_NAME = 'doc_id'
                )
                BEGIN
                    ALTER TABLE memoria_chat_messages ADD doc_id VARCHAR(36) NULL
                END
            """))
            conn.execute(text("""
                IF NOT EXISTS (
                    SELECT 1
                    FROM sys.indexes
                    WHERE name = 'ix_memoria_chat_messages_doc_id'
                      AND object_id = OBJECT_ID('memoria_chat_messages')
                )
                BEGIN
                    CREATE INDEX ix_memoria_chat_messages_doc_id
                        ON memoria_chat_messages (doc_id)
                END
            """))
            conn.commit()
            print("memoria_chat_messages.doc_id is up to date.")
    except Exception as e:
        print(f"Error altering memoria_chat_messages: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
