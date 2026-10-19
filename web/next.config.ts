import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  experimental: {
    // Above the 500 MB application limit so a large scan reaches the API
    // instead of being truncated while middleware clones the body.
    middlewareClientMaxBodySize: "600mb",
  },
};

export default nextConfig;
