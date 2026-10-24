import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

const container = document.getElementById("tracecore-root");
if (container) {
  createRoot(container).render(<StrictMode>{null}</StrictMode>);
}
