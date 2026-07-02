"""Configuración offline aplicada antes de importar la aplicación en tests."""

import os


os.environ["ENVIRONMENT"] = "dev"
os.environ["KEY_VAULT_NAME"] = ""
os.environ["DATABASE_URL"] = "sqlite:///./test_app.db"
os.environ["AZURE_SEARCH_ENDPOINT"] = ""
os.environ["AZURE_SEARCH_KEY"] = ""
os.environ["AZURE_OPENAI_ENDPOINT"] = ""
os.environ["AZURE_OPENAI_KEY"] = ""
os.environ["AZURE_STORAGE_CONNECTION_STRING"] = ""
os.environ["AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT"] = ""
os.environ["AZURE_DOCUMENT_INTELLIGENCE_KEY"] = ""
os.environ["APPLICATIONINSIGHTS_CONNECTION_STRING"] = ""
