from sqlalchemy.orm import DeclarativeBase

# Base aislada del engine para evitar imports circulares.
# Los modelos importan de aquí; database.py importa de aquí para metadata.
class Base(DeclarativeBase):
    pass
