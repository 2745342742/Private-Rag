import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

const container = document.getElementById("root");

if (!container) {
  throw new Error("未找到 id 为 'root' 的根元素");
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

