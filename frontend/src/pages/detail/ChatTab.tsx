import { useState, useRef, useEffect } from 'react';
import ChatMarkdown from '../../components/ChatMarkdown';
import { queryLicitacion, fetchQueryHistory, fetchQuerySessions } from '../../services/api';
import type {
  LicitacionResponse,
  Citation,
  DocumentType,
  QueryHistoryItem,
  QuerySession,
} from '../../types/licitacion';

interface Message {
  role: 'user' | 'assistant';
  content: string;
  citations?: Citation[];
  timestamp: string;
}

interface ChatTabProps {
  licitacion: LicitacionResponse;
  onOpenDocument: (opts: { filename?: string; documentType?: string; page?: number | null }) => void;
}

const DOC_TYPE_LABELS: Record<string, string> = {
  pcap: 'PCAP',
  ppt: 'PPT',
  anexo: 'Anexo',
};

function formatTime(dateStr?: string): string {
  if (!dateStr) return new Date().toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
  const d = new Date(dateStr);
  return d.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
}

function historyToMessages(items: QueryHistoryItem[]): Message[] {
  const out: Message[] = [];
  for (const item of items) {
    out.push({ role: 'user', content: item.question, timestamp: formatTime(item.created_at) });
    out.push({
      role: 'assistant',
      content: item.answer,
      citations: item.citations,
      timestamp: formatTime(item.created_at),
    });
  }
  return out;
}

