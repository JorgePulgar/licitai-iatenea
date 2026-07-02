import { useState, useEffect, useRef } from 'react';
import { Bot, Send, FileText, Check, Plus, Download, Loader2, GripVertical, Upload, Trash2, Save, Edit2 } from 'lucide-react';
import RichDocumentEditor from '../../components/RichDocumentEditor';
import AiEditingOverlay from '../../components/AiEditingOverlay';
import { useModal } from '../../hooks/useModal';
import {
  DndContext,
  closestCenter,
  PointerSensor,
  useSensor,
  useSensors,
  DragEndEvent,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  verticalListSortingStrategy,
  useSortable,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';

import type {
  LicitacionResponse,
  MemoriaSectionDraft,
  MemoriaDocumentResponse,
  MemoriaChatMessageResponse,
  CompanyTemplateResponse
} from '../../types/licitacion';
import {
  fetchMemoriaDocuments,
  generateMemoriaEsquema,
  generateMemoriaPropuesta,
  chatMemoria,
  fetchMemoriaChatHistory,
  exportMemoriaPdf,
  updateMemoriaDocument,
  fetchCompanyTemplates,
  uploadCompanyTemplate,
  deleteCompanyTemplate,
  saveMemoriaSections
} from '../../services/api';

// --- DnD Sortable Item Component ---
function SortableSection({ section, index }: { section: MemoriaSectionDraft; index: number }) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: section.title }); // Assuming title is unique enough for the draft phase

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`flex items-start gap-3 p-3 mb-2 bg-white border rounded shadow-sm ${
        isDragging ? 'border-primary ring-2 ring-primary ring-opacity-50' : 'border-line'
      }`}
    >
      <div
        {...attributes}
        {...listeners}
        className="mt-1 cursor-grab active:cursor-grabbing text-ink-3 hover:text-ink-1"
      >
        <GripVertical size={18} />
      </div>
      <div className="flex-1">
        <div className="font-medium text-ink-1 flex items-center gap-2">
          {index + 1}. {section.title}
          {section.max_puntos != null && Number.isFinite(section.max_puntos) && (
            <span className="text-12 bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full font-normal">
              {section.max_puntos} pts
            </span>
          )}
        </div>
        {section.description && (
          <p className="text-13 text-ink-2 mt-1">{section.description}</p>
        )}
      </div>
    </div>
  );
}

