"""GLSL shaders for the visualizer.

From Konsl/spicetify-visualizer (MIT), src/shaders/ncs-visualizer/ (see LICENSE-spicetify-visualizer).
particle and blur are unchanged; dot draws one point per dot instead of an instanced quad
(much faster); finalize adds the optional two-colour gradient.

The sources have no #version line: gl_pipeline.py adds "#version 330 core" for desktop
OpenGL or "#version 300 es" for OpenGL ES, which accept the same code here.
"""

PARTICLE_VERTEX = """\
in vec2 inPosition;
out vec2 fragUV;

void main() {
    gl_Position = vec4(inPosition, 0.0, 1.0);
    fragUV = (inPosition + 1.0) / 2.0;
}
"""

PARTICLE_FRAGMENT = """\
precision highp float;

uniform float uNoiseOffset;
uniform float uAmplitude;
uniform int uSeed;

uniform float uDotSpacing;
uniform float uDotOffset;

uniform float uSphereRadius;
uniform float uFeather;

uniform float uNoiseFrequency;
uniform float uNoiseAmplitude;

in vec2 fragUV;
out vec2 outColor;

// https://github.com/Auburn/FastNoiseLite

const float FREQUENCY = 0.01;

const float GAIN = 0.5;
const float LACUNARITY = 1.5;
const float FRACTAL_BOUNDING = 1.0 / 1.75;

const ivec3 PRIMES = ivec3(501125321, 1136930381, 1720413743);

const float GRADIENTS_3D[] = float[](
    0., 1., 1., 0.,  0.,-1., 1., 0.,  0., 1.,-1., 0.,  0.,-1.,-1., 0.,
    1., 0., 1., 0., -1., 0., 1., 0.,  1., 0.,-1., 0., -1., 0.,-1., 0.,
    1., 1., 0., 0., -1., 1., 0., 0.,  1.,-1., 0., 0., -1.,-1., 0., 0.,
    0., 1., 1., 0.,  0.,-1., 1., 0.,  0., 1.,-1., 0.,  0.,-1.,-1., 0.,
    1., 0., 1., 0., -1., 0., 1., 0.,  1., 0.,-1., 0., -1., 0.,-1., 0.,
    1., 1., 0., 0., -1., 1., 0., 0.,  1.,-1., 0., 0., -1.,-1., 0., 0.,
    0., 1., 1., 0.,  0.,-1., 1., 0.,  0., 1.,-1., 0.,  0.,-1.,-1., 0.,
    1., 0., 1., 0., -1., 0., 1., 0.,  1., 0.,-1., 0., -1., 0.,-1., 0.,
    1., 1., 0., 0., -1., 1., 0., 0.,  1.,-1., 0., 0., -1.,-1., 0., 0.,
    0., 1., 1., 0.,  0.,-1., 1., 0.,  0., 1.,-1., 0.,  0.,-1.,-1., 0.,
    1., 0., 1., 0., -1., 0., 1., 0.,  1., 0.,-1., 0., -1., 0.,-1., 0.,
    1., 1., 0., 0., -1., 1., 0., 0.,  1.,-1., 0., 0., -1.,-1., 0., 0.,
    0., 1., 1., 0.,  0.,-1., 1., 0.,  0., 1.,-1., 0.,  0.,-1.,-1., 0.,
    1., 0., 1., 0., -1., 0., 1., 0.,  1., 0.,-1., 0., -1., 0.,-1., 0.,
    1., 1., 0., 0., -1., 1., 0., 0.,  1.,-1., 0., 0., -1.,-1., 0., 0.,
    1., 1., 0., 0.,  0.,-1., 1., 0., -1., 1., 0., 0.,  0.,-1.,-1., 0.
);

float smootherStep(float t) {
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0);
}
vec3 smootherStep(vec3 coord) {
    return vec3(smootherStep(coord.x), smootherStep(coord.y), smootherStep(coord.z));
}

int hash(int seed, ivec3 primed) {
    return (seed ^ primed.x ^ primed.y ^ primed.z) * 0x27d4eb2d;
}

float gradCoord(int seed, ivec3 primed, vec3 d) {
    int hash = hash(seed, primed);
    hash ^= hash >> 15;
    hash &= 63 << 2;
    return d.x * GRADIENTS_3D[hash] + d.y * GRADIENTS_3D[hash | 1] + d.z * GRADIENTS_3D[hash | 2];
}

float perlinSingle(int seed, vec3 coord) {
    ivec3 coord0 = ivec3(floor(coord));
    vec3 d0 = coord - vec3(coord0);
    vec3 d1 = d0 - 1.0;
    vec3 s = smootherStep(d0);
    coord0 *= PRIMES;
    ivec3 coord1 = coord0 + PRIMES;
    float xf00 = mix(gradCoord(seed,                              coord0,                     d0), gradCoord(seed,          ivec3(coord1.x, coord0.yz),      vec3(d1.x, d0.yz)), s.x);
    float xf10 = mix(gradCoord(seed, ivec3(coord0.x, coord1.y, coord0.z), vec3(d0.x, d1.y, d0.z)), gradCoord(seed,          ivec3(coord1.xy, coord0.z),      vec3(d1.xy, d0.z)), s.x);
    float xf01 = mix(gradCoord(seed,          ivec3(coord0.xy, coord1.z),      vec3(d0.xy, d1.z)), gradCoord(seed, ivec3(coord1.x, coord0.y, coord1.z), vec3(d1.x, d0.y, d1.z)), s.x);
    float xf11 = mix(gradCoord(seed,          ivec3(coord0.x, coord1.yz),      vec3(d0.x, d1.yz)), gradCoord(seed,                              coord1,                     d1), s.x);
    float yf0 = mix(xf00, xf10, s.y);
    float yf1 = mix(xf01, xf11, s.y);
    return mix(yf0, yf1, s.z) * 0.964921414852142333984375f;
}

float fractalNoise(vec3 coord) {
    return perlinSingle(uSeed, coord) * FRACTAL_BOUNDING
        + perlinSingle(uSeed + 1, coord * LACUNARITY) * FRACTAL_BOUNDING * GAIN
        + perlinSingle(uSeed + 2, coord * LACUNARITY * LACUNARITY) * FRACTAL_BOUNDING * GAIN * GAIN;
}

void main() {
    float noise = fractalNoise(vec3(fragUV * uNoiseFrequency, uNoiseOffset)) * uNoiseAmplitude;
    vec3 dotCenter = vec3(fragUV * uDotSpacing + uDotOffset + noise, (noise + 0.5 * uNoiseAmplitude) * (0.4 + 0.6 * uAmplitude) * 0.4);
    
    float distanceFromCenter = length(dotCenter);
    dotCenter /= distanceFromCenter;
    distanceFromCenter = min(uSphereRadius, distanceFromCenter);
    dotCenter *= distanceFromCenter;

    float featherRadius = uSphereRadius - uFeather;
    float featherStrength = 1.0 - clamp((distanceFromCenter - featherRadius) / uFeather, 0.0, 1.0);
    dotCenter *= featherStrength * (uSphereRadius / distanceFromCenter - 1.0) + 1.0;

    dotCenter.y *= -1.0;
    outColor = dotCenter.xy;
}
"""

