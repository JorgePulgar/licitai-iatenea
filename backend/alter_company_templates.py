"""
Añade las columnas nuevas a `company_templates` para soportar:
  - title, description (metadatos editables por el usuario)
  - mime_type, file_size, page_count (metadatos del archivo)
  - summary (síntesis profunda del agente de resumen — alimenta el prompt de Memoria)

Si la tabla no existe aún, llama antes a `create_missing_tables.py`. Este script solo
añade columnas que falten; no toca las existentes ni los datos.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.database import engine
from sqlalchemy import text


ALTERS = [
    ("title", "NVARCHAR(255) NULL"),
    ("description", "NVARCHAR(MAX) NULL"),
    ("mime_type", "NVARCHAR(100) NOT NULL DEFAULT 'application/pdf'"),
    ("file_size", "INTEGER NULL"),
    ("page_count", "INTEGER NULL"),
    ("summary", "NVARCHAR(MAX) NULL"),
]


def main():
    try:
        with engine.connect() as conn:
            for column, ddl in ALTERS:
                conn.execute(text(f"""
                    IF NOT EXISTS (
                        SELECT 1
                        FROM INFORMATION_SCHEMA.COLUMNS
                        WHERE TABLE_NAME = 'company_templates' AND COLUMN_NAME = '{column}'
                    )
                    BEGIN
                        ALTER TABLE company_templates ADD {column} {ddl}
                    END
                """))
                print(f"  ✓ Column ensured: {column}")
            conn.commit()
            print("company_templates schema is up to date.")
    except Exception as e:
        print(f"Error altering company_templates: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
