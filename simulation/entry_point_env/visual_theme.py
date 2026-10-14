"""Shared colours for the E05-Pro SOFA scene and its OpenGL framebuffer."""

from __future__ import annotations


# OpenGL RGBA floats. This is approximately #EBF7FF.
SCENE_BACKGROUND_RGBA = (0.92, 0.97, 1.0, 1.0)


def apply_opengl_background(opengl_gl: object) -> None:
    """Apply the scene colour to the framebuffer that produces MJPEG frames."""

    opengl_gl.glClearColor(*SCENE_BACKGROUND_RGBA)
    opengl_gl.glClear(
        opengl_gl.GL_COLOR_BUFFER_BIT | opengl_gl.GL_DEPTH_BUFFER_BIT
    )
