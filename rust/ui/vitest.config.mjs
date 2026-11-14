import { fileURLToPath } from "node:url";
const frontend = fileURLToPath(new URL("../../frontend/", import.meta.url));
export default {
  root: frontend,
  resolve: {
    alias: {
      "@": frontend + "src",
      react: frontend + "node_modules/react",
      "react-dom": frontend + "node_modules/react-dom",
      "@testing-library/react":
        frontend + "node_modules/@testing-library/react",
      "@testing-library/jest-dom":
        frontend + "node_modules/@testing-library/jest-dom",
      vitest: frontend + "node_modules/vitest",
      "next/server": frontend + "node_modules/next/server.js",
    },
  },
  test: {
    environment: "jsdom",
    include: ["../rust/ui/*.test.tsx"],
    setupFiles: ["./tests/setup.ts"],
    restoreMocks: true,
    testTimeout: 15000,
  },
};
