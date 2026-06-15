import type { AuditEvent } from "../../lib/api";
import { Panel } from "../ui";

const TONE: Record<string, string> = {
  authorize: "text-accent",
  start: "text-signal-managed",
  restart: "text-signal-managed",
  stop: "text-haze-300",
  kill: "text-signal-rogue",
  kill_port: "text-signal-rogue",
  flag_unauthorized: "text-signal-rogue",
  reserve: "text-signal-reserved",
  release: "text-haze-400",
};

function time(ts: string | null): string {
  if (!ts) return "";
  try {
    return new Date(ts).toLocaleTimeString([], { hour12: false });
  } catch {
    return "";
  }
}

function summary(detail: Record<string, unknown>): string {
  const parts: string[] = [];
  if (detail.service) parts.push(String(detail.service));
  if (detail.port) parts.push(`:${detail.port}`);
  if (detail.purpose) parts.push(String(detail.purpose));
  return parts.join(" ");
}

export default function AuditFeed({ events }: { events: AuditEvent[] }) {
  return (
    <Panel title="Activity" className="max-h-[420px]">
      {events.length === 0 ? (
        <p className="px-4 py-8 text-center text-sm text-haze-400">No activity yet.</p>
      ) : (
        <ul className="divide-y divide-white/5">
          {events.map((e) => (
            <li key={e.id} className="flex items-baseline gap-3 px-4 py-2 text-sm">
              <span className="tnum shrink-0 text-[11px] text-haze-400">{time(e.ts)}</span>
              <span className={`shrink-0 font-medium ${TONE[e.type] ?? "text-haze-300"}`}>
                {e.type}
              </span>
              <span className="truncate text-haze-400">{summary(e.detail)}</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
