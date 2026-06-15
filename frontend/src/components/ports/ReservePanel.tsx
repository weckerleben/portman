import { useState } from "react";
import { api, type Reservation } from "../../lib/api";
import { Button, Panel } from "../ui";

interface Props {
  reservations: Reservation[];
  onChanged: () => void;
  notify: (msg: string) => void;
}

export default function ReservePanel({ reservations, onChanged, notify }: Props) {
  const [port, setPort] = useState("");
  const [purpose, setPurpose] = useState("");
  const [generated, setGenerated] = useState<number | null>(null);

  const guard = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      onChanged();
    } catch (e) {
      notify(e instanceof Error ? e.message : String(e));
    }
  };

  const generate = () =>
    guard(async () => {
      const { port: p } = await api.generatePort();
      setGenerated(p);
    });

  const reserve = () =>
    guard(async () => {
      await api.reserve({
        port: port ? Number(port) : null,
        purpose,
        auto: !port,
      });
      setPort("");
      setPurpose("");
    });

  return (
    <Panel
      title="Ports & reservations"
      action={
        <Button variant="accent" onClick={generate}>
          🎲 Random free port
        </Button>
      }
    >
      <div className="space-y-3 p-4">
        {generated !== null && (
          <div className="flex items-center justify-between rounded-lg border border-accent/30 bg-accent/10 px-3 py-2 text-sm">
            <span className="text-haze-300">Free port found</span>
            <span className="tnum font-mono text-lg font-semibold text-accent">{generated}</span>
          </div>
        )}
        <div className="flex gap-2">
          <input
            value={port}
            onChange={(e) => setPort(e.target.value)}
            placeholder="port (blank = auto)"
            className="tnum w-28 rounded-lg border border-white/10 bg-ink-900/60 px-2.5 py-1.5 font-mono text-sm text-haze-200 placeholder:text-haze-400/50 focus:border-accent/50 focus:outline-none"
          />
          <input
            value={purpose}
            onChange={(e) => setPurpose(e.target.value)}
            placeholder="reserve for…"
            className="flex-1 rounded-lg border border-white/10 bg-ink-900/60 px-2.5 py-1.5 text-sm text-haze-200 placeholder:text-haze-400/50 focus:border-accent/50 focus:outline-none"
          />
          <Button variant="solid" onClick={reserve}>
            Reserve
          </Button>
        </div>

        {reservations.length > 0 && (
          <ul className="divide-y divide-white/5 pt-1">
            {reservations.map((r) => (
              <li key={r.id} className="flex items-center justify-between py-2">
                <div className="flex items-center gap-2">
                  <span className="tnum font-mono font-semibold text-signal-reserved">:{r.port}</span>
                  <span className="text-xs text-haze-400">{r.purpose || "—"}</span>
                </div>
                <Button variant="ghost" onClick={() => guard(() => api.release(r.id))}>
                  Release
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Panel>
  );
}
