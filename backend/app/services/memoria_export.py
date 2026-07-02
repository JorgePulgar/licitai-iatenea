"""
Export de la Memoria Técnica: Markdown → PDF (WeasyPrint).

Los imports de `markdown` y `weasyprint` son perezosos (dentro de la función) para
que la app no falle al cargar si las dependencias nativas de WeasyPrint (cairo,
pango) no están instaladas en el entorno. Ver ADR-002 §6.
"""

import html
import re
from typing import Mapping

# CSS básico y sobrio para un entregable legible en A4. No garantiza el formato
# obligatorio del PCAP (fuentes/márgenes/límite de páginas) — eso es trabajo futuro.
#
# IMPORTANTE: mantener en sintonía con `frontend/src/lib/memoriaPaged.css`,
# que aplica las MISMAS reglas vía paged.js en el visor de la pestaña Memoria.
# Si tocas tamaño, márgenes o jerarquía aquí, actualízalo también allí.
_PDF_CSS = """
@page {
  size: A4;
  margin: 2.5cm 2cm 2.4cm;
  @top-center { content: element(document-header); }
  @bottom-left { content: element(document-footer); }
}
* { box-sizing: border-box; }
html, body { width: 100%; max-width: 100%; }
body {
  font-family: 'Helvetica', 'Arial', sans-serif;
  font-size: 11pt;
  line-height: 1.5;
  color: #1a1a1a;
  overflow-wrap: anywhere;
  word-break: normal;
}
.document-header {
  position: running(document-header);
  width: 100%;
  color: #4b5563;
  border-bottom: 0.5pt solid #d1d5db;
  padding-bottom: 5pt;
  font-size: 9pt;
}
.document-footer {
  position: running(document-footer);
  width: 100%;
  color: #6b7280;
  font-size: 8.5pt;
}
h1 { font-size: 20pt; margin: 0 0 0.6em; }
h2 { font-size: 15pt; margin: 1.2em 0 0.4em; border-bottom: 1px solid #ddd; padding-bottom: 0.2em; }
h3 { font-size: 12.5pt; margin: 1em 0 0.3em; }
p, li { margin: 0.3em 0; }
ul, ol { padding-left: 1.5em; }
a { color: #1d4ed8; overflow-wrap: anywhere; }
img, svg, video {
  display: block;
  max-width: 100%;
  height: auto;
  object-fit: contain;
  margin: 0.8em auto;
}
figure.document-image {
  display: block;
  max-width: 100%;
  margin-top: 0.8em;
  margin-bottom: 0.8em;
}
figure.document-image img {
  width: 100%;
  max-width: 100%;
  margin: 0;
  transform-origin: center;
}
table {
  border-collapse: collapse;
  width: 100%;
  max-width: 100%;
  table-layout: fixed;
  margin: 0.6em 0;
}
th, td {
  border: 1px solid #ccc;
  padding: 4px 8px;
  text-align: left;
  font-size: 10pt;
  overflow-wrap: anywhere;
  word-break: break-word;
}
th { background: #f2f2f2; }
code {
  background: #f4f4f4;
  padding: 1px 4px;
  border-radius: 3px;
  overflow-wrap: anywhere;
}
pre {
  max-width: 100%;
  padding: 8pt;
  background: #f4f4f4;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
}
pre code { padding: 0; }
blockquote {
  margin: 0.8em 0;
  padding: 0.2em 0 0.2em 1em;
  border-left: 3px solid #d1d5db;
  color: #4b5563;
}
.document-video {
  max-width: 100%;
  margin: 0.9em 0;
  padding: 12pt;
  border: 1px solid #d1d5db;
  border-radius: 5pt;
  background: #f9fafb;
}
.document-video__label {
  display: block;
  margin-bottom: 3pt;
  color: #111827;
  font-weight: bold;
}
.document-video a {
  display: block;
  font-size: 9pt;
  overflow-wrap: anywhere;
}
.document-variable[data-variable="page"],
.document-variable[data-variable="pages"] {
  font-size: 0;
}
.document-variable[data-variable="page"]::after,
.document-variable[data-variable="pages"]::after {
  font-size: 8.5pt;
}
.document-variable[data-variable="page"]::after { content: counter(page); }
.document-variable[data-variable="pages"]::after { content: counter(pages); }
.document-settings { display: none; }
.page-break { break-after: page; page-break-after: always; }
h1, h2, h3 { break-after: avoid; page-break-after: avoid; }
img, figure, table, pre, blockquote {
  break-inside: avoid;
  page-break-inside: avoid;
}
/* Mantén el rótulo ("Tabla 1: …", "Figura 2: …") pegado al elemento que describe:
   un párrafo o lista seguido inmediatamente de una tabla/figura no debe quedar
   huérfano al final de la página mientras su tabla salta a la siguiente. */
p:has(+ table), p:has(+ figure),
ul:has(+ table), ol:has(+ table),
li:has(+ table) {
  break-after: avoid;
  page-break-after: avoid;
}
"""

