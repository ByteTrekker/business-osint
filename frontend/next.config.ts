import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  // Next 16 generuje własne AGENTS.md i CLAUDE.md w katalogu frontendu.
  // Instrukcje dla agentów trzymamy w jednym miejscu — w CLAUDE.md w korzeniu.
  agentRules: false,
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1",
  },
};

export default config;
