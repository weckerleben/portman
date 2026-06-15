import { useState } from "react";
import { api } from "../../lib/api";
import { usePoll } from "../../hooks/usePoll";
import { Button, Stat } from "../ui";
import PortsTable from "../ports/PortsTable";
import ReservePanel from "../ports/ReservePanel";
import ServicesPanel from "../service/ServicesPanel";
import LogsDrawer from "../service/LogsDrawer";
import AuditFeed from "./AuditFeed";

export default function Dashboard() {
  const view = usePoll(api.ports, 2000);
  const audit = usePoll(api.audit, 5000);
  const [logTarget, setLogTarget] = useState<{ runId: number; name: string } | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const notify = (msg: string) => {
    setToast(msg);
    window.setTimeout(() => setToast(null), 4000);
  };
  const refreshAll = () => {
    view.refresh();
    audit.refresh();
  };

  const data = view.data;
  const counts = data?.counts ?? { managed: 0, unauthorized: 0, reserved_idle: 0 };
  const online = !view.error;

  return (
    <div className="mx-auto min-h-full max-w-[1400px] px-5 pb-16 pt-6">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-mono text-3xl font-bold tracking-tight text-haze-200">
            port<span className="text-accent">man</span>
          </h1>
          <p className="mt-1 max-w-md text-sm text-haze-400">
            Nothing binds a port here without being authorized first. Watch, control and audit
            every local service.
          </p>
        </div>
        <div className="flex items-center gap-7">
          <Stat label="managed" value={counts.managed} tone="text-signal-managed" />
          <Stat label="unauthorized" value={counts.unauthorized} tone="text-signal-rogue" />
          <Stat label="reserved" value={counts.reserved_idle} tone="text-signal-reserved" />
          <div className="flex flex-col items-end gap-2">
            <span
              className={`inline-flex items-center gap-2 text-xs font-medium ${
                online ? "text-signal-managed" : "text-signal-rogue"
              }`}
            >
              <span className="h-2 w-2 rounded-full bg-current shadow-glow" />
              {online ? "daemon online" : "daemon offline"}
            </span>
            <Button variant="ghost" onClick={refreshAll}>
              ↻ refresh
            </Button>
          </div>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-12">
        <div className="flex flex-col gap-5 lg:col-span-8">
          <ServicesPanel
            services={data?.services ?? []}
            onChanged={refreshAll}
            onLogs={(runId, name) => setLogTarget({ runId, name })}
            notify={notify}
          />
          <PortsTable
            ports={data?.ports ?? []}
            idleReservations={data?.idle_reservations ?? []}
            onChanged={refreshAll}
            notify={notify}
          />
        </div>
        <div className="flex flex-col gap-5 lg:col-span-4">
          <ReservePanel
            reservations={data?.reservations ?? []}
            onChanged={refreshAll}
            notify={notify}
          />
          <AuditFeed events={audit.data ?? []} />
        </div>
      </div>

      {logTarget && (
        <LogsDrawer
          runId={logTarget.runId}
          name={logTarget.name}
          onClose={() => setLogTarget(null)}
        />
      )}

      {toast && (
        <div className="fixed bottom-5 left-1/2 z-50 -translate-x-1/2 rounded-xl border border-signal-rogue/40 bg-ink-800 px-4 py-2.5 text-sm text-signal-rogue shadow-panel">
          {toast}
        </div>
      )}
    </div>
  );
}
