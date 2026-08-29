/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone", // 容器部署（deploy/Dockerfile.web）

  // 生产由既有 Traefik 做 /api 路由（技术方案 §16）；本地开发代理到 FastAPI
  async rewrites() {
    return [
      { source: "/api/:path*", destination: "http://localhost:8000/api/:path*" },
    ];
  },
};

export default nextConfig;
