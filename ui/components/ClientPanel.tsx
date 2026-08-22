/** The left rail: pick a client and request a briefing. */

"use client";

import { useEffect, useRef, useState } from "react";
import { CLIENT_TEMPLATE_URL, listClients, registerClient } from "@/lib/api";
import { Pill } from "./ui";

const SAMPLE_CLIENTS = [
  { id: "client-000042", label: "Balanced, growth + income" },
  { id: "client-000077", label: "Conservative, preservation" },
  { id: "client-000113", label: "Aggressive, growth" },
  { id: "client-000201", label: "Balanced, ESG-only" },
];

export function ClientPanel({
  onRun,
  loading,
  health,
}: {
  onRun: (clientId: string) => void;
  loading: boolean;
  health: { ok: boolean; profile?: string; region?: string };
}) {
  const [clientId, setClientId] = useState(SAMPLE_CLIENTS[0].id);
  const [registered, setRegistered] = useState<string[]>([]);
  const [uploadNote, setUploadNote] = useState<{ ok: boolean; text: string } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  // Under live the fictional sample clients do not exist server-side: the picker shows
  // audience-registered clients instead (empty until the first registration).
  const isLive = health.profile === "live";

  useEffect(() => {
    if (!health.ok) return;
    listClients()
      .then((ids) => {
        setRegistered(ids);
        if (isLive && ids.length > 0) setClientId(ids[0]);
        else if (isLive) setClientId("");
      })
      .catch(() => setRegistered([]));
  }, [health.ok, isLive]);

  async function onUpload() {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setUploadNote(null);
    try {
      const body = JSON.parse(await file.text()) as { client_id?: string };
      const result = await registerClient(body);
      setUploadNote({
        ok: true,
        text: `Registered ${result.client_id} (${result.holdings} holdings)`,
      });
      setClientId(result.client_id);
      setRegistered(await listClients());
    } catch (e) {
      setUploadNote({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  const picker = isLive
    ? registered.map((id) => ({ id, label: "registered" }))
    : SAMPLE_CLIENTS;

  return (
    <aside className="w-full space-y-4 lg:w-72">
      <div className="rounded-xl border border-ink-200 bg-white p-4 shadow-panel">
        <div className="flex items-center justify-between">
          <h1 className="text-base font-semibold text-ink-800">CIO Advisory</h1>
          <Pill tone={health.ok ? "good" : "bad"}>{health.ok ? "online" : "offline"}</Pill>
        </div>
        <p className="mt-1 text-xs text-ink-400">
          B3 · decision-support, not advice
          {health.region ? ` · ${health.region}` : ""}
          {health.profile ? ` · ${health.profile}` : ""}
        </p>
      </div>

      <div className="rounded-xl border border-ink-200 bg-white p-4 shadow-panel">
        <label className="text-xs font-semibold uppercase tracking-wide text-ink-500">
          Client reference
        </label>
        <input
          value={clientId}
          onChange={(e) => setClientId(e.target.value)}
          className="mt-1 w-full rounded-md border border-ink-200 px-2 py-1.5 font-mono text-sm"
          placeholder="client-000042"
        />
        <p className="mt-1 text-[11px] text-ink-400">Opaque reference only, never PII.</p>

        <ul className="mt-3 space-y-1">
          {picker.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                onClick={() => setClientId(c.id)}
                className={`w-full rounded-md px-2 py-1 text-left text-xs ${
                  c.id === clientId
                    ? "bg-regblue-100 text-regblue-800"
                    : "text-ink-600 hover:bg-ink-50"
                }`}
              >
                <span className="font-mono">{c.id}</span>
                <span className="ml-1 text-ink-400">{c.label}</span>
              </button>
            </li>
          ))}
        </ul>

        <button
          type="button"
          disabled={loading || !clientId.trim()}
          onClick={() => onRun(clientId.trim())}
          className="mt-4 w-full rounded-md bg-regblue-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {loading ? "Building briefing..." : "Build briefing"}
        </button>
      </div>

      <div className="rounded-xl border border-ink-200 bg-white p-4 shadow-panel">
        <div className="flex items-center justify-between">
          <label className="text-xs font-semibold uppercase tracking-wide text-ink-500">
            Add a client
          </label>
          <a
            href={CLIENT_TEMPLATE_URL}
            download
            className="text-[11px] font-medium text-regblue-600 underline decoration-dotted"
          >
            Template
          </a>
        </div>
        <p className="mt-1 text-[11px] text-ink-400">
          Upload a profile + holdings JSON (start from the template; opaque ids only,
          never PII). The briefing runs on the uploaded portfolio.
        </p>
        <div className="mt-2 flex items-center gap-2">
          <input
            ref={fileRef}
            type="file"
            accept=".json,application/json"
            className="min-w-0 flex-1 text-[11px] text-ink-500 file:mr-2 file:rounded-md file:border file:border-ink-200 file:bg-white file:px-2 file:py-1 file:text-[11px] file:font-medium file:text-ink-600 hover:file:bg-ink-50"
          />
          <button
            type="button"
            onClick={() => void onUpload()}
            className="rounded-md bg-ink-900 px-2.5 py-1.5 text-[11px] font-medium text-white hover:bg-ink-700"
          >
            Register
          </button>
        </div>
        {uploadNote ? (
          <p
            className={`mt-1.5 text-[11px] ${uploadNote.ok ? "text-emerald-600" : "text-rose-600"}`}
          >
            {uploadNote.text}
          </p>
        ) : null}
      </div>
    </aside>
  );
}
