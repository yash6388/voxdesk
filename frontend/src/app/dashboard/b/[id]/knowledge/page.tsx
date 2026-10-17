"use client";

import {
  CircleCheck,
  CircleX,
  FileText,
  FileUp,
  Layers,
  LoaderCircle,
  MessageSquare,
  Trash2,
} from "lucide-react";
import { useParams } from "next/navigation";
import { useRef, useState } from "react";

import { ButtonLink } from "@/components/ui/Button";
import { Badge, Card, PageHeader } from "@/components/ui/primitives";
import type { VoxDocument } from "@/lib/api";
import { BRAND_TINT, cn, formatDate } from "@/lib/utils";
import { useDocuments } from "@/lib/useDocuments";

const ACCEPT = ".pdf,.txt,.md";

export default function KnowledgePage() {
  const { id } = useParams<{ id: string }>();
  const { documents, error, uploading, upload, remove, stats } = useDocuments(id);

  return (
    <>
      <PageHeader
        title="Knowledge base"
        description="Everything your agent knows. Answers are grounded in these documents and cite them."
        actions={
          stats.ready > 0 && (
            <ButtonLink href={`/dashboard/b/${id}`} variant="secondary">
              <MessageSquare className="size-4" /> Try in Playground
            </ButtonLink>
          )
        }
      />

      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        <Stat icon={FileText} label="Documents" value={stats.total} />
        <Stat icon={CircleCheck} label="Ready" value={stats.ready} />
        <Stat icon={Layers} label="Chunks indexed" value={stats.chunks} />
      </div>

      <Dropzone uploading={uploading} onFiles={upload} />
      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}

      <Card className="mt-6 overflow-hidden">
        <div className="border-b border-border px-5 py-3 text-sm font-medium">Documents</div>
        {documents === null ? (
          <div className="space-y-2 p-5">
            {[0, 1].map((i) => (
              <div key={i} className="h-12 animate-pulse rounded-lg bg-zinc-200/60 dark:bg-zinc-800/60" />
            ))}
          </div>
        ) : documents.length === 0 ? (
          <p className="px-5 py-10 text-center text-sm text-muted">
            No documents yet. Upload a price list, FAQ or policy document to get started.
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {documents.map((d) => (
              <DocumentRow key={d.id} document={d} onDelete={() => remove(d.id)} />
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}

function Stat({ icon: Icon, label, value }: { icon: React.ElementType; label: string; value: number }) {
  return (
    <Card className="flex items-center gap-4 p-5">
      <span className={cn("flex size-10 items-center justify-center rounded-xl", BRAND_TINT)}>
        <Icon className="size-5" />
      </span>
      <div>
        <div className="text-2xl font-semibold tabular-nums">{value}</div>
        <div className="text-xs text-muted">{label}</div>
      </div>
    </Card>
  );
}

function Dropzone({ uploading, onFiles }: { uploading: boolean; onFiles: (files: File[]) => void }) {
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  function handle(files: FileList | null) {
    const list = Array.from(files ?? []);
    if (list.length) onFiles(list);
    if (input.current) input.current.value = "";
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        handle(e.dataTransfer.files);
      }}
      onClick={() => !uploading && input.current?.click()}
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition",
        dragging
          ? "border-indigo-500 bg-indigo-50/60 dark:bg-indigo-500/10"
          : "border-border bg-surface hover:border-indigo-300 hover:bg-indigo-50/30 dark:hover:border-indigo-500/40 dark:hover:bg-indigo-500/5",
      )}
    >
      <span className={cn("flex size-12 items-center justify-center rounded-full", BRAND_TINT)}>
        {uploading ? <LoaderCircle className="size-5 animate-spin" /> : <FileUp className="size-5" />}
      </span>
      <p className="mt-4 font-medium">{uploading ? "Uploading…" : "Drop files here or click to upload"}</p>
      <p className="mt-1 text-sm text-muted">PDF, TXT or Markdown · up to 10 MB each</p>
      <input
        ref={input}
        type="file"
        multiple
        accept={ACCEPT}
        className="hidden"
        onChange={(e) => handle(e.target.files)}
      />
    </div>
  );
}

function DocumentRow({ document: d, onDelete }: { document: VoxDocument; onDelete: () => void }) {
  return (
    <li className="flex items-center gap-4 px-5 py-3">
      <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-zinc-100 text-muted dark:bg-zinc-800">
        <FileText className="size-4" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">{d.filename}</div>
        <div className="mt-0.5 text-xs text-muted">
          Uploaded {formatDate(d.created_at)}
          {d.status === "ready" && ` · ${d.num_chunks} chunks`}
        </div>
        {d.error && <div className="mt-1 text-xs text-red-600">{d.error}</div>}
      </div>
      <StatusBadge status={d.status} />
      <button
        onClick={onDelete}
        className="rounded-md p-2 text-muted transition hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-500/10"
        aria-label={`Delete ${d.filename}`}
      >
        <Trash2 className="size-4" />
      </button>
    </li>
  );
}

function StatusBadge({ status }: { status: VoxDocument["status"] }) {
  if (status === "processing")
    return (
      <Badge tone="warning">
        <LoaderCircle className="size-3 animate-spin" /> Processing
      </Badge>
    );
  if (status === "ready")
    return (
      <Badge tone="success">
        <CircleCheck className="size-3" /> Ready
      </Badge>
    );
  return (
    <Badge tone="danger">
      <CircleX className="size-3" /> Failed
    </Badge>
  );
}
