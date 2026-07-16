import hashlib
import json
from typing import List

from app.core.logging import get_logger
from app.models.domain import CompanyProfile
from app.models.schemas import MatchResponse, RequirementResponse
from app.prompts.match import MATCH_SYSTEM_PROMPT
from app.services.embeddings import get_openai_client

logger = get_logger(__name__)

LLM_MODEL = "extraccion_datos_4o"
LLM_TEMPERATURE = 0.2


def compute_profile_hash(profile: CompanyProfile) -> str:
    """Deterministic hash of profile fields for cache invalidation."""
    fields = (
        profile.name or "",
        profile.description or "",
        profile.sectors or "",
        profile.certifications or "",
        str(profile.employee_count or ""),
        profile.annual_revenue or "",
        profile.solvency_tech or "",
        profile.solvency_econ or "",
        profile.notable_clients or "",
    )
    raw = "|".join(fields)
    return hashlib.sha256(raw.encode()).hexdigest()


def build_profile_text(profile: CompanyProfile) -> str:
    """Builds a human-readable profile text for the LLM.

    API pública: también la consume el servicio de Memoria Técnica (DRY §6)."""
    parts = [f"Empresa: {profile.name}"]
    if profile.description:
        parts.append(f"Descripción: {profile.description}")
    if profile.sectors:
        sectors = json.loads(profile.sectors) if isinstance(profile.sectors, str) else profile.sectors
        parts.append(f"Sectores: {', '.join(sectors)}")
    if profile.certifications:
        certs = json.loads(profile.certifications) if isinstance(profile.certifications, str) else profile.certifications
        parts.append(f"Certificaciones: {', '.join(certs)}")
    if profile.employee_count:
        parts.append(f"Número de empleados: {profile.employee_count}")
    if profile.annual_revenue:
        parts.append(f"Facturación anual: {profile.annual_revenue}")
    if profile.solvency_tech:
        parts.append(f"Solvencia técnica: {profile.solvency_tech}")
    if profile.solvency_econ:
        parts.append(f"Solvencia económica: {profile.solvency_econ}")
    if profile.notable_clients:
        clients = json.loads(profile.notable_clients) if isinstance(profile.notable_clients, str) else profile.notable_clients
        parts.append(f"Clientes destacados: {', '.join(clients)}")
    return "\n".join(parts)


def _build_requirements_text(requirements: List[RequirementResponse]) -> str:
    """Builds a structured list of requirements for the LLM."""
    if not requirements:
        return "No se han extraído requisitos del pliego."

    lines = []
    for req in requirements:
        tipo = "OBLIGATORIO" if req.es_obligatorio else "VALORABLE"
        page = f" [p. {req.pagina}]" if req.pagina else ""
        lines.append(
            f"- [{req.id}] ({req.categoria}, {tipo}{page}): {req.descripcion}"
        )
    return "\n".join(lines)


async def calculate_match(
    licitacion_id: str,
    user_id: str,
    title: str,
    profile: CompanyProfile,
    requirements: List[RequirementResponse],
) -> MatchResponse:
    """
    Evaluates company profile against extracted requirements using LLM.
    """
    profile_text = build_profile_text(profile)
    requirements_text = _build_requirements_text(requirements)

    client = get_openai_client()
    if not client:
        logger.warning("Azure OpenAI not configured — match score unavailable.")
        return MatchResponse(
            licitacion_id=licitacion_id,
            puntuacion_total=0,
            nivel_encaje="Bajo",
            resumen="El servicio de análisis de encaje no está disponible en este momento.",
            desglose=[],
            requisitos_evaluados=[],
        )

    # Fencing anti-inyección (1.8): requisitos y perfil son texto no confiable;
    # el prompt v1.0 trata el contenido de <requisitos>/<perfil> como datos.
    user_message = (
        f"Licitación: '{title}'\n\n"
        f"<requisitos>\n{requirements_text}\n</requisitos>\n\n"
        f"<perfil>\n{profile_text}\n</perfil>"
    )

    try:
        response = await client.chat.completions.create(
            model=LLM_MODEL,
            temperature=LLM_TEMPERATURE,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": MATCH_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        )
        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"LLM returned invalid JSON for match of licitacion {licitacion_id}: {e}")
        raise
    except Exception as e:
        logger.error(f"Error calculating match for licitacion {licitacion_id}: {e}")
        raise

    return MatchResponse(licitacion_id=licitacion_id, **data)
