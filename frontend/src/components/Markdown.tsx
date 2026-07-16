import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Render de Markdown del dominio Pliexa:
 * - Marcadores [COMPLETAR: …] resaltados (spec-memoria-prompts §7: visibles,
 *   no perdidos en el texto).
 * - Citas [p. X] / [pcap p. X] / [ppt p. X] como chips; clicables si se pasa
 *   onCitationClick (spec-demo-minimal §3.4).
 */
const TOKEN_PATTERN = /(\[COMPLETAR:[^\]]*\]|\[(?:pcap |ppt |anexo )?p\.\s*\d+\])/g;

function renderTokens(
  text: string,
  onCitationClick?: (label: string) => void,
): ReactNode[] {
  return text.split(TOKEN_PATTERN).map((part, i) => {
    if (part.startsWith("[COMPLETAR:")) {
      return (
        <mark key={i} className="gap-marker">
          {part}
        </mark>
      );
    }
    if (TOKEN_PATTERN.test(part) && part.includes("p.")) {
      TOKEN_PATTERN.lastIndex = 0;
      return (
        <button
          key={i}
          type="button"
          onClick={onCitationClick ? () => onCitationClick(part) : undefined}
          className={`mx-0.5 inline-flex items-center rounded bg-accent/10 px-1 font-mono text-xs text-accent ${
            onCitationClick ? "cursor-pointer hover:bg-accent/20" : "cursor-default"
          }`}
        >
          {part}
        </button>
      );
    }
    TOKEN_PATTERN.lastIndex = 0;
    return part;
  });
}

function withTokens(children: ReactNode, onCitationClick?: (label: string) => void): ReactNode {
  if (typeof children === "string") return renderTokens(children, onCitationClick);
  if (Array.isArray(children)) {
    return children.map((child, i) =>
      typeof child === "string" ? (
        <span key={i}>{renderTokens(child, onCitationClick)}</span>
      ) : (
        child
      ),
    );
  }
  return children;
}

export function Markdown({
  children,
  onCitationClick,
}: {
  children: string;
  onCitationClick?: (label: string) => void;
}) {
  return (
    <div className="space-y-3 text-sm leading-relaxed text-ink-1 [&_h1]:text-xl [&_h1]:font-semibold [&_h2]:mt-4 [&_h2]:text-lg [&_h2]:font-semibold [&_h3]:font-semibold [&_li]:ml-4 [&_ol]:list-decimal [&_table]:w-full [&_table]:border-collapse [&_td]:border [&_td]:border-line [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:border-line [&_th]:bg-bg [&_th]:px-2 [&_th]:py-1 [&_ul]:list-disc">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children: c }) => <p>{withTokens(c, onCitationClick)}</p>,
          li: ({ children: c }) => <li>{withTokens(c, onCitationClick)}</li>,
          td: ({ children: c }) => <td>{withTokens(c, onCitationClick)}</td>,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
