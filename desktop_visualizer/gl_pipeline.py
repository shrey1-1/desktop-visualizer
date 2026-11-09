"""The visualizer's OpenGL drawing passes, independent of any window.

Same passes as the original NCSVisualizer.tsx (particle positions, dots, two blur passes,
final combine), drawn with Qt's OpenGL helpers so they run inside a Qt Quick window, or
offscreen for tests. Needs a current OpenGL 3.3 core (or OpenGL ES 3.0) context.
"""

import struct
from dataclasses import dataclass

from PySide6.QtCore import QSize
from PySide6.QtGui import QOpenGLContext
from PySide6.QtOpenGL import (QOpenGLBuffer, QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat,
                              QOpenGLShader, QOpenGLShaderProgram, QOpenGLTexture, QOpenGLVertexArrayObject)

from . import shaders

# OpenGL constants (PySide6 doesn't export them).
GL_POINTS = 0x0000
GL_TRIANGLE_FAN = 0x0006
GL_COLOR_BUFFER_BIT = 0x4000
GL_BLEND = 0x0BE2
GL_DEPTH_TEST = 0x0B71
GL_SCISSOR_TEST = 0x0C11
GL_STENCIL_TEST = 0x0B90
GL_CULL_FACE = 0x0B44
GL_FUNC_ADD = 0x8006
GL_ONE = 1
GL_ONE_MINUS_SRC_ALPHA = 0x0303
GL_MAX = 0x8008
GL_PROGRAM_POINT_SIZE = 0x8642
GL_TEXTURE_2D = 0x0DE1
GL_TEXTURE0 = 0x84C0
GL_TEXTURE_MAG_FILTER = 0x2800
GL_TEXTURE_MIN_FILTER = 0x2801
GL_TEXTURE_WRAP_S = 0x2802
GL_TEXTURE_WRAP_T = 0x2803
GL_NEAREST = 0x2600
GL_LINEAR = 0x2601
GL_CLAMP_TO_EDGE = 0x812F
GL_FLOAT = 0x1406
GL_FRAMEBUFFER = 0x8D40
GL_COLOR_ATTACHMENT0 = 0x8CE0

DOT_COUNT = 322  # dots per side of the grid, as in the original


@dataclass
class RenderTarget:
    fbo: QOpenGLFramebufferObject
    texture: QOpenGLTexture
    size: int


STYLES = ("sphere", "sphere_ring", "ring", "bars", "wave", "pulse")
SPHERE_RING_SCALE = 0.72  # sphere size inside the ring for "sphere_ring"


@dataclass
class FrameState:
    amplitude: float = 0.0
    noise_offset: float = 0.0
    seed: int = 0
    colour: tuple = (0x53 / 255,) * 3
    colour2: tuple = (0x53 / 255,) * 3
    gradient_style: int = 0  # 0 solid, 1 vertical, 2 diagonal, 3 radial
    style: str = "sphere"
    bands: tuple = (0.0,) * 64  # 0..1 per frequency band, bass first
    wave: tuple = (0.0,) * 128  # -1..1 waveform
    rings: tuple = (-1.0,) * 8  # ages of pulse ripples in seconds, negative = unused


def shader_source(source, gles):
    """Add the #version line. On desktop OpenGL, drop `precision` statements: Qt defines
    highp/mediump/lowp as empty there, which would leave them as invalid code."""
    if gles:
        return "#version 300 es\n" + source
    lines = [line for line in source.splitlines(keepends=True) if not line.lstrip().startswith("precision ")]
    return "#version 330 core\n" + "".join(lines)


