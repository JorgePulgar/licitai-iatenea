from app.services.memoria_export import normalize_markdown, render_markdown_html


def test_normalize_markdown_removes_document_fence():
    markdown = "```markdown\n# Memoria\n\nTexto con **formato**.\n```"

    assert normalize_markdown(markdown) == "# Memoria\n\nTexto con **formato**."


def test_normalize_markdown_preserves_regular_code_blocks():
    markdown = "# Memoria\n\n```python\nprint('ok')\n```"

    assert normalize_markdown(markdown) == markdown


def test_render_markdown_html_processes_wrapped_markdown():
    html = render_markdown_html("```md\n# Memoria\n\nTexto con **formato**.\n```")

    assert "<h1>Memoria</h1>" in html
    assert "<strong>formato</strong>" in html
    assert "language-md" not in html
    assert 'content: "Página " counter(page) " de " counter(pages)' in html


def test_render_markdown_html_keeps_document_components():
    markdown = """
<header class="document-header">Cabecera corporativa</header>

# Memoria

<figure class="document-video">
  <span class="document-video__label">Vídeo de presentación</span>
  <a href="https://example.com/video">https://example.com/video</a>
</figure>

<footer class="document-footer">Oferta técnica</footer>
"""

    html = render_markdown_html(markdown)

    assert '<header class="document-header">Cabecera corporativa</header>' in html
    assert '<figure class="document-video">' in html
    assert '<footer class="document-footer">Oferta técnica</footer>' in html
    assert html.index('<header class="document-header">') < html.index("<h1>Memoria</h1>")
    assert html.index('<footer class="document-footer">') < html.index("<h1>Memoria</h1>")


def test_render_markdown_html_resolves_variables_and_page_settings():
    markdown = """
<div class="document-settings" data-page-size="letter" data-orientation="landscape"></div>
<header class="document-header">
  <span class="document-variable" data-variable="company_name">Nombre de empresa</span>
</header>
<footer class="document-footer">
  Página <span class="document-variable" data-variable="page">Página actual</span>
  de <span class="document-variable" data-variable="pages">Total de páginas</span>
</footer>

# Memoria
"""

    html = render_markdown_html(markdown, {"company_name": "Empresa & Asociados"})

    assert "@page { size: Letter landscape;" in html
    assert "Empresa &amp; Asociados" in html
    assert 'data-variable="page"></span>' in html
    assert 'data-variable="pages"></span>' in html
    assert 'content: "Página " counter(page) " de " counter(pages)' not in html


def test_render_markdown_html_keeps_image_layout_attributes():
    markdown = """
<figure class="document-image" data-width="50" data-rotation="90" data-align="right"
 style="width:50%;margin-left:auto;margin-right:0;">
  <img src="data:image/png;base64,abc" alt="Plano" style="transform:rotate(90deg);">
</figure>
"""

    html = render_markdown_html(markdown)

    assert 'data-width="50"' in html
    assert "transform:rotate(90deg)" in html
