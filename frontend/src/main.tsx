import React from "react";
import ReactDOM from "react-dom/client";
import "leaflet/dist/leaflet.css";
import "leaflet-velocity/dist/leaflet-velocity.css";

import App from "./App";
import "./index.css";
import { watchServiceWorkerUpdate } from "./lib/swReload";

watchServiceWorkerUpdate();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
