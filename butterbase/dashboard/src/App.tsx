import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { buildEntries, buildParts, loadSnapshot, partsOfEntry, when } from "./data";
import type { QuoteEntry } from "./data";
import { matches, searchableText } from "./search";
import type { Snapshot } from "./types";
import Home from "./components/Home";
import type { Bucket } from "./components/Home";
import InputList from "./components/InputList";
import PartTable from "./components/PartTable";
import PartView from "./components/PartView";
import TriggerButton from "./components/TriggerButton";
import WorkingList from "./components/WorkingList";

type View = { name: "home" } | { name: Bucket } | { name: "part"; part: string; back: View };

const TITLE: Record<Bucket, string> = {
  ready: "Ready for review",
  needs_input: "Needs your input",
  working: "Agent working",
};

export default function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [view, setView] = useState<View>({ name: "home" });

  useEffect(() => {
    loadSnapshot()
      .then(setSnapshot)
      .catch((err: Error) => setError(err.message));
  }, []);

  // Derived once per snapshot. "Now" is the viewer's clock: the follow-up
  // countdown is about today, even though the data is as of the last deploy.
  const entries = useMemo(() => buildEntries(snapshot?.rfqs ?? [], new Date()), [snapshot]);
  const parts = useMemo(() => buildParts(entries), [entries]);
  const haystacks = useMemo(
    () => new Map(parts.map((p) => [p.partNumber, searchableText(p)])),
    [parts],
  );
  const partOf = useMemo(() => {
    const cache = new Map(entries.map((e) => [e.key, partsOfEntry(parts, e)[0] ?? null]));
    return (e: QuoteEntry) => cache.get(e.key) ?? null;
  }, [entries, parts]);

  const searching = query.trim().length > 0;
  const hits = searching ? parts.filter((p) => matches(haystacks.get(p.partNumber) ?? "", query)) : [];

  const openPart = (part: string) => {
    setView((current) => ({ name: "part", part, back: current.name === "part" ? current.back : current }));
    setQuery("");
  };

  if (error) {
    return (
      <div className="wrap">
        <div className="panel error">
          <strong>Could not load the RFQ snapshot.</strong>
          <p>
            The page ships a snapshot baked in at deploy time. In local development, run{" "}
            <code>python3 butterbase/deploy-frontend.py --snapshot-only</code> first.
          </p>
          <code>{error}</code>
        </div>
      </div>
    );
  }

  let body: ReactNode;
  let crumb: { label: string; to: View } | null = null;

  if (!snapshot) {
    body = <p className="muted">Loading…</p>;
  } else if (searching) {
    body = (
      <section>
        <h2 className="view-title">
          {hits.length} part{hits.length === 1 ? "" : "s"} matching “{query.trim()}”
        </h2>
        <div className="panel">
          <PartTable parts={hits} onOpen={openPart} empty="No part, supplier or RFQ matches that search." />
        </div>
      </section>
    );
  } else if (view.name === "home") {
    body = <Home entries={entries} partCount={parts.length} onOpen={(b) => setView({ name: b })} />;
  } else if (view.name === "part") {
    const part = parts.find((p) => p.partNumber === view.part);
    crumb = {
      label: view.back.name === "home" ? "Home" : TITLE[view.back.name as Bucket],
      to: view.back,
    };
    body = part ? <PartView part={part} /> : <p className="empty">That part is not in this snapshot.</p>;
  } else {
    const bucket = view.name;
    const inBucket = entries.filter((e) => e.state === bucket);
    crumb = { label: "Home", to: { name: "home" } };
    body = (
      <section>
        <h2 className="view-title">
          {TITLE[bucket]} <span className="muted">({inBucket.length})</span>
        </h2>
        <div className="panel">
          {bucket === "ready" && (
            <PartTable
              parts={parts.filter((p) => p.rows.some((r) => r.entry.state === "ready"))}
              onOpen={openPart}
              empty="No complete quotes yet."
            />
          )}
          {bucket === "needs_input" && (
            <InputList entries={inBucket} partOf={partOf} onOpenPart={openPart} />
          )}
          {bucket === "working" && (
            <WorkingList entries={inBucket} partOf={partOf} onOpenPart={openPart} />
          )}
        </div>
      </section>
    );
  }

  return (
    <div className="wrap">
      <header className="top">
        <div>
          <h1>
            <button className="home-link" onClick={() => { setView({ name: "home" }); setQuery(""); }}>
              ForgeFlow
            </button>
          </h1>
          <p className="muted">
            Buyer dashboard
            {snapshot?.captured_at && ` · data as of ${when(snapshot.captured_at)}`}
          </p>
        </div>
        <div className="top-actions">
          <input
            type="search"
            value={query}
            placeholder="Search part #, supplier or RFQ"
            onChange={(e) => setQuery(e.target.value)}
          />
          {snapshot?.trigger_url && <TriggerButton url={snapshot.trigger_url} />}
        </div>
      </header>

      {crumb && !searching && (
        <button className="link crumb" onClick={() => setView(crumb!.to)}>
          ← {crumb.label}
        </button>
      )}

      {body}
    </div>
  );
}