_OUTER_MARKDOWN_FENCE = re.compile(
    r"\A\s*```(?:markdown|md)?[ \t]*\r?\n(?P<body>[\s\S]*?)\r?\n```[ \t]*\s*\Z",
    re.IGNORECASE,
)
_RUNNING_ELEMENT = re.compile(
    r"<(?P<tag>header|footer)\b"
    r"(?=[^>]*\bclass=[\"'][^\"']*\bdocument-(?:header|footer)\b[^\"']*[\"'])"
    r"[^>]*>[\s\S]*?</(?P=tag)>",
    re.IGNORECASE,
)
_DOCUMENT_SETTINGS = re.compile(
    r"<div\b(?=[^>]*\bclass=[\"'][^\"']*\bdocument-settings\b[^\"']*[\"'])"
    r"(?P<attrs>[^>]*)></div>",
    re.IGNORECASE,
)
_VARIABLE_SPAN = re.compile(
    r"<span\b(?P<attrs>[^>]*\bdata-variable=[\"'](?P<key>[a-z_]+)[\"'][^>]*)>"
    r"[\s\S]*?</span>",
    re.IGNORECASE,
)
_ATTRIBUTE = re.compile(r"\b(?P<name>[a-z-]+)=[\"'](?P<value>[^\"']*)[\"']", re.IGNORECASE)

_PAGE_SIZES = {
    "a4": "A4",
    "letter": "Letter",
    "a3": "A3",
}


def normalize_markdown(markdown_text: str) -> str:
    """Quita el fence global que algunos modelos añaden a todo el documento."""
    match = _OUTER_MARKDOWN_FENCE.match(markdown_text)
    return match.group("body") if match else markdown_text


def _move_running_elements_first(html_body: str) -> str:
    """Sitúa header/footer antes del contenido para repetirlos desde la página 1."""
    elements = [match.group(0) for match in _RUNNING_ELEMENT.finditer(html_body)]
    if not elements:
        return html_body

    content = _RUNNING_ELEMENT.sub("", html_body).lstrip()
    return "".join(elements) + content


def _page_rule(html_body: str) -> str:
    match = _DOCUMENT_SETTINGS.search(html_body)
    attrs = (
        {
            item.group("name").lower(): item.group("value").lower()
            for item in _ATTRIBUTE.finditer(match.group("attrs"))
        }
        if match
        else {}
    )
    page_size = _PAGE_SIZES.get(attrs.get("data-page-size", "a4"), "A4")
    orientation = "landscape" if attrs.get("data-orientation") == "landscape" else "portrait"
    has_page_variable = re.search(
        r"\bdata-variable=[\"'](?:page|pages)[\"']",
        html_body,
        re.IGNORECASE,
    )
    default_counter = (
        ""
        if has_page_variable
        else """
  @bottom-right {
    content: "Página " counter(page) " de " counter(pages);
    color: #6b7280;
    font-size: 8.5pt;
  }"""
    )
    return f"@page {{ size: {page_size} {orientation};{default_counter}\n}}"


def _resolve_document_variables(
    html_body: str,
    variables: Mapping[str, str] | None,
) -> str:
    values = variables or {}

    def replace(match: re.Match[str]) -> str:
        key = match.group("key").lower()
        attrs = match.group("attrs")
        if key in {"page", "pages"}:
            return f"<span{attrs}></span>"
        value = html.escape(str(values.get(key, "")))
        return f"<span{attrs}>{value}</span>"

    return _VARIABLE_SPAN.sub(replace, html_body)


def render_markdown_html(
    markdown_text: str,
    variables: Mapping[str, str] | None = None,
) -> str:
    """Convierte el Markdown normalizado a un documento HTML completo."""
    import markdown as md

    html_body = md.markdown(
        normalize_markdown(markdown_text),
        extensions=["tables", "fenced_code", "sane_lists"],
    )
    page_rule = _page_rule(html_body)
    html_body = _resolve_document_variables(html_body, variables)
    html_body = _move_running_elements_first(html_body)
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<style>{_PDF_CSS}\n{page_rule}</style></head><body>{html_body}</body></html>"
    )


def render_markdown_pdf(
    markdown_text: str,
    variables: Mapping[str, str] | None = None,
) -> bytes:
    """Convierte Markdown a PDF y devuelve los bytes."""
    from weasyprint import HTML

    return HTML(string=render_markdown_html(markdown_text, variables)).write_pdf()
