import { defineConfig } from "astro/config";
import { fileURLToPath } from "node:url";
const src = (p) => fileURLToPath(new URL(`./src/${p}`, import.meta.url));

export default defineConfig({
  vite: {
    resolve: {
      alias: {
        "@": src(""),
        "@components": src("components"),
        "@scripts": src("scripts"),
        "@styles": src("styles"),
      },
    },
  },
});