export default function ChatTab({ licitacion, onOpenDocument }: ChatTabProps) {
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [sending, setSending] = useState(false);
  const [docTypeFilter, setDocTypeFilter] = useState<DocumentType | ''>('');
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [sessions, setSessions] = useState<QuerySession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string>('');
  const bottomRef = useRef<HTMLDivElement>(null);

  // Carga los hilos de la licitación al montar y abre el más reciente (o uno nuevo).
  useEffect(() => {
    let cancelled = false;

    async function loadSessions() {
      setLoadingHistory(true);
      try {
        const list = await fetchQuerySessions(licitacion.id);
        if (cancelled) return;
        setSessions(list);

        if (list.length > 0) {
          const active = list[0].session_id; // ordenados del más reciente al más antiguo
          setActiveSessionId(active);
          const history = await fetchQueryHistory(licitacion.id, active);
          if (cancelled) return;
          setMessages(historyToMessages(history));
        } else {
          // Sin hilos previos: arranca una conversación nueva (aún sin persistir).
          setActiveSessionId(crypto.randomUUID());
          setMessages([]);
        }
      } catch {
        if (!cancelled) {
          setActiveSessionId(crypto.randomUUID());
          setMessages([]);
        }
      } finally {
        if (!cancelled) setLoadingHistory(false);
      }
    }

    loadSessions();
    return () => { cancelled = true; };
  }, [licitacion.id]);

  // Abre un hilo existente: carga su historial acotado a esa sesión.
  async function openSession(sessionId: string) {
    if (sessionId === activeSessionId || sending) return;
    setActiveSessionId(sessionId);
    setLoadingHistory(true);
    try {
      const history = await fetchQueryHistory(licitacion.id, sessionId);
      setMessages(historyToMessages(history));
    } catch {
      setMessages([]);
    } finally {
      setLoadingHistory(false);
    }
  }

  // "Nueva conversación": hilo limpio con su propio session_id (sin contexto previo).
  function startNewSession() {
    if (sending) return;
    setActiveSessionId(crypto.randomUUID());
    setMessages([]);
    setInput('');
  }

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const isReady = licitacion.status === 'indexed' || licitacion.status === 'partial_error';
  const notReady = !isReady;

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || sending) return;

    setMessages((m) => [
      ...m,
      { role: 'user', content: text, timestamp: formatTime() },
    ]);
    setInput('');
    setSending(true);

    try {
      const response = await queryLicitacion({
        question: text,
        licitacion_id: licitacion.id,
        session_id: activeSessionId,
        ...(docTypeFilter ? { document_type: docTypeFilter } : {}),
      });

      setMessages((m) => [
        ...m,
        {
          role: 'assistant',
          content: response.answer,
          citations: response.citations,
          timestamp: formatTime(),
        },
      ]);

      // Refresca los hilos: el nuevo aparece en la lista y se actualizan los contadores.
      fetchQuerySessions(licitacion.id).then(setSessions).catch(() => {});
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Error desconocido';
      setMessages((m) => [
        ...m,
        {
          role: 'assistant',
          content: `Error al consultar la licitación: ${msg}`,
          timestamp: formatTime(),
        },
      ]);
    } finally {
      setSending(false);
    }
  }

  const suggestions = [
    '¿Cuál es el presupuesto base de licitación?',
    '¿Qué equipo mínimo se requiere?',
    '¿Cuáles son las penalizaciones por SLA?',
  ];

  // Available document types for filter
  const availableDocTypes = [...new Set(licitacion.documents.map((d) => d.document_type))];

  return (
    <div className="flex flex-1 min-h-0">
      {/* Thread list */}
      <div className="flex flex-col w-[220px] bg-surface border-r border-line shrink-0">
        <div className="p-3 flex items-center justify-between border-b border-line">
          <span className="t-up">Hilos · {sessions.length}</span>
          <button
            className="btn sm"
            onClick={startNewSession}
            disabled={sending}
          >
            + Nueva
          </button>
        </div>

        <div className="flex flex-col overflow-y-auto flex-1">
          {/* Hilo nuevo aún sin persistir (no aparece en la lista hasta el primer envío). */}
          {!sessions.some((s) => s.session_id === activeSessionId) && (
            <div className="flex flex-col gap-1 px-3 py-2 border-l-2 border-accent bg-accent-bg">
              <div className="t-medium text-12">Nueva conversación</div>
              <div className="t-xs t-mute">Escribe para comenzar</div>
            </div>
          )}

          {sessions.map((s) => {
            const active = s.session_id === activeSessionId;
            return (
              <button
                key={s.session_id}
                onClick={() => openSession(s.session_id)}
                className={`flex flex-col gap-1 px-3 py-2 text-left border-l-2 transition-colors ${
                  active ? 'border-accent bg-accent-bg' : 'border-transparent hover:bg-surface-2'
                }`}
              >
                <div className="t-medium text-12 truncate">{s.title}</div>
                <div className="flex justify-between t-xs t-mute">
                  <span>{formatTime(s.updated_at)}</span>
                  <span>{s.message_count} msgs</span>
                </div>
              </button>
            );
          })}

          {sessions.length === 0 && loadingHistory && (
            <div className="flex items-center justify-center flex-1 text-ink-4 text-12 p-4 text-center">
              Cargando historial…
            </div>
          )}
        </div>

        {/* Document type filter */}
        {availableDocTypes.length > 1 && (
          <div className="p-3 border-t border-line mt-auto">
            <div className="t-up mb-2 text-10">Filtrar por documento</div>
            <select
              className="real-input text-12 w-full"
              value={docTypeFilter}
              onChange={(e) => setDocTypeFilter(e.target.value as DocumentType | '')}
            >
              <option value="">Todos los documentos</option>
              {availableDocTypes.map((dt) => (
                <option key={dt} value={dt}>{DOC_TYPE_LABELS[dt] || dt}</option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Chat area */}
      <div className="flex flex-col flex-1 min-w-0">
        {/* Header */}
        <div className="flex justify-between items-center p-3 border-b border-line bg-surface shrink-0">
          <div className="flex flex-col">
            <div className="t-medium">
              {messages.length > 0 ? messages[0].content.slice(0, 60) : 'Nueva consulta'}
            </div>
            <div className="t-xs t-mute">
              Contexto: {licitacion.title} · {licitacion.documents.length} documento{licitacion.documents.length !== 1 ? 's' : ''} · {messages.length} mensajes
              {docTypeFilter && ` · Filtro: ${DOC_TYPE_LABELS[docTypeFilter] || docTypeFilter}`}
            </div>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 p-4 flex flex-col gap-4 overflow-auto bg-bg">
          {notReady && (
            <div className="surface-2 p-3 flex items-center gap-3 text-12 rounded-sm">
              <span className="dot warn" />
              <span>
                Esta licitación está en estado <strong>{licitacion.status}</strong>. El chatbot
                solo estará disponible cuando la licitación esté indexada.
              </span>
            </div>
          )}

          {loadingHistory && messages.length === 0 && (
            <div className="flex items-center justify-center flex-1 text-ink-4 text-13">
              Cargando historial de conversación…
            </div>
          )}

          {!loadingHistory && messages.length === 0 && !notReady && (
            <div className="flex items-center justify-center flex-col gap-3 flex-1 text-ink-4">
              <div className="text-13 text-ink-3 text-center max-w-[360px]">
                Haz una pregunta sobre esta licitación. Las respuestas incluirán citas
                con referencia al documento y página de origen.
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <div key={i} className="flex gap-3">
              <div className={`chat-role ${msg.role === 'assistant' ? 'text-accent' : 'text-ink-3'}`}>
                {msg.role === 'assistant' ? 'IA' : 'Tú'}
              </div>

              {msg.role === 'user' ? (
                <div className="surface p-3 flex-1 max-w-[720px]">
                  <div className="t-xs t-mute mb-[6px]">{msg.timestamp}</div>
                  <div className="text-13">{msg.content}</div>
                </div>
              ) : (
                <div className="surface flex-1 max-w-[720px]">
                  <div className="flex justify-between items-center p-3 border-b border-line">
                    <span className="t-xs t-mute">LicitAI · {msg.timestamp}</span>
                  </div>
                  <div className="p-4 text-13 leading-[1.65]">
                    <ChatMarkdown content={msg.content} />
                  </div>
                  {msg.citations && msg.citations.length > 0 && (
                    <div className="px-4 pb-4">
                      <div className="t-up mb-2 text-11">Fuentes citadas</div>
                      <div className="flex flex-col gap-2">
                        {msg.citations.map((cit, ci) => (
                          <div key={ci} className="surface-2 p-3 text-12 rounded-sm">
                            <div className="flex items-center gap-2 mb-1">
                              <span className="tag text-10">
                                {DOC_TYPE_LABELS[cit.document_type] || cit.document_type}
                              </span>
                              <button
                                className="tag text-10 hover:bg-accent hover:text-white transition-colors cursor-pointer"
                                title={`Abrir ${cit.filename} en la página ${cit.page_number ?? '?'}`}
                                onClick={() =>
                                  onOpenDocument({
                                    filename: cit.filename,
                                    documentType: cit.document_type,
                                    page: cit.page_number,
                                  })
                                }
                              >
                                {cit.page_number != null ? `p. ${cit.page_number}` : 'sin página'} ↗
                              </button>
                              <span className="t-mute text-11">{cit.filename}</span>
                            </div>
                            <div className="text-ink-2 leading-relaxed">{cit.content}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}

          {sending && (
            <div className="flex gap-3">
              <div className="chat-role text-accent">IA</div>
              <div className="t-mute text-12 pt-[6px]">
                Buscando en la licitación…
              </div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="p-3 border-t border-line bg-surface shrink-0">
          <div className="flex gap-2 mb-2 t-xs">
            <span className="tag">Sugerencias:</span>
            {suggestions.map((s) => (
              <span key={s} className="ref" onClick={() => setInput(s)}>
                {s}
              </span>
            ))}
          </div>

          <form onSubmit={handleSend}>
            <div className="flex items-center gap-2">
              <div className="input flex-1 h-8">
                <input
                  placeholder={
                    notReady
                      ? 'Licitación no indexada — consultas no disponibles'
                      : 'Pregunta sobre esta licitación…'
                  }
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  disabled={notReady || sending}
                />
                <span className="kbd">⌘</span>
                <span className="kbd ml-1">↵</span>
              </div>
              <button
                type="submit"
                className="btn primary"
                disabled={notReady || sending || !input.trim()}
              >
                Enviar
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
