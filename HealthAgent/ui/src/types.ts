// Mirrors the agent's HandoffResponse (src/python/central_park/main.py:63-73)
// and the citation shape from tools/vector.py.

export type TriageLevel = "self-care" | "see-gp" | "urgent-care" | "ed";

export interface Citation {
  source?: string;
  slug?: string;
  snippet?: string;
  score?: number;
}

export interface Handoff {
  care_plan_job_id?: string | null;
  care_plan_status?: string | null;
  triage_level: TriageLevel | string | null;
  chief_complaint: string | null;
  hpi: string | null;
  red_flags: string[];
  recommended_actions: string[];
  citations: Citation[];
  questionnaire_response_id: string | null;
  encounter_id?: string | null;
  service_request_id?: string | null;
  observation_ids?: string[];
}

// One answered intake question, ready to become a QuestionnaireResponse.item.
export interface QA {
  link_id: string;
  question: string;
  answer: string;
}

export interface PatientRegistration {
  registration_id: string;
  full_name: string;
  birth_date: string;
  gender: "female" | "male" | "other" | "unknown";
}

export interface RegisteredPatient {
  patient_id: string;
  full_name: string;
}

// A question proposed by the adaptive-interview agent (/api/interview/next).
// snake_case mirrors the backend (central_park/interview.py:_normalize_question);
// data/questions.ts:toQuestion converts it to the camelCase Question the
// interview UI renders.
export interface DynamicQuestion {
  link_id: string;
  kind: "text" | "scale" | "choices";
  short: string;
  prompt: string;
  help?: string | null;
  placeholder?: string | null;
  min?: number;
  max?: number;
  min_label?: string;
  max_label?: string;
  options?: string[];
  none_option?: string;
}

export interface NextQuestionResult {
  done: boolean;
  question: DynamicQuestion | null;
}

export interface EvidenceSource {
  passage_id: string;
  publisher: string;
  title: string;
  official_url: string;
  version: string;
  version_id: string;
  checksum: string;
  page?: number | null;
  source_format?: string;
  source_file?: string;
  line_start?: number;
  line_end?: number;
  char_start?: number;
  char_end?: number;
  official_url_kind?: string;
  section: string;
  text: string;
  original_text: string;
  applicability: string;
  exceptions: string;
  workflow_title?: string;
  evidence_role?: string;
  original_decision?: string;
  clinical_validation_complete?: boolean;
  context_spans?: { line_start: number; line_end: number; char_start?: number; char_end?: number; original_text: string }[];
  duplicate_sources?: { source_file: string; line_start: number; line_end: number; char_start?: number; char_end?: number }[];
}

export interface CareActivity {
  category?: string;
  description: string;
  timing?: string | null;
  provenance: "icmr" | "context-informed" | "model" | "assessment" | "missing-information" | "legacy";
  source_ids?: string[];
}

export interface CareDraft {
  title: string;
  activities: CareActivity[];
  evidence_sources: EvidenceSource[];
  related_icmr_context?: EvidenceSource[];
  generation_mode?: "grounded" | "enriched";
  context_status?: string;
  missing_information?: string[];
  uncovered_conditions?: string[];
  review_notes?: string[];
  generated_at?: string;
  model?: string;
}

export interface FhirResource {
  resourceType?: string;
  id?: string;
  [key: string]: unknown;
}

export interface CareJob {
  job_id: string;
  patient_id: string;
  patient_name?: string;
  questionnaire_response_id?: string;
  assessment_id?: string;
  interview_date?: string;
  urgency?: string;
  status: string;
  reason?: string | null;
  draft?: CareDraft | null;
  context?: {
    patient: FhirResource;
    questionnaire: FhirResource;
    assessment: FhirResource;
    conditions: FhirResource[];
    medications: FhirResource[];
    observations: FhirResource[];
    allergies: FhirResource[];
  };
  context_error?: string;
}

export interface CareWorklist {
  items: CareJob[];
  total: number;
  offset: number;
  limit: number;
}
