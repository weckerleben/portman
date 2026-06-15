import { api, type ClassifiedPort, type Reservation } from "../../lib/api";
import { Button, Panel, StatusBadge } from "../ui";

interface Props {
  ports: ClassifiedPort[];
  idleReservations: Reservation[];
  onChanged: () => void;
  notify: (msg: string) => void;
}

export default function PortsTable({ ports, idleReservations, onChanged, notify }: Props) {
  const kill = async (port: number) => {
    try {
      await api.killPort(port);
      onChanged();
    } catch (e) {
      notify(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <Panel title={`Live ports (${ports.length})`}>
      <table className="w-full text-left text-sm">
        <thead className="sticky top-0 bg-ink-800/95 text-[11px] uppercase tracking-wider text-haze-400">
          <tr>
            <th className="px-4 py-2 font-medium">Port</th>
            <th className="px-4 py-2 font-medium">Status</th>
            <th className="px-4 py-2 font-medium">Process</th>
            <th className="px-4 py-2 font-medium">PID</th>
            <th className="px-4 py-2 font-medium">Command</th>
            <th className="px-4 py-2 text-right font-medium">Action</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-white/5">
          {ports.length === 0 && (
            <tr>
              <td colSpan={6} className="px-4 py-8 text-center text-haze-400">
                Nothing is listening.
              </td>
            </tr>
          )}
          {ports.map((p) => (
            <tr
              key={`${p.port}-${p.pid}`}
              className={`transition-colors hover:bg-white/[0.03] ${
                p.status === "unauthorized" ? "bg-signal-rogue/[0.04]" : ""
              }`}
            >
              <td className="tnum px-4 py-2.5 font-mono font-semibold text-haze-200">{p.port}</td>
              <td className="px-4 py-2.5">
                <StatusBadge status={p.status} />
              </td>
              <td className="px-4 py-2.5 text-haze-300">{p.name || "—"}</td>
              <td className="tnum px-4 py-2.5 text-haze-400">{p.pid ?? "—"}</td>
              <td className="max-w-[280px] truncate px-4 py-2.5 font-mono text-xs text-haze-400">
                {p.cmdline || "—"}
              </td>
              <td className="px-4 py-2.5 text-right">
                {p.status === "unauthorized" && (
                  <Button variant="danger" onClick={() => kill(p.port)}>
                    Kill port
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {idleReservations.length > 0 && (
        <div className="border-t border-white/5 px-4 py-3">
          <p className="mb-2 text-[11px] uppercase tracking-wider text-haze-400">
            Reserved, not yet bound
          </p>
          <div className="flex flex-wrap gap-2">
            {idleReservations.map((r) => (
              <span
                key={r.id}
                className="tnum inline-flex items-center gap-2 rounded-lg border border-signal-reserved/30 bg-signal-reserved/10 px-2.5 py-1 text-xs text-signal-reserved"
                title={r.purpose}
              >
                :{r.port}
                {r.purpose && <span className="text-haze-400">· {r.purpose}</span>}
              </span>
            ))}
          </div>
        </div>
      )}
    </Panel>
  );
}
