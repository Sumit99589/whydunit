"use client";

import { useSearchParams } from "next/navigation";
import { UploadPanel } from "./Upload";

export function UploadFromQuery() {
  const q = useSearchParams();
  return <UploadPanel initialKind={q.get("kind") ?? undefined} caseId={q.get("case") ?? undefined} />;
}