DOT_VERTEX = """\
uniform int uDotCount;
uniform float uDotRadius;
uniform float uDotRadiusPX;
uniform float uViewportSize;

uniform sampler2D uParticleTexture;

out float fragDotRadiusPX;

void main() {
    ivec2 dotIndex = ivec2(gl_VertexID % uDotCount, gl_VertexID / uDotCount);
    vec2 dotCenter = texelFetch(uParticleTexture, dotIndex, 0).xy;

    gl_Position = vec4(dotCenter, 0.0, 1.0);
    // The original quad spanned uDotRadius * (1 + 1 / uDotRadiusPX) on each side of the centre.
    gl_PointSize = uDotRadius * (1.0 + 1.0 / uDotRadiusPX) * uViewportSize;
    fragDotRadiusPX = uDotRadiusPX + 1.0;
}
"""

DOT_FRAGMENT = """\
precision highp float;

in float fragDotRadiusPX;
out float outColor;

void main() {
    vec2 fragUV = gl_PointCoord * 2.0 - 1.0;
    float t = clamp((1.0 - length(fragUV)) * fragDotRadiusPX, 0.0, 1.0);
    outColor = t;
}
"""

BLUR_VERTEX = """\
uniform float uBlurRadius;
uniform vec2 uBlurDirection;

in vec2 inPosition;

out vec2 fragUV;
flat out vec2 fragBlurDirection;
flat out int fragSupport;
flat out vec3 fragGaussCoefficients;

float calculateGaussianTotal(int support, vec3 fragGaussCoefficients) {
    float total = fragGaussCoefficients.x;
    for (int i = 1; i < support; i++) {
        fragGaussCoefficients.xy *= fragGaussCoefficients.yz;
        total += 2.0 * fragGaussCoefficients.x;
    }
    return total;
}

void main() {
    fragSupport = int(ceil(1.5 * uBlurRadius)) * 2;
    fragGaussCoefficients = vec3(1.0 / (sqrt(2.0 * 3.14159265) * uBlurRadius), exp(-0.5 / (uBlurRadius * uBlurRadius)), 0.0);
    fragGaussCoefficients.z = fragGaussCoefficients.y * fragGaussCoefficients.y;
    fragGaussCoefficients.x /= calculateGaussianTotal(fragSupport, fragGaussCoefficients);

    gl_Position = vec4(inPosition, 0.0, 1.0);
    fragUV = (inPosition + 1.0) / 2.0;
    fragBlurDirection = uBlurDirection;
}
"""