class Pipeline:
    """Create with the OpenGL context current; call render() with it current too."""

    def __init__(self):
        context = QOpenGLContext.currentContext()
        if context is None:
            raise RuntimeError("no current OpenGL context")
        self.gl = context.extraFunctions()
        self.is_gles = context.isOpenGLES()
        gles = self.is_gles
        self.particle = self._program(gles, shaders.PARTICLE_VERTEX, shaders.PARTICLE_FRAGMENT, "particle")
        self.dot = self._program(gles, shaders.DOT_VERTEX, shaders.DOT_FRAGMENT, "dot")
        self.blur = self._program(gles, shaders.BLUR_VERTEX, shaders.BLUR_FRAGMENT, "blur")
        self.finalize = self._program(gles, shaders.FINALIZE_VERTEX, shaders.FINALIZE_FRAGMENT, "finalize")

        # A vertex array object is required in core profiles, even for the attribute-less dot pass.
        self.vao = QOpenGLVertexArrayObject()
        self.vao.create()
        self.vao.bind()
        self.quad = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self.quad.create()
        self.quad.bind()
        data = struct.pack("8f", -1, -1, -1, 1, 1, 1, 1, -1)
        self.quad.allocate(data, len(data))
        self.vao.release()

        # Dot positions: two 32-bit floats per dot.
        self.particle_target = self._target_texture(DOT_COUNT, QOpenGLTexture.TextureFormat.RG32F,
                                                    QOpenGLTexture.PixelFormat.RG, QOpenGLTexture.PixelType.Float32,
                                                    QOpenGLTexture.Filter.Nearest)
        self.size = 0
        self.dot_fbo = self.blur_x_fbo = self.blur_y_fbo = None
        self.styles = {}  # extra style programs, compiled on first use

    # ---- setup ----

    @staticmethod
    def _program(gles, vertex, fragment, name):
        program = QOpenGLShaderProgram()
        if not program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, shader_source(vertex, gles)):
            raise RuntimeError(f"{name} vertex shader: {program.log()}")
        if not program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, shader_source(fragment, gles)):
            raise RuntimeError(f"{name} fragment shader: {program.log()}")
        program.bindAttributeLocation("inPosition", 0)
        if not program.link():
            raise RuntimeError(f"{name} shader link: {program.log()}")
        return program

    def _target_texture(self, size, texture_format, pixel_format, pixel_type, filter_):
        """A render target whose texture has exactly the format we want.

        QOpenGLFramebufferObject only sets up RGBA8 reliably (on OpenGL ES it gets R8 and
        float formats wrong), so QOpenGLTexture creates the texture and it replaces the
        framebuffer's own. Single-channel R8 matters: the dot pass blends tens of thousands
        of overlapping dots, and R8 is a quarter of the memory traffic of RGBA8.
        """
        texture = QOpenGLTexture(QOpenGLTexture.Target.Target2D)
        texture.setFormat(texture_format)
        texture.setSize(size, size)
        texture.setMinMagFilters(filter_, filter_)
        texture.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
        texture.allocateStorage(pixel_format, pixel_type)
        if not texture.isStorageAllocated():
            raise RuntimeError(f"could not create a {size}px texture ({texture_format})")
        fmt = QOpenGLFramebufferObjectFormat()
        fmt.setAttachment(QOpenGLFramebufferObject.Attachment.NoAttachment)
        fbo = QOpenGLFramebufferObject(QSize(size, size), fmt)
        fbo.bind()
        self.gl.glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, texture.textureId(), 0)
        fbo.release()
        return RenderTarget(fbo, texture, size)

    def _r8_target(self, size):
        return self._target_texture(size, QOpenGLTexture.TextureFormat.R8_UNorm, QOpenGLTexture.PixelFormat.Red,
                                    QOpenGLTexture.PixelType.UInt8, QOpenGLTexture.Filter.Linear)

    def _resize(self, size):
        if size == self.size:
            return
        self.size = size
        # The dot texture is sampled with LINEAR so the half-resolution blur averages 2x2
        # blocks instead of skipping thin dots. The glow is blurred at half resolution:
        # it's soft anyway, and that makes it 4x cheaper.
        self.dot_fbo = self._r8_target(size)
        self.blur_size = max(1, round(size / 2))
        self.blur_x_fbo = self._r8_target(self.blur_size)
        self.blur_y_fbo = self._r8_target(self.blur_size)

    # ---- drawing ----

    def _target(self, fbo, size):
        fbo.bind()
        self.gl.glViewport(0, 0, size, size)
        self.gl.glClearColor(0, 0, 0, 0)
        self.gl.glClear(GL_COLOR_BUFFER_BIT)

    def _texture(self, unit, target):
        self.gl.glActiveTexture(GL_TEXTURE0 + unit)
        self.gl.glBindTexture(GL_TEXTURE_2D, target.texture.textureId())

    def _quad(self, program):
        program.setAttributeBuffer(0, GL_FLOAT, 0, 2, 0)
        program.enableAttributeArray(0)
        self.gl.glDrawArrays(GL_TRIANGLE_FAN, 0, 4)

    def render(self, target, state):
        """Draw one frame into `target` (a square QOpenGLFramebufferObject)."""
        size = min(target.width(), target.height())
        if size <= 0:
            return
        if state.style == "sphere_ring":
            self._render_sphere(target, state, size, SPHERE_RING_SCALE)
            self._render_style(target, state, size, "ring", clear=False)
        elif state.style in ("ring", "bars", "wave", "pulse"):
            self._render_style(target, state, size, state.style, clear=True)
        else:
            self._render_sphere(target, state, size, 1.0)

    def _style_program(self, name):
        if name not in self.styles:
            fragment = {"ring": shaders.RING_FRAGMENT, "bars": shaders.BARS_FRAGMENT,
                        "wave": shaders.WAVE_FRAGMENT, "pulse": shaders.PULSE_FRAGMENT}[name]
            self.styles[name] = self._program(self.is_gles, shaders.STYLE_VERTEX, fragment, name)
        return self.styles[name]

    def _render_style(self, target, state, size, name, clear):
        """One-pass styles, drawn straight into the target."""
        gl = self.gl
        for cap in (GL_DEPTH_TEST, GL_STENCIL_TEST, GL_SCISSOR_TEST, GL_CULL_FACE):
            gl.glDisable(cap)
        program = self._style_program(name)
        self.vao.bind()
        self.quad.bind()
        target.bind()
        gl.glViewport(0, 0, size, size)
        if clear:
            gl.glClearColor(0, 0, 0, 0)
            gl.glClear(GL_COLOR_BUFFER_BIT)
            gl.glDisable(GL_BLEND)
        else:
            # Over the sphere: premultiplied "over" blending.
            gl.glEnable(GL_BLEND)
            gl.glBlendEquation(GL_FUNC_ADD)
            gl.glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA)
        program.bind()
        program.setUniformValue("uOutputColor", *map(float, state.colour))
        program.setUniformValue("uOutputColor2", *map(float, state.colour2))
        program.setUniformValue1i("uGradientStyle", int(state.gradient_style))
        program.setUniformValue1f("uAmplitude", float(state.amplitude))
        if name == "ring":
            inner, length = (0.70, 0.26) if not clear else (0.55, 0.38)
            program.setUniformValue1f("uInner", inner)
            program.setUniformValue1f("uLength", length)
        if name in ("ring", "bars"):
            program.setUniformValueArray(program.uniformLocation("uBands"), [float(v) for v in state.bands], 64, 1)
        elif name == "wave":
            program.setUniformValueArray(program.uniformLocation("uWave"), [float(v) for v in state.wave], 128, 1)
        elif name == "pulse":
            program.setUniformValueArray(program.uniformLocation("uRings"), [float(v) for v in state.rings], 8, 1)
        self._quad(program)
        program.release()
        gl.glDisable(GL_BLEND)
        self.quad.release()
        self.vao.release()

    def _render_sphere(self, target, state, size, scale):
        """The original dot sphere. With scale < 1 it's drawn smaller, centred."""
        full_size = size
        size = max(1, round(full_size * scale))
        offset = (full_size - size) // 2
        self._resize(size)
        gl = self.gl
        for cap in (GL_DEPTH_TEST, GL_STENCIL_TEST, GL_SCISSOR_TEST, GL_CULL_FACE):
            gl.glDisable(cap)
        if not self.is_gles:
            gl.glEnable(GL_PROGRAM_POINT_SIZE)

        amplitude = state.amplitude
        dot_radius = 1.25 * 0.9 / DOT_COUNT
        dot_radius_px = dot_radius * 0.5 * size
        sphere_radius = amplitude * (0.9 - 0.75 * 0.9) + 0.75 * 0.9
        feather = (amplitude + 3) ** 2 * (45 / 1568)

        self.vao.bind()
        self.quad.bind()

        # particle positions
        gl.glDisable(GL_BLEND)
        self._target(self.particle_target.fbo, DOT_COUNT)
        p = self.particle
        p.bind()
        p.setUniformValue1f("uNoiseOffset", float(state.noise_offset))
        p.setUniformValue1f("uAmplitude", float(amplitude))
        p.setUniformValue1i("uSeed", int(state.seed))
        p.setUniformValue1f("uDotSpacing", 0.9)
        p.setUniformValue1f("uDotOffset", -0.9 / 2)
        p.setUniformValue1f("uSphereRadius", float(sphere_radius))
        p.setUniformValue1f("uFeather", float(feather))
        p.setUniformValue1f("uNoiseFrequency", 4.0)
        p.setUniformValue1f("uNoiseAmplitude", 0.32 * 0.9)
        self._quad(p)

        # dots: one point each, combined with MAX blending
        gl.glEnable(GL_BLEND)
        gl.glBlendEquation(GL_MAX)
        self._target(self.dot_fbo.fbo, size)
        d = self.dot
        d.bind()
        d.setUniformValue1i("uDotCount", DOT_COUNT)
        d.setUniformValue1f("uDotRadius", float(dot_radius))
        d.setUniformValue1f("uDotRadiusPX", float(dot_radius_px))
        d.setUniformValue1f("uViewportSize", float(size))
        d.setUniformValue1i("uParticleTexture", 0)
        self._texture(0, self.particle_target)
        gl.glDrawArrays(GL_POINTS, 0, DOT_COUNT * DOT_COUNT)
        gl.glBlendEquation(GL_FUNC_ADD)
        gl.glDisable(GL_BLEND)

        # blur X then Y, at half resolution (same radius relative to the sphere)
        b = self.blur
        self._target(self.blur_x_fbo.fbo, self.blur_size)
        b.bind()
        b.setUniformValue1f("uBlurRadius", float(0.01 * self.blur_size))
        b.setUniformValue("uBlurDirection", 1.0 / self.blur_size, 0.0)
        b.setUniformValue1i("uInputTexture", 0)
        self._texture(0, self.dot_fbo)
        self._quad(b)

        self._target(self.blur_y_fbo.fbo, self.blur_size)
        b.setUniformValue("uBlurDirection", 0.0, 1.0 / self.blur_size)
        self._texture(0, self.blur_x_fbo)
        self._quad(b)

        # combine glow and dots into the target, premultiplied for a transparent window
        self._target(target, full_size)
        gl.glViewport(offset, offset, size, size)
        f = self.finalize
        f.bind()
        f.setUniformValue("uOutputColor", *map(float, state.colour))
        f.setUniformValue("uOutputColor2", *map(float, state.colour2))
        f.setUniformValue1i("uGradientStyle", int(state.gradient_style))
        f.setUniformValue1i("uBlurredTexture", 0)
        f.setUniformValue1i("uOriginalTexture", 1)
        self._texture(0, self.blur_y_fbo)
        self._texture(1, self.dot_fbo)
        self._quad(f)

        f.release()
        gl.glActiveTexture(GL_TEXTURE0)
        self.quad.release()
        self.vao.release()
