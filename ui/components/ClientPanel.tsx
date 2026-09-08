/** The left rail: pick a client and request a briefing. */

"use client";

import { useEffect, useRef, useState } from "react";
import { CLIENT_TEMPLATE_URL, listClientSummaries, registerClient } from "@/lib/api";
import type { ClientSummary } from "@/lib/types";
import { Pill } from "./ui";

export function ClientPanel({
  onRun,
  onSelect,
  loading,
  health,
}: {
  onRun: (clientId: string) => void;
  onSelect?: (clientId: string) => void;
  loading: boolean;
  health: { ok: boolean; profile?: string; region?: string };
}) {
  const [clientId, setClientId] = useState("");
  // The picker's contents come from the SERVER, never from a list in this file. It used to
  // carry four hardcoded clients, two of which the server did not serve at all, so picking
  // either one errored in front of whoever was watching. The label is derived server-side
  // from the profile for the same reason.
  const [clients, setClients] = useState<ClientSummary[]>([]);
  const [book, setBook] = useState<{ version: string; fictional: boolean }>({
    version: "",
    fictional: false,
  });
  const [uploadNote, setUploadNote] = useState<{ ok: boolean; text: string } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  function choose(id: string) {
    setClientId(id);
    onSelect?.(id);
  }

  useEffect(() => {
    if (!health.ok) return;
    listClientSummaries()
      .then((list) => {
        setClients(list.items);
        setBook({ version: list.book_version, fictional: list.fictional });
        if (list.items.length > 0) {
          setClientId((current) => {
            if (current) return current;
            onSelect?.(list.items[0].client_id);
            return list.items[0].client_id;
          });
        }
      })
      .catch(() => setClients([]));
    // onSelect is a stable useCallback in the page; re-running on identity would refetch
    // the picker on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [health.ok]);

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
      choose(result.client_id);
      setClients((await listClientSummaries()).items);
    } catch (e) {
      setUploadNote({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      if (fileRef.current) fileRef.current.value = "";
    }
  }


  return (
    <aside className="w-full space-y-4 lg:w-72">
      <div className="rounded-xl border border-ink-200 bg-white p-4 shadow-panel">
        <div className="flex items-center justify-between">
          <h1 className="text-base font-semibold text-ink-800">CIO Advisory</h1>
          <Pill tone={health.ok ? "good" : "bad"}>{health.ok ? "online" : "offline"}</Pill>
        </div>
        <p className="mt-1 text-xs text-ink-400">
          decision-support, not advice
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
          onChange={(e) => choose(e.target.value)}
          className="mt-1 w-full rounded-md border border-ink-200 px-2 py-1.5 font-mono text-sm"
          placeholder="client-000042"
        />
        <p className="mt-1 text-[11px] text-ink-400">Opaque reference only, never PII.</p>

        <ul className="mt-3 space-y-1">
          {clients.map((c) => (
            <li key={c.client_id}>
              <button
                type="button"
                onClick={() => choose(c.client_id)}
                className={`w-full rounded-md px-2 py-1 text-left text-xs ${
                  c.client_id === clientId
                    ? "bg-regblue-100 text-regblue-800"
                    : "text-ink-600 hover:bg-ink-50"
                }`}
              >
                <span className="font-mono">{c.client_id}</span>
                {c.label ? <span className="ml-1 text-ink-400">{c.label}</span> : null}
              </button>
            </li>
          ))}
          {clients.length === 0 ? (
            <li className="px-2 py-1 text-xs text-ink-400">
              No clients yet. Register one below.
            </li>
          ) : null}
        </ul>
        {book.fictional ? (
          <p className="mt-2 text-[11px] text-ink-400">
            Fictional demo book {book.version}. No real client is represented here.
          </p>
        ) : null}

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
