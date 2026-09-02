import {
  PanelSection,
  PanelSectionRow,
  SliderField,
  staticClasses,
  ToggleField,
} from "@decky/ui";
import { definePlugin } from "@decky/api";
import { useState } from "react";
import { FaKeyboard } from "react-icons/fa";

import { CaretController } from "./input-controller";
import { loadSettings, saveSettings, type PluginSettings } from "./settings";

const controller = new CaretController(loadSettings());

function Content() {
  const [settings, setSettings] = useState<PluginSettings>(() => controller.settings);

  const update = (patch: Partial<PluginSettings>) => {
    const next = { ...settings, ...patch };
    setSettings(next);
    saveSettings(next);
    controller.updateSettings(next);
  };

  return (
    <>
      <PanelSection title="Caret controls">
        <PanelSectionRow>
          <ToggleField
            label="Enabled"
            description="Move the text caret with a connected controller"
            checked={settings.enabled}
            onChange={(enabled) => update({ enabled })}
          />
        </PanelSectionRow>

        <PanelSectionRow>
          <ToggleField
            label="Shoulder buttons"
            description="L1/LB/L moves left; R1/RB/R moves right"
            checked={settings.bumpersEnabled}
            disabled={!settings.enabled}
            onChange={(bumpersEnabled) => update({ bumpersEnabled })}
          />
        </PanelSectionRow>

        <PanelSectionRow>
          <ToggleField
            label="Right stick"
            description="Move left, right, up, and down"
            checked={settings.stickEnabled}
            disabled={!settings.enabled}
            onChange={(stickEnabled) => update({ stickEnabled })}
          />
        </PanelSectionRow>

        <PanelSectionRow>
          <SliderField
            label="Stick deadzone"
            description="Increase this to prevent accidental movement"
            value={settings.stickDeadzonePercent}
            min={25}
            max={85}
            step={5}
            showValue
            valueSuffix="%"
            disabled={!settings.enabled || !settings.stickEnabled}
            onChange={(stickDeadzonePercent) => update({ stickDeadzonePercent })}
          />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Behavior">
        <PanelSectionRow>
          <ToggleField
            label="Repeat while held"
            description="Hold a bumper or the stick to move repeatedly"
            checked={settings.repeatEnabled}
            disabled={!settings.enabled}
            onChange={(repeatEnabled) => update({ repeatEnabled })}
          />
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}

export default definePlugin(() => {
  controller.start();

  return {
    name: "Caret Control",
    titleView: <div className={staticClasses.Title}>Caret Control</div>,
    content: <Content />,
    icon: <FaKeyboard />,
    onDismount() {
      controller.stop();
    },
  };
});
