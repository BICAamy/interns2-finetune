from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from web.backend.main import create_app


def _frontend(root: Path, marker: str) -> Path:
    assets = root / "assets"
    assets.mkdir(parents=True)
    (root / "index.html").write_text(
        f"<!doctype html><title>{marker}</title>",
        encoding="utf-8",
    )
    (assets / "identity.js").write_text(marker, encoding="utf-8")
    return root


@pytest.fixture
def frontend_roots(tmp_path: Path) -> tuple[Path, Path]:
    return (
        _frontend(tmp_path / "demo", "DEMO_FRONTEND"),
        _frontend(tmp_path / "inside", "INSIDE_FRONTEND"),
    )


def _app(variant: str, roots: tuple[Path, Path]):
    demo, inside = roots
    return create_app(
        object(),
        frontend_variant=variant,
        demo_static_dir=demo,
        inside_static_dir=inside,
    )


@pytest.mark.parametrize(
    ("variant", "marker"),
    (("web", "DEMO_FRONTEND"), ("web_inside", "INSIDE_FRONTEND")),
)
def test_single_frontend_is_served_at_root(
    frontend_roots: tuple[Path, Path],
    variant: str,
    marker: str,
) -> None:
    with TestClient(_app(variant, frontend_roots)) as client:
        assert marker in client.get("/").text
        assert marker in client.get("/assets/identity.js").text


def test_both_frontends_have_isolated_routes(
    frontend_roots: tuple[Path, Path],
) -> None:
    with TestClient(_app("both", frontend_roots)) as client:
        assert "DEMO_FRONTEND" in client.get("/").text
        assert "DEMO_FRONTEND" in client.get("/assets/identity.js").text
        assert "INSIDE_FRONTEND" in client.get("/inside/").text
        assert "INSIDE_FRONTEND" in client.get("/inside/assets/identity.js").text

        redirected = client.get("/inside", follow_redirects=False)
        assert redirected.status_code == 307
        assert redirected.headers["location"] == "/inside/"


def test_api_path_is_not_swallowed_by_spa(
    frontend_roots: tuple[Path, Path],
) -> None:
    with TestClient(_app("both", frontend_roots)) as client:
        response = client.get("/api/definitely-not-a-route")
    assert response.status_code == 404
    assert "DEMO_FRONTEND" not in response.text
    assert "INSIDE_FRONTEND" not in response.text


def test_browser_robot_geometry_is_served_as_a_static_asset(
    frontend_roots: tuple[Path, Path],
) -> None:
    with TestClient(_app("both", frontend_roots)) as client:
        response = client.get("/robot-assets/e05/elfin_link1.STL")
    assert response.status_code == 200
    assert len(response.content) > 1_000


def test_invalid_frontend_variant_is_rejected() -> None:
    with pytest.raises(ValueError, match="INTERNS2_WEB_VARIANT"):
        create_app(object(), frontend_variant="unknown")


def test_environment_selects_internal_frontend(
    monkeypatch: pytest.MonkeyPatch,
    frontend_roots: tuple[Path, Path],
) -> None:
    demo, inside = frontend_roots
    monkeypatch.setenv("INTERNS2_WEB_VARIANT", "web_inside")
    app = create_app(
        object(),
        demo_static_dir=demo,
        inside_static_dir=inside,
    )
    assert app.state.web_variant == "web_inside"
    with TestClient(app) as client:
        assert "INSIDE_FRONTEND" in client.get("/").text


def test_default_frontend_remains_demo(
    monkeypatch: pytest.MonkeyPatch,
    frontend_roots: tuple[Path, Path],
) -> None:
    demo, inside = frontend_roots
    monkeypatch.delenv("INTERNS2_WEB_VARIANT", raising=False)
    app = create_app(
        object(),
        demo_static_dir=demo,
        inside_static_dir=inside,
    )
    assert app.state.web_variant == "web"
    with TestClient(app) as client:
        assert "DEMO_FRONTEND" in client.get("/").text
