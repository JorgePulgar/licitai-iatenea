import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

/**
 * Renderiza el Markdown de una respuesta del chatbot RAG (negritas, listas,
 * tablas, encabezados, código). NO usa rehype-raw a propósito: la salida del
 * LLM no debe poder inyectar HTML arbitrario en el DOM (prevención de XSS).
 *
 * El estilado vive en `.chat-md` (src/index.css) y reutiliza los tokens de
 * diseño del proyecto para mantener la paleta sobria.
 */
export default function ChatMarkdown({ content }: { content: string }) {
  return (
    <div className="chat-md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // Los enlaces externos se abren en pestaña nueva sin filtrar el opener.
          a: (props) => (
            <a {...props} target="_blank" rel="noopener noreferrer" />
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
