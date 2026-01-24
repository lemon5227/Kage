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
    app.ticker.add(() => {
      if (!model || !model.internalModel) return;

      if (isSpeaking) {
        // Simulate talking with sine wave
        const t = Date.now() / 100;
        mouthValue = (Math.sin(t) + 1) / 2; // 0 to 1
      } else {
        // Close mouth gently
        mouthValue = Math.max(0, mouthValue - 0.1);
      }

      try {
        // PixiLive2DDisplay v0.4.0 Core Model Access
        model.internalModel.coreModel.setParameterValueById('ParamMouthOpenY', mouthValue);
      } catch (e) {
        // Ignore safe errors
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
