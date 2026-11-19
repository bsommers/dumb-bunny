/* ==========================================================================
   OPERATION DUMB BUNNY — GitHub Pages Interactive Engine (Zero Dependencies)
   - Interactive Before/After Facial Crack Comparison Slider + Mask Overlay
   - Zero-Dependency Binary STL 3D Inspector (WebGL + Canvas 2D Fallback)
   - Gallery Phase Filter + Accessible Native <dialog> Lightbox
   - Accessible ARIA Tabs & One-Click Clipboard Copy
   ========================================================================== */

(() => {
  "use strict";

  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ------------------------------------------------------------------------
     1. Interactive Before / After Facial Crack Comparison Slider
     ------------------------------------------------------------------------ */
  function initFaceCompare() {
    const stage = document.getElementById("compareStage");
    const afterWrap = document.getElementById("compareAfterWrap");
    const divider = document.getElementById("compareDivider");
    const range = document.getElementById("compareRange");
    const pctLabel = document.getElementById("comparePctLabel");
    const maskOverlay = document.getElementById("compareMaskOverlay");
    const toggleMaskBtn = document.getElementById("toggleMaskBtn");
    const resetSplitBtn = document.getElementById("resetSplitBtn");

    if (!stage || !afterWrap || !divider || !range) return;

    function setSplit(pct) {
      const clamped = Math.max(0, Math.min(100, Number(pct)));
      afterWrap.style.clipPath = `inset(0 0 0 ${clamped}%)`;
      divider.style.left = `${clamped}%`;
      range.value = String(Math.round(clamped));
      if (pctLabel) pctLabel.textContent = `${Math.round(clamped)}%`;
    }

    setSplit(50);

    range.addEventListener("input", () => setSplit(range.value));

    let dragging = false;
    function updateFromClientX(clientX) {
      const rect = stage.getBoundingClientRect();
      if (rect.width <= 0) return;
      const pct = ((clientX - rect.left) / rect.width) * 100;
      setSplit(pct);
    }

    stage.addEventListener("pointerdown", (e) => {
      dragging = true;
      stage.setPointerCapture(e.pointerId);
      updateFromClientX(e.clientX);
    });

    stage.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      updateFromClientX(e.clientX);
    });

    const endDrag = () => { dragging = false; };
    stage.addEventListener("pointerup", endDrag);
    stage.addEventListener("pointercancel", endDrag);

    if (toggleMaskBtn && maskOverlay) {
      toggleMaskBtn.addEventListener("click", () => {
        const on = !maskOverlay.classList.contains("visible");
        maskOverlay.classList.toggle("visible", on);
        toggleMaskBtn.setAttribute("aria-pressed", String(on));
        toggleMaskBtn.classList.toggle("active", on);
        toggleMaskBtn.textContent = on
          ? "🎯 Diagnostic Crack Mask: ON"
          : "🎯 Diagnostic Crack Mask: OFF";
      });
    }

    if (resetSplitBtn) {
      resetSplitBtn.addEventListener("click", () => setSplit(50));
    }
  }

  /* ------------------------------------------------------------------------
     2. Gallery Filter Pills & Accessible Native <dialog> Lightbox
     ------------------------------------------------------------------------ */
  function initGalleryAndLightbox() {
    const dialog = document.getElementById("lightboxDialog");
    const lbImg = document.getElementById("lightboxImg");
    const lbTitle = document.getElementById("lightboxTitle");
    const lbCaption = document.getElementById("lightboxCaption");
    const lbCounter = document.getElementById("lightboxCounter");
    const prevBtn = document.getElementById("lightboxPrevBtn");
    const nextBtn = document.getElementById("lightboxNextBtn");
    const closeBtn = document.getElementById("lightboxCloseBtn");

    const filterBtns = Array.from(document.querySelectorAll("[data-gallery-filter]"));
    const cards = Array.from(document.querySelectorAll("#galleryGrid .gallery-card"));
    const hudBtn = document.getElementById("openHudLightboxBtn");

    let activeItems = [];
    let currentIndex = 0;
    let lastTrigger = null;

    function getVisibleGalleryCards() {
      return cards.filter((c) => !c.hidden);
    }

    filterBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        const filter = btn.dataset.galleryFilter;
        filterBtns.forEach((b) => {
          const active = b === btn;
          b.classList.toggle("active", active);
          b.setAttribute("aria-pressed", String(active));
        });
        cards.forEach((card) => {
          card.hidden = filter !== "all" && card.dataset.category !== filter;
        });
      });
    });

    function renderLightboxItem(index) {
      if (!activeItems.length || !lbImg) return;
      currentIndex = (index + activeItems.length) % activeItems.length;
      const item = activeItems[currentIndex];
      lbImg.src = item.src;
      lbImg.alt = item.title;
      if (lbTitle) lbTitle.textContent = item.title;
      if (lbCaption) lbCaption.textContent = item.caption;
      if (lbCounter) {
        lbCounter.textContent = activeItems.length > 1
          ? `${currentIndex + 1} / ${activeItems.length}`
          : "FULL-RES HUD CAPTURE";
      }
      const multi = activeItems.length > 1;
      if (prevBtn) prevBtn.hidden = !multi;
      if (nextBtn) nextBtn.hidden = !multi;
    }

    function openLightbox(items, idx, trigger) {
      if (!dialog) return;
      activeItems = items;
      lastTrigger = trigger || null;
      renderLightboxItem(idx);
      if (typeof dialog.showModal === "function") {
        dialog.showModal();
      } else {
        dialog.setAttribute("open", "");
      }
    }

    function closeLightbox() {
      if (!dialog) return;
      if (typeof dialog.close === "function") {
        dialog.close();
      } else {
        dialog.removeAttribute("open");
      }
      if (lastTrigger) lastTrigger.focus();
    }

    cards.forEach((card) => {
      card.addEventListener("click", () => {
        const visible = getVisibleGalleryCards();
        const items = visible.map((c) => ({
          src: c.dataset.full,
          title: c.dataset.title || "Render",
          caption: c.dataset.caption || "",
        }));
        const idx = visible.indexOf(card);
        openLightbox(items, Math.max(0, idx), card);
      });
    });

    if (hudBtn) {
      hudBtn.addEventListener("click", () => {
        openLightbox(
          [{
            src: hudBtn.dataset.full,
            title: hudBtn.dataset.title || "Live Mission Control HUD",
            caption: hudBtn.dataset.caption || "",
          }],
          0,
          hudBtn
        );
      });
    }

    if (prevBtn) prevBtn.addEventListener("click", () => renderLightboxItem(currentIndex - 1));
    if (nextBtn) nextBtn.addEventListener("click", () => renderLightboxItem(currentIndex + 1));
    if (closeBtn) closeBtn.addEventListener("click", closeLightbox);

    if (dialog) {
      // Fallback light-dismiss on backdrop click for browsers without closedby="any"
      dialog.addEventListener("click", (e) => {
        const rect = dialog.getBoundingClientRect();
        const inside =
          e.clientX >= rect.left &&
          e.clientX <= rect.right &&
          e.clientY >= rect.top &&
          e.clientY <= rect.bottom;
        if (!inside) closeLightbox();
      });

      dialog.addEventListener("keydown", (e) => {
        if (activeItems.length <= 1) return;
        if (e.key === "ArrowLeft") {
          e.preventDefault();
          renderLightboxItem(currentIndex - 1);
        } else if (e.key === "ArrowRight") {
          e.preventDefault();
          renderLightboxItem(currentIndex + 1);
        }
      });
    }
  }

  /* ------------------------------------------------------------------------
     3. Accessible ARIA Tabs & Clipboard Copy Buttons
     ------------------------------------------------------------------------ */
  function initTabsAndCopy() {
    const tabs = Array.from(document.querySelectorAll('[role="tab"]'));
    const panels = Array.from(document.querySelectorAll('[role="tabpanel"]'));

    function activateTab(tab, focusTab = false) {
      if (!tab) return;
      tabs.forEach((t) => {
        const sel = t === tab;
        t.setAttribute("aria-selected", String(sel));
        t.tabIndex = sel ? 0 : -1;
      });
      panels.forEach((p) => {
        p.hidden = p.id !== tab.getAttribute("aria-controls");
      });
      if (focusTab) tab.focus();
    }

    tabs.forEach((tab, idx) => {
      tab.addEventListener("click", () => activateTab(tab, false));
      tab.addEventListener("keydown", (e) => {
        if (e.key === "ArrowRight") {
          e.preventDefault();
          activateTab(tabs[(idx + 1) % tabs.length], true);
        } else if (e.key === "ArrowLeft") {
          e.preventDefault();
          activateTab(tabs[(idx - 1 + tabs.length) % tabs.length], true);
        }
      });
    });

    // Allow hero CTA buttons to open a specific tab cleanly
    document.querySelectorAll("[data-open-tab]").forEach((el) => {
      el.addEventListener("click", () => {
        const targetTab = document.getElementById(el.dataset.openTab);
        if (targetTab) activateTab(targetTab, false);
      });
    });

    // One-click clipboard copy buttons
    document.querySelectorAll("[data-copy-target]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const src = document.getElementById(btn.dataset.copyTarget);
        if (!src) return;
        const orig = btn.textContent;
        try {
          await navigator.clipboard.writeText(src.textContent.trim());
          btn.textContent = "Copied ✓";
        } catch {
          btn.textContent = "Select & Copy";
        }
        window.setTimeout(() => { btn.textContent = orig; }, 1800);
      });
    });
  }

  /* ------------------------------------------------------------------------
     4. Zero-Dependency Binary STL 3D Viewer (WebGL + Canvas 2D Fallback)
     ------------------------------------------------------------------------ */
  const STL_MODELS = {
    full: {
      url: "assets/site/dumb_bunny_web_preview.stl",
      label: "Full Figurine · 139.6 × 95.6 × 184.0 mm · 784.6 cm³ (358k print / 24.5k preview)",
      defaultYaw: -0.44,
      defaultPitch: 0.16,
      defaultZoom: 2.55,
      baseColor: [0.83, 0.57, 0.68], // Dusty-rose velour tint
    },
    mask: {
      url: "assets/site/face_mask_web_preview.stl",
      label: "Repaired Face Mask · 58.6 × 26.8 × 56.5 mm · 0.0029 mm X-RMS (124k print / 14.1k preview)",
      defaultYaw: -0.32,
      defaultPitch: 0.08,
      defaultZoom: 2.25,
      baseColor: [0.78, 0.64, 0.48], // Vintage peach rubber vinyl tint
    },
  };

  function parseBinarySTL(buffer) {
    const view = new DataView(buffer);
    if (buffer.byteLength < 84) throw new Error("STL buffer too small");
    const triCount = view.getUint32(80, true);
    const expected = 84 + triCount * 50;
    if (expected > buffer.byteLength) {
      throw new Error(`Unexpected STL byte length (${buffer.byteLength} vs ${expected})`);
    }

    const positions = new Float32Array(triCount * 9);
    const normals = new Float32Array(triCount * 9);
    let minX = Infinity, minY = Infinity, minZ = Infinity;
    let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;

    let offset = 84;
    for (let i = 0; i < triCount; i++) {
      // Read 3 vertices in Blender Z-up (front = -Y), convert to right-handed Y-up (front = +Z):
      // (x, y, z) -> (x, z, -y)
      const x0 = view.getFloat32(offset + 12, true);
      const y0 = view.getFloat32(offset + 16, true);
      const z0 = view.getFloat32(offset + 20, true);

      const x1 = view.getFloat32(offset + 24, true);
      const y1 = view.getFloat32(offset + 28, true);
      const z1 = view.getFloat32(offset + 32, true);

      const x2 = view.getFloat32(offset + 36, true);
      const y2 = view.getFloat32(offset + 40, true);
      const z2 = view.getFloat32(offset + 44, true);
      offset += 50;

      const ax = x0, ay = z0, az = -y0;
      const bx = x1, by = z1, bz = -y1;
      const cx = x2, cy = z2, cz = -y2;

      const e1x = bx - ax, e1y = by - ay, e1z = bz - az;
      const e2x = cx - ax, e2y = cy - ay, e2z = cz - az;
      let nx = e1y * e2z - e1z * e2y;
      let ny = e1z * e2x - e1x * e2z;
      let nz = e1x * e2y - e1y * e2x;
      const len = Math.hypot(nx, ny, nz) || 1;
      nx /= len; ny /= len; nz /= len;

      const p = i * 9;
      positions[p] = ax; positions[p + 1] = ay; positions[p + 2] = az;
      positions[p + 3] = bx; positions[p + 4] = by; positions[p + 5] = bz;
      positions[p + 6] = cx; positions[p + 7] = cy; positions[p + 8] = cz;

      normals[p] = nx; normals[p + 1] = ny; normals[p + 2] = nz;
      normals[p + 3] = nx; normals[p + 4] = ny; normals[p + 5] = nz;
      normals[p + 6] = nx; normals[p + 7] = ny; normals[p + 8] = nz;

      if (ax < minX) minX = ax; if (ax > maxX) maxX = ax;
      if (bx < minX) minX = bx; if (bx > maxX) maxX = bx;
      if (cx < minX) minX = cx; if (cx > maxX) maxX = cx;

      if (ay < minY) minY = ay; if (ay > maxY) maxY = ay;
      if (by < minY) minY = by; if (by > maxY) maxY = by;
      if (cy < minY) minY = cy; if (cy > maxY) maxY = cy;

      if (az < minZ) minZ = az; if (az > maxZ) maxZ = az;
      if (bz < minZ) minZ = bz; if (bz > maxZ) maxZ = bz;
      if (cz < minZ) minZ = cz; if (cz > maxZ) maxZ = cz;
    }

    const midX = 0.5 * (minX + maxX);
    const midY = 0.5 * (minY + maxY);
    const midZ = 0.5 * (minZ + maxZ);
    const extent = Math.max(maxX - minX, maxY - minY, maxZ - minZ) || 1;
    const scale = 1.75 / extent;

    for (let i = 0; i < positions.length; i += 3) {
      positions[i] = (positions[i] - midX) * scale;
      positions[i + 1] = (positions[i + 1] - midY) * scale;
      positions[i + 2] = (positions[i + 2] - midZ) * scale;
    }

    return { triCount, positions, normals };
  }

  function buildWireframeLines(positions) {
    // Subsample clean edges (every triangle's 3 edges) for WebGL LINES wireframe overlay
    const triCount = positions.length / 9;
    const lines = new Float32Array(triCount * 18);
    let dst = 0;
    for (let i = 0; i < positions.length; i += 9) {
      // v0-v1
      lines[dst++] = positions[i];     lines[dst++] = positions[i + 1]; lines[dst++] = positions[i + 2];
      lines[dst++] = positions[i + 3]; lines[dst++] = positions[i + 4]; lines[dst++] = positions[i + 5];
      // v1-v2
      lines[dst++] = positions[i + 3]; lines[dst++] = positions[i + 4]; lines[dst++] = positions[i + 5];
      lines[dst++] = positions[i + 6]; lines[dst++] = positions[i + 7]; lines[dst++] = positions[i + 8];
      // v2-v0
      lines[dst++] = positions[i + 6]; lines[dst++] = positions[i + 7]; lines[dst++] = positions[i + 8];
      lines[dst++] = positions[i];     lines[dst++] = positions[i + 1]; lines[dst++] = positions[i + 2];
    }
    return lines;
  }

  function createMat4Perspective(fovRad, aspect, near, far) {
    const f = 1.0 / Math.tan(fovRad / 2);
    const nf = 1 / (near - far);
    return new Float32Array([
      f / aspect, 0, 0, 0,
      0, f, 0, 0,
      0, 0, (far + near) * nf, -1,
      0, 0, 2 * far * near * nf, 0,
    ]);
  }

  function createModelView(yaw, pitch, dist) {
    const cy = Math.cos(yaw), sy = Math.sin(yaw);
    const cp = Math.cos(pitch), sp = Math.sin(pitch);
    // R = Rx(pitch) * Ry(yaw), translated by (0, 0, -dist)
    return new Float32Array([
      cy,        sp * sy,  -cp * sy, 0,
      0,         cp,       sp,       0,
      sy,        -sp * cy, cp * cy,  0,
      0,         0,        -dist,    1,
    ]);
  }

  function initSTLViewer() {
    const canvas = document.getElementById("stlCanvas");
    const stage = document.getElementById("viewerStage");
    const statusEl = document.getElementById("viewerStatus");
    const statsPill = document.getElementById("viewerStatsPill");
    const toggleOrbitBtn = document.getElementById("toggleOrbitBtn");
    const resetCamBtn = document.getElementById("resetCamBtn");
    const modelBtns = Array.from(document.querySelectorAll("[data-stl-model]"));
    const modeBtns = Array.from(document.querySelectorAll("[data-render-mode]"));

    if (!canvas || !stage) return;

    const state = {
      modelKey: "full",
      renderMode: "shaded", // "shaded" | "tron" | "wire"
      autoOrbit: !prefersReducedMotion,
      yaw: STL_MODELS.full.defaultYaw,
      pitch: STL_MODELS.full.defaultPitch,
      zoom: STL_MODELS.full.defaultZoom,
      mesh: null,
      cache: {},
      dirty: true,
    };

    if (toggleOrbitBtn) {
      toggleOrbitBtn.setAttribute("aria-pressed", String(state.autoOrbit));
      toggleOrbitBtn.classList.toggle("active", state.autoOrbit);
      toggleOrbitBtn.textContent = state.autoOrbit ? "Auto-Orbit: ON" : "Auto-Orbit: OFF";
    }

    // Attempt WebGL first; gracefully fall back to crisp Canvas 2D painter's engine
    let gl = null;
    try {
      gl = canvas.getContext("webgl", { antialias: true, alpha: true, preserveDrawingBuffer: true });
    } catch {
      gl = null;
    }

    let glRes = null;
    let ctx2d = null;

    if (gl) {
      const vsSource = `
        attribute vec3 aPos;
        attribute vec3 aNorm;
        uniform mat4 uProj;
        uniform mat4 uMV;
        varying vec3 vNormal;
        varying vec3 vViewPos;
        varying vec3 vLocalPos;
        void main() {
          vec4 mvPos = uMV * vec4(aPos, 1.0);
          vViewPos = -mvPos.xyz;
          vNormal = normalize(mat3(uMV) * aNorm);
          vLocalPos = aPos;
          gl_Position = uProj * mvPos;
        }
      `;
      const fsSource = `
        precision mediump float;
        varying vec3 vNormal;
        varying vec3 vViewPos;
        varying vec3 vLocalPos;
        uniform vec3 uBaseColor;
        uniform int uMode; // 0 = shaded, 1 = tron, 2 = wire
        void main() {
          vec3 N = normalize(vNormal);
          if (!gl_FrontFacing) N = -N;
          vec3 V = normalize(vViewPos);
          vec3 L1 = normalize(vec3(0.55, 0.72, 0.85));
          vec3 L2 = normalize(vec3(-0.75, 0.25, 0.45));
          float diff1 = max(dot(N, L1), 0.0);
          float diff2 = max(dot(N, L2), 0.0);
          vec3 H = normalize(L1 + V);
          float spec = pow(max(dot(N, H), 0.0), 28.0);
          float fresnel = pow(1.0 - max(dot(N, V), 0.0), 2.4);

          if (uMode == 2) {
            gl_FragColor = vec4(0.0, 0.90, 1.0, 0.78);
            return;
          }

          if (uMode == 1) {
            // TRON Neon Grid Shader: dark obsidian core + glowing cyan grid bands + neon rim
            float gx = abs(fract(vLocalPos.x * 12.0 - 0.5) - 0.5) / 0.06;
            float gy = abs(fract(vLocalPos.y * 12.0 - 0.5) - 0.5) / 0.06;
            float gridLine = 1.0 - clamp(min(gx, gy), 0.0, 1.0);
            vec3 core = vec3(0.03, 0.07, 0.16) + vec3(0.05, 0.18, 0.30) * diff1;
            vec3 neon = vec3(0.0, 0.90, 1.0) * (fresnel * 1.15 + gridLine * 0.52);
            vec3 pinkRim = vec3(0.95, 0.55, 0.75) * pow(diff2, 2.0) * 0.25;
            gl_FragColor = vec4(core + neon + pinkRim, 1.0);
            return;
          }

          // Bionic Studio 3-point shaded mode
          vec3 ambient = uBaseColor * 0.24 + vec3(0.03, 0.06, 0.12);
          vec3 key = uBaseColor * diff1 * 0.78 + vec3(0.98, 0.95, 0.92) * spec * 0.22;
          vec3 fill = vec3(0.45, 0.78, 0.98) * diff2 * 0.24;
          vec3 rim = vec3(0.15, 0.85, 1.0) * fresnel * 0.48;
          gl_FragColor = vec4(ambient + key + fill + rim, 1.0);
        }
      `;

      function compile(type, src) {
        const sh = gl.createShader(type);
        gl.shaderSource(sh, src);
        gl.compileShader(sh);
        if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
          throw new Error(gl.getShaderInfoLog(sh) || "Shader compile failed");
        }
        return sh;
      }

      try {
        const prog = gl.createProgram();
        gl.attachShader(prog, compile(gl.VERTEX_SHADER, vsSource));
        gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, fsSource));
        gl.linkProgram(prog);
        if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
          throw new Error("WebGL link error");
        }
        glRes = {
          prog,
          aPos: gl.getAttribLocation(prog, "aPos"),
          aNorm: gl.getAttribLocation(prog, "aNorm"),
          uProj: gl.getUniformLocation(prog, "uProj"),
          uMV: gl.getUniformLocation(prog, "uMV"),
          uBaseColor: gl.getUniformLocation(prog, "uBaseColor"),
          uMode: gl.getUniformLocation(prog, "uMode"),
          posBuf: gl.createBuffer(),
          normBuf: gl.createBuffer(),
          wireBuf: gl.createBuffer(),
          vertCount: 0,
          wireVertCount: 0,
        };
      } catch {
        gl = null;
      }
    }

    if (!gl) {
      ctx2d = canvas.getContext("2d");
    }

    function uploadMeshToGL(mesh) {
      if (!gl || !glRes) return;
      gl.bindBuffer(gl.ARRAY_BUFFER, glRes.posBuf);
      gl.bufferData(gl.ARRAY_BUFFER, mesh.positions, gl.STATIC_DRAW);
      gl.bindBuffer(gl.ARRAY_BUFFER, glRes.normBuf);
      gl.bufferData(gl.ARRAY_BUFFER, mesh.normals, gl.STATIC_DRAW);
      if (!mesh.wireLines) mesh.wireLines = buildWireframeLines(mesh.positions);
      gl.bindBuffer(gl.ARRAY_BUFFER, glRes.wireBuf);
      gl.bufferData(gl.ARRAY_BUFFER, mesh.wireLines, gl.STATIC_DRAW);
      glRes.vertCount = mesh.triCount * 3;
      glRes.wireVertCount = mesh.wireLines.length / 3;
    }

    function resizeCanvas() {
      const rect = stage.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = Math.max(1, Math.floor(rect.width * dpr));
      const h = Math.max(1, Math.floor(rect.height * dpr));
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
        state.dirty = true;
      }
    }

    function renderWebGL() {
      if (!gl || !glRes || !state.mesh) return;
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.clearColor(0.02, 0.04, 0.09, 0.0);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.enable(gl.DEPTH_TEST);

      gl.useProgram(glRes.prog);
      const aspect = canvas.width / Math.max(1, canvas.height);
      const proj = createMat4Perspective(Math.PI / 4, aspect, 0.05, 50.0);
      const mv = createModelView(state.yaw, state.pitch, state.zoom);

      gl.uniformMatrix4fv(glRes.uProj, false, proj);
      gl.uniformMatrix4fv(glRes.uMV, false, mv);
      gl.uniform3fv(glRes.uBaseColor, STL_MODELS[state.modelKey].baseColor);

      if (state.renderMode === "wire") {
        // Dark faint core pass + crisp neon cyan wireframe lines
        gl.enable(gl.POLYGON_OFFSET_FILL);
        gl.polygonOffset(1.0, 1.0);
        gl.bindBuffer(gl.ARRAY_BUFFER, glRes.posBuf);
        gl.enableVertexAttribArray(glRes.aPos);
        gl.vertexAttribPointer(glRes.aPos, 3, gl.FLOAT, false, 0, 0);
        gl.bindBuffer(gl.ARRAY_BUFFER, glRes.normBuf);
        gl.enableVertexAttribArray(glRes.aNorm);
        gl.vertexAttribPointer(glRes.aNorm, 3, gl.FLOAT, false, 0, 0);
        gl.uniform1i(glRes.uMode, 1);
        gl.drawArrays(gl.TRIANGLES, 0, glRes.vertCount);
        gl.disable(gl.POLYGON_OFFSET_FILL);

        gl.bindBuffer(gl.ARRAY_BUFFER, glRes.wireBuf);
        gl.enableVertexAttribArray(glRes.aPos);
        gl.vertexAttribPointer(glRes.aPos, 3, gl.FLOAT, false, 0, 0);
        gl.disableVertexAttribArray(glRes.aNorm);
        gl.uniform1i(glRes.uMode, 2);
        gl.drawArrays(gl.LINES, 0, glRes.wireVertCount);
      } else {
        gl.bindBuffer(gl.ARRAY_BUFFER, glRes.posBuf);
        gl.enableVertexAttribArray(glRes.aPos);
        gl.vertexAttribPointer(glRes.aPos, 3, gl.FLOAT, false, 0, 0);
        gl.bindBuffer(gl.ARRAY_BUFFER, glRes.normBuf);
        gl.enableVertexAttribArray(glRes.aNorm);
        gl.vertexAttribPointer(glRes.aNorm, 3, gl.FLOAT, false, 0, 0);
        gl.uniform1i(glRes.uMode, state.renderMode === "tron" ? 1 : 0);
        gl.drawArrays(gl.TRIANGLES, 0, glRes.vertCount);
      }
    }

    function renderCanvas2DFallback() {
      if (!ctx2d || !state.mesh) return;
      const w = canvas.width;
      const h = canvas.height;
      ctx2d.clearRect(0, 0, w, h);

      // Subtle glowing pedestal ellipse
      ctx2d.save();
      ctx2d.strokeStyle = "rgba(0, 229, 255, 0.35)";
      ctx2d.lineWidth = 2;
      ctx2d.beginPath();
      ctx2d.ellipse(w * 0.5, h * 0.82, Math.min(w, h) * 0.28, Math.min(w, h) * 0.065, 0, 0, Math.PI * 2);
      ctx2d.stroke();
      ctx2d.restore();

      const pos = state.mesh.positions;
      const nrm = state.mesh.normals;
      const cy = Math.cos(state.yaw), sy = Math.sin(state.yaw);
      const cp = Math.cos(state.pitch), sp = Math.sin(state.pitch);
      const fov = Math.min(w, h) * 0.92;
      const dist = state.zoom;
      const cx = w * 0.5;
      const cyScr = h * 0.5;

      const stride = state.mesh.triCount > 16000 ? 2 : 1;
      const visible = [];
      for (let t = 0; t < state.mesh.triCount; t += stride) {
        const i = t * 9;
        // Rotate normal
        const nx0 = nrm[i], ny0 = nrm[i + 1], nz0 = nrm[i + 2];
        const rxn = nx0 * cy + nz0 * sy;
        const rzn = -nx0 * sy + nz0 * cy;
        const ryn = ny0 * cp - rzn * sp;
        const rzn2 = ny0 * sp + rzn * cp;
        if (rzn2 <= -0.05) continue; // backface cull

        const sx = [], syArr = [];
        let zSum = 0;
        for (let k = 0; k < 3; k++) {
          const px = pos[i + k * 3], py = pos[i + k * 3 + 1], pz = pos[i + k * 3 + 2];
          const x1 = px * cy + pz * sy;
          const z1 = -px * sy + pz * cy;
          const y2 = py * cp - z1 * sp;
          const z2 = py * sp + z1 * cp;
          const denom = Math.max(0.2, dist - z2);
          sx.push(cx + (x1 * fov) / denom);
          syArr.push(cyScr - (y2 * fov) / denom);
          zSum += z2;
        }
        const light = Math.max(0.15, rxn * 0.45 + ryn * 0.65 + rzn2 * 0.62);
        const rim = Math.pow(1 - Math.max(0, rzn2), 2.2);
        visible.push({ z: zSum, sx, sy: syArr, light, rim });
      }

      visible.sort((a, b) => a.z - b.z);
      const bc = STL_MODELS[state.modelKey].baseColor;

      for (let i = 0; i < visible.length; i++) {
        const f = visible[i];
        ctx2d.beginPath();
        ctx2d.moveTo(f.sx[0], f.sy[0]);
        ctx2d.lineTo(f.sx[1], f.sy[1]);
        ctx2d.lineTo(f.sx[2], f.sy[2]);
        ctx2d.closePath();

        if (state.renderMode === "wire") {
          ctx2d.strokeStyle = `rgba(0, 229, 255, ${(0.25 + f.light * 0.65).toFixed(2)})`;
          ctx2d.lineWidth = 0.8;
          ctx2d.stroke();
        } else if (state.renderMode === "tron") {
          const r = Math.min(255, Math.round(12 + f.rim * 50));
          const g = Math.min(255, Math.round(45 + f.light * 70 + f.rim * 180));
          const b = Math.min(255, Math.round(85 + f.light * 90 + f.rim * 170));
          ctx2d.fillStyle = `rgb(${r},${g},${b})`;
          ctx2d.fill();
          ctx2d.strokeStyle = "rgba(0, 229, 255, 0.22)";
          ctx2d.lineWidth = 0.5;
          ctx2d.stroke();
        } else {
          const r = Math.min(255, Math.round(bc[0] * 255 * f.light + f.rim * 35));
          const g = Math.min(255, Math.round(bc[1] * 255 * f.light + f.rim * 165));
          const b = Math.min(255, Math.round(bc[2] * 255 * f.light + f.rim * 210));
          ctx2d.fillStyle = `rgb(${r},${g},${b})`;
          ctx2d.fill();
        }
      }
    }

    async function loadModel(key) {
      const cfg = STL_MODELS[key];
      if (!cfg) return;
      state.modelKey = key;
      state.yaw = cfg.defaultYaw;
      state.pitch = cfg.defaultPitch;
      state.zoom = cfg.defaultZoom;

      if (statusEl) statusEl.textContent = `Loading ${cfg.url.split("/").pop()}…`;

      try {
        let mesh = state.cache[key];
        if (!mesh) {
          const res = await fetch(cfg.url);
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          const buf = await res.arrayBuffer();
          mesh = parseBinarySTL(buf);
          state.cache[key] = mesh;
        }
        state.mesh = mesh;
        if (gl) uploadMeshToGL(mesh);
        state.dirty = true;

        const engineTag = gl ? "WebGL Hardware Phong" : "Canvas 2D Engine";
        if (statusEl) statusEl.textContent = `LIVE 3D // ${engineTag} · ${mesh.triCount.toLocaleString()} Tris`;
        if (statsPill) statsPill.textContent = cfg.label;
      } catch (err) {
        if (statusEl) statusEl.textContent = `3D Load Error: ${err.message}`;
      }
    }

    // Pointer orbit & wheel zoom controls
    let dragging = false;
    let lastX = 0, lastY = 0;

    stage.addEventListener("pointerdown", (e) => {
      dragging = true;
      lastX = e.clientX;
      lastY = e.clientY;
      stage.setPointerCapture(e.pointerId);
    });

    stage.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      const dx = e.clientX - lastX;
      const dy = e.clientY - lastY;
      lastX = e.clientX;
      lastY = e.clientY;
      state.yaw += dx * 0.009;
      state.pitch = Math.max(-1.35, Math.min(1.35, state.pitch + dy * 0.008));
      state.dirty = true;
    });

    const stopDrag = () => { dragging = false; };
    stage.addEventListener("pointerup", stopDrag);
    stage.addEventListener("pointercancel", stopDrag);

    stage.addEventListener("wheel", (e) => {
      e.preventDefault();
      state.zoom = Math.max(1.25, Math.min(5.2, state.zoom + Math.sign(e.deltaY) * 0.18));
      state.dirty = true;
    }, { passive: false });

    modelBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        const key = btn.dataset.stlModel;
        modelBtns.forEach((b) => {
          const active = b === btn;
          b.classList.toggle("active", active);
          b.setAttribute("aria-pressed", String(active));
        });
        loadModel(key);
      });
    });

    modeBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        state.renderMode = btn.dataset.renderMode;
        modeBtns.forEach((b) => {
          const active = b === btn;
          b.classList.toggle("active", active);
          b.setAttribute("aria-pressed", String(active));
        });
        state.dirty = true;
      });
    });

    if (toggleOrbitBtn) {
      toggleOrbitBtn.addEventListener("click", () => {
        state.autoOrbit = !state.autoOrbit;
        toggleOrbitBtn.classList.toggle("active", state.autoOrbit);
        toggleOrbitBtn.setAttribute("aria-pressed", String(state.autoOrbit));
        toggleOrbitBtn.textContent = state.autoOrbit ? "Auto-Orbit: ON" : "Auto-Orbit: OFF";
      });
    }

    if (resetCamBtn) {
      resetCamBtn.addEventListener("click", () => {
        const cfg = STL_MODELS[state.modelKey];
        state.yaw = cfg.defaultYaw;
        state.pitch = cfg.defaultPitch;
        state.zoom = cfg.defaultZoom;
        state.dirty = true;
      });
    }

    window.addEventListener("resize", resizeCanvas);
    resizeCanvas();
    loadModel("full");

    function tick() {
      resizeCanvas();
      if (state.mesh && (state.dirty || (state.autoOrbit && !dragging))) {
        if (state.autoOrbit && !dragging) {
          state.yaw += 0.0065;
        }
        if (gl) {
          renderWebGL();
        } else {
          renderCanvas2DFallback();
        }
        state.dirty = false;
      }
      window.requestAnimationFrame(tick);
    }

    window.requestAnimationFrame(tick);
  }

  /* ------------------------------------------------------------------------
     Bootstrap All Interactive Modules
     ------------------------------------------------------------------------ */
  document.addEventListener("DOMContentLoaded", () => {
    initFaceCompare();
    initGalleryAndLightbox();
    initTabsAndCopy();
    initSTLViewer();
  });
})();
