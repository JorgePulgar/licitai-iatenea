import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { Extension, Node, mergeAttributes } from '@tiptap/core';
import type { Node as ProseMirrorNode } from '@tiptap/pm/model';
import { Plugin, PluginKey } from '@tiptap/pm/state';
import { Decoration, DecorationSet } from '@tiptap/pm/view';
import ImageExtension from '@tiptap/extension-image';
import LinkExtension from '@tiptap/extension-link';
import Placeholder from '@tiptap/extension-placeholder';
import TableExtension from '@tiptap/extension-table';
import TableCell from '@tiptap/extension-table-cell';
import TableHeader from '@tiptap/extension-table-header';
import TableRow from '@tiptap/extension-table-row';
import TextAlign from '@tiptap/extension-text-align';
import UnderlineExtension from '@tiptap/extension-underline';
import StarterKit from '@tiptap/starter-kit';
import {
  EditorContent,
  NodeViewWrapper,
  ReactNodeViewRenderer,
  useEditor,
  type Editor,
  type NodeViewProps,
} from '@tiptap/react';
import {
  AlignCenter,
  AlignJustify,
  AlignLeft,
  AlignRight,
  Bold,
  Image,
  Italic,
  Link,
  List,
  ListOrdered,
  Minus,
  PanelBottom,
  PanelTop,
  Quote,
  Redo2,
  RotateCw,
  Strikethrough,
  Table,
  Trash2,
  Underline,
  Undo2,
  Video,
} from 'lucide-react';

import { useModal } from '../hooks/useModal';
import {
  documentHtmlToMarkdown,
  documentMarkdownToHtml,
} from '../utils/documentMarkdown';
import './RichDocumentEditor.css';

interface RichDocumentEditorProps {
  markdown: string;
  onChange: (markdown: string) => void;
  disabled?: boolean;
}

interface TextDialogProps {
  label: string;
  initialValue?: string;
  placeholder?: string;
  multiline?: boolean;
  submitLabel: string;
  close: (value: string) => void;
  dismiss: () => void;
}

interface MediaDialogValue {
  url: string;
  label: string;
}

interface DocumentVariableDefinition {
  key: string;
  label: string;
}

type PageSize = 'a4' | 'letter' | 'a3';
type PageOrientation = 'portrait' | 'landscape';

interface PageSettings {
  size: PageSize;
  orientation: PageOrientation;
}

const PAGE_DIMENSIONS: Record<PageSize, { width: number; height: number }> = {
  a4: { width: 794, height: 1123 },
  letter: { width: 816, height: 1056 },
  a3: { width: 1123, height: 1587 },
};

