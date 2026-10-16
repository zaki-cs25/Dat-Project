import type { Handoff, NextQuestionResult, QA, CareJob, CareWorklist, PatientRegistration, RegisteredPatient } from "@/types";

// Same-origin routes. nginx (prod) and the vite dev proxy both map:
//   /fhir/*  -> IRIS FHIR R4 endpoint (with server-side Basic auth injected)
//   /api/*   -> the triage agent FastAPI
const FHIR_BASE = "/fhir";
const AGENT_BASE = "/api";

export type ApiErrorKind =
  | "fhir-unreachable"
  | "fhir-http"
  | "fhir-no-id"
  | "agent-unreachable"
  | "agent-http";

export class ApiError extends Error {
  kind: ApiErrorKind;
  status?: number;
  detail?: string;

  constructor(kind: ApiErrorKind, message: string, status?: number, detail?: string) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.detail = detail;
  }
}

// IRIS returns 201 with an empty body; the new id lives in the Location
// header (often relative). Pull the segment after "QuestionnaireResponse".
function idFromLocation(location: string | null): string {
  if (!location) return "";
  const parts = location.split("/").filter(Boolean);
  const idx = parts.indexOf("QuestionnaireResponse");
  if (idx >= 0 && idx + 1 < parts.length) return parts[idx + 1];
  return "";
}

export async function validatePatient(patientId: string): Promise<void> {
  if (!/^[A-Za-z0-9.-]{1,64}$/.test(patientId)) {
    throw new ApiError("fhir-http", "Enter a valid patient ID.");
  }
  let resp: Response;
  try {
    resp = await fetch(`${FHIR_BASE}/Patient/${encodeURIComponent(patientId)}`, {
      headers: { Accept: "application/fhir+json" },
    });
  } catch {
    throw new ApiError("fhir-unreachable", "Cannot reach the FHIR server.");
  }
  if (resp.status === 404) {
    throw new ApiError("fhir-http", `Patient '${patientId}' was not found. Check the ID or choose New patient to register.`, 404);
  }
  if (!resp.ok) {
    throw new ApiError("fhir-http", "Cannot verify the patient record. Please try again.", resp.status);
  }
}

export async function registerPatient(details: PatientRegistration): Promise<RegisteredPatient> {
  let response: Response;
  try {
    response = await fetch(`${AGENT_BASE}/patients`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(details),
    });
  } catch {
    throw new ApiError("agent-unreachable", "Cannot save your registration. Please try again.");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body.detail === "string" ? body.detail : "Check your details and try again.";
    throw new ApiError("agent-http", `Registration could not be saved. ${detail}`, response.status);
  }
  return response.json() as Promise<RegisteredPatient>;
}

export async function createQuestionnaireResponse(
  patientId: string,
  qa: QA[],
): Promise<string> {
  await validatePatient(patientId);
  const payload = {
    resourceType: "QuestionnaireResponse",
    questionnaire: "Questionnaire/triage-intake",
    status: "completed",
    subject: { reference: `Patient/${patientId}` },
    authored: new Date().toISOString(),
    item: qa.map((item) => ({
      linkId: item.link_id,
      text: item.question,
      answer: [{ valueString: item.answer }],
    })),
  };

  let resp: Response;
  try {
    resp = await fetch(`${FHIR_BASE}/QuestionnaireResponse`, {
      method: "POST",
      headers: {
        "Content-Type": "application/fhir+json",
        Accept: "application/fhir+json",
      },
      body: JSON.stringify(payload),
    });
  } catch {
    throw new ApiError("fhir-unreachable", "Cannot reach the FHIR server.");
  }

  if (!resp.ok) {
    const detail = await resp.text().catch(() => "");
    throw new ApiError("fhir-http", "FHIR rejected the interview.", resp.status, detail);
  }

  // Prefer the response body id; fall back to the Location header.
  let id = "";
  const body = await resp.text().catch(() => "");
  if (body) {
    try {
      id = (JSON.parse(body) as { id?: string }).id ?? "";
    } catch {
      /* empty/non-JSON body is expected from IRIS */
    }
  }
  if (!id) {
    id =
      idFromLocation(resp.headers.get("Location")) ||
      idFromLocation(resp.headers.get("Content-Location"));
  }
  if (!id) {
    throw new ApiError(
      "fhir-no-id",
      "FHIR accepted the interview but returned no resource id.",
    );
  }
  return id;
}

// Adaptive intake: ask the agent for the next question given the answers so
// far. The caller falls back to the fixed question set if this throws, so the
// interview is never blocked by the agent being unreachable.
export async function fetchNextQuestion(
  patientId: string,
  answers: QA[],
  language = "English",
): Promise<NextQuestionResult> {
  let resp: Response;
  try {
    resp = await fetch(`${AGENT_BASE}/interview/next`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ patient_id: patientId, answers, language }),
    });
  } catch {
    throw new ApiError("agent-unreachable", "Cannot reach the triage agent.");
  }
  if (!resp.ok) {
    const detail = await resp.text().catch(() => "");
    throw new ApiError("agent-http", "The triage agent returned an error.", resp.status, detail);
  }
  return (await resp.json()) as NextQuestionResult;
}

export async function runInterview(
  patientId: string,
  questionnaireResponseId: string,
): Promise<Handoff> {
  let resp: Response;
  try {
    resp = await fetch(`${AGENT_BASE}/interview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        patient_id: patientId,
        questionnaire_response_id: questionnaireResponseId,
      }),
    });
  } catch {
    throw new ApiError("agent-unreachable", "Cannot reach the triage agent.");
  }

  if (!resp.ok) {
    const detail = await resp.text().catch(() => "");
    throw new ApiError("agent-http", "The triage agent returned an error.", resp.status, detail);
  }
  return (await resp.json()) as Handoff;
}

async function careRequest<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${AGENT_BASE}${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Care-plan request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const fetchCarePlans = (offset = 0) => careRequest<CareWorklist>(`/careplans?offset=${offset}&limit=25`);
export const fetchCarePlan = (id: string) => careRequest<CareJob>(`/careplans/${encodeURIComponent(id)}`);
export const retryCarePlan = (id: string) => careRequest<CareJob>(`/careplans/${encodeURIComponent(id)}/retry`, {});
export const enqueueCarePlan = (job: CareJob) => careRequest<CareJob>("/careplan", {
  patient_id: job.patient_id, questionnaire_response_id: job.questionnaire_response_id, assessment_id: job.assessment_id,
});