BLUR_FRAGMENT = """\
precision highp float;

uniform sampler2D uInputTexture;

in vec2 fragUV;
flat in vec2 fragBlurDirection;
flat in int fragSupport;
flat in vec3 fragGaussCoefficients;

out float outColor;

void main() {
    vec3 gaussCoefficients = fragGaussCoefficients;
    outColor = gaussCoefficients.x * texture(uInputTexture, fragUV).r;

    for (int i = 1; i < fragSupport; i += 2) {
        gaussCoefficients.xy *= gaussCoefficients.yz;
        float coefficientSum = gaussCoefficients.x;
        gaussCoefficients.xy *= gaussCoefficients.yz;
        coefficientSum += gaussCoefficients.x;

        float pixelRatio = gaussCoefficients.x / coefficientSum;
        vec2 offset = (float(i) + pixelRatio) * fragBlurDirection;

        outColor += coefficientSum * (texture(uInputTexture, fragUV + offset).r + texture(uInputTexture, fragUV - offset).r);
    }
}
"""

FINALIZE_VERTEX = """\
uniform vec3 uOutputColor;
in vec2 inPosition;

out vec2 fragUV;
out vec3 fragOutputColor;

void main() {
    gl_Position = vec4(inPosition, 0.0, 1.0);
    fragUV = (inPosition + 1.0) / 2.0;
    fragOutputColor = uOutputColor;
}
"""

FINALIZE_FRAGMENT = """\
precision highp float;

uniform sampler2D uBlurredTexture;
uniform sampler2D uOriginalTexture;

uniform vec3 uOutputColor2;
uniform int uGradientStyle; // 0 solid, 1 vertical, 2 diagonal, 3 radial

in vec2 fragUV;
in vec3 fragOutputColor;

out vec4 outColor;

void main() {
    float value = max(texture(uBlurredTexture, fragUV).r, texture(uOriginalTexture, fragUV).r);
    float t = 0.0;
    if (uGradientStyle == 1) t = fragUV.y;
    else if (uGradientStyle == 2) t = (fragUV.x + fragUV.y) * 0.5;
    else if (uGradientStyle == 3) t = clamp(length(fragUV - 0.5) * 2.2, 0.0, 1.0);
    vec3 color = mix(fragOutputColor, uOutputColor2, smoothstep(0.1, 0.9, t));
    outColor = vec4(color * value, value);
}
"""


# ---- extra styles (one pass each, drawn straight into the target) ----
# All share the gradient colouring of FINALIZE_FRAGMENT and output premultiplied colour.

STYLE_VERTEX = """\
in vec2 inPosition;
out vec2 fragUV;

void main() {
    gl_Position = vec4(inPosition, 0.0, 1.0);
    fragUV = (inPosition + 1.0) / 2.0;
}
"""

_STYLE_COMMON = """\
precision highp float;

uniform vec3 uOutputColor;
uniform vec3 uOutputColor2;
uniform int uGradientStyle; // 0 solid, 1 vertical, 2 diagonal, 3 radial
uniform float uAmplitude;

in vec2 fragUV;
out vec4 outColor;

const float TAU = 6.28318530718;

vec3 paint() {
    float t = 0.0;
    if (uGradientStyle == 1) t = fragUV.y;
    else if (uGradientStyle == 2) t = (fragUV.x + fragUV.y) * 0.5;
    else if (uGradientStyle == 3) t = clamp(length(fragUV - 0.5) * 2.2, 0.0, 1.0);
    return mix(uOutputColor, uOutputColor2, smoothstep(0.1, 0.9, t));
}

void emit(float value) {
    value = clamp(value, 0.0, 1.0);
    outColor = vec4(paint() * value, value);
}

// 0 at the bottom of the circle, 1 at the top, the same on both sides (mirrored).
float mirroredAngle(vec2 p) {
    return abs(atan(p.x, -p.y)) / (TAU * 0.5);
}
"""

