import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  envDir: "..", // read VITE_* variables from ProjectCode/.env
  server: { port: 3000, proxy: { "/api": "http://localhost:8000" } },
});
