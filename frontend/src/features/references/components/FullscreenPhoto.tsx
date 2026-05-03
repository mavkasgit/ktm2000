import React, { useEffect, useRef, useState } from "react";
import { Plus, X, Maximize2 } from "lucide-react";

export function FullscreenPhoto({
  src,
  alt,
  onClose,
}: {
  src: string;
  alt: string;
  onClose: () => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const [scale, setScale] = useState(1);
  const [translate, setTranslate] = useState({ x: 0, y: 0 });
  const isDragging = useRef(false);
  const dragStart = useRef({ x: 0, y: 0 });
  const translateStart = useRef({ x: 0, y: 0 });
  const clickStart = useRef({ x: 0, y: 0 });
  const hasDragged = useRef(false);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    el.requestFullscreen().catch(() => {});

    const handleFullscreenChange = () => {
      if (!document.fullscreenElement) onClose();
    };
    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => {
      document.removeEventListener("fullscreenchange", handleFullscreenChange);
      if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    };
  }, [onClose]);

  const zoomToPoint = (clientX: number, clientY: number, newScale: number) => {
    const container = containerRef.current;
    if (!container) return;
    const rect = container.getBoundingClientRect();
    const px = clientX - rect.left - rect.width / 2;
    const py = clientY - rect.top - rect.height / 2;

    setTranslate((prev) => ({
      x: px - (px - prev.x) * (newScale / scale),
      y: py - (py - prev.y) * (newScale / scale),
    }));
    setScale(newScale);
  };

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? -0.15 : 0.15;
    const newScale = Math.max(0.5, Math.min(10, scale + delta));
    if (newScale !== scale) {
      zoomToPoint(e.clientX, e.clientY, newScale);
    }
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    isDragging.current = true;
    hasDragged.current = false;
    dragStart.current = { x: e.clientX, y: e.clientY };
    translateStart.current = { ...translate };
    clickStart.current = { x: e.clientX, y: e.clientY };
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging.current) return;
    const dx = e.clientX - dragStart.current.x;
    const dy = e.clientY - dragStart.current.y;
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
      hasDragged.current = true;
    }
    setTranslate({
      x: translateStart.current.x + dx,
      y: translateStart.current.y + dy,
    });
  };

  const handleMouseUp = (e: React.MouseEvent) => {
    if (!isDragging.current) return;
    isDragging.current = false;

    if (!hasDragged.current) {
      const dist = Math.hypot(e.clientX - clickStart.current.x, e.clientY - clickStart.current.y);
      if (dist < 5) {
        const newScale = scale >= 3 ? 1 : Math.min(10, scale * 1.6);
        zoomToPoint(e.clientX, e.clientY, newScale);
      }
    }
  };

  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    const newScale = Math.max(0.5, scale / 1.6);
    if (newScale < 0.7) {
      setScale(1);
      setTranslate({ x: 0, y: 0 });
    } else {
      zoomToPoint(e.clientX, e.clientY, newScale);
    }
  };

  const handleDoubleClick = () => {
    setScale(1);
    setTranslate({ x: 0, y: 0 });
  };

  return (
    <div
      ref={containerRef}
      className="fixed inset-0 z-[100] bg-black flex items-center justify-center overflow-hidden select-none"
      onWheel={handleWheel}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      onContextMenu={handleContextMenu}
      onDoubleClick={handleDoubleClick}
    >
      <div className="absolute top-4 right-4 flex gap-2 z-10">
        <button
          onClick={() => {
            const newScale = Math.min(10, scale * 1.5);
            const rect = containerRef.current?.getBoundingClientRect();
            if (rect) zoomToPoint(rect.left + rect.width / 2, rect.top + rect.height / 2, newScale);
          }}
          className="p-2 bg-black/50 hover:bg-black/70 text-white rounded-full"
          type="button"
          title="Приблизить (+)"
        >
          <Plus className="w-5 h-5" />
        </button>
        <button
          onClick={() => {
            const newScale = Math.max(0.5, scale / 1.5);
            const rect = containerRef.current?.getBoundingClientRect();
            if (rect) zoomToPoint(rect.left + rect.width / 2, rect.top + rect.height / 2, newScale);
          }}
          className="p-2 bg-black/50 hover:bg-black/70 text-white rounded-full"
          type="button"
          title="Отдалить (-)"
        >
          <X className="w-5 h-5" />
        </button>
        <button
          onClick={handleDoubleClick}
          className="p-2 bg-black/50 hover:bg-black/70 text-white rounded-full"
          type="button"
          title="Сбросить (1:1)"
        >
          <Maximize2 className="w-5 h-5" />
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            document.exitFullscreen().catch(() => {});
          }}
          className="p-2 bg-black/50 hover:bg-black/70 text-white rounded-full"
          type="button"
          title="Закрыть"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      <div className="absolute bottom-4 left-4 text-white/60 text-sm z-10 pointer-events-none">
        {Math.round(scale * 100)}% • ЛКМ: приблизить/перетащить • Колесико: зум • ПКМ: отдалить • Двойной клик: сброс
      </div>

      <img
        ref={imageRef}
        src={src}
        alt={alt}
        draggable={false}
        className="max-w-none transition-transform duration-75 ease-out"
        style={{
          transform: `translate(${translate.x}px, ${translate.y}px) scale(${scale})`,
          cursor: isDragging.current ? "grabbing" : scale > 1 ? "grab" : "zoom-in",
        }}
      />
    </div>
  );
}