// --- Main Tab Component ---
export default function MemoriaTab({ licitacion }: { licitacion: LicitacionResponse }) {
  const { showModal } = useModal();
  const [phase, setPhase] = useState<'list' | 'prompt' | 'esquema' | 'documento'>('list');
  const [loading, setLoading] = useState(false);
  const [loadingMsg, setLoadingMsg] = useState('');
  // Loading scoped al panel del documento (chat IA editando). No bloquea header ni chat panel.
  const [chatEditing, setChatEditing] = useState(false);
  
  // List State
  const [docs, setDocs] = useState<MemoriaDocumentResponse[]>([]);
  const [editingDocId, setEditingDocId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState('');
  
  // Prompt State
  const [promptMsg, setPromptMsg] = useState('');
  const [templates, setTemplates] = useState<CompanyTemplateResponse[]>([]);
  const [selectedTemplateIds, setSelectedTemplateIds] = useState<string[]>([]);
  const [uploadingTemplate, setUploadingTemplate] = useState(false);
  const [deletingTemplateId, setDeletingTemplateId] = useState<string | null>(null);
  const [templateError, setTemplateError] = useState<string | null>(null);
  const templateFileRef = useRef<HTMLInputElement>(null);
  
  // Esquema State
  const [esquema, setEsquema] = useState<MemoriaSectionDraft[]>([]);
  const [esquemaReply, setEsquemaReply] = useState('');
  const [esquemaChatHistory, setEsquemaChatHistory] = useState<MemoriaChatMessageResponse[]>([]);
  const [esquemaChatInput, setEsquemaChatInput] = useState('');
  const [esquemaChatEditing, setEsquemaChatEditing] = useState(false);
  
  // Document State
  const [activeDoc, setActiveDoc] = useState<MemoriaDocumentResponse | null>(null);
  const [markdown, setMarkdown] = useState('');
  const [chatHistory, setChatHistory] = useState<MemoriaChatMessageResponse[]>([]);
  const [chatInput, setChatInput] = useState('');

  // Autosave State para edición manual del documento.
  const [saveStatus, setSaveStatus] = useState<'idle' | 'dirty' | 'saving' | 'saved' | 'error'>('idle');
  const lastSavedRef = useRef<string>('');
  const markdownRef = useRef<string>('');
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const saveQueueRef = useRef<Promise<unknown>>(Promise.resolve());

  const [isStateLoaded, setIsStateLoaded] = useState(false);
  const [docsError, setDocsError] = useState<string | null>(null);
  const storageKey = `memoria_state_${licitacion.id}`;

  const isReady = licitacion.status === 'indexed' || licitacion.status === 'partial_error';

  // --- Initial Load ---
  // Reglas:
  //   * Siempre aterrizamos en `list` para que el usuario vea el histórico.
  //   * Si el `localStorage` arrastra una sesión en `documento`/`prompt`, la
  //     restauramos solo si el documento referenciado SIGUE existiendo en el
  //     servidor. Si no, limpiamos el estado rancio (caso típico: BD reseteada).
  useEffect(() => {
    if (!isReady) return;

    const saved = localStorage.getItem(storageKey);
    let parsed: any = null;
    if (saved) {
      try {
        parsed = JSON.parse(saved);
      } catch (e) {
        console.error('Failed to parse localStorage', e);
      }
    }

    fetchMemoriaDocuments(licitacion.id)
      .then((data) => {
        setDocs(data);
        setDocsError(null);

        // Siempre aterrizamos en 'list' por defecto según lo solicitado.
        setPhase('list');

        // Restauramos los datos del borrador en background por si se implementa un "continuar borrador"
        if (parsed) {
          if (parsed.promptMsg) setPromptMsg(parsed.promptMsg);
          if (parsed.esquema) setEsquema(parsed.esquema);
          if (parsed.esquemaReply) setEsquemaReply(parsed.esquemaReply);
          if (parsed.esquemaChatHistory) setEsquemaChatHistory(parsed.esquemaChatHistory);
          if (Array.isArray(parsed.selectedTemplateIds)) setSelectedTemplateIds(parsed.selectedTemplateIds);

          const savedDocStillExists = parsed.activeDoc?.id && data.some(d => d.id === parsed.activeDoc.id);
          if (savedDocStillExists) {
            setActiveDoc(parsed.activeDoc);
            if (parsed.markdown) setMarkdown(parsed.markdown);
            if (parsed.chatHistory) setChatHistory(parsed.chatHistory);
          }
        }
      })
      .catch((err) => {
        console.error('Error fetching memorias:', err);
        setDocsError(
          err instanceof Error ? err.message : 'No se pudieron cargar las memorias.'
        );
        setPhase('list');
      })
      .finally(() => setIsStateLoaded(true));
  }, [licitacion.id, isReady, storageKey]);

  // --- Auto-save to localStorage ---
  useEffect(() => {
    if (!isStateLoaded) return;
    
    // Clear draft if returning to list
    if (phase === 'list') {
      localStorage.removeItem(storageKey);
      return;
    }

    const stateToSave = {
      phase,
      promptMsg,
      esquema,
      esquemaReply,
      esquemaChatHistory,
      activeDoc,
      markdown,
      chatHistory,
      selectedTemplateIds,
    };
    try {
      localStorage.setItem(storageKey, JSON.stringify(stateToSave));
    } catch (err) {
      // Las imágenes embebidas pueden superar la cuota; el autosave remoto sigue activo.
      console.warn('No se pudo guardar el borrador en localStorage', err);
    }
  }, [isStateLoaded, phase, promptMsg, esquema, esquemaReply, esquemaChatHistory, activeDoc, markdown, chatHistory, selectedTemplateIds, storageKey]);

  useEffect(() => {
    markdownRef.current = markdown;
  }, [markdown]);

  // --- Carga de plantillas de referencia (lazy, al entrar en prompt) ---
  useEffect(() => {
    if (phase !== 'prompt') return;
    fetchCompanyTemplates()
      .then(setTemplates)
      .catch(() => setTemplates([]));
  }, [phase]);

  function toggleTemplate(id: string) {
    setSelectedTemplateIds(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    );
  }

  async function handleUploadTemplate(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setTemplateError(null);
    setUploadingTemplate(true);
    try {
      const created = await uploadCompanyTemplate(file, { title: file.name });
      setTemplates(prev => [created, ...prev]);
      setSelectedTemplateIds(prev => [...prev, created.id]);
    } catch (err) {
      setTemplateError(err instanceof Error ? err.message : 'Error al subir el documento');
    } finally {
      setUploadingTemplate(false);
      if (templateFileRef.current) templateFileRef.current.value = '';
    }
  }

  async function handleDeleteTemplate(id: string, label: string) {
    const confirmed = await showModal({
      type: 'confirmation',
      title: 'Eliminar plantilla',
      description: <>Se eliminará <strong>{label}</strong>. Esta acción no se puede deshacer.</>,
      tone: 'danger',
      confirmLabel: 'Eliminar',
    });
    if (!confirmed) return;

    setTemplateError(null);
    setDeletingTemplateId(id);
    try {
      await deleteCompanyTemplate(id);
      setTemplates(prev => prev.filter(t => t.id !== id));
      setSelectedTemplateIds(prev => prev.filter(x => x !== id));
    } catch (err) {
      setTemplateError(err instanceof Error ? err.message : 'Error al eliminar la plantilla');
    } finally {
      setDeletingTemplateId(null);
    }
  }

  // --- Refrescar la lista al volver a la fase 'list' ---
  // Sin esto, el listado queda con los `docs` cargados al montar y no
  // muestra memorias creadas en la misma sesión.
  useEffect(() => {
    if (!isReady || phase !== 'list') return;
    fetchMemoriaDocuments(licitacion.id)
      .then(setDocs)
      .catch(err => console.error('Error refreshing memorias:', err));
  }, [phase, isReady, licitacion.id]);

  // --- Autosave Markdown (edición manual con debounce) ---
  useEffect(() => {
    if (!activeDoc) return;
    if (markdown === lastSavedRef.current) return;

    setSaveStatus('dirty');
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    const docId = activeDoc.id;
    const markdownToSave = markdown;
    saveTimerRef.current = setTimeout(() => {
      persistDocument(docId, markdownToSave).catch(err => {
        console.error('Autosave failed', err);
      });
    }, 1200);

    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, [markdown, activeDoc, licitacion.id]);

  // --- Renaming ---
  async function handleRenameSubmit(docId: string, e?: React.MouseEvent | React.KeyboardEvent) {
    if (e) e.stopPropagation();
    if (!editingTitle.trim()) {
      setEditingDocId(null);
      return;
    }
    try {
      const updated = await updateMemoriaDocument(licitacion.id, docId, { title: editingTitle.trim() });
      setDocs(prev => prev.map(d => d.id === docId ? updated : d));
      if (activeDoc?.id === docId) setActiveDoc(updated);
    } catch (err) {
      console.error('Error al renombrar', err);
    } finally {
      setEditingDocId(null);
    }
  }

  // --- Actions ---
  function persistDocument(docId: string, markdownToSave: string): Promise<MemoriaDocumentResponse> {
    const request = saveQueueRef.current
      .catch(() => undefined)
      .then(async () => {
        setSaveStatus('saving');
        const updated = await updateMemoriaDocument(
          licitacion.id,
          docId,
          { markdown: markdownToSave }
        );
        lastSavedRef.current = markdownToSave;
        setActiveDoc(prev => prev?.id === docId ? updated : prev);
        setDocs(prev => [updated, ...prev.filter(doc => doc.id !== docId)]);
        setSaveStatus(markdownRef.current === markdownToSave ? 'saved' : 'dirty');
        return updated;
      })
      .catch(err => {
        setSaveStatus('error');
        throw err;
      });

    saveQueueRef.current = request.catch(() => undefined);
    return request;
  }

  async function handleSaveDocument(showError = true): Promise<boolean> {
    if (!activeDoc) return false;
    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    try {
      await persistDocument(activeDoc.id, markdown);
      return true;
    } catch (err) {
      console.error('Save failed', err);
      if (showError) {
        await showModal({
          type: 'alert',
          title: 'No se pudo guardar la memoria',
          description: 'Revisa la conexión e inténtalo de nuevo.',
          tone: 'danger',
        });
      }
      return false;
    }
  }

  async function handleGenerateEsquema() {
    if (!promptMsg.trim()) return;
    setLoading(true);
    setLoadingMsg('Analizando licitación y diseñando estructura (puede tardar un poco)...');
    try {
      const res = await generateMemoriaEsquema(licitacion.id, promptMsg, selectedTemplateIds);
      setEsquema(res.esquema);
      setEsquemaReply(res.reply);
      setEsquemaChatHistory([
        { id: 'initial-user', role: 'user', content: promptMsg, created_at: new Date().toISOString() },
        { id: 'initial-assistant', role: 'assistant', content: res.reply, created_at: new Date().toISOString() }
      ]);
      setPhase('esquema');
    } catch (err) {
      console.error(err);
      await showModal({
        type: 'alert',
        title: 'No se pudo generar el esquema',
        description: 'El servicio no ha podido completar la estructura de la memoria.',
        tone: 'danger',
      });
    } finally {
      setLoading(false);
    }
  }

  async function handleGeneratePropuesta() {
    setLoading(true);
    setLoadingMsg('Redactando memoria técnica basada en el esquema... (esto puede tardar unos minutos)');
    try {
      const res = await generateMemoriaPropuesta(licitacion.id, esquema, selectedTemplateIds);

      const defaultTitle = `Versión ${docs.length + 1}`;

      // Backend returns doc_id, title, markdown
      const newDoc: MemoriaDocumentResponse = {
        id: res.doc_id,
        licitacion_id: licitacion.id,
        title: defaultTitle,
        markdown: res.markdown,
        updated_at: new Date().toISOString()
      };

      // Actualizar silenciosamente el título por defecto en el backend
      updateMemoriaDocument(licitacion.id, res.doc_id, { title: defaultTitle }).catch(console.error);

      setActiveDoc(newDoc);
      setMarkdown(res.markdown);
      lastSavedRef.current = res.markdown;
      setSaveStatus('saved');
      setChatHistory([]);
      // Añade la versión recién creada a la lista para que aparezca al volver.
      setDocs(prev => [newDoc, ...prev.filter(d => d.id !== newDoc.id)]);
      setPhase('documento');
    } catch (err) {
      console.error(err);
      await showModal({
        type: 'alert',
        title: 'No se pudo redactar la propuesta',
        description: 'El servicio no ha podido generar la memoria técnica.',
        tone: 'danger',
      });
    } finally {
      setLoading(false);
    }
  }

  async function handleSendEsquemaChat() {
    if (!esquemaChatInput.trim() || esquemaChatEditing) return;
    const msg = esquemaChatInput.trim();
    setEsquemaChatInput('');
    setEsquemaChatEditing(true);

    const tempMsg: MemoriaChatMessageResponse = {
      id: 'temp-' + Date.now(),
      role: 'user',
      content: msg,
      created_at: new Date().toISOString()
    };
    setEsquemaChatHistory(prev => [...prev, tempMsg]);

    try {
      // 1. Guardar el estado actual del esquema para que el backend lo vea como `existing`
      await saveMemoriaSections(licitacion.id, esquema);

      // 2. Opcionalmente incluir el historial en el mensaje para darle contexto al LLM
      const contextMessage = esquemaChatHistory
        .map(h => `${h.role === 'user' ? 'Usuario' : 'Asistente'}: ${h.content}`)
        .join('\n') + `\nUsuario: ${msg}`;

      const res = await generateMemoriaEsquema(licitacion.id, contextMessage, selectedTemplateIds);
      
      setEsquema(res.esquema);
      setEsquemaReply(res.reply);
      
      const replyMsg: MemoriaChatMessageResponse = {
        id: 'reply-' + Date.now(),
        role: 'assistant',
        content: res.reply,
        created_at: new Date().toISOString()
      };
      setEsquemaChatHistory(prev => [...prev, replyMsg]);
    } catch (err) {
      console.error(err);
      await showModal({
        type: 'alert',
        title: 'No se pudo editar el esquema',
        description: 'El asistente no ha podido aplicar el cambio solicitado.',
        tone: 'danger',
      });
      setEsquemaChatInput(msg); // restore input
    } finally {
      setEsquemaChatEditing(false);
    }
  }

  async function handleSendChat() {
    if (!chatInput.trim() || !activeDoc || chatEditing) return;
    const msg = chatInput.trim();
    setChatInput('');
    // Scoped: solo el panel del documento muestra el overlay; header y chat siguen vivos.
    setChatEditing(true);

    // Optimistic UI update for chat
    const tempMsg: MemoriaChatMessageResponse = {
      id: 'temp-' + Date.now(),
      role: 'user',
      content: msg,
      created_at: new Date().toISOString()
    };
    setChatHistory(prev => [...prev, tempMsg]);

    try {
      const res = await chatMemoria(licitacion.id, activeDoc.id, markdown, msg);
      setMarkdown(res.markdown);
      // El chat endpoint ya persistió el nuevo markdown — evitamos autosave redundante.
      lastSavedRef.current = res.markdown;
      setSaveStatus('saved');
      // Refresh chat history to get the actual IDs and timestamps (scoped to this doc).
      const hist = await fetchMemoriaChatHistory(licitacion.id, activeDoc.id);
      setChatHistory(hist);
    } catch (err) {
      console.error(err);
      await showModal({
        type: 'alert',
        title: 'No se pudo editar la memoria',
        description: 'El asistente no ha podido aplicar el cambio solicitado.',
        tone: 'danger',
      });
      setChatInput(msg); // restore input
    } finally {
      setChatEditing(false);
    }
  }

  async function handleOpenDocument(doc: MemoriaDocumentResponse) {
    setLoading(true);
    setLoadingMsg('Cargando documento...');
    try {
      setActiveDoc(doc);
      const md = doc.markdown || '';
      setMarkdown(md);
      lastSavedRef.current = md;
      setSaveStatus('saved');
      const hist = await fetchMemoriaChatHistory(licitacion.id, doc.id);
      setChatHistory(hist);
      setPhase('documento');
    } catch (err) {
      console.error(err);
      await showModal({
        type: 'alert',
        title: 'No se pudo cargar la memoria',
        description: 'Vuelve al listado e inténtalo de nuevo.',
        tone: 'danger',
      });
    } finally {
      setLoading(false);
    }
  }

  async function handleExportPdf() {
    if (!activeDoc) return;
    setLoading(true);
    setLoadingMsg('Guardando y generando PDF...');
    try {
      const saved = await handleSaveDocument(false);
      if (!saved) {
        await showModal({
          type: 'alert',
          title: 'No se ha exportado el PDF',
          description: 'La memoria no pudo guardarse antes de la exportación.',
          tone: 'danger',
        });
        return;
      }
      const blob = await exportMemoriaPdf(licitacion.id, activeDoc.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `Memoria_${licitacion.id.slice(0,6)}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error(err);
      await showModal({
        type: 'alert',
        title: 'No se pudo exportar el PDF',
        description: 'Comprueba que el servidor está disponible y tiene instaladas las dependencias de PDF.',
        tone: 'danger',
      });
    } finally {
      setLoading(false);
    }
  }

  async function handleCancelDraft() {
    const confirmed = await showModal({
      type: 'confirmation',
      title: 'Descartar borrador',
      description: 'Se perderán los cambios del borrador actual y volverás al listado.',
      tone: 'warning',
      confirmLabel: 'Descartar',
    });
    if (confirmed) setPhase('list');
  }

  async function handleGenerateOrRegenerateEsquema() {
    if (esquema.length > 0) {
      const confirmed = await showModal({
        type: 'confirmation',
        title: 'Regenerar esquema',
        description: 'La estructura ordenada actual será reemplazada por una nueva propuesta.',
        tone: 'warning',
        confirmLabel: 'Regenerar',
      });
      if (!confirmed) return;
    }
    await handleGenerateEsquema();
  }

  // --- DnD Handlers ---
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 5,
      },
    })
  );

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (over && active.id !== over.id) {
      setEsquema((items) => {
        const oldIndex = items.findIndex(i => i.title === active.id);
        const newIndex = items.findIndex(i => i.title === over.id);
        const newArray = arrayMove(items, oldIndex, newIndex);
        // update sort_order
        return newArray.map((item, idx) => ({ ...item, sort_order: idx }));
      });
    }
  }

  // --- Render ---
  if (!isReady) {
    return (
      <div className="p-8 text-center text-ink-3">
        La licitación debe estar indexada para generar memorias.
      </div>
    );
  }

  return (
    <div className="flex flex-col flex-1 h-full min-h-0 bg-surface relative">
      {/* Global Loading Overlay */}
      {loading && (
        <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-white/80 backdrop-blur-sm">
          <Loader2 className="w-10 h-10 animate-spin text-primary mb-4" />
          <p className="text-ink-1 font-medium text-15">{loadingMsg}</p>
        </div>
      )}

      {/* PHASE: List */}
      {phase === 'list' && (
        <div className="flex-1 min-h-0 overflow-y-auto p-8 max-w-4xl mx-auto w-full">
          <div className="flex items-center justify-between mb-8">
            <h2 className="text-2xl font-bold text-ink-1">Memorias Técnicas</h2>
            <button 
              className="btn primary"
              onClick={() => {
                setPromptMsg('');
                setEsquema([]);
                setEsquemaReply('');
                setSelectedTemplateIds([]);
                setPhase('prompt');
              }}
            >
              <Plus size={16} className="mr-2" />
              Nueva versión
            </button>
          </div>
          
          {docsError && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 rounded text-13">
              {docsError}
            </div>
          )}

          {docs.length === 0 && !docsError ? (
            <div className="border border-dashed border-line rounded-lg p-10 text-center bg-white">
              <FileText size={32} className="text-ink-3 mx-auto mb-3" />
              <h3 className="text-ink-1 font-semibold mb-1">Aún no hay memorias para esta licitación</h3>
              <p className="text-13 text-ink-3 mb-4">
                Cuando generes una memoria técnica, aparecerá aquí. Podrás abrir versiones anteriores y comparar enfoques.
              </p>
              <button
                className="btn primary"
                onClick={() => {
                  setPromptMsg('');
                  setEsquema([]);
                  setEsquemaReply('');
                  setSelectedTemplateIds([]);
                  setPhase('prompt');
                }}
              >
                <Plus size={16} className="mr-2" />
                Crear primera memoria
              </button>
            </div>
          ) : (
            <div className="grid gap-4">
              {docs.map(doc => (
                <div
                  key={doc.id}
                  className="flex items-center justify-between p-4 bg-white border border-line rounded-lg shadow-sm hover:border-primary cursor-pointer transition-colors"
                  onClick={() => handleOpenDocument(doc)}
                >
                  <div className="flex items-center gap-4 flex-1">
                    <div className="p-3 bg-blue-50 text-blue-600 rounded-full">
                      <FileText size={24} />
                    </div>
                    <div className="flex-1">
                      {editingDocId === doc.id ? (
                        <div className="flex items-center gap-2" onClick={e => e.stopPropagation()}>
                          <input
                            type="text"
                            className="real-input text-14 py-1 px-2"
                            value={editingTitle}
                            onChange={e => setEditingTitle(e.target.value)}
                            onKeyDown={e => e.key === 'Enter' && handleRenameSubmit(doc.id, e)}
                            autoFocus
                          />
                          <button className="btn primary xs" onClick={e => handleRenameSubmit(doc.id, e)}>
                            Guardar
                          </button>
                          <button className="btn xs" onClick={e => { e.stopPropagation(); setEditingDocId(null); }}>
                            Cancelar
                          </button>
                        </div>
                      ) : (
                        <div className="flex items-center gap-2">
                          <h3 className="font-semibold text-ink-1">{doc.title || 'Documento'}</h3>
                          <button
                            className="text-ink-3 hover:text-ink-1 p-1 transition-colors"
                            onClick={e => {
                              e.stopPropagation();
                              setEditingDocId(doc.id);
                              setEditingTitle(doc.title || '');
                            }}
                            title="Renombrar versión"
                          >
                            <Edit2 size={14} />
                          </button>
                        </div>
                      )}
                      <p className="text-13 text-ink-3 mt-1">
                        Última modificación: {doc.updated_at ? new Date(doc.updated_at).toLocaleString() : 'N/A'}
                      </p>
                    </div>
                  </div>
                  <div className="text-primary font-medium text-14 ml-4">
                    Ver documento &rarr;
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* PHASE: Prompt */}
      {phase === 'prompt' && (
        <div className="flex-1 min-h-0 overflow-y-auto p-8 flex flex-col items-center justify-center max-w-2xl mx-auto w-full text-center">
          <Bot size={48} className="text-primary mb-6" />
          <h2 className="text-2xl font-bold text-ink-1 mb-2">Crear nueva Memoria Técnica</h2>
          <p className="text-ink-2 mb-8 text-15">
            Dime cómo quieres enfocar la propuesta técnica. El agente analizará los pliegos y creará una estructura inicial para tu revisión.
          </p>
          <textarea
            className="w-full min-h-[128px] p-4 text-15 resize-none border border-line-strong rounded bg-surface text-ink outline-none focus:outline-2 focus:-outline-offset-1 focus:outline-accent shadow-sm mb-6"
            placeholder="Ej: Haz hincapié en nuestra certificación medioambiental y en la reducción de plazos de entrega..."
            value={promptMsg}
            onChange={e => setPromptMsg(e.target.value)}
          />

          {/* Plantillas de referencia */}
          <div className="w-full mb-6 text-left">
            <div className="flex items-center justify-between mb-2">
              <div>
                <div className="text-13 font-medium text-ink-1">
                  Plantillas de referencia
                  {selectedTemplateIds.length > 0 && (
                    <span className="ml-2 text-12 text-ink-3">
                      ({selectedTemplateIds.length} seleccionada{selectedTemplateIds.length > 1 ? 's' : ''})
                    </span>
                  )}
                </div>
                <div className="text-12 text-ink-3">
                  La IA copiará su estilo, tono y estructura al redactar.
                </div>
              </div>
              <div>
                <input
                  ref={templateFileRef}
                  type="file"
                  accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                  className="hidden"
                  onChange={handleUploadTemplate}
                />
                <button
                  type="button"
                  className="btn xs"
                  onClick={() => templateFileRef.current?.click()}
                  disabled={uploadingTemplate}
                >
                  <Upload size={14} className="mr-1" />
                  {uploadingTemplate ? 'Procesando…' : 'Subir nueva'}
                </button>
              </div>
            </div>

            {templateError && (
              <div className="text-12 text-red-500 bg-red-50 border border-red-200 rounded px-3 py-2 mb-2 text-left">
                {templateError}
              </div>
            )}

            {templates.length === 0 ? (
              <div className="text-12 text-ink-3 italic border border-dashed border-line rounded px-3 py-3 text-left">
                Aún no hay plantillas. Súbelas aquí o desde Ajustes &rarr; Documentos de referencia.
              </div>
            ) : (
              <ul className="border border-line rounded divide-y divide-line text-left max-h-48 overflow-y-auto">
                {templates.map(t => {
                  const checked = selectedTemplateIds.includes(t.id);
                  const isDeleting = deletingTemplateId === t.id;
                  return (
                    <li key={t.id} className="flex items-center gap-3 px-3 py-2">
                      <input
                        id={`tpl-${t.id}`}
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleTemplate(t.id)}
                        className="h-4 w-4 accent-primary"
                      />
                      <label htmlFor={`tpl-${t.id}`} className="flex-1 cursor-pointer min-w-0">
                        <div className="text-13 text-ink-1 truncate">{t.title || t.filename}</div>
                        <div className="text-11 text-ink-3 flex gap-3 mt-0.5">
                          <span className="truncate">{t.filename}</span>
                          {t.page_count != null && <span>{t.page_count} págs.</span>}
                          {!t.has_summary && <span className="text-amber-600">Sin análisis</span>}
                        </div>
                      </label>
                      <button
                        type="button"
                        className="p-1.5 text-ink-3 hover:text-red-600 disabled:opacity-40 transition-colors"
                        onClick={() => handleDeleteTemplate(t.id, t.title || t.filename)}
                        disabled={isDeleting}
                        title="Eliminar plantilla"
                      >
                        {isDeleting
                          ? <Loader2 size={14} className="animate-spin" />
                          : <Trash2 size={14} />}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          <div className="flex gap-4">
            <button
              className="btn text-ink-2"
              onClick={() => void handleCancelDraft()}
            >
              &larr; Ver lista de memorias
            </button>
            {esquema.length > 0 && (
              <button className="btn" onClick={() => setPhase('esquema')}>
                Siguiente &rarr;
              </button>
            )}
            <button 
              className="btn primary px-8"
              onClick={() => void handleGenerateOrRegenerateEsquema()}
              disabled={!promptMsg.trim() || loading}
            >
              {esquema.length > 0 ? 'Regenerar Esquema' : 'Generar Esquema'}
            </button>
          </div>
        </div>
      )}

      {/* PHASE: Esquema */}
      {phase === 'esquema' && (
        <div className="flex flex-1 overflow-hidden">
          {/* Left Pane: Esquema Editor */}
          <div className="flex-1 flex flex-col border-r border-line bg-white relative">
            <div className="flex items-center justify-between p-3 border-b border-line shrink-0">
              <div className="flex items-center gap-3">
                <button
                  className="btn xs text-ink-2"
                  onClick={() => void handleCancelDraft()}
                  title="Ver lista de memorias"
                >
                  &larr; Ver lista de memorias
                </button>
                <button 
                  className="btn xs"
                  onClick={() => setPhase('prompt')}
                >
                  &larr; Atrás
                </button>
                <div className="font-semibold text-ink-1 ml-2">
                  Estructura Propuesta
                </div>
              </div>
              
              <div className="flex items-center gap-2">
                <button 
                  className="btn xs primary"
                  onClick={handleGeneratePropuesta}
                >
                  <Check size={14} className="mr-1" />
                  Redactar Memoria
                </button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto p-8 relative">
              <p className="text-ink-2 text-14 mb-6">
                Arrastra las secciones para reordenarlas. Pide cambios al asistente o haz clic en Redactar Memoria.
              </p>

              <DndContext
                sensors={sensors}
                collisionDetection={closestCenter}
                onDragEnd={handleDragEnd}
              >
                <SortableContext
                  items={esquema.map(s => s.title)}
                  strategy={verticalListSortingStrategy}
                >
                  {esquema.map((section, idx) => (
                    <SortableSection key={section.title} section={section} index={idx} />
                  ))}
                </SortableContext>
              </DndContext>

              {esquemaChatEditing && <AiEditingOverlay />}
            </div>
          </div>

          {/* Right Pane: Chat */}
          <div className="w-80 flex flex-col bg-surface shrink-0">
            <div className="p-3 border-b border-line shrink-0 flex items-center gap-2 font-semibold text-14 text-ink-1">
              <Bot size={18} className="text-primary"/> Asistente IA (Esquema)
            </div>
            
            <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-4">
              {esquemaChatHistory.map(msg => (
                <div 
                  key={msg.id} 
                  className={`flex flex-col max-w-[90%] ${msg.role === 'user' ? 'self-end items-end' : 'self-start items-start'}`}
                >
                  <div className={`p-3 rounded-lg text-13 whitespace-pre-wrap ${
                    msg.role === 'user'
                      ? 'bg-ink text-white rounded-br-none'
                      : 'bg-white border border-line text-ink-1 rounded-bl-none shadow-sm'
                  }`}>
                    {msg.content}
                  </div>
                </div>
              ))}
            </div>

            <div className="p-4 border-t border-line shrink-0 bg-white">
              <div className="flex gap-2">
                <input
                  type="text"
                  className="real-input flex-1 text-13"
                  placeholder="Dime qué cambiar..."
                  value={esquemaChatInput}
                  onChange={e => setEsquemaChatInput(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleSendEsquemaChat()}
                />
                <button
                  className="btn primary p-2"
                  onClick={handleSendEsquemaChat}
                  disabled={!esquemaChatInput.trim() || esquemaChatEditing}
                >
                  <Send size={16} />
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* PHASE: Documento */}
      {phase === 'documento' && (
        <div className="flex flex-1 overflow-hidden">
          {/* Left Pane: Document Viewer */}
          <div className="flex-1 flex flex-col border-r border-line bg-white relative">
            <div className="flex items-center justify-between p-3 border-b border-line shrink-0">
              <div className="flex items-center gap-3">
                <button 
                  className="btn xs"
                  onClick={() => setPhase('list')}
                  title="Ver lista de memorias"
                >
                  &larr; Ver lista de memorias
                </button>
                <div className="font-semibold text-ink-1">
                  {activeDoc?.title || 'Documento'}
                </div>
              </div>
              
              <div className="flex items-center gap-2">
                <span className="text-12 text-ink-3 min-w-[80px] text-right pr-1">
                  {saveStatus === 'saving' && 'Guardando…'}
                  {saveStatus === 'saved' && 'Guardado'}
                  {saveStatus === 'dirty' && 'Sin guardar'}
                  {saveStatus === 'error' && 'Error al guardar'}
                </span>
                <button
                  className="btn xs"
                  onClick={() => void handleSaveDocument()}
                  disabled={!activeDoc || saveStatus === 'saving'}
                >
                  <Save size={14} className="mr-1" />
                  Guardar
                </button>
                <button className="btn xs primary" onClick={handleExportPdf}>
                  <Download size={14} className="mr-1" />
                  Exportar PDF
                </button>
              </div>
            </div>

            {/*
              Wrapper relative que NO hace scroll: el overlay del agente se
              ancla aquí para mantenerse fijo aunque el contenedor interior
              se desplace.
            */}
            <div className="flex-1 relative overflow-hidden">
              <div className="absolute inset-0 overflow-hidden bg-gray-100">
                <RichDocumentEditor
                  markdown={markdown}
                  onChange={setMarkdown}
                  disabled={chatEditing}
                />
              </div>
              {chatEditing && <AiEditingOverlay />}
            </div>
          </div>

          {/* Right Pane: Chat */}
          <div className="w-80 flex flex-col bg-surface shrink-0">
            <div className="p-3 border-b border-line shrink-0 flex items-center gap-2 font-semibold text-14 text-ink-1">
              <Bot size={18} className="text-primary"/> Asistente IA
            </div>
            
            <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-4">
              {chatHistory.map(msg => (
                <div 
                  key={msg.id} 
                  className={`flex flex-col max-w-[90%] ${msg.role === 'user' ? 'self-end items-end' : 'self-start items-start'}`}
                >
                  <div className={`p-3 rounded-lg text-13 whitespace-pre-wrap ${
                    msg.role === 'user'
                      ? 'bg-ink text-white rounded-br-none'
                      : 'bg-white border border-line text-ink-1 rounded-bl-none shadow-sm'
                  }`}>
                    {msg.content}
                  </div>
                </div>
              ))}
            </div>

            <div className="p-4 border-t border-line shrink-0 bg-white">
              <div className="flex gap-2">
                <input
                  type="text"
                  className="real-input flex-1 text-13"
                  placeholder="Dime qué cambiar..."
                  value={chatInput}
                  onChange={e => setChatInput(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleSendChat()}
                />
                <button
                  className="btn primary p-2"
                  onClick={handleSendChat}
                  disabled={!chatInput.trim() || chatEditing}
                >
                  <Send size={16} />
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
