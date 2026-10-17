import { AudioWaveform } from "lucide-react";
import Link from "next/link";

export function Logo({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="flex items-center gap-2">
      <span className="flex size-8 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 via-violet-500 to-fuchsia-500 text-white shadow-md shadow-violet-500/30">
        <AudioWaveform className="size-4.5" strokeWidth={2.5} />
      </span>
      <span className="text-lg font-semibold tracking-tight">VoxDesk</span>
    </Link>
  );
}
