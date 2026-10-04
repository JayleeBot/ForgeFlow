import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Butterbase serves the zip at the site root, so the default base is right.
// Assets land in dist/assets/ and index.html references them absolutely.
export default defineConfig({
  plugins: [react()],
});
