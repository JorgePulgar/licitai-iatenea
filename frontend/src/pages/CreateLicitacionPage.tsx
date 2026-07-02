import { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { v4 as uuidv4 } from 'uuid';
import AppShell from '../components/layout/AppShell';
import StateTag from '../components/ui/StateTag';
import { createLicitacion, fetchUploadToken } from '../services/api';
import { uploadFileToBlob, type BlobUploadResult } from '../services/blobStorage';
import { useLicitaciones } from '../hooks/useLicitaciones';
import { useModal } from '../hooks/useModal';
import type { DocumentUploadInfo, LicitacionCreateRequest } from '../types/licitacion';

type DocSlotKey = 'pcap' | 'ppt' | 'anexo';

interface FileSlot {
  file: File;
  type: DocSlotKey;
  progress: number;
  status: 'pending' | 'uploading' | 'uploaded' | 'error';
  blobResult?: BlobUploadResult;
  error?: string;
}

function formatBytes(b: number): string {
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(0)} KB`;
  return `${(b / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('es-ES', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

const DOC_TYPE_LABELS: Record<DocSlotKey, string> = {
  pcap: 'PCAP (obligatorio)',
  ppt: 'PPT (opcional)',
  anexo: 'Anexo',
};

export default function CreateLicitacionPage() {
  const navigate = useNavigate();
  const { showModal } = useModal();
  const { licitaciones, reload } = useLicitaciones(5_000);
  const [title, setTitle] = useState('');
  const [deadline, setDeadline] = useState('');
  const [files, setFiles] = useState<FileSlot[]>([]);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState<DocSlotKey | null>(null);

  const pcapRef = useRef<HTMLInputElement>(null);
  const pptRef = useRef<HTMLInputElement>(null);
  const anexoRef = useRef<HTMLInputElement>(null);

  const recentlyDone = licitaciones
    .filter((l) => l.status === 'indexed')
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 5);

  const inProgressLicitaciones = licitaciones.filter(
    (l) => l.status === 'processing',
  );

  const pcapFile = files.find((f) => f.type === 'pcap');
  const pptFile = files.find((f) => f.type === 'ppt');
  const anexoFiles = files.filter((f) => f.type === 'anexo');

  const canSubmit = !!title.trim() && !!pcapFile && !creating;

  function addFile(file: File, type: DocSlotKey) {
    const ok = file.type === 'application/pdf' || file.name.endsWith('.pdf');
    if (!ok) {
      void showModal({
        type: 'alert',
        title: 'Formato no válido',
        description: <>El archivo <strong>{file.name}</strong> no es un PDF.</>,
        tone: 'warning',
      });
      return;
    }
    if (file.size > 50 * 1024 * 1024) {
      void showModal({
        type: 'alert',
        title: 'Archivo demasiado grande',
        description: <><strong>{file.name}</strong> supera el límite de 50 MB.</>,
        tone: 'warning',
      });
      return;
    }

    if (type === 'pcap' || type === 'ppt') {
      // Replace existing file of this type
      setFiles((prev) => [
        ...prev.filter((f) => f.type !== type),
        { file, type, progress: 0, status: 'pending' },
      ]);
    } else {
      // Append for anexos
      setFiles((prev) => [
        ...prev,
        { file, type, progress: 0, status: 'pending' },
      ]);
    }
  }

  function removeFile(idx: number) {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
  }

  function handleDrop(e: React.DragEvent, type: DocSlotKey) {
    e.preventDefault();
    setDragging(null);
    const dropped = Array.from(e.dataTransfer.files);
    if (type === 'pcap' || type === 'ppt') {
      if (dropped[0]) addFile(dropped[0], type);
    } else {
      dropped.forEach((f) => addFile(f, 'anexo'));
    }
  }

  function handleFileInput(e: React.ChangeEvent<HTMLInputElement>, type: DocSlotKey) {
    if (e.target.files) {
      const arr = Array.from(e.target.files);
      if (type === 'pcap' || type === 'ppt') {
        if (arr[0]) addFile(arr[0], type);
      } else {
        arr.forEach((f) => addFile(f, 'anexo'));
      }
      e.target.value = '';
    }
  }

  function updateFileSlot(idx: number, patch: Partial<FileSlot>) {
    setFiles((prev) => prev.map((f, i) => (i === idx ? { ...f, ...patch } : f)));
  }

  async function handleSubmit() {
    if (!canSubmit) return;

    setCreating(true);
    setError(null);

    const licitacionPrefix = uuidv4();

    try {
      // 0. Get upload token from backend
      const auth = await fetchUploadToken();

      // 1. Upload all files to blob storage
      for (let i = 0; i < files.length; i++) {
        const slot = files[i];
        updateFileSlot(i, { status: 'uploading', progress: 0 });

        try {
          const result = await uploadFileToBlob(
            slot.file,
            licitacionPrefix,
            auth,
            (pct) => updateFileSlot(i, { progress: pct }),
          );
          updateFileSlot(i, { status: 'uploaded', progress: 100, blobResult: result });
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          updateFileSlot(i, { status: 'error', error: msg });
          throw new Error(`Error subiendo "${slot.file.name}": ${msg}`);
        }
      }

      // 2. Read back the updated files with blob results
      // We need a fresh read because setState is async
      const updatedFiles = await new Promise<FileSlot[]>((resolve) => {
        setFiles((prev) => {
          resolve(prev);
          return prev;
        });
      });

      const pcapSlot = updatedFiles.find((f) => f.type === 'pcap');
      const pptSlot = updatedFiles.find((f) => f.type === 'ppt');
      const anexoSlots = updatedFiles.filter((f) => f.type === 'anexo');

      if (!pcapSlot?.blobResult) {
        throw new Error('Error: no se pudo obtener la URL del PCAP');
      }

      // 3. Build request body
      const body: LicitacionCreateRequest = {
        title: title.trim(),
        ...(deadline ? { deadline } : {}),
        pcap: toDocUploadInfo(pcapSlot.blobResult),
        ...(pptSlot?.blobResult ? { ppt: toDocUploadInfo(pptSlot.blobResult) } : {}),
        anexos: anexoSlots
          .filter((s) => s.blobResult)
          .map((s) => toDocUploadInfo(s.blobResult!)),
      };

      // 4. Create licitacion in the backend
      const licitacion = await createLicitacion(body);
      reload();

      // 5. Navigate to the new licitacion
      navigate(`/licitaciones/${licitacion.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setCreating(false);
    }
  }

  function toDocUploadInfo(result: BlobUploadResult): DocumentUploadInfo {
    return {
      blob_url: result.blob_url,
      filename: result.filename,
      size_bytes: result.size_bytes,
    };
  }

  function renderDropZone(
    type: DocSlotKey,
    ref: React.RefObject<HTMLInputElement>,
    existingFile?: FileSlot,
    multiple = false,
  ) {
    const isActive = dragging === type;
    const label = DOC_TYPE_LABELS[type];

    return (
      <div className="flex flex-col gap-2">
        <div className="t-up">{label}</div>

        {existingFile && (
          <div className="surface p-3 flex items-center gap-3">
            <span className="icn-doc" />
            <div className="flex flex-col flex-1 min-w-0">
              <div className="t-medium text-12 truncate">{existingFile.file.name}</div>
              <div className="flex gap-2 t-xs t-mute">
                <span>{formatBytes(existingFile.file.size)}</span>
                {existingFile.status === 'uploading' && (
                  <span className="text-accent">{existingFile.progress}%</span>
                )}
                {existingFile.status === 'uploaded' && (
                  <span className="text-ok">✓ Subido</span>
                )}
                {existingFile.status === 'error' && (
                  <span className="text-err">✕ {existingFile.error}</span>
                )}
              </div>
            </div>
            {existingFile.status !== 'uploading' && (
              <button
                className="btn sm ghost danger px-[6px] py-[2px]"
                onClick={() => {
                  const idx = files.indexOf(existingFile);
                  if (idx >= 0) removeFile(idx);
                }}
              >
                ✕
              </button>
            )}
          </div>
        )}

        {(!existingFile || type === 'anexo') && (
          <div
            className={`surface border-dashed p-6 text-center transition-all duration-150 ${
              isActive ? 'border-accent bg-accent-bg' : 'border-line-strong'
            }`}
            onDragOver={(e) => { e.preventDefault(); setDragging(type); }}
            onDragLeave={() => setDragging(null)}
            onDrop={(e) => handleDrop(e, type)}
          >
            <div className="t-xs t-mute mb-2">
              {isActive ? 'Suelta para añadir' : 'Arrastra un PDF aquí'}
            </div>
            <input
              ref={ref}
              type="file"
              accept=".pdf"
              multiple={multiple}
              className="hidden"
              onChange={(e) => handleFileInput(e, type)}
            />
            <button
              className="btn sm"
              onClick={() => ref.current?.click()}
            >
              Seleccionar archivo{multiple ? 's' : ''}
            </button>
          </div>
        )}
      </div>
    );
  }

  return (
    <AppShell
      crumbs={['Licitaciones', 'Nueva']}
      licitacionCount={licitaciones.length}
      queueCount={inProgressLicitaciones.length}
      statusItems={[`${inProgressLicitaciones.length} en proceso`]}
    >
      <div className="page">
        <div className="t-2xl mb-1">Nueva licitación</div>
        <div className="help mb-4">
          Sube los documentos de la licitación: PCAP (obligatorio), PPT (opcional) y anexos.
          Los archivos se suben directamente a Azure Blob Storage.
        </div>

        <div className="flex gap-4 items-start">
          {/* Left: form + file slots */}
          <div className="flex flex-col flex-1 gap-4">
            {/* Title + deadline */}
            <div className="surface p-4 flex flex-col gap-3">
              <div>
                <label className="label">Título de la licitación *</label>
                <input
                  className="real-input w-full"
                  placeholder="Ej: Contrato de servicios IT — Ayuntamiento de Madrid 2026"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  disabled={creating}
                />
              </div>
              <div>
                <label className="label">Fecha límite de presentación (opcional)</label>
                <input
                  type="date"
                  className="real-input w-full"
                  value={deadline}
                  onChange={(e) => setDeadline(e.target.value)}
                  disabled={creating}
                />
                <div className="help mt-1">Podrás editarla y cambiar el estado después en el detalle.</div>
              </div>
            </div>

            {/* PCAP */}
            {renderDropZone('pcap', pcapRef as React.RefObject<HTMLInputElement>, pcapFile)}

            {/* PPT */}
            {renderDropZone('ppt', pptRef as React.RefObject<HTMLInputElement>, pptFile)}

            {/* Anexos */}
            <div className="flex flex-col gap-2">
              <div className="t-up">Anexos (opcional)</div>
              {anexoFiles.map((slot, i) => (
                <div key={i} className="surface p-3 flex items-center gap-3">
                  <span className="icn-doc" />
                  <div className="flex flex-col flex-1 min-w-0">
                    <div className="t-medium text-12 truncate">{slot.file.name}</div>
                    <div className="flex gap-2 t-xs t-mute">
                      <span>{formatBytes(slot.file.size)}</span>
                      {slot.status === 'uploading' && (
                        <span className="text-accent">{slot.progress}%</span>
                      )}
                      {slot.status === 'uploaded' && (
                        <span className="text-ok">✓ Subido</span>
                      )}
                      {slot.status === 'error' && (
                        <span className="text-err">✕ {slot.error}</span>
                      )}
                    </div>
                  </div>
                  {slot.status !== 'uploading' && (
                    <button
                      className="btn sm ghost danger px-[6px] py-[2px]"
                      onClick={() => {
                        const realIdx = files.indexOf(slot);
                        if (realIdx >= 0) removeFile(realIdx);
                      }}
                    >
                      ✕
                    </button>
                  )}
                </div>
              ))}
              <div
                className={`surface border-dashed p-6 text-center transition-all duration-150 ${
                  dragging === 'anexo' ? 'border-accent bg-accent-bg' : 'border-line-strong'
                }`}
                onDragOver={(e) => { e.preventDefault(); setDragging('anexo'); }}
                onDragLeave={() => setDragging(null)}
                onDrop={(e) => handleDrop(e, 'anexo')}
              >
                <div className="t-xs t-mute mb-2">
                  {dragging === 'anexo' ? 'Suelta para añadir' : 'Arrastra PDFs aquí'}
                </div>
                <input
                  ref={anexoRef}
                  type="file"
                  accept=".pdf"
                  multiple
                  className="hidden"
                  onChange={(e) => handleFileInput(e, 'anexo')}
                />
                <button
                  className="btn sm"
                  onClick={() => anexoRef.current?.click()}
                >
                  Seleccionar anexos
                </button>
              </div>
            </div>

            {/* Submit */}
            <div className="flex items-center gap-3">
              <button
                className="btn primary"
                disabled={!canSubmit}
                onClick={handleSubmit}
              >
                {creating ? 'Creando licitación…' : 'Crear licitación'}
              </button>
              <button
                className="btn"
                onClick={() => navigate('/licitaciones')}
                disabled={creating}
              >
                Cancelar
              </button>
            </div>

            {error && (
              <div className="text-12 text-red-500 bg-red-50 border border-red-200 rounded px-3 py-2">
                {error}
              </div>
            )}

            {/* Config */}
            <div className="surface">
              <div className="flex justify-between items-center p-3 border-b border-line">
                <div className="t-medium">Configuración por defecto</div>
              </div>
              <div className="p-3 flex flex-col gap-2 text-12">
                {[
                  ['Almacenamiento', 'Azure Blob Storage (directo)'],
                  ['Política de retención', '5 años (LCSP)'],
                  ['Detección de tipo', 'Automática (pipeline v0.4.2)'],
                  ['Idioma OCR', 'Español (es-ES)'],
                  ['Pipeline', 'v0.4.2 estable'],
                ].map(([k, v]) => (
                  <div key={k} className="flex justify-between">
                    <span className="t-mute">{k}</span>
                    <span>{v}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Right: queue + recently done */}
          <div className="flex flex-col w-[380px] gap-2">
            <div className="flex justify-between items-center">
              <div className="t-up">En proceso · {inProgressLicitaciones.length}</div>
              <span className="t-xs t-mute">actualiza cada 5s</span>
            </div>

            {inProgressLicitaciones.length === 0 && (
              <div className="surface flex items-center justify-center p-6 text-ink-4 text-12">
                Sin licitaciones en proceso
              </div>
            )}

            {inProgressLicitaciones.map((l) => (
              <div
                key={l.id}
                className="surface p-3 flex flex-col gap-2 cursor-pointer"
                onClick={() => navigate(`/licitaciones/${l.id}`)}
              >
                <div className="flex items-center gap-2">
                  <span className="icn-doc" />
                  <div className="flex flex-col flex-1 min-w-0">
                    <div className="t-medium text-12 truncate">{l.title}</div>
                    <div className="flex gap-2 t-xs t-mute">
                      <span className="num">{l.id.slice(0, 8).toUpperCase()}</span>
                      <span>·</span>
                      <span><StateTag status={l.status} /></span>
                      <span>·</span>
                      <span>{l.documents.length} docs</span>
                    </div>
                  </div>
                </div>
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: '50%' }} />
                </div>
              </div>
            ))}

            <div className="divider" />

            <div className="t-up">Completadas · {recentlyDone.length}</div>

            {recentlyDone.length === 0 && (
              <div className="t-xs t-mute py-2">
                Sin licitaciones indexadas aún
              </div>
            )}

            {recentlyDone.map((l) => (
              <div
                key={l.id}
                className="flex items-center gap-2 p-2 surface text-12 cursor-pointer"
                onClick={() => navigate(`/licitaciones/${l.id}`)}
              >
                <span className="dot ok" />
                <span className="flex-1 truncate">{l.title}</span>
                <span className="num t-mute t-xs">{l.id.slice(0, 8).toUpperCase()}</span>
                <span className="num t-mute t-xs">{formatDate(l.created_at)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
