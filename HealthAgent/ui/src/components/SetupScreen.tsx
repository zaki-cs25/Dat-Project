import { useRef, useState } from "react";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { DEMO_PATIENT } from "@/data/demoPatient";
import { registerPatient, validatePatient } from "@/api";
import type { PatientRegistration } from "@/types";

interface Props {
  initialId: string;
  onStart: (id: string) => void;
}

export function SetupScreen({ initialId, onStart }: Props) {
  const [id, setId] = useState(initialId);
  const [mode, setMode] = useState<"new" | "existing">(initialId ? "existing" : "new");
  const [fullName, setFullName] = useState("");
  const [birthDate, setBirthDate] = useState("");
  const [gender, setGender] = useState<PatientRegistration["gender"]>("unknown");
  const registrationId = useRef<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");
  const isDemo = id.trim() === DEMO_PATIENT.id;

  async function start() {
    setChecking(true);
    setError("");
    try {
      let patientId = id.trim();
      if (mode === "new") {
        registrationId.current ??= crypto.randomUUID();
        const patient = await registerPatient({
          registration_id: registrationId.current,
          full_name: fullName.trim(), birth_date: birthDate, gender,
        });
        patientId = patient.patient_id;
      } else {
        await validatePatient(patientId);
      }
      onStart(patientId);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="mx-auto max-w-md space-y-7 pt-8">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Before you see a clinician</h1>
        <p className="text-sm leading-relaxed text-muted-foreground">
          A few quick questions about how you're feeling today. It takes about a minute and helps
          the clinician understand your concern before you're seen. There are no wrong answers.
        </p>
      </div>

      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (!checking) void start();
        }}
      >
        <div className="flex gap-2" aria-label="Patient registration">
          {([['new', 'New patient'], ['existing', 'Existing patient']] as const).map(([value, title]) => (
            <button key={value} type="button" aria-pressed={mode === value} disabled={checking}
              className={cn("flex-1 rounded-md border px-3 py-2 text-sm disabled:opacity-40", mode === value && "border-primary bg-accent font-medium")}
              onClick={() => { setMode(value); setError(""); }}>{title}</button>
          ))}
        </div>
        {mode === "new" ? <fieldset disabled={checking} className="space-y-4">
          <p className="text-sm text-muted-foreground">Enter your details to register and start your interview.</p>
          <div className="space-y-2"><Label htmlFor="patient-name">Full name</Label>
            <Input id="patient-name" autoComplete="name" required maxLength={200} autoFocus
              value={fullName} onChange={e => { setFullName(e.target.value); setError(""); }} />
          </div>
          <div className="space-y-2"><Label htmlFor="patient-birth-date">Date of birth</Label>
            <Input id="patient-birth-date" type="date" autoComplete="bday" required max={new Date().toISOString().slice(0, 10)}
              value={birthDate} onChange={e => { setBirthDate(e.target.value); setError(""); }} />
          </div>
          <div className="space-y-2"><Label htmlFor="patient-gender">Gender</Label>
            <select id="patient-gender" value={gender} onChange={e => setGender(e.target.value as PatientRegistration["gender"])}
              className="h-10 w-full rounded-md border border-input bg-card px-3 py-2 text-sm">
              <option value="unknown">Prefer not to say</option><option value="female">Female</option>
              <option value="male">Male</option><option value="other">Other</option>
            </select>
          </div>
        </fieldset> : <div className="space-y-2">
          <Label htmlFor="patient-id">Patient ID</Label>
          <Input id="patient-id" value={id} onChange={e => { setId(e.target.value); setError(""); }}
            disabled={checking} placeholder="Enter your patient ID" required autoFocus />
          <p className="text-xs text-muted-foreground">
            {isDemo ? <>Checking in as <span className="font-medium text-foreground">{DEMO_PATIENT.name}</span>{" · "}{DEMO_PATIENT.summary}</>
              : <>Demo uses <code className="rounded bg-muted px-1 py-0.5">demo-patient-1</code>.</>}
          </p>
        </div>}
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <Button type="submit" className="w-full" disabled={checking || (mode === "new" ? !fullName.trim() || !birthDate : !id.trim())}>
          {checking ? (mode === "new" ? "Registering…" : "Checking…") : (mode === "new" ? "Register and start interview" : "Start interview")} <ArrowRight />
        </Button>
      </form>
    </div>
  );
}
