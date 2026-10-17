import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Self-contained server bundle for the Docker image (no node_modules needed at runtime).
  output: "standalone",

  // Clickjacking protection: no page may be framed by another site — except the customer
  // chat page, which the website widget embeds on businesses' own sites.
  async headers() {
    return [
      {
        source: "/((?!c/).*)",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
        ],
      },
      {
        source: "/c/:path*",
        headers: [{ key: "Content-Security-Policy", value: "frame-ancestors *" }],
      },
    ];
  },
};

export default nextConfig;
