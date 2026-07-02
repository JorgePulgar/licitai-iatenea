import { marked } from 'marked';
import TurndownService from 'turndown';
import { gfm } from 'turndown-plugin-gfm';

const OUTER_MARKDOWN_FENCE =
  /^\s*```(?:markdown|md)?[ \t]*\r?\n([\s\S]*?)\r?\n```[ \t]*\s*$/i;

// Una línea que abre/cierra un bloque de código: captura el lenguaje (info string).
const FENCE_LINE = /^[ \t]*(?:```|~~~)[ \t]*([A-Za-z0-9_+-]*)[ \t]*$/;

/**
 * Quita los "fences" que algún agente generó por error envolviendo prosa Markdown
 * (```markdown … ``` o ``` … ```), incluso si quedaron sin cerrar. marked los pinta
 * como bloque de código monoespaciado y deja el `##`/`**` sin interpretar.
 *
 * Conserva los bloques con lenguaje real (```python, ```ts, …): una Memoria Técnica no
 * contiene código, así que solo desenvolvemos fences sin lenguaje o etiquetados
 * markdown/md, que siempre son un error del modelo.
 */
function stripStrayMarkdownFences(markdown: string): string {
  const lines = markdown.split('\n');
  const out: string[] = [];
  let inStray = false;   // fence de prosa mal generado → se elimina la línea de fence
  let inCode = false;    // fence con lenguaje real → se conserva intacto

  for (const line of lines) {
    const match = line.match(FENCE_LINE);
    if (match) {
      const info = match[1].toLowerCase();
      if (inCode) { out.push(line); inCode = false; continue; }   // cierre de código real
      if (inStray) { inStray = false; continue; }                 // cierre del fence espurio
      if (info === '' || info === 'markdown' || info === 'md') {
        inStray = true;                                           // apertura espuria → drop
        continue;
      }
      out.push(line); inCode = true; continue;                    // apertura de código real
    }
    out.push(line);
  }
  return out.join('\n');
}

export function normalizeDocumentMarkdown(markdown: string): string {
  const match = markdown.match(OUTER_MARKDOWN_FENCE);
  const unwrapped = match ? match[1] : markdown;
  return stripStrayMarkdownFences(unwrapped);
}

export function documentMarkdownToHtml(markdown: string): string {
  return marked.parse(normalizeDocumentMarkdown(markdown), {
    async: false,
    gfm: true,
    breaks: false,
  }) as string;
}

function elementHasClass(node: Node, className: string): node is HTMLElement {
  return node instanceof HTMLElement && node.classList.contains(className);
}

function rawBlock(node: Node): string {
  return `\n\n${(node as HTMLElement).outerHTML}\n\n`;
}

const turndown = new TurndownService({
  bulletListMarker: '-',
  codeBlockStyle: 'fenced',
  emDelimiter: '*',
  headingStyle: 'atx',
  strongDelimiter: '**',
});

turndown.use(gfm);

turndown.addRule('documentSettings', {
  filter: node => elementHasClass(node, 'document-settings'),
  replacement: (_content, node) => rawBlock(node),
});

turndown.addRule('documentHeader', {
  filter: node => elementHasClass(node, 'document-header'),
  replacement: (_content, node) => rawBlock(node),
});

turndown.addRule('documentFooter', {
  filter: node => elementHasClass(node, 'document-footer'),
  replacement: (_content, node) => rawBlock(node),
});

turndown.addRule('documentVideo', {
  filter: node => elementHasClass(node, 'document-video'),
  replacement: (_content, node) => rawBlock(node),
});

turndown.addRule('documentImage', {
  filter: node => elementHasClass(node, 'document-image'),
  replacement: (_content, node) => rawBlock(node),
});

turndown.addRule('pageBreak', {
  filter: node => elementHasClass(node, 'page-break'),
  replacement: () => '\n\n<div class="page-break"></div>\n\n',
});

turndown.addRule('underline', {
  filter: ['u'],
  replacement: (_content, node) => (node as HTMLElement).outerHTML,
});

turndown.addRule('alignedBlock', {
  filter: node => {
    if (!(node instanceof HTMLElement)) return false;
    if (!['P', 'H1', 'H2', 'H3'].includes(node.tagName)) return false;
    const alignment = node.style.textAlign;
    return Boolean(alignment && alignment !== 'left' && alignment !== 'start');
  },
  replacement: (_content, node) => rawBlock(node),
});

export function documentHtmlToMarkdown(html: string): string {
  return turndown
    .turndown(html)
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}
