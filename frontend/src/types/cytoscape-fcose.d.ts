/**
 * cytoscape-fcose nie dostarcza deklaracji typów.
 *
 * Deklarujemy wyłącznie sam moduł — bez rozszerzania typów `cytoscape`.
 * Próba augmentacji `declare module "cytoscape"` z pliku .d.ts bez importów
 * na najwyższym poziomie tworzy deklarację ambientową, która PRZESŁANIA
 * oryginalne typy zamiast je uzupełnić, i psuje cały moduł.
 */
declare module "cytoscape-fcose" {
  import type { Ext } from "cytoscape";
  const extension: Ext;
  export default extension;
}
