import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import GestureOverlay from "./GestureOverlay";
import "./styles.css";
import "./gesture.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
    <GestureOverlay />
  </React.StrictMode>,
);
