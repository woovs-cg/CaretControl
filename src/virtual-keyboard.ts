import type { Direction } from "./input-controller";
import type { PluginSettings } from "./settings";

interface VirtualKeyboardComponent {
  TypeKeyInternal: (event: { strKey: string; strKeycode?: string }) => void;
  m_keyboardDiv?: Node;
}

interface Fiber {
  child: Fiber | null;
  sibling: Fiber | null;
  stateNode?: unknown;
}

interface SteamWindowInstance {
  BrowserWindow?: Window;
}

interface SteamUIStoreShape {
  ActiveWindowInstance?: SteamWindowInstance;
  WindowStore?: {
    SteamUIWindows?: SteamWindowInstance[];
  };
}

type SteamGlobalWindow = Window & {
  SteamUIStore?: SteamUIStoreShape;
  SteamClient?: {
    Input?: {
      ControllerKeyboardSetKeyState?: (key: number, pressed: boolean) => void;
      RegisterForControllerStateChanges?: (
        callback: (changes: ControllerStateChange[]) => void,
      ) => Unregisterable;
    };
  };
};

interface Unregisterable {
  unregister: () => void;
}

interface ControllerStateChange {
  unControllerIndex: number;
  ulButtons: number;
  sRightStickX: number;
  sRightStickY: number;
}

interface GamepadEventDetail {
  button?: number;
}

const DIRECTION_KEYS: Record<Direction, string> = {
  left: "ArrowLeft",
  right: "ArrowRight",
  up: "ArrowUp",
  down: "ArrowDown",
};

const HID_DIRECTION_KEYS: Record<Direction, number> = {
  right: 79,
  left: 80,
  down: 81,
  up: 82,
};

const L1_MASK = 1 << 3;
const R1_MASK = 1 << 2;

const GAMEPAD_BUMPER_LEFT = 5;
const GAMEPAD_BUMPER_RIGHT = 6;
const GAMEPAD_DIRECTION_BUTTONS: Partial<Record<number, Direction>> = {
  9: "up",
  10: "down",
  11: "left",
  12: "right",
};

export interface VirtualKeyboardState {
  open: boolean;
  targetReady: boolean;
}

export class SteamVirtualKeyboard {
  private timer?: number;
  private component: VirtualKeyboardComponent | null = null;
  private eventDocument: Document | null = null;
  private controllerRegistration: Unregisterable | null = null;
  private controllerStates = new Map<number, ControllerStateChange>();
  private suppressedButtons = new Set<number>();
  private gamepadMode = true;
  private state: VirtualKeyboardState = {
    open: false,
    targetReady: false,
  };

  constructor(
    private settings: PluginSettings,
    private readonly onStateChanged: (state: VirtualKeyboardState) => void,
  ) {}

  start(): void {
    this.refresh();
    this.timer = window.setInterval(() => this.refresh(), 200);
  }

  stop(): void {
    if (this.timer !== undefined) window.clearInterval(this.timer);
    this.setEventDocument(null);
    this.component = null;
  }

  setSettings(settings: PluginSettings): void {
    this.settings = settings;
    this.refresh();
  }

  getState(): VirtualKeyboardState {
    return this.state;
  }

  typeDirection(direction: Direction): boolean {
    const component = this.component ?? this.findComponent(this.findKeyboardDom());
    if (!component) return false;

    try {
      component.TypeKeyInternal({ strKey: DIRECTION_KEYS[direction] });
      return true;
    } catch (error) {
      console.error("[Caret Control] Could not send direction to Steam keyboard", error);
      return false;
    }
  }

  typeSystemDirection(direction: Direction): boolean {
    const input =
      (this.eventDocument?.defaultView as SteamGlobalWindow | null)?.SteamClient?.Input ??
      (window as SteamGlobalWindow).SteamClient?.Input;
    if (!input?.ControllerKeyboardSetKeyState) return false;

    try {
      const key = HID_DIRECTION_KEYS[direction];
      input.ControllerKeyboardSetKeyState(key, true);
      input.ControllerKeyboardSetKeyState(key, false);
      return true;
    } catch (error) {
      console.error("[Caret Control] Could not send a system arrow key", error);
      return false;
    }
  }

  setGamepadMode(gamepadMode: boolean): void {
    this.gamepadMode = gamepadMode;
    if (!gamepadMode) this.suppressedButtons.clear();
  }

  private refresh(): void {
    const nextDom = this.findKeyboardDom();
    this.setEventDocument(nextDom?.ownerDocument ?? null);
    this.component = this.findComponent(nextDom);

    const nextState: VirtualKeyboardState = {
      open: nextDom !== null,
      targetReady: this.component !== null,
    };

    if (
      nextState.open !== this.state.open ||
      nextState.targetReady !== this.state.targetReady
    ) {
      this.state = nextState;
      this.onStateChanged(nextState);
    }
  }

