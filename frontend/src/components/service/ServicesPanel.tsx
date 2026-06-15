import { useState } from "react";
import { api, type ServiceAction, type ServiceItem } from "../../lib/api";
import { Button, Panel } from "../ui";

interface Props {
  services: ServiceItem[];
  onChanged: () => void;
  onLogs: (runId: number, name: string) => void;
  notify: (msg: string) => void;
}

const BLANK = { name: "", command: "", description: "", cwd: "", port: "", auto_port: true };

export default function ServicesPanel({ services, onChanged, onLogs, notify }: Props) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ ...BLANK });
  const [busy, setBusy] = useState<number | null>(null);

  const run = async (fn: () => Promise<unknown>, id?: number) => {
    try {
      if (id) setBusy(id);
      await fn();
      onChanged();
    } catch (e) {
      notify(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const act = (svc: ServiceItem, a: ServiceAction) => run(() => api.action(svc.id, a), svc.id);

  const submit = async () => {
    if (!form.name.trim() || !form.command.trim()) {
      notify("Name and command are required.");
      return;
    }
    await run(() =>
      api.createService({
        name: form.name,
        command: form.command,
        description: form.description,
        cwd: form.cwd,
        port: form.port ? Number(form.port) : null,
        auto_port: form.auto_port && !form.port,
      }),
    );
    setForm({ ...BLANK });
    setOpen(false);
  };

  return (
    <Panel
      title="Services"
      action={
        <Button variant="accent" onClick={() => setOpen((v) => !v)}>
          {open ? "Cancel" : "+ Authorize service"}
        </Button>
      }
    >
      {open && (
        <div className="grid grid-cols-2 gap-3 border-b border-white/5 bg-ink-900/40 p-4">
          <Field label="Name" value={form.name} onChange={(v) => setForm({ ...form, name: v })} />
          <Field
            label="Assigned port (blank = auto)"
            value={form.port}
            onChange={(v) => setForm({ ...form, port: v })}
            placeholder="auto"
          />
          <Field
            label="Command"
            value={form.command}
            onChange={(v) => setForm({ ...form, command: v })}
            className="col-span-2"
            placeholder="npm run dev   ($PORT is injected)"
          />
          <Field
            label="Working directory"
            value={form.cwd}
            onChange={(v) => setForm({ ...form, cwd: v })}
            placeholder="/path/to/project"
          />
          <Field
            label="What it does"
            value={form.description}
            onChange={(v) => setForm({ ...form, description: v })}
          />
          <div className="col-span-2 flex justify-end">
            <Button variant="accent" onClick={submit}>
              Authorize
            </Button>
          </div>
        </div>
      )}

      {services.length === 0 ? (
        <Empty>No services authorized yet. Add one to start managing it.</Empty>
      ) : (
        <ul className="divide-y divide-white/5">
          {services.map((svc) => (
            <li key={svc.id} className="flex items-start justify-between gap-3 px-4 py-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span
                    className={`h-2 w-2 rounded-full ${
                      svc.running ? "bg-signal-managed shadow-glow" : "bg-signal-idle"
                    }`}
                  />
                  <span className="font-medium text-haze-200">{svc.name}</span>
                  {svc.assigned_port && (
                    <span className="tnum rounded bg-white/5 px-1.5 py-0.5 text-[11px] text-accent">
                      :{svc.assigned_port}
                    </span>
                  )}
                  {svc.pid && (
                    <span className="tnum text-[11px] text-haze-400">pid {svc.pid}</span>
                  )}
                </div>
                <p className="mt-1 truncate font-mono text-xs text-haze-400">{svc.command}</p>
                {svc.description && (
                  <p className="mt-0.5 truncate text-xs text-haze-400/80">{svc.description}</p>
                )}
              </div>
              <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
                {svc.running ? (
                  <>
                    <Button onClick={() => act(svc, "restart")} disabled={busy === svc.id}>
                      Restart
                    </Button>
                    <Button onClick={() => act(svc, "stop")} disabled={busy === svc.id}>
                      Stop
                    </Button>
                    <Button variant="danger" onClick={() => act(svc, "kill")} disabled={busy === svc.id}>
                      Kill
                    </Button>
                  </>
                ) : (
                  <Button variant="accent" onClick={() => act(svc, "start")} disabled={busy === svc.id}>
                    Start
                  </Button>
                )}
                {svc.latest_run_id && (
                  <Button variant="ghost" onClick={() => onLogs(svc.latest_run_id!, svc.name)}>
                    Logs
                  </Button>
                )}
                {!svc.running && (
                  <Button
                    variant="ghost"
                    onClick={() => run(() => api.deleteService(svc.id), svc.id)}
                    disabled={busy === svc.id}
                  >
                    ✕
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  className = "",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  className?: string;
}) {
  return (
    <label className={`flex flex-col gap-1 ${className}`}>
      <span className="text-[11px] uppercase tracking-wider text-haze-400">{label}</span>
      <input
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-lg border border-white/10 bg-ink-900/60 px-2.5 py-1.5 font-mono text-sm text-haze-200 placeholder:text-haze-400/50 focus:border-accent/50 focus:outline-none"
      />
    </label>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="px-4 py-8 text-center text-sm text-haze-400">{children}</p>;
}
