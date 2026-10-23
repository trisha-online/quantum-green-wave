# Quantum Green Wave — implementation plan

## Scope
A single-page, static explainer for the hackathon project "Quantum Green Wave". The requested deliverable is a self-contained `index.html` with inline CSS and vanilla JavaScript; no frameworks, backend, package installation, or build step.

## Design
- **Design Movement:** quantum observatory / dark scientific editorial — 0.06
- **Alternative:** restrained cybernetic dashboard — 0.04
- **Alternative:** kinetic research poster — 0.02
- **Chosen movement:** quantum observatory / dark scientific editorial.
- **Core principles:** evidence before spectacle; cyan signal against midnight space; concise scientific notation; motion only where it explains a process.
- **Color philosophy:** #0A0D18 and #0F1426 create a quiet instrument-panel field, #6CCBFF marks quantum structure and measurable progress, #FF9150 marks the ambulance signal, and #E9EDF5/#A9B3C7 keep dense content legible.
- **Layout paradigm:** a vertical research narrative with asymmetric hero composition, narrow reading measure for claims, and full-bleed data bands for the interactive grid and comparisons.
- **Signature elements:** a rotating SVG Bloch sphere, fine interference lines/particles, and ket notation used as labels rather than decoration.
- **Interaction philosophy:** clicks reveal the binary phase state; scroll reveals expose evidence progressively; reduced-motion users receive the same information without animation.
- **Animation:** slow orbital Bloch motion, subtle starfield drift, one-time bar reveals, and a self-running four-step loop with a calm cadence.
- **Typography:** Space Grotesk for headings, IBM Plex Sans for body copy, JetBrains Mono for equations, metrics, labels, and table values.
- **Brand essence:** quantum optimization explained honestly for people building better city systems; precise, candid, kinetic.
- **Brand voice:** direct, technical, and transparent. Example lines: “Every light a qubit.” and “Not quantum advantage. A tested hybrid loop.”
- **Wordmark & logo:** a split-wave mark made from two cyan arcs and one orange pulse, paired with the title in Space Grotesk.
- **Signature brand color:** quantum cyan #6CCBFF.

## Structure
- `index.html`: all markup, styling, SVG, canvas, and behavior.
- `manus-routes.json`: declares the single `/` route for Preview.
- `plan.md` and `TODO.md`: project records; not part of the requested final deliverable.

## Runtime
Static files are served directly from the project root on port 3000 by a dependency-free Node HTTP command. No build step is needed.
