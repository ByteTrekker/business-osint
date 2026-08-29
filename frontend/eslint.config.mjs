import coreWebVitals from "eslint-config-next/core-web-vitals";
import typescript from "eslint-config-next/typescript";

/**
 * Konfiguracja płaska (flat config). `next lint` zostało usunięte w Next 16,
 * a eslint-config-next 16 eksportuje gotowe zestawy flat — nie potrzeba
 * FlatCompat ani pliku .eslintrc.
 */
const config = [
  { ignores: [".next/**", "node_modules/**", "next-env.d.ts"] },
  ...coreWebVitals,
  ...typescript,
];

export default config;
