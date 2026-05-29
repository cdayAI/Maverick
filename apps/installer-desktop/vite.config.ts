import { defineConfig } from 'vite';
import { svelte, vitePreprocess } from '@sveltejs/vite-plugin-svelte';

export default defineConfig({
  // vitePreprocess transpiles <script lang="ts"> (TS -> JS via esbuild).
  // Without it the Svelte compiler can't parse any TypeScript in a
  // component -- which is why the build failed on the first type-import.
  plugins: [svelte({ preprocess: vitePreprocess() })],
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
  },
  envPrefix: ['VITE_', 'TAURI_'],
});
