// Thin typed client over the portman daemon REST API.

export type PortStatus = "managed" | "unauthorized";
export type ServiceAction = "start" | "stop" | "restart" | "kill";

export interface ClassifiedPort {
  port: number;
  pid: number | null;
  name: string;
  cmdline: string;
  cwd: string;
  status: PortStatus;
  service_id: number | null;
  reservation_id: number | null;
}

export interface ServiceItem {
  id: number;
  name: string;
  slug: string;
  description: string;
  command: string;
  cwd: string;
  env: Record<string, string>;
  assigned_port: number | null;
  auto_restart: boolean;
  source: string;
  created_at: string | null;
  running: boolean;
  pid: number | null;
  latest_run_id: number | null;
}

export interface Reservation {
  id: number;
  port: number;
  purpose: string;
  service_id: number | null;
  status: string;
  reserved_at: string | null;
}

export interface PortsView {
  ports: ClassifiedPort[];
  services: ServiceItem[];
  reservations: Reservation[];
  idle_reservations: Reservation[];
  counts: { managed: number; unauthorized: number; reserved_idle: number };
}

export interface AuditEvent {
  id: number;
  ts: string | null;
  type: string;
  detail: Record<string, unknown>;
}

async function handle(res: Response) {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* non-json error body */
    }
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

const post = (url: string, body?: unknown) =>
  fetch(url, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  }).then(handle);

export interface ServiceInput {
  name: string;
  command: string;
  description?: string;
  cwd?: string;
  port?: number | null;
  auto_port?: boolean;
}

export const api = {
  ports: (): Promise<PortsView> => fetch("/api/ports").then(handle),
  service: (id: number): Promise<ServiceItem & { runs: unknown[] }> =>
    fetch(`/api/services/${id}`).then(handle),
  createService: (body: ServiceInput): Promise<ServiceItem> => post("/api/services", body),
  action: (id: number, a: ServiceAction) => post(`/api/services/${id}/${a}`),
  deleteService: (id: number) =>
    fetch(`/api/services/${id}`, { method: "DELETE" }).then(handle),
  runLog: (runId: number): Promise<{ run_id: number; lines: string[] }> =>
    fetch(`/api/runs/${runId}/log?tail=600`).then(handle),
  killPort: (port: number): Promise<{ port: number; killed_pids: number[] }> =>
    post(`/api/ports/${port}/kill`),
  generatePort: (): Promise<{ port: number }> => post("/api/ports/generate"),
  reserve: (body: { port?: number | null; purpose?: string; auto?: boolean }): Promise<Reservation> =>
    post("/api/reservations", body),
  release: (id: number) => fetch(`/api/reservations/${id}`, { method: "DELETE" }).then(handle),
  audit: (): Promise<AuditEvent[]> => fetch("/api/audit?limit=60").then(handle),
};
