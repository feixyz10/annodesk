import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
export default defineConfig({
  plugins: [vue()],
  build: { outDir: "../src/annodesk/web_dist", emptyOutDir: true },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8765",
      "/ui-config.json": "http://127.0.0.1:8765",
    },
  },
});
