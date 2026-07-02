import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.database import engine
from sqlalchemy import text

def main():
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'memoria_sections')
                BEGIN
                    CREATE TABLE memoria_sections (
                        id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
                        licitacion_id UNIQUEIDENTIFIER NOT NULL,
                        user_id VARCHAR(36) NOT NULL,
                        titulo NVARCHAR(512) NOT NULL,
                        descripcion NVARCHAR(MAX) NULL,
                        criterio_adjudicacion NVARCHAR(MAX) NULL,
                        max_puntos FLOAT NULL,
                        page_budget INTEGER NULL,
                        content NVARCHAR(MAX) NULL,
                        orden INTEGER NOT NULL DEFAULT 0,
                        status NVARCHAR(20) NOT NULL DEFAULT 'proposed',
                        source NVARCHAR(20) NOT NULL DEFAULT 'llm',
                        created_at DATETIMEOFFSET NOT NULL DEFAULT sysdatetimeoffset(),
                        updated_at DATETIMEOFFSET NOT NULL DEFAULT sysdatetimeoffset(),
                        PRIMARY KEY (id),
                        FOREIGN KEY(licitacion_id) REFERENCES licitaciones (id) ON DELETE CASCADE
                    )
                END
            """))
            conn.execute(text("""
                IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'memoria_chat_messages')
                BEGIN
                    CREATE TABLE memoria_chat_messages (
                        id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
                        licitacion_id UNIQUEIDENTIFIER NOT NULL,
                        user_id VARCHAR(36) NOT NULL,
                        role NVARCHAR(20) NOT NULL,
                        content NVARCHAR(MAX) NOT NULL,
                        created_at DATETIMEOFFSET NOT NULL DEFAULT sysdatetimeoffset(),
                        PRIMARY KEY (id),
                        FOREIGN KEY(licitacion_id) REFERENCES licitaciones (id) ON DELETE CASCADE
                    )
                END
            """))
            conn.execute(text("""
                IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'memoria_documents')
                BEGIN
                    CREATE TABLE memoria_documents (
                        id UNIQUEIDENTIFIER NOT NULL DEFAULT newid(),
                        licitacion_id UNIQUEIDENTIFIER NOT NULL,
                        user_id VARCHAR(36) NOT NULL,
                        title NVARCHAR(255) NOT NULL DEFAULT 'Borrador',
                        markdown NVARCHAR(MAX) NULL,
                        created_at DATETIMEOFFSET NOT NULL DEFAULT sysdatetimeoffset(),
                        updated_at DATETIMEOFFSET NOT NULL DEFAULT sysdatetimeoffset(),
                        PRIMARY KEY (id),
                        FOREIGN KEY(licitacion_id) REFERENCES licitaciones (id) ON DELETE CASCADE
                    )
                END
            """))
            conn.execute(text("""
                IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'company_templates')
                BEGIN
                    CREATE TABLE company_templates (
                        id VARCHAR(36) NOT NULL,
                        user_id VARCHAR(36) NOT NULL,
                        filename NVARCHAR(512) NOT NULL,
                        title NVARCHAR(255) NULL,
                        description NVARCHAR(MAX) NULL,
                        mime_type NVARCHAR(100) NOT NULL DEFAULT 'application/pdf',
                        file_size INTEGER NULL,
                        page_count INTEGER NULL,
                        blob_url NVARCHAR(MAX) NOT NULL,
                        extracted_text NVARCHAR(MAX) NOT NULL,
                        summary NVARCHAR(MAX) NULL,
                        created_at DATETIMEOFFSET NOT NULL DEFAULT sysdatetimeoffset(),
                        PRIMARY KEY (id)
                    )
                END
            """))
            conn.commit()
            print("Tables created successfully")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    main()
