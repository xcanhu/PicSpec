"""Optional face tools: find faces and compare identities, without asking a vision model.

Needs ``pip install picspec[face]`` (OpenCV) and two small ONNX models from the OpenCV
model zoo, YuNet for detection and SFace for identity. They are downloaded on first use
into ``PICSPEC_FACE_MODELS`` (default ``~/.cache/picspec/face``); put the files there
yourself to work offline.
"""

from __future__ import annotations

import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

_ZOO = "https://github.com/opencv/opencv_zoo/raw/main/models/"
_HF = "https://huggingface.co/opencv/"
MODELS: dict[str, tuple[str, tuple[str, ...]]] = {
    "detect": ("face_detection_yunet_2023mar.onnx", (
        _ZOO + "face_detection_yunet/face_detection_yunet_2023mar.onnx",
        _HF + "face_detection_yunet/resolve/main/face_detection_yunet_2023mar.onnx")),
    "identity": ("face_recognition_sface_2021dec.onnx", (
        _ZOO + "face_recognition_sface/face_recognition_sface_2021dec.onnx",
        _HF + "face_recognition_sface/resolve/main/face_recognition_sface_2021dec.onnx")),
}
# Cosine similarity at or above this counts as the same person. SFace's authors publish 0.363 for photographs
# of real people, but unrelated generated faces scored up to 0.61 in our tests, so the default is higher.
SAME_PERSON = 0.6
_MIN_BYTES = 100_000  # anything smaller is an error page or a Git LFS pointer, not a model


class FaceToolsMissing(RuntimeError):
    """OpenCV or the model files are not available."""


@dataclass
class Face:
    box: tuple[int, int, int, int]  # left, top, width, height in pixels
    score: float
    raw: Any = None  # the detector's own row, needed to align the face for comparison

    def _eyes(self) -> tuple[float, float, float] | None:
        if self.raw is None:
            return None
        eye_a, eye_b, nose = float(self.raw[4]), float(self.raw[6]), float(self.raw[8])
        return min(eye_a, eye_b), max(eye_a, eye_b), nose

    @property
    def profile(self) -> bool:
        """True when the head is turned so far that the face cannot be compared at all: the two eyes
        are less than a quarter of the face width apart. In live runs side and back views measured
        0.08 and 0.16, three-quarter views 0.36 to 0.40, frontal faces 0.45."""
        eyes = self._eyes()
        return eyes is not None and eyes[1] - eyes[0] < 0.25 * self.box[2]

    @property
    def turned(self) -> bool:
        """True for a three-quarter view or more: the nose lies at or outside the eyes. Such a face can
        match a reference taken from a similar angle, but a low score against a frontal reference
        says little."""
        eyes = self._eyes()
        if eyes is None:
            return False
        low, high, nose = eyes
        return high - low <= 0 or not 0.1 <= (nose - low) / (high - low) <= 0.9

    @property
    def area(self) -> int:
        return self.box[2] * self.box[3]


def model_dir() -> Path:
    return Path(os.environ.get("PICSPEC_FACE_MODELS") or Path.home() / ".cache" / "picspec" / "face")


def _fetch(key: str) -> Path:
    name, urls = MODELS[key]
    path = model_dir() / name
    if path.is_file() and path.stat().st_size >= _MIN_BYTES:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    errors = []
    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                data = resp.read()
            if len(data) < _MIN_BYTES:
                raise OSError("the download was not a model file")
            path.write_bytes(data)
            return path
        except OSError as e:
            errors.append(f"{url}: {e}")
    raise FaceToolsMissing(f"could not download {name}. Put it in {path.parent} yourself. " + "; ".join(errors))


class FaceTools:
    """Detection and identity comparison. Build once and reuse: loading the models takes a moment."""

    def __init__(self, min_score: float = 0.7) -> None:
        try:
            import cv2
            import numpy as np
        except ImportError as e:
            raise FaceToolsMissing("face tools need OpenCV: pip install 'picspec[face]'") from e
        self._cv2, self._np = cv2, np
        try:
            cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)  # hide per-load backend notices
        except Exception:
            pass
        self._detector = cv2.FaceDetectorYN.create(str(_fetch("detect")), "", (320, 320), min_score, 0.3, 5000)
        self._recognizer = None

    def _bgr(self, image: Image.Image) -> Any:
        return self._np.asarray(image.convert("RGB"))[:, :, ::-1].copy()

    def detect(self, image: Image.Image, max_side: int = 1280) -> list[Face]:
        """Faces in ``image``, largest first. Boxes are in the image's own pixels."""
        scale = min(1.0, max_side / max(image.size))
        small = image if scale == 1.0 else image.resize((round(image.width * scale), round(image.height * scale)))
        self._detector.setInputSize(small.size)
        _, rows = self._detector.detect(self._bgr(small))
        faces = []
        for row in rows if rows is not None else []:
            row = row.copy()
            row[:14] /= scale  # box and the five landmarks, back to full-size pixels
            x, y, w, h = (int(round(float(v))) for v in row[:4])
            faces.append(Face((x, y, w, h), float(row[14]), row))
        return sorted(faces, key=lambda f: -f.area)

    def embedding(self, image: Image.Image, face: Face) -> Any:
        if self._recognizer is None:
            self._recognizer = self._cv2.FaceRecognizerSF.create(str(_fetch("identity")), "")
        aligned = self._recognizer.alignCrop(self._bgr(image), face.raw)
        return self._recognizer.feature(aligned).copy()

    def similarity(self, a: Image.Image, b: Image.Image) -> float | None:
        """Cosine similarity between the largest face in each image, or ``None`` if either has no face."""
        fa, fb = self.detect(a), self.detect(b)  # largest face in each
        if not fa or not fb:
            return None
        ea, eb = self.embedding(a, fa[0]), self.embedding(b, fb[0])
        return float(self._recognizer.match(ea, eb, self._cv2.FaceRecognizerSF_FR_COSINE))


def face_crop(image: Image.Image, face: Face, margin: float = 0.35, out_side: int = 768) -> Image.Image:
    """A square close-up around ``face`` at the image's full resolution, enlarged to ``out_side`` if smaller."""
    x, y, w, h = face.box
    side = int(max(w, h) * (1 + 2 * margin))
    cx, cy = x + w // 2, y + h // 2
    left = max(0, min(cx - side // 2, image.width - side))
    top = max(0, min(cy - side // 2, image.height - side))
    crop = image.crop((left, top, min(image.width, left + side), min(image.height, top + side)))
    if max(crop.size) < out_side:
        k = out_side / max(crop.size)
        crop = crop.resize((round(crop.width * k), round(crop.height * k)), Image.LANCZOS)
    return crop


_shared: FaceTools | None = None
_failed: str | None = None


def shared() -> FaceTools | None:
    """The process-wide tools, or ``None`` when they cannot be loaded. Never raises."""
    global _shared, _failed
    if _shared is None and _failed is None:
        if os.environ.get("PICSPEC_FACE", "").casefold() in ("0", "off", "no", "false"):
            _failed = "turned off by PICSPEC_FACE"
        else:
            try:
                _shared = FaceTools()
            except Exception as e:  # missing OpenCV, no network, a broken model file
                _failed = str(e)
    return _shared


def why_missing() -> str:
    return _failed or ""
