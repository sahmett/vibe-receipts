// Builds the thermal printer for the --video clip with the anatomy isometric kit
// (https://github.com/wheresryan22/anatomy, MIT) and writes skills/vibe-receipts/scripts/printer.json:
//   back   SVG of the printer, drawn behind the paper
//   front  SVG of the tear bar, drawn over the paper where it leaves the slot
//   geo    where the paper leaves the slot and how it lies on screen, in video px (1080 x 1920)
// Only needed when the printer changes; receipts.py reads the JSON and needs no Node.
//
//   ANATOMY_KIT=~/.claude/skills/anatomy/kit node tools/printer/build.mjs [--preview]
import { writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const KIT = process.env.ANATOMY_KIT || join(homedir(), ".claude/skills/anatomy/kit");
const k = await import(pathToFileURL(join(KIT, "iso-kit.mjs")).href);
const G = await import(pathToFileURL(join(KIT, "lathe.mjs")).href);

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..", "..");

// The SVG is drawn at the kit's own scale (about 1 px per world unit, 0.6 px lines) and rasterised
// VS times larger into the 1080 x 1920 video, so every line and dot keeps the kit's proportions.
const VS = 2.4;
const WIDTH = 1080 / VS;
const HEIGHT = 1920 / VS;
const AZIMUTH = 76;          // nearly head-on, so the receipt stays straight; the right side still shows
const ELEVATION = 24;
const LEAN = 24;             // the paper leans back as it leaves the slot, square to the camera

// World: x across, y toward the viewer, z up. A countertop thermal printer, 150 x 120 x 70.
const SHELL = { x: -75, y: -60, w: 150, d: 120, r: 10 };
const FRONT = SHELL.y + SHELL.d;           // 60
const SIDE = SHELL.x + SHELL.w;            // 75
const FOOT_H = 3;
const PLINTH = { z0: FOOT_H, z1: 8 };
const PART = 44;                           // where the lid and the cutter cover sit on the shell
const TOP = 70;
const SLOT_Y = 33.3;                       // the paper leaves here, between the lid and the cutter cover
const LID = { x: -73, y: -58, w: 146, d: SLOT_Y - 1.1 + 58, r: 9 };
const CUT = { x: -73, y: SLOT_Y + 1.1, w: 146, d: FRONT - SLOT_Y - 1.1, r: 6 };
const PAPER_W = 104;                       // 80 mm paper on a 115 mm printer
const VOID = { x: -PAPER_W / 2 - 3, y: SLOT_Y - 1.1, w: PAPER_W + 6, d: 2.2, r: 1.1 };
const BAR = { x: -PAPER_W / 2 - 5, y: SLOT_Y + 1.1, w: PAPER_W + 10, d: 1.6, r: 0.6 };
const BAR_H = 1.6;

// Camera: fit the printer's width, then stand it at the bottom of the frame.
const corners = [...k.boxCorners(SHELL, 0, TOP)];
const fit = k.fitProjection(corners, WIDTH, HEIGHT, { pad: 40, azimuth: AZIMUTH, elevation: ELEVATION });
const unit = { ...fit, origin: [0, 0] };
const flat = corners.map((c) => k.iso(c, unit));
const left = Math.min(...flat.map(([x]) => x)), right = Math.max(...flat.map(([x]) => x));
const bottom = Math.max(...flat.map(([, y]) => y));
const P = { ...fit, origin: [WIDTH / 2 - ((left + right) / 2), (1840 / VS) - bottom] };

const at = (point) => k.iso(point, P);
const S = (paths, style) => k.solidSvg(paths, style);
const L = (d, style) => k.lineSvg(d, style);
const D = (points, style) => k.dotsSvg(points, style);
const byDepth = (points) => [...points].sort((a, b) => k.depthOf([a[0], a[1], 0], P) - k.depthOf([b[0], b[1], 0], P));
const planeOf = (y) => k.sideMatrix([0, y], 0, P, "left");
const rect = (x0, z0, x1, z1, r, steps = 6) => k.pathOf(k.roundedPlan({ x: x0, y: z0, w: x1 - x0, d: z1 - z0, r }, steps).map(([u, z]) => [u, -z]), true);
const onFace = (y, d, style) => `<g transform="${planeOf(y)}">${L(d, style)}</g>`;
const sideSlot = (y, z0, z1, half = 0.8) => k.pathOf(k.roundedPlan({ x: y - half, y: z0, w: half * 2, d: z1 - z0, r: half }, 4).map(([u, z]) => at([SIDE, u, z])), true);

let clips = 0;
// A recess in the front face (from the anatomy desk computer): clipped walls, a back plate, two outlines.
function recess({ x0, x1, z0, z1, r, depth }, y, back = "", backClass = "pr-well") {
  const id = `pr-clip-${clips++}`;
  const ring = k.roundedPlan({ x: x0, y: z0, w: x1 - x0, d: z1 - z0, r }, 6);
  const cx = (x0 + x1) / 2, cz = (z0 + z1) / 2;
  const { sinA } = k.cameraOf(P);
  const tops = [], sides = [[], [], [], []];
  ring.forEach(([ax, az], index) => {
    const [bx, bz] = ring[(index + 1) % ring.length];
    const length = Math.hypot(bx - ax, bz - az) || 1;
    let [nx, nz] = [(bz - az) / length, -(bx - ax) / length];
    if (nx * (cx - (ax + bx) / 2) + nz * (cz - (az + bz) / 2) < 0) [nx, nz] = [-nx, -nz];
    if (nx <= 0 && nz <= 0) return;
    const quad = k.pathOf([at([ax, y, az]), at([bx, y, bz]), at([bx, y - depth, bz]), at([ax, y - depth, az])], true);
    if (nz >= nx) tops.push(quad);
    else sides[Math.min(3, Math.max(0, Math.floor(((nx * -sinA + 1) / 2) * 4)))].push(quad);
  });
  const shape = rect(x0, z0, x1, z1, r);
  return [
    `<clipPath id="${id}"><path transform="${planeOf(y)}" d="${shape}"/></clipPath>`,
    `<g clip-path="url(#${id})">`,
    `<path class="iso-top" d="${tops.join("")}"/>`,
    ...sides.map((d, shade) => (d.length ? `<path class="iso-shade" data-shade="${shade}" d="${d.join("")}"/>` : "")),
    `<g transform="${planeOf(y - depth)}"><path class="${backClass}" d="${shape}"/>${back}<path class="iso-line" data-tone="faint" d="${shape}"/></g>`,
    `</g>`,
    onFace(y, shape, { tone: "lo" }),
  ].join("");
}

function feet() {
  // a flat cast shadow on the floor from a high light on the left (as on the vesika figures), not a blurred halo
  const SH = [0.24, -0.14];
  const box = [];
  for (const z of [0, TOP]) for (const x of [SHELL.x, SHELL.x + SHELL.w]) for (const y of [SHELL.y, SHELL.y + SHELL.d]) box.push(at([x + z * SH[0], y + z * SH[1], 0]));
  const out = [`<path class="pr-shadow" d="${k.pathOf(G.hullOf(box), true)}"/>`];
  for (const [x, y] of byDepth(k.corners(SHELL, 16))) {
    out.push(S(k.cylinder(x, y, 7.5, 0, 1.2, P, 28), { tone: "lo" }));
    out.push(S(k.cylinder(x, y, 6, 1.2, FOOT_H - 1.2 + 0.4, P, 28), { tone: "lo" }));
  }
  out.push(S(k.slabOf(k.insetPlan(SHELL, 3), PLINTH.z0, PLINTH.z1 - PLINTH.z0, P, 8), { tone: "lo" }));
  // a row of intake slots along the plinth front, closed outlines in the face plane
  const slots = Array.from({ length: 16 }, (_, i) => rect(-60 + i * 7.6, PLINTH.z0 + 1.6, -55.4 + i * 7.6, PLINTH.z1 - 1.6, 0.9, 4)).join("");
  out.push(onFace(FRONT - 3, slots, { tone: "faint" }));
  return out.join("");
}

const LEDS = [{ x: 28, z: 26 }, { x: 36, z: 26 }, { x: 44, z: 26 }];
const BUTTON = { x0: 52, x1: 66, z0: 19, z1: 33 };
function shell() {
  const out = [S(k.slabOf(SHELL, PLINTH.z1, PART - PLINTH.z1, P, 8, 1.2), { tone: "mid" })];
  // front panel: an inset groove with the grille, three status lamps and the feed button
  out.push(onFace(FRONT, rect(-69, PLINTH.z1 + 4, 69, PART - 4, 4), { tone: "faint" }));
  const grille = Array.from({ length: 13 }, (_, i) => rect(-63 + i * 3.4, 16, -61.6 + i * 3.4, 36, 0.7, 4)).join("");
  out.push(onFace(FRONT, grille, { tone: "lo" }));
  out.push(recess({ x0: 22, x1: 70, z0: 15, z1: 37, r: 3, depth: 1.4 }, FRONT, "", "pr-well"));
  for (const led of LEDS) {
    out.push(L(k.sideRing([led.x, FRONT - 1.4, led.z], 2, "y", P, 20), { tone: "lo" }));
    out.push(D([at([led.x, FRONT - 1.4, led.z])], { size: 0.9, tone: "mid" }));
  }
  // three short rule lines under the lamps stand for their printed names
  out.push(onFace(FRONT - 1.4, LEDS.map(({ x }) => `M${x - 2.2} ${-20}H${x + 2.2}`).join(""), { tone: "lo", free: true }));
  const btn = { x: BUTTON.x0, y: FRONT - 1.4, w: BUTTON.x1 - BUTTON.x0, d: 3.6, r: 1.6 };
  out.push(S(k.slabOf(btn, BUTTON.z0, BUTTON.z1 - BUTTON.z0, P, 4, 0.5), { tone: "mid" }));
  out.push(onFace(btn.y + btn.d, rect(BUTTON.x0 + 2.2, BUTTON.z0 + 2.2, BUTTON.x1 - 2.2, BUTTON.z1 - 2.2, 1.6, 4), { tone: "faint" }));
  // screws in the front corners
  for (const [x, z] of [[-66, 12], [-66, 40]]) {
    out.push(L(k.sideRing([x, FRONT, z], 1.6, "y", P, 16), { tone: "lo" }));
    out.push(D([at([x, FRONT, z])], { size: 0.5 }));
  }
  // right side: vents, two interface ports and the platen knob
  const row = (from, to, gap) => Array.from({ length: Math.floor((to - from) / gap + 1e-9) + 1 }, (_, i) => from + i * gap);
  out.push(L(row(-44, -6, 3.2).map((y) => sideSlot(y, 16, 36)).join(""), { tone: "faint" }));
  for (const [y, w] of [[18, 9], [32, 12]]) {
    out.push(S(k.slabOf({ x: SIDE - 0.4, y, w: 1.2, d: w, r: 0.8 }, 13, 7, P, 3), { tone: "lo" }));
    out.push(D([at([SIDE + 0.8, y - 1.6, 16.5]), at([SIDE + 0.8, y + w + 1.6, 16.5])], { size: 0.4 }));
  }
  return out.join("");
}

function knob() {
  const F = G.frameAlong([SIDE, -32, 26], [1, 0, 0]);
  const out = [S(G.disc(0, 2, 11, F, P), { tone: "lo" })];
  const body = G.disc(2, 8, 9.5, F, P);
  const knurl = G.ribsOf(F, 2, 8, 9.5, 40, P, { fade: [0.1, 0.55], seams: true });
  out.push(S(body, { tone: "mid", inner: k.fadedSvg(knurl, { tone: "lo" }) }));
  out.push(S(G.disc(8, 9.2, 4.2, F, P), { tone: "mid" }));
  out.push(D([at([SIDE + 9.2, -32, 26])], { size: 0.5, tone: "mid" }));
  return out.join("");
}

function lid() {
  const out = [S(k.slabOf(LID, PART, TOP - PART, P, 8, 1.2), { tone: "mid" })];
  out.push(L(k.planOutline(k.insetPlan({ ...LID, d: LID.d - 4 }, 6), TOP, P, 8), { tone: "faint" }));
  // label plate with three rule lines, two screws
  const plate = { x: -60, y: -50, w: 44, d: 14, r: 1.4 };
  out.push(S(k.slabOf(plate, TOP, 0.8, P, 3), { tone: "lo", crease: "none" }));
  out.push(L(k.planOutline(k.insetPlan(plate, 1.6), TOP + 0.8, P, 3), { tone: "faint" }));
  out.push(L([30, 22, 26].map((w, i) => k.lineOnTop([plate.x + 5, plate.y + 4 + i * 3], [plate.x + 5 + w, plate.y + 4 + i * 3], TOP + 0.8, P)).join(""), { tone: "lo", free: true }));
  out.push(D([at([plate.x + plate.w - 3.4, plate.y + 3.4, TOP + 0.8]), at([plate.x + plate.w - 3.4, plate.y + plate.d - 3.4, TOP + 0.8])], { size: 0.45 }));
  const screws = [[LID.x + 9, LID.y + 8], [LID.x + LID.w - 9, LID.y + 8]];
  out.push(L(screws.map(([x, y]) => k.ring(x, y, 2.2, TOP, P, 16)).join(""), { tone: "lo" }));
  out.push(D(screws.map(([x, y]) => at([x, y, TOP])), { size: 0.5 }));
  // lid release lever on the right side, knurled
  const lever = { x: LID.x + LID.w, y: 6, w: 2.2, d: 18, r: 1 };
  out.push(S(k.slabOf(lever, 52, 12, P, 3, 0.4), { tone: "mid" }));
  out.push(L(Array.from({ length: 7 }, (_, i) => k.segment([lever.x + lever.w, lever.y + 3 + i * 2, 52], [lever.x + lever.w, lever.y + 3 + i * 2, 64], P)).join(""), { tone: "lo" }));
  // parting line across the top where the lid meets the cutter cover, and the dark slot
  out.push(`<path class="pr-dark" d="${k.planOutline(VOID, TOP, P, 4)}"/>`);
  out.push(L(k.planOutline(VOID, TOP, P, 4), { tone: "lo" }));
  return out.join("");
}

function cutter() {
  const out = [S(k.slabOf(CUT, PART, TOP - PART, P, 6, 1.2), { tone: "mid" })];
  // a ruler strip across the paper width, ticks every 4, a major every 5th
  const strip = { x: -PAPER_W / 2 - 2, y: FRONT - 13, w: PAPER_W + 4, d: 6, r: 1 };
  out.push(S(k.slabOf(strip, TOP, 0.6, P, 3), { tone: "lo", crease: "none" }));
  const ticks = k.topTicks(-PAPER_W / 2, PAPER_W / 2, 4, 6, strip.y + 0.6, TOP + 0.6, [2, 3.6], P);
  out.push(L(ticks.minor, { tone: "lo" }), L(ticks.major, { tone: "mid" }));
  // the one engraved label, on the cutter cover front, and its two screws
  out.push(k.faceTextSvg(`${planeOf(FRONT)} translate(0 ${-(PART + 10.2)})`, "VIBE RECEIPTS", { size: 4.6, tone: "hi", anchor: "middle" }));
  out.push(onFace(FRONT, rect(-34, PART + 6, 34, PART + 18, 2), { tone: "faint" }));
  for (const x of [-66, 66]) {
    out.push(L(k.sideRing([x, FRONT, PART + 13], 1.6, "y", P, 16), { tone: "lo" }));
    out.push(D([at([x, FRONT, PART + 13])], { size: 0.5 }));
  }
  out.push(L(k.sideSeam(CUT, PART, P, 6), { tone: "lo" }));
  return out.join("");
}

function tearBar() {
  const out = [S(k.slabOf(BAR, TOP, BAR_H, P, 3, 0.3), { tone: "hi", lit: true })];
  // serrated top edge: a zigzag along the bar, from end to end
  const teeth = [];
  for (let x = BAR.x + 0.6, i = 0; x <= BAR.x + BAR.w - 0.6; x += 1.5, i++) teeth.push(at([x, BAR.y + 0.2, TOP + BAR_H + (i % 2 ? 0.9 : 0)]));
  out.push(L(k.pathOf(teeth), { tone: "mid" }));
  return out.join("");
}

const CSS = `
.iso-svg path,.iso-svg circle{vector-effect:none}
.pr-dark{fill:#030303;stroke:none}
.pr-shadow{fill:#000;opacity:.34;stroke:none}
.pr-well{fill:var(--anatomy-shade-0)}
.iso-face-text{letter-spacing:.3em;font-weight:700}
/* the kit's dark theme, a step lighter and cooler so it reads on the video's near-black ground */
.iso{--anatomy-paper:#16171d;--anatomy-face:#1d1e26;--anatomy-top:#22232c;
  --anatomy-shade-0:#121318;--anatomy-shade-1:#15161c;--anatomy-shade-2:#181920;--anatomy-shade-3:#1b1c24;
  --anatomy-lit-top:#2c2d38;--anatomy-lit-shade:#22232c;
  --anatomy-hi:#e4e5ee;--anatomy-mid:#8a8da0;--anatomy-lo:#55586a;--anatomy-faint:#363846;--anatomy-dot:#e4e5ee;
  --anatomy-halo:#000;--anatomy-halo-opacity:.95}
`;
const svgOf = (body, label) =>
  k.figureSvg({ width: WIDTH, height: HEIGHT, label, body: `<style>${CSS}</style>${body}`, standalone: "dark" })
    .replace("<svg ", `<svg width="${1080}" height="${1920}" `);

const back = svgOf([feet(), shell(), knob(), lid(), cutter()].join(""), "A countertop thermal receipt printer.");
const front = svgOf(tearBar(), "The printer's tear bar.");

// Where the paper is on screen: s across from the left end of the paper, t up the leaning sheet.
const V = (p) => at(p).map((v) => v * VS);
const sub = (a, b) => [a[0] - b[0], a[1] - b[1]];
const lean = (LEAN * Math.PI) / 180;
const origin = [-PAPER_W / 2, SLOT_Y, TOP];
const o = V(origin);
const u = sub(V([PAPER_W / 2, SLOT_Y, TOP]), o).map((v) => v / PAPER_W);
const v = sub(V([-PAPER_W / 2, SLOT_Y - Math.sin(lean), TOP + Math.cos(lean)]), o);
const geo = {
  paperW: PAPER_W, origin: o, u, v,
  y: sub(V([0, 1, 0]), V([0, 0, 0])), z: sub(V([0, 0, 1]), V([0, 0, 0])),   // screen px per world unit, to bend the paper
  leds: LEDS.map(({ x, z }) => V([x, FRONT - 1.4, z])), ledR: 0.9 * VS,
  bottom: V([0, FRONT, 0])[1],
};
writeFileSync(join(ROOT, "skills/vibe-receipts/scripts/printer.json"), JSON.stringify({ back, front, geo }));
console.log("printer.json:", ((back.length + front.length) / 1024).toFixed(0), "KB · paper u", u.map((x) => x.toFixed(3)), "v", v.map((x) => x.toFixed(3)));

if (process.argv.includes("--preview")) {
  const page = `<!doctype html><meta charset="utf-8"><body style="margin:0;background:#0b0c10">
<div style="position:relative;width:1080px;height:1920px">${back.replace("<svg ", '<svg style="position:absolute;inset:0" ')}
${front.replace("<svg ", '<svg style="position:absolute;inset:0" ')}</div>`;
  writeFileSync(join(HERE, "preview.html"), page);
  console.log("wrote tools/printer/preview.html");
}
