import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { applyMotionPref } from "./lib/motion";
import "./styles/index.css";

applyMotionPref();

createRoot(document.getElementById("root")!).render(<ErrorBoundary><App /></ErrorBoundary>);
