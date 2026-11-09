// NCS visualizer renderer, ported from Konsl/spicetify-visualizer (MIT),
// src/components/renderer/NCSVisualizer.tsx. The drawing passes are unchanged;
// the difference is the input: the original reads Spotify's precomputed
// loudness curve for the track, this version is fed live levels from Python.

(() => {
	"use strict";

	const DEFAULT_COLOR = [0x53 / 255, 0x53 / 255, 0x53 / 255];
	const AMPLITUDE_SMOOTHING = 0.06; // seconds, time constant of the level smoothing
	const SIGNAL_TIMEOUT = 0.15; // seconds without a level update before treating it as silence
	let HIDE_AFTER_SILENCE = 2.0; // seconds of silence before the overlay fades out (settings)
	let FADE_WHEN_SILENT = true;

	const canvas = document.getElementById("canvas");
	const gl = canvas.getContext("webgl2", { premultipliedAlpha: true, alpha: true, antialias: false });

	const input = {
		level: 0, // latest level from Python, 0..1
		levelTime: 0, // performance.now() / 1000 when it arrived
		color: DEFAULT_COLOR,
		color2: DEFAULT_COLOR,
		gradientStyle: 0, // 0 solid, 1 vertical, 2 diagonal, 3 radial
		seed: 0
	};

	const anim = {
		amplitude: 0,
		time: 0, // seconds since the track started (drives the original's 0.5 * progress term)
		integral: 0, // accumulated amplitude over time
		lastFrame: 0,
		silentFor: HIDE_AFTER_SILENCE,
		running: false,
		editing: false // while moving/resizing, stay visible even in silence
	};

	// ---- API called from QML ----

	window.pushLevel = level => {
		input.level = Math.min(Math.max(level, 0), 1);
		input.levelTime = performance.now() / 1000;
		if (input.level > 0.01) {
			anim.silentFor = 0;
			setVisible(true);
			start();
		}
	};

	window.setTrack = seed => {
		input.seed = seed | 0;
		anim.time = 0;
		anim.integral = 0;
	};

	window.setColors = (r, g, b, r2, g2, b2, gradientStyle) => {
		input.color = [r, g, b];
		input.color2 = [r2, g2, b2];
		input.gradientStyle = gradientStyle | 0;
	};

	window.setFade = (enabled, delay) => {
		FADE_WHEN_SILENT = !!enabled;
		HIDE_AFTER_SILENCE = Math.max(+delay || 0, 0.1);
		if (!FADE_WHEN_SILENT) {
			setVisible(true);
			start();
		}
	};

	window.setEditing = editing => {
		anim.editing = !!editing;
		if (anim.editing) {
			setVisible(true);
			start();
		}
	};

	// ---- visibility: fade out when Spotify is silent, stop rendering once hidden ----

	function setVisible(visible) {
		document.body.classList.toggle("hidden", !visible);
	}

	canvas.addEventListener("transitionend", () => {
		if (document.body.classList.contains("hidden")) anim.running = false;
	});

	// ---- WebGL setup (same passes as the original onInit) ----

	if (!gl || !gl.getExtension("EXT_color_buffer_float")) {
		console.error("[desktop-visualizer] WebGL2 with float render targets is not available");
		return;
	}

	function createShader(type, source, name) {
		const shader = gl.createShader(type);
		gl.shaderSource(shader, source);
		gl.compileShader(shader);
		if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS))
			throw new Error(`Failed to compile '${name}' shader: ${gl.getShaderInfoLog(shader)}`);
		return shader;
	}

	function createProgram(name) {
		const src = window.SHADERS[name];
		const program = gl.createProgram();
		gl.attachShader(program, createShader(gl.VERTEX_SHADER, src.vertex, `${name} vertex`));
		gl.attachShader(program, createShader(gl.FRAGMENT_SHADER, src.fragment, `${name} fragment`));
		gl.linkProgram(program);
		if (!gl.getProgramParameter(program, gl.LINK_STATUS))
			throw new Error(`Failed to link '${name}' shader: ${gl.getProgramInfoLog(program)}`);

		const uniforms = {};
		const count = gl.getProgramParameter(program, gl.ACTIVE_UNIFORMS);
		for (let i = 0; i < count; i++) {
			const info = gl.getActiveUniform(program, i);
			uniforms[info.name] = gl.getUniformLocation(program, info.name);
		}
		return { program, uniforms, inPosition: gl.getAttribLocation(program, "inPosition") };
	}

	function createFramebuffer(filter) {
		const framebuffer = gl.createFramebuffer();
		gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer);
		const texture = gl.createTexture();
		gl.bindTexture(gl.TEXTURE_2D, texture);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, filter);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, filter);
		gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, texture, 0);
		return { framebuffer, texture };
	}

	const particle = createProgram("particle");
	const dot = createProgram("dot");
	const blur = createProgram("blur");
	const finalize = createProgram("finalize");

	const particleFb = createFramebuffer(gl.NEAREST);
	const dotFb = createFramebuffer(gl.NEAREST);
	const blurXFb = createFramebuffer(gl.LINEAR);
	const blurYFb = createFramebuffer(gl.NEAREST);

	const quadBuffer = gl.createBuffer();
	gl.bindBuffer(gl.ARRAY_BUFFER, quadBuffer);
	gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, -1, 1, 1, 1, 1, -1]), gl.STATIC_DRAW);
	gl.blendEquation(gl.MAX);

	let viewportSize = 0;
	let particleTextureSize = 0;

	function resize() {
		const size = Math.round(Math.min(canvas.clientWidth, canvas.clientHeight) * window.devicePixelRatio);
		if (size === viewportSize || size === 0) return;
		canvas.width = canvas.height = viewportSize = size;
		for (const fb of [dotFb, blurXFb, blurYFb]) {
			gl.bindTexture(gl.TEXTURE_2D, fb.texture);
			gl.texImage2D(gl.TEXTURE_2D, 0, gl.R8, size, size, 0, gl.RED, gl.UNSIGNED_BYTE, null);
		}
	}

	function drawQuad(program, instances) {
		gl.bindBuffer(gl.ARRAY_BUFFER, quadBuffer);
		gl.enableVertexAttribArray(program.inPosition);
		gl.vertexAttribPointer(program.inPosition, 2, gl.FLOAT, false, 0, 0);
		if (instances) gl.drawArraysInstanced(gl.TRIANGLE_FAN, 0, 4, instances);
		else gl.drawArrays(gl.TRIANGLE_FAN, 0, 4);
	}

	function bindTarget(fb, size) {
		gl.bindFramebuffer(gl.FRAMEBUFFER, fb ? fb.framebuffer : null);
		gl.viewport(0, 0, size, size);
		gl.clearColor(0, 0, 0, 0);
		gl.clear(gl.COLOR_BUFFER_BIT);
	}

	// ---- per-frame input: live level instead of the track's loudness curve ----

	function updateInput(now) {
		const dt = Math.min(now - anim.lastFrame, 0.1);
		anim.lastFrame = now;

		const target = now - input.levelTime > SIGNAL_TIMEOUT ? 0 : input.level;
		anim.amplitude += (target - anim.amplitude) * (1 - Math.exp(-dt / AMPLITUDE_SMOOTHING));

		anim.time += dt;
		anim.integral += anim.amplitude * dt;

		if (target <= 0.01) {
			anim.silentFor += dt;
			if (FADE_WHEN_SILENT && anim.silentFor >= HIDE_AFTER_SILENCE && !anim.editing) setVisible(false);
		}
	}

	// ---- render (same passes and constants as the original onRender) ----

	function render() {
		resize();
		if (!viewportSize) return;

		const uAmplitude = anim.amplitude;
		const uNoiseOffset = (0.5 * anim.time + anim.integral) * 75 * 0.01;
		const uDotCount = 322;
		const uDotRadius = 0.9 / uDotCount;
		const uDotRadiusPX = uDotRadius * 0.5 * viewportSize;
		const uSphereRadius = uAmplitude * (0.9 - 0.75 * 0.9) + 0.75 * 0.9;
		const uFeather = Math.pow(uAmplitude + 3, 2) * (45 / 1568);

		if (particleTextureSize !== uDotCount) {
			particleTextureSize = uDotCount;
			gl.bindTexture(gl.TEXTURE_2D, particleFb.texture);
			gl.texImage2D(gl.TEXTURE_2D, 0, gl.RG32F, uDotCount, uDotCount, 0, gl.RG, gl.FLOAT, null);
		}

		// particle positions
		gl.disable(gl.BLEND);
		bindTarget(particleFb, uDotCount);
		gl.useProgram(particle.program);
		const pu = particle.uniforms;
		gl.uniform1f(pu.uNoiseOffset, uNoiseOffset);
		gl.uniform1f(pu.uAmplitude, uAmplitude);
		gl.uniform1i(pu.uSeed, input.seed);
		gl.uniform1f(pu.uDotSpacing, 0.9);
		gl.uniform1f(pu.uDotOffset, -0.9 / 2);
		gl.uniform1f(pu.uSphereRadius, uSphereRadius);
		gl.uniform1f(pu.uFeather, uFeather);
		gl.uniform1f(pu.uNoiseFrequency, 4);
		gl.uniform1f(pu.uNoiseAmplitude, 0.32 * 0.9);
		drawQuad(particle);

		// dots
		gl.enable(gl.BLEND);
		bindTarget(dotFb, viewportSize);
		gl.useProgram(dot.program);
		gl.uniform1i(dot.uniforms.uDotCount, uDotCount);
		gl.uniform1f(dot.uniforms.uDotRadius, uDotRadius);
		gl.uniform1f(dot.uniforms.uDotRadiusPX, uDotRadiusPX);
		gl.uniform1i(dot.uniforms.uParticleTexture, 0);
		gl.activeTexture(gl.TEXTURE0);
		gl.bindTexture(gl.TEXTURE_2D, particleFb.texture);
		drawQuad(dot, uDotCount * uDotCount);

		// blur X
		bindTarget(blurXFb, viewportSize);
		gl.useProgram(blur.program);
		gl.uniform1f(blur.uniforms.uBlurRadius, 0.01 * viewportSize);
		gl.uniform2f(blur.uniforms.uBlurDirection, 1 / viewportSize, 0);
		gl.uniform1i(blur.uniforms.uInputTexture, 0);
		gl.activeTexture(gl.TEXTURE0);
		gl.bindTexture(gl.TEXTURE_2D, dotFb.texture);
		drawQuad(blur);

		// blur Y
		bindTarget(blurYFb, viewportSize);
		gl.uniform2f(blur.uniforms.uBlurDirection, 0, 1 / viewportSize);
		gl.bindTexture(gl.TEXTURE_2D, blurXFb.texture);
		drawQuad(blur);

		// combine blurred and original onto the transparent canvas
		bindTarget(null, viewportSize);
		gl.useProgram(finalize.program);
		gl.uniform3f(finalize.uniforms.uOutputColor, ...input.color);
		gl.uniform3f(finalize.uniforms.uOutputColor2, ...input.color2);
		gl.uniform1i(finalize.uniforms.uGradientStyle, input.gradientStyle);
		gl.uniform1i(finalize.uniforms.uBlurredTexture, 0);
		gl.uniform1i(finalize.uniforms.uOriginalTexture, 1);
		gl.activeTexture(gl.TEXTURE0);
		gl.bindTexture(gl.TEXTURE_2D, blurYFb.texture);
		gl.activeTexture(gl.TEXTURE1);
		gl.bindTexture(gl.TEXTURE_2D, dotFb.texture);
		drawQuad(finalize);
	}

	function frame() {
		if (!anim.running) return;
		updateInput(performance.now() / 1000);
		render();
		requestAnimationFrame(frame);
	}

	function start() {
		if (anim.running) return;
		anim.running = true;
		anim.lastFrame = performance.now() / 1000;
		requestAnimationFrame(frame);
	}
})();
