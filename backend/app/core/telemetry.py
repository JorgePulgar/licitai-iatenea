"""Observabilidad: integración con Azure Application Insights (LIC-101 / LIC-103).

Envía los logs de la aplicación (incluidos los fallos de Document Intelligence y
Azure OpenAI) a Application Insights vía OpenTelemetry. A partir de ahí el equipo
monta alertas y Workbooks sobre la tabla de telemetría.
"""

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

# Captura todos los loggers "app.*" (get_logger usa __name__, p.ej. "app.services.ocr").
_APP_LOGGER_NAME = "app"

_configured = False


def setup_telemetry() -> None:
    """Configura el envío de logs a Application Insights.

    No-op si la connection string no está definida o el SDK no está instalado,
    de modo que el entorno local sin telemetría sigue arrancando con normalidad.
    Idempotente: configurar dos veces duplicaría exportadores.
    """
    global _configured
    if _configured:
        return

    conn = settings.APPLICATIONINSIGHTS_CONNECTION_STRING
    if not conn:
        logger.info(
            "APPLICATIONINSIGHTS_CONNECTION_STRING no definida — telemetría deshabilitada."
        )
        return

    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
    except ImportError:
        logger.warning(
            "azure-monitor-opentelemetry no instalado — telemetría deshabilitada."
        )
        return

    # logger_name="app" engancha un handler de OTel al logger raíz de la app.
    # Los logs siguen propagando al StreamHandler JSON de setup_logging (consola),
    # así que tenemos salida local + envío a App Insights simultáneamente.
    configure_azure_monitor(
        connection_string=conn,
        logger_name=_APP_LOGGER_NAME,
    )
    _configured = True
    logger.info("Telemetría Azure Application Insights configurada (logger_name='app').")
