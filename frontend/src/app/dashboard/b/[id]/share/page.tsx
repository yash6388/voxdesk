"use client";

import { Check, Code2, Copy, Download, ExternalLink, Link2, MessageCircle, QrCode } from "lucide-react";
import { useParams } from "next/navigation";
import QRCode from "qrcode";
import { useEffect, useState } from "react";

import { Button, buttonClass } from "@/components/ui/Button";
import { Card, PageHeader } from "@/components/ui/primitives";
import { type Business, getBusiness } from "@/lib/api";
import { BRAND_TINT, cn } from "@/lib/utils";

export default function SharePage() {
  const { id } = useParams<{ id: string }>();
  const [business, setBusiness] = useState<Business | null>(null);

  useEffect(() => {
    getBusiness(id).then(setBusiness).catch(() => {});
  }, [id]);

  if (!business) {
    return <div className="h-64 animate-pulse rounded-xl bg-zinc-200/60 dark:bg-zinc-800/60" />;
  }

  const origin = window.location.origin;
  const link = `${origin}/c/${business.slug}`;
  const widget = `<script src="${origin}/widget.js" data-business="${business.slug}" async></script>`;
  const iframe = `<iframe src="${link}?embed=1" title="Chat with ${business.name}" width="400" height="620" style="border:0;border-radius:16px" allow="microphone"></iframe>`;

  return (
    <>
      <PageHeader
        title="Share with customers"
        description="Everywhere your customers already are — your website, Google profile, social bios, or a QR code at the counter."
      />
      <div className="grid gap-6 lg:grid-cols-2">
        <ShareCard
          icon={Link2}
          title="Customer link"
          description="Put it in your Instagram or WhatsApp bio, Google Business Profile, emails and SMS reminders."
        >
          <CopyField value={link} />
          <a href={link} target="_blank" rel="noopener noreferrer" className={cn(buttonClass("secondary", "sm"), "mt-3")}>
            <ExternalLink className="size-4" /> Open customer page
          </a>
        </ShareCard>

        <ShareCard
          icon={QrCode}
          title="QR code"
          description="Print it for your counter, mirrors, business cards or posters — customers scan and start chatting."
        >
          <QrPanel link={link} name={business.slug} />
        </ShareCard>

        <ShareCard
          icon={MessageCircle}
          title="Website chat bubble"
          description="Paste this one line before </body> on any website (WordPress, Wix, Shopify, custom). A chat bubble appears in the corner of every page."
        >
          <CopyField value={widget} code />
          <WidgetPreview origin={origin} slug={business.slug} />
        </ShareCard>

        <ShareCard
          icon={Code2}
          title="Inline embed"
          description="Show the chat directly inside a page, e.g. your Contact or Book Now page."
        >
          <CopyField value={iframe} code />
        </ShareCard>
      </div>
    </>
  );
}

function ShareCard({
  icon: Icon,
  title,
  description,
  children,
}: {
  icon: React.ElementType;
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <Card className="p-5">
      <div className="flex items-start gap-3">
        <span className={cn("flex size-10 shrink-0 items-center justify-center rounded-xl", BRAND_TINT)}>
          <Icon className="size-5" />
        </span>
        <div>
          <h2 className="font-semibold">{title}</h2>
          <p className="mt-1 text-sm text-muted">{description}</p>
        </div>
      </div>
      <div className="mt-4">{children}</div>
    </Card>
  );
}

function CopyField({ value, code }: { value: string; code?: boolean }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }
  return (
    <div className="flex items-stretch gap-2">
      <div
        className={cn(
          "min-w-0 flex-1 rounded-lg border border-border bg-zinc-50 px-3 py-2 text-xs dark:bg-zinc-900",
          code ? "break-all font-mono" : "truncate",
        )}
      >
        {value}
      </div>
      <Button variant="secondary" size="sm" onClick={copy} className="h-auto shrink-0">
        {copied ? <Check className="size-4 text-emerald-600" /> : <Copy className="size-4" />}
        {copied ? "Copied" : "Copy"}
      </Button>
    </div>
  );
}

function QrPanel({ link, name }: { link: string; name: string }) {
  const [dataUrl, setDataUrl] = useState<string | null>(null);

  useEffect(() => {
    // High error correction (H) keeps the code scannable even if printed small or scuffed.
    QRCode.toDataURL(link, { width: 640, margin: 2, errorCorrectionLevel: "H" })
      .then(setDataUrl)
      .catch(() => setDataUrl(null));
  }, [link]);

  return (
    <div className="flex items-center gap-5">
      <div className="rounded-xl border border-border bg-white p-2">
        {dataUrl ? (
          // eslint-disable-next-line @next/next/no-img-element -- generated data URL
          <img src={dataUrl} alt={`QR code for ${link}`} className="size-36" />
        ) : (
          <div className="size-36 animate-pulse rounded bg-zinc-100" />
        )}
      </div>
      <div className="space-y-2">
        <p className="text-sm text-muted">Scans straight to your customer page.</p>
        {dataUrl && (
          <a href={dataUrl} download={`${name}-qr.png`} className={buttonClass("primary", "sm")}>
            <Download className="size-4" /> Download PNG
          </a>
        )}
      </div>
    </div>
  );
}

/** Loads the real widget script on this page, so the owner sees exactly what visitors get. */
function WidgetPreview({ origin, slug }: { origin: string; slug: string }) {
  const [active, setActive] = useState(false);

  function preview() {
    if (document.querySelector("script[data-voxdesk-preview]")) return;
    const script = document.createElement("script");
    script.src = `${origin}/widget.js`;
    script.async = true;
    script.dataset.business = slug;
    script.dataset.voxdeskPreview = "true";
    document.body.appendChild(script);
    setActive(true);
  }

  return (
    <div className="mt-3 flex items-center gap-3">
      <Button variant="secondary" size="sm" onClick={preview} disabled={active}>
        <MessageCircle className="size-4" /> {active ? "Preview active ↘" : "Preview on this page"}
      </Button>
      {active && <span className="text-xs text-muted">Look at the bottom-right corner.</span>}
    </div>
  );
}
