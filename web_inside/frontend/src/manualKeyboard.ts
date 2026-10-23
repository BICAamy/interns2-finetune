export type ManualKind = "translation" | "rotation" | "joint";
export type ManualDirection = { kind: ManualKind; axis: number; direction: -1 | 1 };

const directions: Record<string, ManualDirection> = {
  KeyW: {kind:"translation",axis:0,direction:1}, KeyS:{kind:"translation",axis:0,direction:-1},
  KeyA: {kind:"translation",axis:1,direction:1}, KeyD:{kind:"translation",axis:1,direction:-1},
  KeyR: {kind:"translation",axis:2,direction:1}, KeyF:{kind:"translation",axis:2,direction:-1},
  KeyI: {kind:"rotation",axis:0,direction:1}, KeyK:{kind:"rotation",axis:0,direction:-1},
  KeyJ: {kind:"rotation",axis:1,direction:1}, KeyL:{kind:"rotation",axis:1,direction:-1},
  KeyU: {kind:"rotation",axis:2,direction:1}, KeyO:{kind:"rotation",axis:2,direction:-1},
};
export function isMotionKey(code: string) { return code in directions || /^Digit[1-6]$/.test(code); }
export function keyDirection(code: string, shift: boolean): ManualDirection | null {
  if (/^Digit[1-6]$/.test(code)) return {kind:"joint",axis:Number(code.slice(-1))-1,direction:shift?-1:1};
  return directions[code] ?? null;
}
export function sameDirection(a: ManualDirection | null,b: ManualDirection | null) {
  return a?.kind===b?.kind && a?.axis===b?.axis && a?.direction===b?.direction;
}
