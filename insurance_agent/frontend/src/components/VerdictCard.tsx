"use client";

import React from "react";
import {
  CheckCircleIcon,
  XCircleIcon,
  ExclamationTriangleIcon,
  ArrowPathIcon,
} from "@heroicons/react/24/outline";

interface VerdictCardProps {
  verdict: string;
  reasoning: string;
  documentSummary?: Array<{ filename: string; identified_type: string; key_facts: string }>;
  extractedDetails?: Record<string, unknown>;
}

const verdictConfig: Record<string, { label: string; color: string; bg: string; border: string; icon: React.ReactNode }> = {
  APPROVE: {
    label: "APPROVED",
    color: "text-green-700",
    bg: "bg-green-50",
    border: "border-green-200",
    icon: <CheckCircleIcon className="w-7 h-7 text-green-600" />,
  },
  REJECT: {
    label: "REJECTED",
    color: "text-red-700",
    bg: "bg-red-50",
    border: "border-red-200",
    icon: <XCircleIcon className="w-7 h-7 text-red-600" />,
  },
  PARTIAL: {
    label: "PARTIALLY APPROVED",
    color: "text-amber-700",
    bg: "bg-amber-50",
    border: "border-amber-200",
    icon: <ExclamationTriangleIcon className="w-7 h-7 text-amber-600" />,
  },
  ESCALATE: {
    label: "ESCALATED FOR REVIEW",
    color: "text-orange-700",
    bg: "bg-orange-50",
    border: "border-orange-200",
    icon: <ArrowPathIcon className="w-7 h-7 text-orange-600" />,
  },
};

export default function VerdictCard({ verdict, reasoning, documentSummary, extractedDetails }: VerdictCardProps) {
  const config = verdictConfig[verdict?.toUpperCase()] || verdictConfig.ESCALATE;

  return (
    <div className={`rounded-2xl border-2 ${config.border} ${config.bg} overflow-hidden`}>
      {/* Verdict Header */}
      <div className="flex items-center gap-3 px-6 py-5 border-b border-inherit">
        {config.icon}
        <div>
          <p className="text-xs text-slate-500 uppercase tracking-wider font-medium">Verdict</p>
          <p className={`text-xl font-bold ${config.color}`}>{config.label}</p>
        </div>
      </div>

      {/* Reasoning */}
      <div className="px-6 py-5">
        <h4 className="text-sm font-semibold text-slate-700 mb-3">Reasoning</h4>
        <p className="text-sm text-slate-600 leading-relaxed whitespace-pre-wrap">{reasoning}</p>
      </div>

      {/* Document Summary */}
      {documentSummary && documentSummary.length > 0 && (
        <div className="px-6 py-5 border-t border-inherit">
          <h4 className="text-sm font-semibold text-slate-700 mb-3">Documents Identified</h4>
          <div className="space-y-3">
            {documentSummary.map((doc, i) => (
              <div key={i} className="flex gap-3 p-3 bg-white/70 rounded-lg">
                <span className="text-lg shrink-0">📄</span>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-700 truncate">{doc.filename}</p>
                  <p className="text-xs text-accent font-medium">{doc.identified_type}</p>
                  {doc.key_facts && (
                    <p className="text-xs text-slate-500 mt-1">{doc.key_facts}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Extracted Details */}
      {extractedDetails && Object.keys(extractedDetails).length > 0 && (
        <div className="px-6 py-5 border-t border-inherit">
          <h4 className="text-sm font-semibold text-slate-700 mb-3">Extracted Details</h4>
          <div className="grid grid-cols-2 gap-2 text-sm">
            {Object.entries(extractedDetails).map(([key, value]) => (
              <div key={key} className="p-2 bg-white/70 rounded">
                <span className="text-xs text-slate-400 uppercase tracking-wide">
                  {key.replace(/_/g, " ")}
                </span>
                <p className="text-slate-700 font-medium truncate">
                  {String(value ?? "")}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
