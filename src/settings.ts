export interface PluginSettings {
  enabled: boolean;
  bumpersEnabled: boolean;
  stickEnabled: boolean;
  stickDeadzonePercent: number;
  repeatEnabled: boolean;
}

export const DEFAULT_SETTINGS: PluginSettings = {
  enabled: true,
  bumpersEnabled: true,
  stickEnabled: true,
  stickDeadzonePercent: 55,
  repeatEnabled: true,
};

const STORAGE_KEY = "caret-control.settings.v1";

export function loadSettings(): PluginSettings {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (!stored) return DEFAULT_SETTINGS;

    const parsed = JSON.parse(stored) as Partial<PluginSettings>;
    return {
      enabled: parsed.enabled ?? DEFAULT_SETTINGS.enabled,
      bumpersEnabled: parsed.bumpersEnabled ?? DEFAULT_SETTINGS.bumpersEnabled,
      stickEnabled: parsed.stickEnabled ?? DEFAULT_SETTINGS.stickEnabled,
      stickDeadzonePercent: clampDeadzone(
        parsed.stickDeadzonePercent ?? DEFAULT_SETTINGS.stickDeadzonePercent,
      ),
      repeatEnabled: parsed.repeatEnabled ?? DEFAULT_SETTINGS.repeatEnabled,
    };
  } catch (error) {
    console.warn("[Caret Control] Could not read settings", error);
    return DEFAULT_SETTINGS;
  }
}

export function saveSettings(settings: PluginSettings): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch (error) {
    console.warn("[Caret Control] Could not save settings", error);
  }
}

function clampDeadzone(value: number): number {
  if (!Number.isFinite(value)) return DEFAULT_SETTINGS.stickDeadzonePercent;
  return Math.min(85, Math.max(25, value));
}
