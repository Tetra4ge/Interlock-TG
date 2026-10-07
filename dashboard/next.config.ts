import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Self-contained server bundle for the Docker image (see dashboard/Dockerfile).
  output: "standalone",
};

export default nextConfig;