const PaginationGuides = Extension.create({
  name: 'paginationGuides',
  addProseMirrorPlugins() {
    const key = new PluginKey<DecorationSet>('documentPaginationGuides');

    return [
      new Plugin<DecorationSet>({
        key,
        state: {
          init: () => DecorationSet.empty,
          apply(transaction, current) {
            const next = transaction.getMeta(key) as Decoration[] | undefined;
            if (next) return DecorationSet.create(transaction.doc, next);
            return current.map(transaction.mapping, transaction.doc);
          },
        },
        props: {
          decorations(state) {
            return key.getState(state);
          },
        },
        view(initialView) {
          let view = initialView;
          let frame = 0;
          let ignoreNextUpdate = false;

          const measure = () => {
            const paper = view.dom.closest<HTMLElement>('.document-editor__paper');
            if (!paper) return;

            const paperStyles = getComputedStyle(paper);
            const contentStyles = getComputedStyle(view.dom);
            const pageHeight = parseFloat(paperStyles.getPropertyValue('--document-page-height')) || 1123;
            const pageCycle = parseFloat(paperStyles.getPropertyValue('--document-page-cycle')) || pageHeight + 28;
            const pageGap = Math.max(0, pageCycle - pageHeight);
            const topPadding = parseFloat(contentStyles.paddingTop) || 72;
            const bottomPadding = parseFloat(contentStyles.paddingBottom) || 80;
            const usablePageHeight = pageHeight - topPadding - bottomPadding;
            const viewTop = view.dom.getBoundingClientRect().top;
            const decorations: Decoration[] = [];

            // `shift` accumulates the total extra height introduced by the page
            // pushes. Each block's virtual position = its natural DOM position + shift.
            let shift = 0;
            // Bottom of the previous block in *clean* (un-paginated) coordinates.
            // We push a block to the next page by enlarging its own `margin-top`
            // (which keeps CSS margin-collapsing intact) instead of injecting a
            // sized spacer element: a spacer breaks the margin collapse between its
            // neighbours, and the resulting ~10px error per page accumulates into a
            // visible drift (the badge and the content slide into the sheet on late
            // pages). Recovering the collapsed margin needs the previous bottom.
            let prevNaturalBottom: number | null = null;

            view.state.doc.forEach((node, offset) => {
              const dom = view.nodeDOM(offset);
              if (!(dom instanceof HTMLElement)) return;

              const rect = dom.getBoundingClientRect();
              const naturalTop = rect.top - viewTop;
              const blockHeight = rect.height;
              // Collapsed margin that precedes this block in the clean flow.
              const gapClean = prevNaturalBottom === null
                ? 0
                : Math.max(0, naturalTop - prevNaturalBottom);
              prevNaturalBottom = naturalTop + blockHeight;

              // Where this block would appear in the virtual (paginated) layout.
              let virtualTop = naturalTop + shift;

              // Which page does virtualTop fall on?
              let pageIdx = Math.max(0, Math.floor(virtualTop / pageCycle));
              let pageContentStart = pageIdx * pageCycle + topPadding;
              let pageContentEnd = pageIdx * pageCycle + pageHeight - bottomPadding;

              // If virtualTop landed in the gap/padding zone between pages,
              // advance to the next page's content start.
              if (virtualTop >= pageContentEnd) {
                pageIdx = pageIdx + 1;
                pageContentStart = pageIdx * pageCycle + topPadding;
                pageContentEnd = pageIdx * pageCycle + pageHeight - bottomPadding;
              }

              // ── Handle explicit page breaks ──
              if (node.type.name === 'pageBreak') {
                const nextPageStart = (pageIdx + 1) * pageCycle + topPadding;
                const breakHeight = Math.max(42, nextPageStart - virtualTop);
                const separatorOffset = pageIdx * pageCycle + pageHeight - virtualTop + pageGap / 2;
                decorations.push(
                  Decoration.node(offset, offset + node.nodeSize, {
                    style: `height:${breakHeight}px;--page-separator-offset:${separatorOffset}px;`,
                    'data-page-number': String(pageIdx + 2),
                  }),
                );
                // The page-break node's natural height is replaced by breakHeight.
                shift += breakHeight - blockHeight;
                return;
              }

              // ── Check if block needs to be pushed to the next page ──
              // Two cases: (a) block starts in the dead zone, (b) block overflows.
              let needsSpacer = false;
              let targetTop = 0;
              let badgePage = 0;

              if (virtualTop < pageContentStart && pageIdx > 0) {
                // (a) Block starts in the gap/padding zone — push to content start.
                needsSpacer = true;
                targetTop = pageContentStart;
                badgePage = pageIdx + 1;
              } else if (
                virtualTop + blockHeight > pageContentEnd &&
                blockHeight <= usablePageHeight
              ) {
                // (b) Block starts in the content area but overflows — push to next page.
                needsSpacer = true;
                const nextPageIdx = pageIdx + 1;
                targetTop = nextPageIdx * pageCycle + topPadding;
                badgePage = nextPageIdx + 1;
              }

              if (needsSpacer) {
                const extra = targetTop - virtualTop;
                if (extra > 0) {
                  // Push via the block's own top margin (collapse-safe): the block
                  // keeps its natural collapsed margin (`gapClean`) plus the gap to
                  // the next page, so it lands exactly on `targetTop` and downstream
                  // blocks shift by `extra` only.
                  const marginTop = gapClean + extra;
                  // The badge holder renders just past the previous block's own
                  // margin (`gapClean`), so the boundary strip sits exactly
                  // `extra - (topPadding + pageGap/2)` below it — independent of
                  // accumulated drift and of the surrounding margins.
                  const badgeOffset = extra - (topPadding + pageGap / 2);

                  decorations.push(
                    Decoration.node(offset, offset + node.nodeSize, {
                      style: `margin-top:${marginTop}px;`,
                    }),
                  );
                  // Zero-height, collapse-transparent widget that only carries the
                  // "Página N" badge, anchored to the boundary strip above the block.
                  decorations.push(
                    Decoration.widget(
                      offset,
                      () => {
                        const badge = document.createElement('div');
                        badge.className = 'document-auto-page-break';
                        badge.contentEditable = 'false';
                        badge.style.setProperty('--page-separator-offset', `${badgeOffset}px`);
                        badge.dataset.pageNumber = String(badgePage);
                        return badge;
                      },
                      { side: -1, key: `page-${badgePage}-${offset}` },
                    ),
                  );
                  shift += extra;
                }
              }
            });

            ignoreNextUpdate = true;
            view.dispatch(view.state.tr.setMeta(key, decorations));
          };

          const schedule = () => {
            cancelAnimationFrame(frame);
            frame = requestAnimationFrame(() => {
              const current = key.getState(view.state);
              if (current && current.find().length > 0) {
                ignoreNextUpdate = true;
                view.dispatch(view.state.tr.setMeta(key, []));
                frame = requestAnimationFrame(measure);
              } else {
                measure();
              }
            });
          };

          window.addEventListener('resize', schedule);
          schedule();

          return {
            update(nextView, previousState) {
              view = nextView;
              if (ignoreNextUpdate) {
                ignoreNextUpdate = false;
                return;
              }
              if (!nextView.state.doc.eq(previousState.doc)) schedule();
            },
            destroy() {
              cancelAnimationFrame(frame);
              window.removeEventListener('resize', schedule);
            },
          };
        },
      }),
    ];
  },
});

