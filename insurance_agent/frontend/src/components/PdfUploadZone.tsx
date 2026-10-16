"use client";

import React, { useCallback, useRef } from "react";
import { XMarkIcon, DocumentIcon } from "@heroicons/react/24/outline";

interface PdfUploadZoneProps {
  files: File[];
  onFilesChange: (files: File[]) => void;
}

export default function PdfUploadZone({ files, onFilesChange }: PdfUploadZoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = React.useState(false);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const dropped = Array.from(e.dataTransfer.files).filter((f) =>
      f.name.toLowerCase().endsWith(".pdf")
    );
    onFilesChange([...files, ...dropped]);
  }, [files, onFilesChange]);

  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      const selected = Array.from(e.target.files);
      onFilesChange([...files, ...selected]);
    }
    // Reset input so the same file can be re-selected if needed
    if (inputRef.current) inputRef.current.value = "";
  }, [files, onFilesChange]);

  const removeFile = useCallback((index: number) => {
    onFilesChange(files.filter((_, i) => i !== index));
  }, [files, onFilesChange]);

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  };

  return (
    <div className="space-y-3">
      {/* Drop Zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={`
          border-2 border-dashed rounded-xl p-8 text-center cursor-pointer
          transition-all duration-200
          ${isDragging
            ? "border-accent bg-accent/5 scale-[1.01]"
            : "border-slate-300 hover:border-accent/50 hover:bg-slate-50"
          }
        `}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,application/pdf"
          multiple
          onChange={handleInputChange}
          className="hidden"
        />
        <DocumentIcon className="w-10 h-10 mx-auto text-slate-400 mb-3" />
        <p className="text-sm font-medium text-slate-700">
          <span className="text-accent">Click to upload</span> or drag &amp; drop
        </p>
        <p className="text-xs text-slate-400 mt-1">PDF files only</p>
      </div>

      {/* File List */}
      {files.length > 0 && (
        <ul className="space-y-2">
          {files.map((file, i) => (
            <li
              key={`${file.name}-${i}`}
              className="flex items-center gap-3 px-4 py-3 bg-slate-50 rounded-lg border border-slate-200"
            >
              <DocumentIcon className="w-5 h-5 text-red-500 shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-slate-700 truncate">{file.name}</p>
                <p className="text-xs text-slate-400">{formatSize(file.size)}</p>
              </div>
              <button
                onClick={() => removeFile(i)}
                className="p-1 text-slate-400 hover:text-red-500 transition-colors"
              >
                <XMarkIcon className="w-4 h-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
