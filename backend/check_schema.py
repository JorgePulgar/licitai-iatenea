from app.db.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    result = conn.execute(text(
        "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH "
        "FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE COLUMN_NAME IN ('id', 'licitacion_id') "
        "AND TABLE_NAME IN ('licitaciones','pliegos','memoria_sections','memoria_chat_messages','memoria_documents','queries','match_results','pliego_requirements','licitacion_summaries') "
        "ORDER BY TABLE_NAME, COLUMN_NAME"
    ))
    for row in result:
        print(f"{row._mapping['TABLE_NAME']}.{row._mapping['COLUMN_NAME']} = {row._mapping['DATA_TYPE']} ({row._mapping['CHARACTER_MAXIMUM_LENGTH']})")
