import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backendPort = env.TV_BACKEND_PORT ?? "8284";
  const frontendPort = Number(env.TV_FRONTEND_PORT ?? "5284");

  return {
    plugins: [react()],
    server: {
      port: frontendPort,
      strictPort: true,
      proxy: {
        // The backend owns both the data and the card artwork it serves from app/heroes.
        "/api": { target: `http://127.0.0.1:${backendPort}`, changeOrigin: false },
        "/heroes": { target: `http://127.0.0.1:${backendPort}`, changeOrigin: false },
      },
    },
  };
});
