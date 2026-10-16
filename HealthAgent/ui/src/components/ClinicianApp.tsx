import { useEffect, useState } from "react";
import { Activity, ArrowLeft, ExternalLink, RefreshCw } from "lucide-react";
import { enqueueCarePlan, fetchCarePlan, fetchCarePlans, retryCarePlan } from "@/api";
import type { CareJob, CareWorklist, EvidenceSource, FhirResource } from "@/types";

const button = "rounded-md border px-3 py-2 text-sm hover:bg-accent disabled:opacity-40";
const pending = (status: string) => ["queued", "running"].includes(status);
const label = (status: string) => status.replace(/-/g, " ");

function concept(resource: FhirResource): string {
  const code = (resource.code || resource.medicationCodeableConcept) as { text?: string; coding?: { display?: string }[] } | undefined;
  return code?.text || code?.coding?.[0]?.display || resource.resourceType || "Record";
}

function RecordSection({ title, records }: { title: string; records: FhirResource[] }) {
  return <section className="mt-5"><h3 className="font-semibold">{title}</h3>
    {records.length === 0 ? <p className="text-sm text-muted-foreground">No records returned.</p> : records.map((r, i) =>
      <details key={r.id || i} className="mt-2 rounded border p-3"><summary className="cursor-pointer text-sm">{concept(r)}</summary>
        <pre className="mt-3 overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(r, null, 2)}</pre>
      </details>)}
  </section>;
}

function SourceDetails({ source, related = false }: { source: EvidenceSource; related?: boolean }) {
  return <details className="mt-3 rounded bg-muted/50 p-3 text-sm">
    <summary className="cursor-pointer font-medium">{related ? "Related ICMR context" : "Evidence"} · {source.title} · {source.source_format === "markdown" ? `${source.source_file}, lines ${source.line_start}–${source.line_end}` : source.page ? `page ${source.page}` : source.section}</summary>
    {related && <p className="mt-2 text-muted-foreground">Context supplied to the model; this citation does not establish support for every recommendation.</p>}
    {source.evidence_role === "context" && <p className="mt-2 text-muted-foreground">Approved for showcase context · Clinical validation not recorded{source.original_decision ? ` · Original classification: ${source.original_decision}` : ""}</p>}
    <p className="mt-3">{source.publisher} · Version: {source.version} · Section: {source.section}</p>
    {source.workflow_title && <p className="mt-2">Workflow: {source.workflow_title}</p>}
    {source.char_start !== undefined && source.char_end !== undefined && <p className="mt-2">Selected cell · line {source.line_start}, characters {source.char_start + 1}–{source.char_end}</p>}
    <p className="mt-3 whitespace-pre-wrap">{source.text}</p><p className="mt-3">Applicability: {source.applicability}</p><p>Exceptions: {source.exceptions || "None recorded"}</p>
    <details className="mt-2"><summary>Original excerpt and document identity</summary><p className="whitespace-pre-wrap">{source.original_text}</p><p className="break-all text-xs">Passage: {source.passage_id}<br />SHA-256: {source.checksum}</p></details>
    {source.context_spans?.map((span, i) => <details key={i} className="mt-2"><summary>Supporting context · {source.source_file}, lines {span.line_start}–{span.line_end}{span.char_start !== undefined && span.char_end !== undefined ? `, characters ${span.char_start + 1}–${span.char_end}` : ""}</summary><p className="mt-2 whitespace-pre-wrap">{span.original_text}</p></details>)}
    {source.duplicate_sources && source.duplicate_sources.length > 0 && <p className="mt-2 text-xs">Also recorded at: {source.duplicate_sources.map(s => `${s.source_file}, lines ${s.line_start}–${s.line_end}${s.char_start !== undefined && s.char_end !== undefined ? `, characters ${s.char_start + 1}–${s.char_end}` : ""}`).join("; ")}</p>}
    <a href={source.official_url} target="_blank" rel="noreferrer" className="mt-3 inline-block text-primary underline">{source.official_url_kind === "catalogue" ? "Official ICMR catalogue" : "Official ICMR document"} <ExternalLink className="inline h-3 w-3" /></a>
  </details>;
}

