import { addEventListener, callable, removeEventListener } from "@decky/api";
import { EUIMode } from "@decky/ui";

import type { PluginSettings } from "./settings";
import { SteamVirtualKeyboard } from "./virtual-keyboard";

export type Direction = "left" | "right" | "up" | "down";

export interface BackendStatus {
  backendReady: boolean;
  controllerConnected?: boolean;
  controllerPath?: string | null;
  directInputReady?: boolean;
  keyboardDetected?: boolean;
  active?: boolean;
  lastInput?: string;
  lastOutput?: string;
  inputEvents?: number;
  inputReports?: number;
  error?: string | null;
}

const configureBackend = callable<
  [settings: PluginSettings, keyboardOpen: boolean, keyboardTargetReady: boolean],
  BackendStatus
>("configure");
export class CaretController {
  private readonly virtualKeyboard: SteamVirtualKeyboard;
  private uiModeRegistration: { unregister: () => void } | null = null;
  private readonly directionListener = (direction: Direction) => {
    this.virtualKeyboard.pressDirection(direction);
  };
  private started = false;

  constructor(public settings: PluginSettings) {
    this.virtualKeyboard = new SteamVirtualKeyboard(
      settings,
      () => void this.syncBackend(),
    );
  }

  start(): void {
    if (this.started) return;
    this.started = true;
    addEventListener<[Direction]>("caret_direction", this.directionListener);
    this.virtualKeyboard.start();
    this.startUIModeTracking();
    void this.syncBackend();
  }

  stop(): void {
    removeEventListener<[Direction]>("caret_direction", this.directionListener);
    this.uiModeRegistration?.unregister();
    this.uiModeRegistration = null;
    this.virtualKeyboard.stop();
    this.started = false;
  }

  updateSettings(settings: PluginSettings): void {
    this.settings = settings;
    this.virtualKeyboard.setSettings(settings);
    void this.syncBackend();
  }

  private async syncBackend(): Promise<void> {
    const keyboardState = this.virtualKeyboard.getState();
    try {
      await configureBackend(
        this.settings,
        keyboardState.open,
        keyboardState.targetReady,
      );
    } catch (error) {
      console.error("[Caret Control] Could not configure backend", error);
    }
  }

  private startUIModeTracking(): void {
    const applyMode = (mode: EUIMode): void => {
      this.virtualKeyboard.setGamepadMode(mode !== EUIMode.Desktop);
    };

    try {
      this.uiModeRegistration = SteamClient.UI.RegisterForUIModeChanged(applyMode);
      void SteamClient.UI.GetUIMode()
        .then(applyMode)
        .catch((error) =>
          console.warn("[Caret Control] Could not read the Steam UI mode", error),
        );
    } catch (error) {
      console.warn("[Caret Control] Could not monitor the Steam UI mode", error);
    }
  }
}
