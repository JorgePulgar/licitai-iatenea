import Skeleton, { SkeletonTheme } from 'react-loading-skeleton';
import 'react-loading-skeleton/dist/skeleton.css';
import { Sparkles } from 'lucide-react';

/**
 * Overlay con efecto shimmer mientras el agente IA edita el documento.
 *
 * Pinta líneas de Skeleton con un degradado que recorre la zona — el
 * usuario percibe "IA escribiendo" en lugar de un spinner genérico.
 * `react-loading-skeleton` aporta el `linear-gradient` animado;
 * `SkeletonTheme` lo tinta con los colores del acento del producto.
 */
export default function AiEditingOverlay() {
  return (
    <div className="absolute inset-0 z-20 flex flex-col bg-gray-100/90 backdrop-blur-sm">
      <div className="flex items-center justify-center gap-2 px-6 py-3 bg-white/95 border-b border-line text-13 font-medium text-ink-1 shrink-0">
        <Sparkles size={16} className="text-accent animate-pulse" />
        El asistente está editando el documento…
      </div>
      {/* Hoja A4 simulada centrada — coincide con la anchura del visor paginado. */}
      <div className="flex-1 overflow-hidden flex justify-center pt-6">
        <div className="w-full max-w-[794px] bg-white border border-line shadow-sm px-16 py-12">
          <SkeletonTheme baseColor="#eef2ff" highlightColor="#dbeafe" duration={1.4}>
            <Skeleton height={28} width="55%" className="mb-6" />
            <Skeleton count={4} height={12} className="mb-2" />
            <Skeleton height={12} width="80%" className="mb-8" />

            <Skeleton height={22} width="40%" className="mb-5" />
            <Skeleton count={3} height={12} className="mb-2" />
            <Skeleton height={12} width="70%" className="mb-8" />

            <Skeleton height={22} width="48%" className="mb-5" />
            <Skeleton count={4} height={12} className="mb-2" />
            <Skeleton height={12} width="65%" />
          </SkeletonTheme>
        </div>
      </div>
    </div>
  );
}
