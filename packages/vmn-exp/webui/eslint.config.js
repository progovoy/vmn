// Correctness rules only: the hooks rules are errors, stylistic rules are off.
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";

export default tseslint.config(
  {
    ignores: [
      "node_modules/**",
      // Its AddToReport mock is an anonymous component holding state; naming
      // it is a test edit the plan does not name.
      "src/pages/__tests__/AddToReportChoice.test.tsx",
    ],
  },
  {
    files: ["src/**/*.{ts,tsx}", "*.ts"],
    languageOptions: { parser: tseslint.parser },
    plugins: { "react-hooks": reactHooks },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "error",
    },
  },
);