function pageSettingsFromMarkdown(markdown: string): PageSettings | null {
  const match = markdown.match(
    /<div\b(?=[^>]*\bclass=["'][^"']*\bdocument-settings\b[^"']*["'])([^>]*)><\/div>/i,
  );
  if (!match) return null;
  const attrs = match?.[1] ?? '';
  const sizeMatch = attrs.match(/\bdata-page-size=["'](a4|letter|a3)["']/i);
  const orientationMatch = attrs.match(/\bdata-orientation=["'](portrait|landscape)["']/i);
  return {
    size: (sizeMatch?.[1]?.toLowerCase() as PageSize | undefined) ?? 'a4',
    orientation: (orientationMatch?.[1]?.toLowerCase() as PageOrientation | undefined) ?? 'portrait',
  };
}

const DocumentSettings = Node.create({
  name: 'documentSettings',
  group: 'block',
  atom: true,
  selectable: false,
  addAttributes() {
    return {
      pageSize: { default: 'a4' },
      orientation: { default: 'portrait' },
    };
  },
  parseHTML() {
    return [{
      tag: 'div.document-settings',
      getAttrs: element => {
        const node = element as HTMLElement;
        return {
          pageSize: node.dataset.pageSize || 'a4',
          orientation: node.dataset.orientation || 'portrait',
        };
      },
    }];
  },
  renderHTML({ node }) {
    return [
      'div',
      {
        class: 'document-settings',
        'data-page-size': node.attrs.pageSize,
        'data-orientation': node.attrs.orientation,
      },
    ];
  },
});

const DOCUMENT_VARIABLES: DocumentVariableDefinition[] = [
  { key: 'page', label: 'Página actual' },
  { key: 'pages', label: 'Total de páginas' },
  { key: 'current_date', label: 'Fecha actual' },
  { key: 'current_year', label: 'Año actual' },
  { key: 'company_name', label: 'Nombre de empresa' },
  { key: 'tender_title', label: 'Nombre de licitación' },
  { key: 'document_title', label: 'Título del documento' },
  { key: 'user_name', label: 'Nombre del usuario' },
  { key: 'user_email', label: 'Email del usuario' },
];

const DOCUMENT_VARIABLE_BY_KEY = new Map(
  DOCUMENT_VARIABLES.map(variable => [variable.key, variable]),
);

function variableTemplateForDisplay(template: string): string {
  return template.replace(/\{\{([a-z_]+)\}\}/g, (token, key: string) => {
    const variable = DOCUMENT_VARIABLE_BY_KEY.get(key);
    return variable ? `«${variable.label}»` : token;
  });
}

function variableTemplateForStorage(template: string): string {
  return DOCUMENT_VARIABLES.reduce(
    (current, variable) => current
      .split(`«${variable.label}»`)
      .join(`{{${variable.key}}}`),
    template,
  );
}

const DocumentVariable = Node.create({
  name: 'documentVariable',
  group: 'inline',
  inline: true,
  atom: true,
  selectable: true,
  addAttributes() {
    return {
      key: { default: '' },
      label: { default: 'Variable' },
    };
  },
  parseHTML() {
    return [{
      tag: 'span.document-variable',
      getAttrs: element => {
        const node = element as HTMLElement;
        const key = node.dataset.variable || '';
        return {
          key,
          label: node.dataset.label || DOCUMENT_VARIABLE_BY_KEY.get(key)?.label || 'Variable',
        };
      },
    }];
  },
  renderHTML({ node, HTMLAttributes }) {
    const key = String(node.attrs.key || '');
    const label = String(node.attrs.label || DOCUMENT_VARIABLE_BY_KEY.get(key)?.label || 'Variable');
    return [
      'span',
      mergeAttributes(HTMLAttributes, {
        class: 'document-variable',
        'data-variable': key,
        'data-label': label,
      }),
      label,
    ];
  },
});

const DocumentHeader = Node.create({
  name: 'documentHeader',
  group: 'block',
  content: 'inline*',
  defining: true,
  parseHTML() {
    return [{ tag: 'header.document-header' }];
  },
  renderHTML({ HTMLAttributes }) {
    return ['header', mergeAttributes(HTMLAttributes, { class: 'document-header' }), 0];
  },
});

const DocumentFooter = Node.create({
  name: 'documentFooter',
  group: 'block',
  content: 'inline*',
  defining: true,
  parseHTML() {
    return [{ tag: 'footer.document-footer' }];
  },
  renderHTML({ HTMLAttributes }) {
    return ['footer', mergeAttributes(HTMLAttributes, { class: 'document-footer' }), 0];
  },
});

const PageBreak = Node.create({
  name: 'pageBreak',
  group: 'block',
  atom: true,
  selectable: true,
  parseHTML() {
    return [{ tag: 'div.page-break' }];
  },
  renderHTML({ HTMLAttributes }) {
    return [
      'div',
      mergeAttributes(HTMLAttributes, {
        class: 'page-break',
        'data-label': 'Salto de página',
      }),
    ];
  },
});

const VideoCard = Node.create({
  name: 'videoCard',
  group: 'block',
  atom: true,
  selectable: true,
  addAttributes() {
    return {
      src: { default: '' },
      title: { default: 'Vídeo' },
    };
  },
  parseHTML() {
    return [{
      tag: 'figure.document-video',
      getAttrs: element => {
        const node = element as HTMLElement;
        const anchor = node.querySelector<HTMLAnchorElement>('a');
        const label = node.querySelector<HTMLElement>('.document-video__label');
        return {
          src: node.dataset.videoUrl || anchor?.href || '',
          title: label?.textContent || 'Vídeo',
        };
      },
    }];
  },
  renderHTML({ node, HTMLAttributes }) {
    const src = String(node.attrs.src || '');
    const title = String(node.attrs.title || 'Vídeo');
    return [
      'figure',
      mergeAttributes(HTMLAttributes, {
        class: 'document-video',
        'data-video-url': src,
      }),
      ['span', { class: 'document-video__label' }, title],
      ['a', { href: src, target: '_blank', rel: 'noopener noreferrer' }, src],
    ];
  },
});

function EditableImageView({
  node,
  selected,
  updateAttributes,
  deleteNode,
}: NodeViewProps) {
  const width = Number(node.attrs.width || 100);
  const rotation = Number(node.attrs.rotation || 0);
  const alignment = String(node.attrs.alignment || 'center');
  const alignmentStyle = alignment === 'left'
    ? { marginLeft: 0, marginRight: 'auto' }
    : alignment === 'right'
      ? { marginLeft: 'auto', marginRight: 0 }
      : { marginLeft: 'auto', marginRight: 'auto' };

  return (
    <NodeViewWrapper
      as="figure"
      className={`document-image ${selected ? 'is-selected' : ''}`}
      data-width={width}
      data-rotation={rotation}
      data-align={alignment}
      style={{ width: `${width}%`, ...alignmentStyle }}
    >
      {selected && (
        <div className="document-image__controls" contentEditable={false}>
          <span className="document-image__drag" data-drag-handle title="Arrastrar imagen">
            ⋮⋮
          </span>
          <input
            type="range"
            min="20"
            max="100"
            step="5"
            value={width}
            onChange={event => updateAttributes({ width: Number(event.target.value) })}
            aria-label="Tamaño de imagen"
            title="Cambiar tamaño de imagen"
          />
          <span className="document-image__size">{width}%</span>
          {[25, 50, 75, 100].map(size => (
            <button
              key={size}
              type="button"
              className={width === size ? 'is-active' : ''}
              title={`Ajustar imagen al ${size}%`}
              onClick={() => updateAttributes({ width: size })}
            >
              {size}
            </button>
          ))}
          <span className="document-image__separator" />
          <button type="button" title="Girar 90 grados" onClick={() => updateAttributes({ rotation: (rotation + 90) % 360 })}>
            <RotateCw size={14} />
          </button>
          <button type="button" title="Alinear a la izquierda" className={alignment === 'left' ? 'is-active' : ''} onClick={() => updateAttributes({ alignment: 'left' })}>
            <AlignLeft size={14} />
          </button>
          <button type="button" title="Centrar" className={alignment === 'center' ? 'is-active' : ''} onClick={() => updateAttributes({ alignment: 'center' })}>
            <AlignCenter size={14} />
          </button>
          <button type="button" title="Alinear a la derecha" className={alignment === 'right' ? 'is-active' : ''} onClick={() => updateAttributes({ alignment: 'right' })}>
            <AlignRight size={14} />
          </button>
          <button type="button" title="Eliminar imagen" className="is-danger" onClick={deleteNode}>
            <Trash2 size={14} />
          </button>
        </div>
      )}
      <img
        src={String(node.attrs.src || '')}
        alt={String(node.attrs.alt || '')}
        title={String(node.attrs.title || '')}
        draggable={false}
        style={{ transform: `rotate(${rotation}deg)` }}
      />
    </NodeViewWrapper>
  );
}

const EditableImage = ImageExtension.extend({
  draggable: true,
  addAttributes() {
    return {
      src: { default: null },
      alt: { default: null },
      title: { default: null },
      width: { default: 100 },
      rotation: { default: 0 },
      alignment: { default: 'center' },
    };
  },
  parseHTML() {
    return [
      {
        tag: 'figure.document-image',
        getAttrs: element => {
          const figure = element as HTMLElement;
          const image = figure.querySelector<HTMLImageElement>('img');
          return {
            src: image?.getAttribute('src'),
            alt: image?.getAttribute('alt'),
            title: image?.getAttribute('title'),
            width: Number(figure.dataset.width || 100),
            rotation: Number(figure.dataset.rotation || 0),
            alignment: figure.dataset.align || 'center',
          };
        },
      },
      {
        tag: 'img[src]',
        getAttrs: element => {
          const image = element as HTMLImageElement;
          return {
            src: image.getAttribute('src'),
            alt: image.getAttribute('alt'),
            title: image.getAttribute('title'),
            width: 100,
            rotation: 0,
            alignment: 'center',
          };
        },
      },
    ];
  },
  renderHTML({ node, HTMLAttributes }) {
    const width = Math.min(100, Math.max(20, Number(node.attrs.width || 100)));
    const rotation = Number(node.attrs.rotation || 0) % 360;
    const alignment = ['left', 'center', 'right'].includes(String(node.attrs.alignment))
      ? String(node.attrs.alignment)
      : 'center';
    const margins = alignment === 'left'
      ? 'margin-left:0;margin-right:auto;'
      : alignment === 'right'
        ? 'margin-left:auto;margin-right:0;'
        : 'margin-left:auto;margin-right:auto;';

    return [
      'figure',
      {
        class: 'document-image',
        'data-width': width,
        'data-rotation': rotation,
        'data-align': alignment,
        style: `width:${width}%;${margins}`,
      },
      [
        'img',
        mergeAttributes(HTMLAttributes, {
          style: `transform:rotate(${rotation}deg);`,
        }),
      ],
    ];
  },
  addNodeView() {
    return ReactNodeViewRenderer(EditableImageView);
  },
});

function TextDialog({
  label,
  initialValue = '',
  placeholder,
  multiline = false,
  submitLabel,
  close,
  dismiss,
}: TextDialogProps) {
  const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement>(null);

  return (
    <form
      className="space-y-4"
      onSubmit={event => {
        event.preventDefault();
        close(inputRef.current?.value.trim() ?? '');
      }}
    >
      <label className="block">
        <span className="label">{label}</span>
        {multiline ? (
          <textarea
            ref={inputRef as React.RefObject<HTMLTextAreaElement>}
            className="real-input min-h-24 h-auto py-2 resize-y"
            defaultValue={initialValue}
            placeholder={placeholder}
            autoFocus
          />
        ) : (
          <input
            ref={inputRef as React.RefObject<HTMLInputElement>}
            className="real-input"
            defaultValue={initialValue}
            placeholder={placeholder}
            autoFocus
          />
        )}
      </label>
      <div className="flex justify-end gap-2">
        <button type="button" className="btn" onClick={dismiss}>
          Cancelar
        </button>
        <button type="submit" className="btn primary">
          {submitLabel}
        </button>
      </div>
    </form>
  );
}

function HeaderFooterDialog({
  initialValue,
  close,
  dismiss,
}: {
  initialValue: string;
  close: (value: string) => void;
  dismiss: () => void;
}) {
  const [value, setValue] = useState(() => variableTemplateForDisplay(initialValue));
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const insertVariable = (variable: DocumentVariableDefinition) => {
    const textarea = textareaRef.current;
    const token = `«${variable.label}»`;
    if (!textarea) {
      setValue(current => `${current}${token}`);
      return;
    }
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    setValue(current => `${current.slice(0, start)}${token}${current.slice(end)}`);
    requestAnimationFrame(() => {
      textarea.focus();
      textarea.setSelectionRange(start + token.length, start + token.length);
    });
  };

  return (
    <form
      className="space-y-4"
      onSubmit={event => {
        event.preventDefault();
        close(variableTemplateForStorage(value.trim()));
      }}
    >
      <label className="block">
        <span className="label">Contenido</span>
        <textarea
          ref={textareaRef}
          className="real-input min-h-24 h-auto py-2 resize-y font-mono"
          value={value}
          onChange={event => setValue(event.target.value)}
          placeholder="Texto del encabezado o pie"
          autoFocus
        />
      </label>
      <div>
        <div className="label">Insertar variable</div>
        <div className="document-variable-picker">
          {DOCUMENT_VARIABLES.map(variable => (
            <button
              key={variable.key}
              type="button"
              title={`Insertar ${variable.label.toLowerCase()}`}
              onClick={() => insertVariable(variable)}
            >
              {variable.label}
            </button>
          ))}
        </div>
        <p className="mt-2 text-11 text-ink-3">
          Las variables se actualizarán al exportar el PDF.
        </p>
      </div>
      <div className="flex justify-end gap-2">
        <button type="button" className="btn" onClick={dismiss}>
          Cancelar
        </button>
        <button type="submit" className="btn primary">
          Aplicar
        </button>
      </div>
    </form>
  );
}

function MediaDialog({
  kind,
  close,
  dismiss,
}: {
  kind: 'image' | 'video';
  close: (value: MediaDialogValue) => void;
  dismiss: () => void;
}) {
  const urlRef = useRef<HTMLInputElement>(null);
  const labelRef = useRef<HTMLInputElement>(null);

  return (
    <form
      className="space-y-4"
      onSubmit={event => {
        event.preventDefault();
        const url = urlRef.current?.value.trim() ?? '';
        if (!url) return;
        close({
          url,
          label: labelRef.current?.value.trim() || (kind === 'video' ? 'Vídeo' : 'Imagen'),
        });
      }}
    >
      <label className="block">
        <span className="label">URL</span>
        <input
          ref={urlRef}
          className="real-input"
          type="url"
          placeholder={kind === 'video' ? 'https://…/video' : 'https://…/imagen.jpg'}
          autoFocus
          required
        />
      </label>
      <label className="block">
        <span className="label">{kind === 'video' ? 'Título del vídeo' : 'Texto alternativo'}</span>
        <input ref={labelRef} className="real-input" placeholder={kind === 'video' ? 'Vídeo de presentación' : 'Descripción de la imagen'} />
      </label>
      <div className="flex justify-end gap-2">
        <button type="button" className="btn" onClick={dismiss}>
          Cancelar
        </button>
        <button type="submit" className="btn primary">
          Insertar
        </button>
      </div>
    </form>
  );
}

function ToolbarButton({
  active = false,
  disabled = false,
  label,
  onClick,
  children,
}: {
  active?: boolean;
  disabled?: boolean;
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      className={`document-toolbar__button ${active ? 'is-active' : ''}`}
      onClick={onClick}
      disabled={disabled}
      title={label}
      data-tooltip={label}
      aria-label={label}
    >
      {children}
    </button>
  );
}

function documentNodeTemplate(node: ProseMirrorNode): string {
  let template = '';
  node.forEach(child => {
    if (child.type.name === 'documentVariable') {
      template += `{{${String(child.attrs.key || '')}}}`;
    } else {
      template += child.textContent;
    }
  });
  return template;
}

function findNodePosition(editor: Editor, type: string): number | null {
  let found: number | null = null;
  editor.state.doc.descendants((node, pos) => {
    if (node.type.name === type) {
      found = pos;
      return false;
    }
    return true;
  });
  return found;
}

function findDocumentNode(editor: Editor, type: string): { pos: number; template: string } | null {
  let found: { pos: number; template: string } | null = null;
  editor.state.doc.descendants((node, pos) => {
    if (node.type.name === type) {
      found = { pos, template: documentNodeTemplate(node) };
      return false;
    }
    return true;
  });
  return found;
}

function templateContent(editor: Editor, template: string) {
  const content = [];
  const tokenPattern = /\{\{([a-z_]+)\}\}/g;
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = tokenPattern.exec(template)) !== null) {
    if (match.index > cursor) {
      content.push(editor.state.schema.text(template.slice(cursor, match.index)));
    }
    const definition = DOCUMENT_VARIABLE_BY_KEY.get(match[1]);
    if (definition) {
      content.push(editor.state.schema.nodes.documentVariable.create({
        key: definition.key,
        label: definition.label,
      }));
    } else {
      content.push(editor.state.schema.text(match[0]));
    }
    cursor = match.index + match[0].length;
  }
  if (cursor < template.length) {
    content.push(editor.state.schema.text(template.slice(cursor)));
  }
  return content;
}

function upsertDocumentNode(
  editor: Editor,
  type: 'documentHeader' | 'documentFooter',
  text: string,
) {
  editor
    .chain()
    .focus()
    .command(({ state, tr }) => {
      const existing = findDocumentNode(editor, type);
      if (existing) {
        const current = state.doc.nodeAt(existing.pos);
        if (!current) return false;
        if (!text) {
          tr.delete(existing.pos, existing.pos + current.nodeSize);
          return true;
        }
        tr.replaceWith(
          existing.pos,
          existing.pos + current.nodeSize,
          current.type.create({}, templateContent(editor, text)),
        );
        return true;
      }

      if (!text) return true;
      const node = state.schema.nodes[type].create({}, templateContent(editor, text));
      tr.insert(type === 'documentHeader' ? 0 : state.doc.content.size, node);
      return true;
    })
    .run();
}

export default function RichDocumentEditor({
  markdown,
  onChange,
  disabled = false,
}: RichDocumentEditorProps) {
  const { showModal } = useModal();
  const imageFileRef = useRef<HTMLInputElement>(null);
  const lastEditorMarkdownRef = useRef(markdown);
  const [pageSettings, setPageSettings] = useState<PageSettings>(
    () => pageSettingsFromMarkdown(markdown) ?? { size: 'a4', orientation: 'portrait' },
  );

  const ensureDocumentSettings = (currentEditor: Editor, settings: PageSettings) => {
    if (findNodePosition(currentEditor, 'documentSettings') !== null) return;
    currentEditor.commands.insertContentAt(0, {
      type: 'documentSettings',
      attrs: {
        pageSize: settings.size,
        orientation: settings.orientation,
      },
    });
  };

  const editor = useEditor({
    extensions: [
      StarterKit,
      PaginationGuides,
      UnderlineExtension,
      LinkExtension.configure({
        autolink: true,
        openOnClick: false,
        protocols: ['http', 'https', 'mailto'],
      }),
      EditableImage.configure({
        allowBase64: true,
        inline: false,
      }),
      TextAlign.configure({
        types: ['heading', 'paragraph'],
        alignments: ['left', 'center', 'right', 'justify'],
      }),
      Placeholder.configure({
        placeholder: 'Empieza a redactar la memoria técnica…',
      }),
      TableExtension.configure({
        resizable: true,
      }),
      TableRow,
      TableHeader,
      TableCell,
      DocumentSettings,
      DocumentVariable,
      DocumentHeader,
      DocumentFooter,
      VideoCard,
      PageBreak,
    ],
    content: documentMarkdownToHtml(markdown),
    editable: !disabled,
    editorProps: {
      attributes: {
        class: 'document-editor__content',
        spellcheck: 'true',
      },
    },
    onCreate: ({ editor: currentEditor }) => {
      ensureDocumentSettings(currentEditor, pageSettings);
    },
    onUpdate: ({ editor: currentEditor }) => {
      const nextMarkdown = documentHtmlToMarkdown(currentEditor.getHTML());
      lastEditorMarkdownRef.current = nextMarkdown;
      onChange(nextMarkdown);
    },
  });

  useEffect(() => {
    if (!editor) return;
    editor.setEditable(!disabled);
  }, [disabled, editor]);

  useEffect(() => {
    if (!editor || markdown === lastEditorMarkdownRef.current) return;
    const nextSettings = pageSettingsFromMarkdown(markdown) ?? pageSettings;
    setPageSettings(nextSettings);
    lastEditorMarkdownRef.current = markdown;
    editor.commands.setContent(documentMarkdownToHtml(markdown), false);
    ensureDocumentSettings(editor, nextSettings);
  }, [editor, markdown]);

  if (!editor) {
    return <div className="document-editor__loading">Preparando editor…</div>;
  }

  const setBlockType = (value: string) => {
    if (value === 'paragraph') {
      editor.chain().focus().setParagraph().run();
      return;
    }
    const level = Number(value.replace('heading-', '')) as 1 | 2 | 3;
    editor.chain().focus().setHeading({ level }).run();
  };

  const currentBlock = editor.isActive('heading', { level: 1 })
    ? 'heading-1'
    : editor.isActive('heading', { level: 2 })
      ? 'heading-2'
      : editor.isActive('heading', { level: 3 })
        ? 'heading-3'
        : 'paragraph';

  const updatePageSettings = (patch: Partial<PageSettings>) => {
    const next = { ...pageSettings, ...patch };
    setPageSettings(next);
    editor
      .chain()
      .focus()
      .command(({ state, tr }) => {
        const position = findNodePosition(editor, 'documentSettings');
        if (position === null) {
          tr.insert(0, state.schema.nodes.documentSettings.create({
            pageSize: next.size,
            orientation: next.orientation,
          }));
          return true;
        }
        const current = state.doc.nodeAt(position);
        if (!current) return false;
        tr.setNodeMarkup(position, undefined, {
          ...current.attrs,
          pageSize: next.size,
          orientation: next.orientation,
        });
        return true;
      })
      .run();
  };

  const editHeaderOrFooter = async (type: 'documentHeader' | 'documentFooter') => {
    const existing = findDocumentNode(editor, type);
    const result = await showModal<string>({
      type: 'custom',
      title: type === 'documentHeader' ? 'Encabezado del documento' : 'Pie de página',
      description: 'Se repetirá automáticamente en todas las páginas del PDF. Déjalo vacío para eliminarlo.',
      content: controls => (
        <HeaderFooterDialog
          initialValue={existing?.template ?? ''}
          close={controls.close}
          dismiss={controls.dismiss}
        />
      ),
    });
    if (result !== undefined) upsertDocumentNode(editor, type, result);
  };

  const editLink = async () => {
    const current = String(editor.getAttributes('link').href || '');
    const result = await showModal<string>({
      type: 'custom',
      title: 'Insertar enlace',
      description: 'Selecciona primero el texto que quieres enlazar.',
      content: controls => (
        <TextDialog
          label="Dirección web"
          initialValue={current}
          placeholder="https://…"
          submitLabel="Aplicar"
          close={controls.close}
          dismiss={controls.dismiss}
        />
      ),
    });
    if (result === undefined) return;
    if (!result) {
      editor.chain().focus().extendMarkRange('link').unsetLink().run();
      return;
    }
    editor.chain().focus().extendMarkRange('link').setLink({ href: result }).run();
  };

  const insertRemoteMedia = async (kind: 'image' | 'video') => {
    const result = await showModal<MediaDialogValue>({
      type: 'custom',
      title: kind === 'video' ? 'Insertar vídeo' : 'Insertar imagen desde URL',
      description: kind === 'video'
        ? 'En el PDF aparecerá una tarjeta enlazada al vídeo.'
        : 'Usa una dirección accesible para que el servidor pueda incluirla en el PDF.',
      content: controls => (
        <MediaDialog kind={kind} close={controls.close} dismiss={controls.dismiss} />
      ),
    });
    if (!result) return;
    if (kind === 'image') {
      editor.chain().focus().insertContent({
        type: 'image',
        attrs: {
          src: result.url,
          alt: result.label,
          width: 100,
          rotation: 0,
          alignment: 'center',
        },
      }).run();
    } else {
      editor.chain().focus().insertContent({
        type: 'videoCard',
        attrs: { src: result.url, title: result.label },
      }).run();
    }
  };

  const insertLocalImage = async (file: File) => {
    if (file.size > 1_500_000) {
      await showModal({
        type: 'alert',
        tone: 'warning',
        title: 'Imagen demasiado grande',
        description: 'Usa una imagen de hasta 1,5 MB o insértala mediante una URL.',
      });
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const src = typeof reader.result === 'string' ? reader.result : '';
      if (src) {
        editor.chain().focus().insertContent({
          type: 'image',
          attrs: {
            src,
            alt: file.name,
            width: 100,
            rotation: 0,
            alignment: 'center',
          },
        }).run();
      }
    };
    reader.readAsDataURL(file);
  };

  const baseDimensions = PAGE_DIMENSIONS[pageSettings.size];
  const pageWidth = pageSettings.orientation === 'landscape'
    ? baseDimensions.height
    : baseDimensions.width;
  const pageHeight = pageSettings.orientation === 'landscape'
    ? baseDimensions.width
    : baseDimensions.height;
  const paperStyle = {
    '--document-page-width': `${pageWidth}px`,
    '--document-page-height': `${pageHeight}px`,
    '--document-page-cycle': `${pageHeight + 28}px`,
  } as CSSProperties;

  return (
    <div className={`document-editor ${disabled ? 'is-disabled' : ''}`}>
      <div className="document-toolbar" aria-label="Herramientas del documento">
        <div className="document-toolbar__group">
          <ToolbarButton label="Deshacer" onClick={() => editor.chain().focus().undo().run()} disabled={!editor.can().undo()}>
            <Undo2 size={16} />
          </ToolbarButton>
          <ToolbarButton label="Rehacer" onClick={() => editor.chain().focus().redo().run()} disabled={!editor.can().redo()}>
            <Redo2 size={16} />
          </ToolbarButton>
        </div>

        <div className="document-toolbar__group">
          <select
            className="document-toolbar__select"
            aria-label="Estilo de párrafo"
            title="Estilo de texto"
            value={currentBlock}
            onChange={event => setBlockType(event.target.value)}
          >
            <option value="paragraph">Texto normal</option>
            <option value="heading-1">Título 1</option>
            <option value="heading-2">Título 2</option>
            <option value="heading-3">Título 3</option>
          </select>
          <ToolbarButton label="Negrita" active={editor.isActive('bold')} onClick={() => editor.chain().focus().toggleBold().run()}>
            <Bold size={16} />
          </ToolbarButton>
          <ToolbarButton label="Cursiva" active={editor.isActive('italic')} onClick={() => editor.chain().focus().toggleItalic().run()}>
            <Italic size={16} />
          </ToolbarButton>
          <ToolbarButton label="Subrayado" active={editor.isActive('underline')} onClick={() => editor.chain().focus().toggleUnderline().run()}>
            <Underline size={16} />
          </ToolbarButton>
          <ToolbarButton label="Tachado" active={editor.isActive('strike')} onClick={() => editor.chain().focus().toggleStrike().run()}>
            <Strikethrough size={16} />
          </ToolbarButton>
        </div>

        <div className="document-toolbar__group">
          <ToolbarButton label="Lista con viñetas" active={editor.isActive('bulletList')} onClick={() => editor.chain().focus().toggleBulletList().run()}>
            <List size={16} />
          </ToolbarButton>
          <ToolbarButton label="Lista numerada" active={editor.isActive('orderedList')} onClick={() => editor.chain().focus().toggleOrderedList().run()}>
            <ListOrdered size={16} />
          </ToolbarButton>
          <ToolbarButton label="Cita" active={editor.isActive('blockquote')} onClick={() => editor.chain().focus().toggleBlockquote().run()}>
            <Quote size={16} />
          </ToolbarButton>
        </div>

        <div className="document-toolbar__group">
          <ToolbarButton label="Alinear a la izquierda" active={editor.isActive({ textAlign: 'left' })} onClick={() => editor.chain().focus().setTextAlign('left').run()}>
            <AlignLeft size={16} />
          </ToolbarButton>
          <ToolbarButton label="Centrar" active={editor.isActive({ textAlign: 'center' })} onClick={() => editor.chain().focus().setTextAlign('center').run()}>
            <AlignCenter size={16} />
          </ToolbarButton>
          <ToolbarButton label="Alinear a la derecha" active={editor.isActive({ textAlign: 'right' })} onClick={() => editor.chain().focus().setTextAlign('right').run()}>
            <AlignRight size={16} />
          </ToolbarButton>
          <ToolbarButton label="Justificar" active={editor.isActive({ textAlign: 'justify' })} onClick={() => editor.chain().focus().setTextAlign('justify').run()}>
            <AlignJustify size={16} />
          </ToolbarButton>
        </div>

        <div className="document-toolbar__group">
          <ToolbarButton label="Insertar enlace" active={editor.isActive('link')} onClick={() => void editLink()}>
            <Link size={16} />
          </ToolbarButton>
          <ToolbarButton label="Insertar imagen desde archivo" onClick={() => imageFileRef.current?.click()}>
            <Image size={16} />
          </ToolbarButton>
          <ToolbarButton label="Insertar imagen desde URL" onClick={() => void insertRemoteMedia('image')}>
            <Image size={16} />
            <span className="document-toolbar__badge">URL</span>
          </ToolbarButton>
          <ToolbarButton label="Insertar vídeo" onClick={() => void insertRemoteMedia('video')}>
            <Video size={16} />
          </ToolbarButton>
          <ToolbarButton label="Insertar tabla" onClick={() => editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()}>
            <Table size={16} />
          </ToolbarButton>
          <ToolbarButton label="Insertar separador" onClick={() => editor.chain().focus().setHorizontalRule().run()}>
            <Minus size={16} />
          </ToolbarButton>
        </div>

        <div className="document-toolbar__group">
          <select
            className="document-toolbar__select document-toolbar__select--page"
            aria-label="Tamaño de página"
            title="Tamaño de página"
            value={pageSettings.size}
            onChange={event => updatePageSettings({ size: event.target.value as PageSize })}
          >
            <option value="a4">A4</option>
            <option value="letter">Carta</option>
            <option value="a3">A3</option>
          </select>
          <select
            className="document-toolbar__select document-toolbar__select--page"
            aria-label="Orientación de página"
            title="Orientación de página"
            value={pageSettings.orientation}
            onChange={event => updatePageSettings({ orientation: event.target.value as PageOrientation })}
          >
            <option value="portrait">Vertical</option>
            <option value="landscape">Horizontal</option>
          </select>
          <ToolbarButton label="Editar encabezado" active={Boolean(findDocumentNode(editor, 'documentHeader'))} onClick={() => void editHeaderOrFooter('documentHeader')}>
            <PanelTop size={16} />
          </ToolbarButton>
          <ToolbarButton label="Editar pie de página" active={Boolean(findDocumentNode(editor, 'documentFooter'))} onClick={() => void editHeaderOrFooter('documentFooter')}>
            <PanelBottom size={16} />
          </ToolbarButton>
          <ToolbarButton label="Insertar salto de página" onClick={() => editor.chain().focus().insertContent({ type: 'pageBreak' }).run()}>
            <span className="document-toolbar__page-break">↵</span>
          </ToolbarButton>
        </div>

        <input
          ref={imageFileRef}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif"
          hidden
          onChange={event => {
            const file = event.target.files?.[0];
            if (file) void insertLocalImage(file);
            event.currentTarget.value = '';
          }}
        />
      </div>

      <div className="document-editor__viewport">
        <div className="document-editor__paper" style={paperStyle}>
          <EditorContent editor={editor} />
        </div>
      </div>
    </div>
  );
}
