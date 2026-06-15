import { useEffect, useRef } from "react";
import { api } from "../../lib/api";
import { usePoll } from "../../hooks/usePoll";
import { Button } from "../ui";

interface Props {
  runId: number;
  name: string;
  onClose: () => void;
}

export default function LogsDrawer({ runId, name, onClose }: Props) {
  const log = usePoll(() => api.runLog(runId), 1200);
  const bottomRef = useRef<HTMLDivElement>(null);
  const lines = log.data?.lines ?? [];

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines.length]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-ink-900/60 backdrop-blur-sm" onClick={onClose}>
      <aside
        className="flex h-full w-full max-w-2xl flex-col border-l border-white/10 bg-ink-800 shadow-panel"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-white/5 px-4 py-3">
          <div>
            <h3 className="font-medium text-haze-200">{name}</h3>
            <p className="text-[11px] uppercase tracking-wider text-haze-400">run #{runId} · live</p>
          </div>
          <Button variant="ghost" onClick={onClose}>
            Close ✕
          </Button>
        </header>
        <div className="flex-1 overflow-auto bg-ink-900/80 p-4 font-mono text-xs leading-relaxed text-haze-300">
          {lines.length === 0 ? (
            <p className="text-haze-400">No output captured yet…</p>
          ) : (
            lines.map((line, i) => (
              <div key={i} className="whitespace-pre-wrap break-words">
                {line}
              </div>
            ))
          )}
          <div ref={bottomRef} />
        </div>
      </aside>
    </div>
  );
}
