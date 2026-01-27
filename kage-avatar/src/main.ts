import './style.css';
import * as PIXI from 'pixi.js';
import { Live2DModel } from 'pixi-live2d-display';
import { getCurrentWindow } from '@tauri-apps/api/window';

const MOTION_COOLDOWN_MS = 4000;
const MOTION_DEMO_LOOP = false;
const MOTION_DEMO_INTERVAL_MS = 3500;
const EXPRESSION_DEMO_LOOP = false;
const EXPRESSION_DEMO_INTERVAL_MS = 2500;
const EXPRESSION_DEMO_LABEL_ID = 'expression-demo-label';
const EXPRESSION_NEUTRAL = 'f05';

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

    if (MOTION_DEMO_LOOP) {
      startMotionDemoLoop(model);
    }

    if (EXPRESSION_DEMO_LOOP) {
      startExpressionDemoLoop(model);
    }


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
let reconnectTimer: number | undefined;

function setupWebSocket(model: Live2DModel) {
  if (reconnectTimer) {
    window.clearTimeout(reconnectTimer);
    reconnectTimer = undefined;
  }
  const socket = new WebSocket("ws://127.0.0.1:12345/ws");
  let lastMotionAt = 0;
  let expressionResetTimer: number | undefined;

  socket.onopen = () => console.log("🔌 Connected to Brain");

  socket.onerror = () => {
    try {
      socket.close();
    } catch (e) {
      console.error('Socket Close Error', e);
    }
  };

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
          if (expressionResetTimer) {
            window.clearTimeout(expressionResetTimer);
            expressionResetTimer = undefined;
          }
          if (data.duration) {
            const durationMs = Math.max(0, Number(data.duration) * 1000);
            if (durationMs > 0) {
              expressionResetTimer = window.setTimeout(() => {
                try {
                  model.expression(EXPRESSION_NEUTRAL);
                } catch (e) {
                  console.error('Expression Reset Error', e);
                }
              }, durationMs);
            }
          }
        } catch (e) { console.error("Expr Error", e); }
      }

      // Handle Motion Trigger
      if (data.type === "motion") {
        console.log("Motion:", data.group, data.index);
        const now = Date.now();
        if (now - lastMotionAt < MOTION_COOLDOWN_MS) {
          return;
        }
        lastMotionAt = now;
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
    if (reconnectTimer) {
      return;
    }
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = undefined;
      setupWebSocket(model);
    }, 3000);
  };
}

function startMotionDemoLoop(model: Live2DModel) {
  const motions = [
    { group: 'Idle', index: 0 },
    { group: 'Idle', index: 1 },
    { group: 'Idle', index: 2 },
    { group: 'Tap', index: 0 },
    { group: 'Tap', index: 1 }
  ];
  let cursor = 0;

  setTimeout(() => {
    setInterval(() => {
      const motion = motions[cursor % motions.length];
      cursor += 1;
      console.log('Motion Demo:', motion.group, motion.index);
      try {
        model.motion(motion.group, motion.index);
      } catch (e) {
        console.error('Motion Demo Error', e);
      }
    }, MOTION_DEMO_INTERVAL_MS);
  }, 800);
}

function startExpressionDemoLoop(model: Live2DModel) {
  const label = ensureExpressionDemoLabel();
  const expressions = [
    'f00',
    'f01',
    'f02',
    'f03',
    'f04',
    'f05',
    'f06',
    'f07'
  ];
  let cursor = 0;

  setTimeout(() => {
    setInterval(() => {
      const name = expressions[cursor % expressions.length];
      cursor += 1;
      console.log('Expression Demo:', name);
      try {
        if (label) {
          label.textContent = `Expression: ${name}`;
        }
        model.expression(name);
      } catch (e) {
        console.error('Expression Demo Error', e);
      }
    }, EXPRESSION_DEMO_INTERVAL_MS);
  }, 800);
}

function ensureExpressionDemoLabel() {
  let label = document.getElementById(EXPRESSION_DEMO_LABEL_ID);
  if (label) {
    return label;
  }

  label = document.createElement('div');
  label.id = EXPRESSION_DEMO_LABEL_ID;
  label.textContent = 'Expression: pending';
  label.style.position = 'fixed';
  label.style.left = '12px';
  label.style.top = '12px';
  label.style.padding = '6px 10px';
  label.style.fontFamily = 'system-ui, -apple-system, sans-serif';
  label.style.fontSize = '12px';
  label.style.color = '#ffffff';
  label.style.background = 'rgba(0, 0, 0, 0.6)';
  label.style.borderRadius = '8px';
  label.style.zIndex = '9999';
  label.style.pointerEvents = 'none';
  document.body.appendChild(label);
  return label;
}


main();
