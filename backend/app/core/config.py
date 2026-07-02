import secrets
import logging
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    PROJECT_NAME: str = "LicitAI"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"

    # Environment flag — controls dev-only endpoints like /auth/register
    ENVIRONMENT: str = "dev"  # "dev" | "staging" | "prod"

    # Database (Azure SQL via pyodbc; full mssql+pyodbc://... URL comes from KV secret SQL-CONNECTION)
    DATABASE_URL: str = ""

    # Azure Storage
    AZURE_STORAGE_CONNECTION_STRING: str | None = None
    AZURE_STORAGE_CONTAINER_NAME: str = "pliegos-raw"
    AZURE_STORAGE_ACCOUNT_NAME: str = "stlicitaidev"

    # Azure Document Intelligence
    AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT: str | None = None
    AZURE_DOCUMENT_INTELLIGENCE_KEY: str | None = None

    # Azure OpenAI
    AZURE_OPENAI_ENDPOINT: str | None = None
    AZURE_OPENAI_KEY: str | None = None

    # Azure AI Search (endpoint is a public URL, safe to keep in .env)
    AZURE_SEARCH_ENDPOINT: str | None = None
    AZURE_SEARCH_KEY: str | None = None
    AZURE_SEARCH_INDEX_NAME: str = "licitai-pliegos-index"

    # Auth / JWT
    JWT_SECRET: str | None = None
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 24

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]

    # Logging
    LOG_LEVEL: str = "INFO"

    # Observability — Azure Application Insights (LIC-101 / LIC-103)
    # Connection string is a secret: lives in .env (dev). For prod, load from
    # Key Vault secret APPINSIGHTS-CONNECTION-STRING in load_from_keyvault().
    APPLICATIONINSIGHTS_CONNECTION_STRING: str | None = None

    # Data retention (LIC-063) — default 5 years per LCSP requirements
    RETENTION_DAYS: int = 1825

    # Key Vault — name only (NOT the URL); the only thing that must be in .env
    KEY_VAULT_NAME: str | None = None

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

    def load_from_keyvault(self) -> None:
        if not self.KEY_VAULT_NAME:
            logger.warning("KEY_VAULT_NAME not set — skipping Key Vault load.")
            self._apply_jwt_fallback()
            return

        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient

        kv_url = f"https://{self.KEY_VAULT_NAME}.vault.azure.net"
        try:
            credential = DefaultAzureCredential()
            client = SecretClient(vault_url=kv_url, credential=credential)
        except Exception as e:
            logger.error(f"Failed to connect to Key Vault {kv_url}: {e}")
            self._apply_jwt_fallback()
            return

        def load_secret(secret_name: str, attr_name: str) -> bool:
            try:
                val = client.get_secret(secret_name).value
                setattr(self, attr_name, val)
                return True
            except Exception as e:
                logger.warning(f"Could not load secret '{secret_name}' from Key Vault: {e}")
                return False

        load_secret("OPENAI-ENDPOINT", "AZURE_OPENAI_ENDPOINT")
        load_secret("OPENAI-KEY", "AZURE_OPENAI_KEY")
        load_secret("SEARCH-ADMIN-KEY", "AZURE_SEARCH_KEY")
        if load_secret("STORAGE-CONNECTION-STRING", "AZURE_STORAGE_CONNECTION_STRING"):
            self._build_storage_connection_string()
        load_secret("DOC-INT-ENDPOINT", "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT")
        load_secret("DOC-INTEL-KEY", "AZURE_DOCUMENT_INTELLIGENCE_KEY")
        # Observabilidad (LIC-101/103). Si el secreto aún no existe en KV,
        # load_secret avisa y continúa; en dev se usa el valor de .env.
        load_secret("APPINSIGHTS-CONNECTION-STRING", "APPLICATIONINSIGHTS_CONNECTION_STRING")
        if not self.DATABASE_URL:
            if load_secret("SQL-CONNECTION", "DATABASE_URL"):
                self._convert_ado_to_sqlalchemy()

        jwt_loaded = load_secret("JWT-SECRET", "JWT_SECRET")
        if not jwt_loaded:
            self._apply_jwt_fallback()

    def _build_storage_connection_string(self) -> None:
        """If KV secret is just the account key, build the full connection string."""
        val = self.AZURE_STORAGE_CONNECTION_STRING or ""
        if "AccountName=" in val:
            return  # Already a full connection string
        # It's just the key — build the connection string
        self.AZURE_STORAGE_CONNECTION_STRING = (
            f"DefaultEndpointsProtocol=https;"
            f"AccountName={self.AZURE_STORAGE_ACCOUNT_NAME};"
            f"AccountKey={val};"
            f"EndpointSuffix=core.windows.net"
        )
        logger.info("Built full Azure Storage connection string from account key.")

    def _convert_ado_to_sqlalchemy(self) -> None:
        """Convert ADO.NET connection string from Key Vault to SQLAlchemy format.

        Uses Azure AD token auth via azure-identity because the ODBC driver
        on macOS does not support Authentication=ActiveDirectoryDefault.
        """
        raw = self.DATABASE_URL
        if raw.startswith("mssql") or raw.startswith("sqlite"):
            return  # Already in SQLAlchemy format

        import re
        parts = {
            k.strip().lower(): v.strip().strip('"')
            for k, v in (
                seg.split("=", 1) for seg in raw.split(";") if "=" in seg
            )
        }

        server = parts.get("server", "")
        server = re.sub(r"^tcp:", "", server)

        database = parts.get("initial catalog", "")
        encrypt = parts.get("encrypt", "True")
        trust_cert = parts.get("trustservercertificate", "False")

        odbc_params = (
            f"DRIVER={{ODBC Driver 18 for SQL Server}};"
            f"SERVER={server};"
            f"DATABASE={database};"
            f"Encrypt={'yes' if encrypt.lower() == 'true' else 'no'};"
            f"TrustServerCertificate={'yes' if trust_cert.lower() == 'true' else 'no'};"
        )

        from urllib.parse import quote_plus
        self.DATABASE_URL = f"mssql+pyodbc:///?odbc_connect={quote_plus(odbc_params)}"
        self._azure_ad_auth = True
        logger.info("Converted ADO.NET connection string to SQLAlchemy format (Azure AD token auth).")

    def _apply_jwt_fallback(self) -> None:
        if self.ENVIRONMENT != "dev":
            raise RuntimeError(
                "JWT-SECRET not found in Key Vault and ENVIRONMENT is not 'dev'. "
                "Refusing to start without a real JWT secret in production."
            )
        self.JWT_SECRET = secrets.token_urlsafe(32)
        logger.warning(
            "JWT-SECRET not provisioned in Key Vault. "
            "Using an ephemeral dev-only random secret. "
            "DO NOT deploy to production without setting JWT-SECRET in Key Vault."
        )


settings = Settings()
settings.load_from_keyvault()
