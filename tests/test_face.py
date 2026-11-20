from PIL import Image

from picspec import face


def test_face_crop_is_square_full_resolution_and_enlarged():
    image = Image.new("RGB", (1024, 1536))
    crop = face.face_crop(image, face.Face((450, 300, 120, 150), 0.9))
    assert crop.size == (768, 768)
    edge = face.face_crop(image, face.Face((0, 0, 400, 500), 0.9), out_side=256)  # clamped to the image
    assert edge.size == (850, 850)


def test_models_are_cached_and_small_downloads_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("PICSPEC_FACE_MODELS", str(tmp_path))
    name = face.MODELS["detect"][0]
    (tmp_path / name).write_bytes(b"x" * 200_000)
    assert face._fetch("detect") == tmp_path / name  # already there: no download

    class Reply:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"version https://git-lfs.github.com/spec/v1"

    monkeypatch.setattr(face.urllib.request, "urlopen", lambda url, timeout=0: Reply())
    try:
        face._fetch("identity")
    except face.FaceToolsMissing as e:
        assert "Put it in" in str(e)
    else:
        raise AssertionError("a Git LFS pointer was accepted as a model")
    assert not (tmp_path / face.MODELS["identity"][0]).exists()
