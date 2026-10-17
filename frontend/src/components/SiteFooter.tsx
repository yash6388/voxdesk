import { Logo } from "@/components/Logo";

const AUTHOR = {
  name: "Yash Kumar Singh",
  linkedin: "https://www.linkedin.com/in/yash-kumarsingh/",
  github: "https://github.com/yash6388",
};

// Brand marks as inline SVGs (Lucide no longer ships brand icons).
function LinkedInIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" className={className}>
      <path d="M20.45 20.45h-3.56v-5.57c0-1.33-.02-3.04-1.85-3.04-1.85 0-2.14 1.45-2.14 2.94v5.67H9.35V9h3.41v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28zM5.34 7.43a2.06 2.06 0 1 1 0-4.13 2.06 2.06 0 0 1 0 4.13zM7.12 20.45H3.56V9h3.56v11.45zM22.22 0H1.77C.79 0 0 .77 0 1.73v20.54C0 23.23.79 24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.73V1.73C24 .77 23.2 0 22.22 0z" />
    </svg>
  );
}

function GitHubIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" className={className}>
      <path d="M12 .3a12 12 0 0 0-3.8 23.38c.6.12.83-.26.83-.57L9 21.07c-3.34.72-4.04-1.61-4.04-1.61-.55-1.39-1.34-1.76-1.34-1.76-1.08-.74.09-.73.09-.73 1.2.09 1.83 1.24 1.83 1.24 1.07 1.83 2.81 1.3 3.5 1 .1-.78.42-1.31.76-1.61-2.67-.3-5.47-1.33-5.47-5.93 0-1.31.47-2.38 1.24-3.22-.14-.3-.54-1.52.1-3.18 0 0 1-.32 3.3 1.23a11.5 11.5 0 0 1 6 0c2.28-1.55 3.29-1.23 3.29-1.23.64 1.66.24 2.88.12 3.18a4.65 4.65 0 0 1 1.23 3.22c0 4.61-2.8 5.63-5.48 5.92.42.36.81 1.1.81 2.22l-.01 3.29c0 .31.2.69.82.57A12 12 0 0 0 12 .3z" />
    </svg>
  );
}

const socialClass =
  "flex size-9 items-center justify-center rounded-lg border border-border text-muted transition hover:-translate-y-0.5 hover:border-indigo-300 hover:text-indigo-600 dark:hover:border-indigo-500/50 dark:hover:text-indigo-400";

export function SiteFooter() {
  return (
    <footer className="border-t border-border">
      <div className="mx-auto flex max-w-6xl flex-col items-center gap-6 px-4 py-10 sm:flex-row sm:justify-between">
        <div className="flex flex-col items-center gap-2 sm:items-start">
          <Logo />
          <span className="text-sm text-muted">
            © {new Date().getFullYear()} VoxDesk. All rights reserved.
          </span>
        </div>

        <div className="flex flex-col items-center gap-3 sm:items-end">
          <span className="text-sm text-muted">
            Built by <span className="font-medium text-foreground">{AUTHOR.name}</span>
          </span>
          <div className="flex gap-2">
            <a
              href={AUTHOR.linkedin}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={`${AUTHOR.name} on LinkedIn`}
              className={socialClass}
            >
              <LinkedInIcon className="size-4" />
            </a>
            <a
              href={AUTHOR.github}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={`${AUTHOR.name} on GitHub`}
              className={socialClass}
            >
              <GitHubIcon className="size-4" />
            </a>
          </div>
        </div>
      </div>
    </footer>
  );
}
