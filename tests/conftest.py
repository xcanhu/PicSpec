import pytest


@pytest.fixture(autouse=True)
def no_real_face_tools(monkeypatch):
    """Tests never load OpenCV models or touch the network; face tests pass a fake explicitly."""
    monkeypatch.setattr("picspec.face.shared", lambda: None)
