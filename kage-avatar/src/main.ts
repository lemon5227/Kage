import './style.css';
import * as PIXI from 'pixi.js';
import { Live2DModel } from 'pixi-live2d-display';
import { getCurrentWindow } from '@tauri-apps/api/window';

// Expose PIXI to window (Required by plugin)
(window as any).PIXI = PIXI;

// Register Ticker
Live2DModel.registerTicker(PIXI.Ticker);

// --- 1. Initialize PIXI v6 Application ---
const app = new PIXI.Application({
  width: 350,
  height: 550,
  transparent: true,
  resolution: window.devicePixelRatio || 1, // Fix Blurring
  autoDensity: true, // Handle CSS scaling
  resizeTo: window,
  autoStart: true
});

// Append to DOM
const canvas = app.view as HTMLCanvasElement;
// CRITICAL: Apply drag region to the canvas itself so clicks on it trigger drag
canvas.setAttribute('data-tauri-drag-region', 'true');
canvas.style.cursor = 'grab';
document.getElementById('app')?.appendChild(canvas);

// --- 2. Enable Window Dragging (Manual JS - More Robust) ---
// Click anywhere on the canvas to drag the window
canvas.addEventListener('mousedown', () => {
  getCurrentWindow().startDragging();
});

// --- 3. Load Model ---
async function main() {
  try {
    console.log("Loading model...");
    const model = await Live2DModel.from('/models/haru/haru_greeter_t03.model3.json');

    app.stage.addChild(model);

    // Scale and Position (User requested 0.13)
    model.scale.set(0.13);
    model.x = -50;
    model.y = -20;

    console.log("✅ Model Loaded!");

    // --- 4. WebSocket Connection (Brain) ---
    setupWebSocket(model);

    // --- 5. LipSync Animation Loop ---
    let mouthValue = 0;

    // Debug flag to print API structure once
    let hasLoggedApi = false;

    app.ticker.add((delta) => {
      if (!model || !model.internalModel) return;

      // DEBUG: Check what APIs are available
      if (!hasLoggedApi) {
        console.log("Model Type:", model.constructor.name);
        console.log("Internal Model:", model.internalModel);
        // @ts-ignore
        if (model.internalModel.coreModel) {
          const core = model.internalModel.coreModel;
          console.log("Core Model:", core);
          // @ts-ignore
          if (core._parameterIds) console.log("Core Indices:", core._parameterIds);
          // @ts-ignore
          if (core.parameters) console.log("Core Parameters:", core.parameters);
        }
        // @ts-ignore
        if (model.internalModel.parameters) console.log("High-level Params:", model.internalModel.parameters);

        hasLoggedApi = true;
      }

      if (isSpeaking) {
        const t = Date.now() / 150; // Slower sine wave
        mouthValue = (Math.sin(t) + 1) / 2 * 0.8; // 0 to 0.8
        // DEBUG: Visual Signal
        document.body.style.border = "4px solid red";
      } else {
        mouthValue = Math.max(0, mouthValue - 0.1 * delta);
        document.body.style.border = "none";
      }

      // --- UNIVERSAL PARAMETER SETTER ---
      // Try all known ways to set ParamMouthOpenY for Pixi-Live2D v0.4 / Cubism 4

      try {
        const im = model.internalModel;
        const core = im.coreModel;
        const paramId = 'ParamMouthOpenY';

        // Method 1: High Level .parameters (If exists)
        // @ts-ignore
        if (im.parameters && im.parameters.ids) {
          // @ts-ignore
          const idx = im.parameters.ids.indexOf(paramId);
          if (idx >= 0) {
            // @ts-ignore
            im.parameters.values[idx] = mouthValue;
            // Note: Some versions require .setValue(id, val)
          }
        }

        // Method 2: Core Model Index (Standard Cubism 4)
        // @ts-ignore
        if (core && core._parameterIds) {
          // @ts-ignore
          const idx = core._parameterIds.indexOf(paramId);
          if (idx >= 0) {
            // @ts-ignore
            core.setParameterValueByIndex(idx, mouthValue, 1.0);
          }
        }

        // Method 3: Core Model Direct ID (Cubism 2/3 Legacy or Wrapper)
        // @ts-ignore
        if (core && core.setParameterValueById) {
          // @ts-ignore
          core.setParameterValueById(paramId, mouthValue);
        }

      } catch (e) {
        // Suppress errors to avoid console flood
      }
    });

  } catch (e) {
    console.error(e);
  }
}

let isSpeaking = false;

function setupWebSocket(model: Live2DModel) {
  const socket = new WebSocket("ws://127.0.0.1:12345/ws");

  socket.onopen = () => console.log("🔌 Connected to Brain");

  socket.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);

      // Handle Speaking State
      if (data.type === "state") {
        console.log("State:", data.state);
        if (data.state === "SPEAKING") {
          isSpeaking = true;
        } else if (data.state === "IDLE" || data.state === "LISTENING") {
          isSpeaking = false;
        }
      }

      // Handle Speech Text
      if (data.type === "speech") {
        console.log("Kage Says: " + data.text);
      }

      // Handle Expression Change
      if (data.type === "expression") {
        console.log("Expression:", data.name);
        try {
          model.expression(data.name);
        } catch (e) { console.error("Expr Error", e); }
      }

      // Handle Motion Trigger
      if (data.type === "motion") {
        console.log("Motion:", data.group, data.index);
        try {
          model.motion(data.group, data.index);
        } catch (e) { console.error("Motion Error", e); }
      }

    } catch (e) {
      console.error("WS Parse Error", e);
    }
  };

  socket.onclose = () => {
    console.log("Disconnected. Retrying in 3s...");
    setTimeout(() => setupWebSocket(model), 3000);
  };
}

main();