RING_FRAGMENT = _STYLE_COMMON + """\
uniform float uBands[64];
uniform float uInner;   // radius where the bars start
uniform float uLength;  // longest bar

void main() {
    vec2 p = fragUV * 2.0 - 1.0;
    float r = length(p);
    float aa = fwidth(r) * 1.5;

    float slot = mirroredAngle(p) * 64.0;          // bass at the bottom, treble at the top
    int i = int(min(floor(slot), 63.0));
    float f = fract(slot);
    float level = uBands[i];
    float outer = uInner + uLength * (0.06 + level);

    float across = abs(f - 0.5);
    float bar = smoothstep(0.36, 0.28, across)
              * smoothstep(-aa, aa, r - uInner) * smoothstep(aa, -aa, r - outer);
    float halo = smoothstep(0.5, 0.15, across) * step(uInner, r) * exp(-max(r - outer, 0.0) * 22.0) * 0.4;
    float base = exp(-abs(r - uInner) * 45.0) * (0.35 + 0.4 * uAmplitude);
    emit(max(max(bar, halo), base));
}
"""

BARS_FRAGMENT = _STYLE_COMMON + """\
uniform float uBands[64];

const float COUNT = 48.0;

void main() {
    vec2 p = fragUV * 2.0 - 1.0;
    float aa = fwidth(p.y) * 1.5;
    float x = (p.x + 0.9) / 1.8;                    // bars span the middle 90 %
    float inside = step(0.0, x) * step(x, 1.0);
    float slot = clamp(x, 0.0, 0.9999) * COUNT;
    int i = int(floor(slot * 64.0 / COUNT));         // bass on the left
    float f = fract(slot);
    float height = 0.03 + 0.82 * uBands[i];

    float across = abs(f - 0.5);
    float y = abs(p.y);                              // mirrored above and below the middle
    float bar = smoothstep(0.38, 0.3, across) * smoothstep(aa, -aa, y - height);
    bar *= 0.6 + 0.4 * (1.0 - y / max(height, 0.01));   // brighter towards the middle
    float halo = smoothstep(0.5, 0.2, across) * exp(-max(y - height, 0.0) * 20.0) * 0.35;
    float line = exp(-y * 70.0) * (0.25 + 0.35 * uAmplitude);
    emit(inside * max(max(bar, halo), line));
}
"""

WAVE_FRAGMENT = _STYLE_COMMON + """\
uniform float uWave[128];

float waveAt(float m) {                               // m in 0..1, mirrored around the circle
    float idx = m * 127.0;
    int i0 = int(floor(idx));
    int i1 = min(i0 + 1, 127);
    return mix(uWave[i0], uWave[i1], fract(idx));
}

float lineAt(float r, float radius, float thickness, float aa) {
    float d = abs(r - radius);
    return smoothstep(thickness + aa, thickness - aa, d) + exp(-d * 32.0) * 0.45;
}

void main() {
    vec2 p = fragUV * 2.0 - 1.0;
    float r = length(p);
    float aa = fwidth(r) * 1.5;
    float w = waveAt(mirroredAngle(p));
    float base = 0.55 + 0.06 * uAmplitude;

    float outline = lineAt(r, base + 0.24 * w, 0.010, aa);
    float echo = lineAt(r, base - 0.07 + 0.12 * w, 0.006, aa) * 0.45;
    float fill = step(r, base + 0.24 * w) * 0.05;
    emit(max(max(outline, echo), fill));
}
"""

PULSE_FRAGMENT = _STYLE_COMMON + """\
uniform float uRings[8];   // age in seconds of each ripple, negative = unused

void main() {
    vec2 p = fragUV * 2.0 - 1.0;
    float r = length(p);
    float aa = fwidth(r) * 1.5;
    float core = 0.16 + 0.12 * uAmplitude;

    float value = smoothstep(core + aa, core - aa, r) * 0.85 + exp(-max(r - core, 0.0) * 9.0) * 0.45;
    for (int k = 0; k < 8; k++) {
        float age = uRings[k];
        if (age < 0.0) continue;
        float radius = core + age * 0.8;
        float fade = clamp(1.0 - age / 1.1, 0.0, 1.0);
        float width = 0.012 + age * 0.03;
        value = max(value, exp(-abs(r - radius) / width) * fade * fade * 0.9);
    }
    emit(value);
}
"""