  private findKeyboardDom(): HTMLElement | null {
    const steamWindow = window as SteamGlobalWindow;
    const instances = [
      steamWindow.SteamUIStore?.ActiveWindowInstance,
      ...(steamWindow.SteamUIStore?.WindowStore?.SteamUIWindows ?? []),
    ];

    for (const instance of instances) {
      const keyboard = instance?.BrowserWindow?.document?.getElementById("virtual keyboard");
      if (keyboard && this.isVisible(keyboard)) return keyboard;
    }

    const localKeyboard = document.getElementById("virtual keyboard");
    if (localKeyboard && this.isVisible(localKeyboard)) {
      return localKeyboard;
    }
    return null;
  }

  private isVisible(element: HTMLElement): boolean {
    const ownerWindow = element.ownerDocument.defaultView;
    const style = ownerWindow?.getComputedStyle(element);
    const bounds = element.getBoundingClientRect();
    return (
      element.isConnected &&
      style?.display !== "none" &&
      style?.visibility !== "hidden" &&
      bounds.width > 0 &&
      bounds.height > 0
    );
  }

  private findComponent(dom: HTMLElement | null): VirtualKeyboardComponent | null {
    if (!dom) return null;
    let root: Fiber | null = null;
    for (const key in dom) {
      if (key.startsWith("__reactFiber$")) {
        root = dom[key as keyof HTMLElement] as unknown as Fiber;
        break;
      }
    }
    if (!root) return null;

    const expectedDiv = dom.firstChild;
    const stack: Fiber[] = [root];
    let visited = 0;
    while (stack.length > 0 && visited < 5000) {
      const current = stack.pop();
      visited += 1;
      if (!current) continue;
      const candidate = current.stateNode as Partial<VirtualKeyboardComponent> | undefined;
      if (
        candidate?.m_keyboardDiv === expectedDiv &&
        typeof candidate.TypeKeyInternal === "function"
      ) {
        return candidate as VirtualKeyboardComponent;
      }
      if (current.sibling) stack.push(current.sibling);
      if (current.child) stack.push(current.child);
    }
    return null;
  }

  private setEventDocument(nextDocument: Document | null): void {
    if (this.eventDocument === nextDocument) return;

    if (this.eventDocument) {
      this.eventDocument.removeEventListener(
        "vgp_onbuttondown",
        this.onGamepadEvent,
        true,
      );
      this.eventDocument.removeEventListener("vgp_onbuttonup", this.onGamepadEvent, true);
    }
    this.controllerRegistration?.unregister();
    this.controllerRegistration = null;
    this.controllerStates.clear();
    this.suppressedButtons.clear();
    this.eventDocument = nextDocument;

    if (!nextDocument) return;
    nextDocument.addEventListener("vgp_onbuttondown", this.onGamepadEvent, true);
    nextDocument.addEventListener("vgp_onbuttonup", this.onGamepadEvent, true);

    const steamWindow = nextDocument.defaultView as SteamGlobalWindow | null;
    try {
      this.controllerRegistration =
        steamWindow?.SteamClient?.Input?.RegisterForControllerStateChanges?.(
          this.onControllerStateChanged,
        ) ?? null;
    } catch (error) {
      console.warn("[Caret Control] Could not monitor controller state", error);
    }
  }

  private readonly onControllerStateChanged = (changes: ControllerStateChange[]): void => {
    for (const change of changes) {
      this.controllerStates.set(change.unControllerIndex, change);
    }
  };

  private readonly onGamepadEvent = (event: Event): void => {
    if (!this.gamepadMode) return;
    const button = (event as CustomEvent<GamepadEventDetail>).detail?.button;
    if (typeof button !== "number") return;

    const directBumper =
      this.settings.enabled &&
      this.settings.bumpersEnabled &&
      (button === GAMEPAD_BUMPER_LEFT || button === GAMEPAD_BUMPER_RIGHT);
    const direction = GAMEPAD_DIRECTION_BUTTONS[button];
    const shouldSuppress =
      event.type === "vgp_onbuttondown"
        ? directBumper || (direction !== undefined && this.isControlledDirectionActive(direction))
        : directBumper || this.suppressedButtons.has(button);
    if (!shouldSuppress) return;

    if (event.type === "vgp_onbuttondown") this.suppressedButtons.add(button);
    else this.suppressedButtons.delete(button);
    this.stopEvent(event);
  };

  private isControlledDirectionActive(direction: Direction): boolean {
    if (!this.settings.enabled || !this.state.open || !this.state.targetReady) return false;
    for (const state of this.controllerStates.values()) {
      if (
        this.settings.bumpersEnabled &&
        ((direction === "left" && (state.ulButtons & L1_MASK) !== 0) ||
          (direction === "right" && (state.ulButtons & R1_MASK) !== 0))
      ) {
        return true;
      }
      if (this.settings.stickEnabled && this.readStickDirection(state) === direction) {
        return true;
      }
    }
    return false;
  }

  private readStickDirection(state: ControllerStateChange): Direction | null {
    const activation = (this.settings.stickDeadzonePercent / 100) * 32767;
    const { sRightStickX: x, sRightStickY: y } = state;
    if (Math.max(Math.abs(x), Math.abs(y)) < activation) return null;
    if (Math.abs(x) > Math.abs(y)) return x < 0 ? "left" : "right";
    return y > 0 ? "up" : "down";
  }

  private stopEvent(event: Event): void {
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();
  }

}