function Case({ initial, onBack }: { initial: CareJob; onBack: () => void }) {
  const [job, setJob] = useState(initial);
  const [tab, setTab] = useState("plan");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    const load = async () => {
      try { const result = await fetchCarePlan(initial.job_id); if (active) { setJob(result); setError(""); } }
      catch (e) { if (active) setError((e as Error).message); }
    };
    void load();
    const timer = window.setInterval(() => { if (pending(job.status)) void load(); }, 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, [initial.job_id, initial.status, job.status]);
  async function retry() {
    setBusy(true); setError("");
    try { setJob(job.status === "unqueued" ? await enqueueCarePlan(job) : await retryCarePlan(job.job_id)); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  const draft = job.draft;
  const context = job.context;
  const retrievedContext = Array.from(new Map(
    [...(draft?.related_icmr_context || []), ...(draft?.evidence_sources || [])].map(source => [source.passage_id, source])
  ).values());
  return <>
    <button className={button} onClick={onBack}><ArrowLeft className="mr-2 inline h-4 w-4" />Care Plans</button>
    <div className="my-6 flex flex-wrap items-center gap-3"><h1 className="text-2xl font-semibold">{initial.patient_name || initial.patient_id}</h1>
      <span className="rounded bg-accent px-3 py-1 text-sm capitalize">{label(job.status)}</span>
      {["failed", "insufficient-evidence", "unqueued"].includes(job.status) && <button className={button} onClick={() => void retry()} disabled={busy}>{busy ? "Requesting…" : "Retry generation"}</button>}
    </div>
    {error && <p role="alert" className="my-3 text-destructive">{error}</p>}
    {job.reason && <p className="mb-4 rounded border p-3 text-sm">{job.reason}</p>}
    {job.context_error && <p role="alert" className="mb-4 text-destructive">{job.context_error}</p>}
    <nav className="mb-6 flex flex-wrap gap-2">{["plan", "patient record", "interview", "assessment"].map(t =>
      <button key={t} className={`${button} capitalize ${tab === t ? "bg-accent font-semibold" : ""}`} onClick={() => setTab(t)}>{t}</button>)}</nav>
    {tab === "plan" && <>
      {pending(job.status) && <p role="status">Generating a draft in the background. This view updates automatically.</p>}
      {draft && <article className="rounded-xl border bg-card p-6">
        <h2 className="text-xl font-semibold">{draft.title}</h2>
        <p className="my-2 text-sm text-muted-foreground">Read-only draft for clinician review · Activities not started</p>
        {draft.generated_at && <p className="text-xs text-muted-foreground">Generated {new Date(draft.generated_at).toLocaleString()} · {draft.model}</p>}
        <ol className="mt-5 space-y-4">{draft.activities.map((activity, i) => <li key={i} className={`rounded-lg border p-4 ${activity.provenance === "assessment" ? "border-destructive bg-destructive/5" : ""}`}>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide">{activity.provenance === "assessment" ? "Urgent assessment instruction" : activity.provenance === "missing-information" ? "Clarify missing information" : activity.provenance === "legacy" ? "Legacy activity — evidence unattributed" : activity.category}</p>
          <p>{activity.description}</p>{activity.timing && <p className="mt-2 text-sm">{draft.generation_mode === "enriched" ? "Proposed timing" : "Timing"}: {activity.timing}</p>}
        </li>)}</ol>
        {retrievedContext.length > 0 && <section className="mt-5"><h3 className="font-semibold">Retrieved ICMR context</h3>{retrievedContext.map(source => <SourceDetails key={source.passage_id} source={source} related />)}<p className="mt-2 text-xs text-muted-foreground">{retrievedContext.length} passages supplied.</p></section>}
        {[['Missing information', draft.missing_information], [draft.generation_mode === "enriched" ? 'Conditions without retrieved ICMR context' : 'Uncovered conditions', draft.uncovered_conditions], ['Review notes', draft.review_notes]].map(([title, values]) =>
          Array.isArray(values) && values.length > 0 ? <section key={String(title)} className="mt-5"><h3 className="font-semibold">{String(title)}</h3><ul className="mt-2 list-disc space-y-1 pl-5 text-sm">{values.map((v, i) => <li key={i}>{v}</li>)}</ul></section> : null)}
      </article>}
    </>}
    {tab === "patient record" && context && <div className="rounded border bg-card p-5"><h2 className="font-semibold">Patient demographics</h2><pre className="mt-3 whitespace-pre-wrap text-xs">{JSON.stringify(context.patient, null, 2)}</pre>
      <RecordSection title="Established conditions" records={context.conditions} /><RecordSection title="Medications" records={context.medications} /><RecordSection title="Allergies" records={context.allergies} /><RecordSection title="Observations" records={context.observations} /></div>}
    {tab === "interview" && context && <div className="rounded border bg-card p-5"><h2 className="mb-4 font-semibold">Exact completed questionnaire</h2>
      {((context.questionnaire.item || []) as { linkId: string; text?: string; answer?: unknown[] }[]).map(item => <section key={item.linkId} className="mb-4"><h3 className="text-sm font-medium">{item.text}</h3><pre className="mt-2 whitespace-pre-wrap text-sm">{JSON.stringify(item.answer, null, 2)}</pre></section>)}</div>}
    {tab === "assessment" && context && <div className="rounded border bg-card p-5"><h2 className="mb-3 font-semibold">Persisted interview assessment</h2><p>Priority: {String(context.assessment.priority)}</p>
      {((context.assessment.note || []) as { text: string }[]).map((n, i) => <p key={i} className="mt-3 whitespace-pre-wrap text-sm">{n.text}</p>)}</div>}
  </>;
}

export function ClinicianApp() {
  const [worklist, setWorklist] = useState<CareWorklist | null>(null);
  const [selected, setSelected] = useState<CareJob | null>(null);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let active = true;
    const load = async () => { try { const result = await fetchCarePlans(offset); if (active) { setWorklist(result); setError(""); } } catch (e) { if (active) setError((e as Error).message); } };
    void load(); const timer = window.setInterval(() => void load(), 5000);
    return () => { active = false; window.clearInterval(timer); };
  }, [offset, refresh]);
  return <div className="min-h-screen bg-background"><header className="border-b bg-card"><div className="mx-auto flex max-w-6xl items-center gap-3 px-6 py-4">
    <Activity className="h-6 w-6 text-primary" /><span className="font-semibold">Care Plans</span><span className="hidden text-sm text-muted-foreground sm:block">Clinician drafts with ICMR context</span>
    <a className="ml-auto text-sm text-primary" href="/intake" target="_blank" rel="noreferrer">Patient intake <ExternalLink className="inline h-3 w-3" /></a>
  </div></header><main className="mx-auto max-w-6xl px-6 py-8">{selected ? <Case key={selected.job_id} initial={selected} onBack={() => { setSelected(null); setRefresh(r => r + 1); }} /> : <>
    <div className="mb-6 flex items-center justify-between"><div><h1 className="text-2xl font-semibold">Care Plans</h1><p className="mt-2 text-sm text-muted-foreground">Completed interviews and generation status. Synthetic demonstration records.</p></div><button className={button} onClick={() => setRefresh(r => r + 1)}><RefreshCw className="mr-2 inline h-4 w-4" />Refresh</button></div>
    {error && <p role="alert" className="mb-4 text-destructive">{error}</p>}
    <div className="overflow-x-auto rounded-xl border bg-card"><table className="w-full text-left text-sm"><thead className="border-b bg-muted/40"><tr>{["Patient", "Interview date", "Urgency", "Generation status", ""].map(t => <th key={t} className="p-4 font-medium">{t}</th>)}</tr></thead>
      <tbody>{worklist?.items.map(job => <tr key={job.job_id} className="border-b last:border-0"><td className="p-4 font-medium">{job.patient_name || job.patient_id}</td><td className="p-4">{job.interview_date ? new Date(job.interview_date).toLocaleString() : "Unknown"}</td><td className={`p-4 ${["stat", "urgent"].includes(job.urgency || "") ? "font-semibold text-destructive" : ""}`}>{job.urgency}</td><td className="p-4 capitalize">{label(job.status)}</td><td className="p-4"><button className={button} onClick={() => setSelected(job)}>Open case</button></td></tr>)}</tbody></table>
      {worklist?.total === 0 && <p className="p-6 text-muted-foreground">No completed interviews yet.</p>}</div>
    <div className="mt-4 flex items-center gap-3"><button className={button} disabled={offset === 0} onClick={() => setOffset(o => Math.max(0, o - 25))}>Previous</button><span className="text-sm">{worklist?.total || 0} records</span><button className={button} disabled={!worklist || offset + 25 >= worklist.total} onClick={() => setOffset(o => o + 25)}>Next</button></div>
  </>}</main></div>;
}
