"use client";

import React, { useState } from "react";
import PdfUploadZone from "@/components/PdfUploadZone";
import VerdictCard from "@/components/VerdictCard";
import { API_BASE } from "@/lib/api";

export default function HealthClaimsPage() {
  const [files, setFiles] = useState<File[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const handleAdjudicate = async () => {
    if (files.length === 0) {
      setError("Please upload at least one PDF document.");
      return;
    }

    setIsProcessing(true);
    setError(null);
    setResult(null);

    const formData = new FormData();
    files.forEach((file) => formData.append("files", file));

    try {
      const response = await fetch(`${API_BASE}/adjudicate`, {
        method: "POST",
        body: formData,
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || `Request failed with status ${response.status}`);
      }

      setResult(data);
    } catch (err: any) {
      setError(err.message || "Something went wrong. Please try again.");
    } finally {
      setIsProcessing(false);
    }
  };

  const handleReset = () => {
    setFiles([]);
    setResult(null);
    setError(null);
  };

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-foreground mb-2">Health Claims Adjudication</h1>
        <p className="text-sm text-muted">
          Upload any documents — policy certificate, discharge summary, hospital bills, claim forms, lab reports.
          The AI will read them all and return a verdict.
        </p>
      </div>

      {/* Upload Zone */}
      <div className="bg-white rounded-2xl border border-border p-6 shadow-sm">
        <h2 className="text-sm font-semibold text-muted uppercase tracking-wider mb-4">
          Upload Documents
        </h2>
        <PdfUploadZone files={files} onFilesChange={setFiles} />
      </div>

      {/* Action Buttons */}
      <div className="flex gap-3">
        <button
          onClick={handleAdjudicate}
          disabled={isProcessing || files.length === 0}
          className="px-8 py-3 bg-accent hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed
                     text-white rounded-xl font-medium shadow-lg shadow-accent/20 transition-all
                     flex items-center gap-2"
        >
          {isProcessing ? (
            <>
              <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              Analyzing Documents...
            </>
          ) : (
            "Adjudicate Claim"
          )}
        </button>

        {result && (
          <button
            onClick={handleReset}
            className="px-6 py-3 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-xl font-medium transition-all"
          >
            Start Over
          </button>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Result */}
      {result && (
        <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
          <VerdictCard
            verdict={result.verdict}
            reasoning={result.reasoning}
            documentSummary={result.document_summary}
            extractedDetails={result.extracted_details}
          />
        </div>
      )}
    </div>
  );
}
