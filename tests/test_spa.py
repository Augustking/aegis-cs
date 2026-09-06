# -*- coding: utf-8 -*-
import pytest

import web_app


@pytest.fixture()
def client(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>SPA</html>", encoding="utf-8")
    (dist / "assets").mkdir()
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setattr(web_app, "DIST_DIR", str(dist))
    web_app.app.config["TESTING"] = True
    return web_app.app.test_client()


@pytest.fixture()
def client_without_dist(monkeypatch, tmp_path):
    monkeypatch.setattr(web_app, "DIST_DIR", str(tmp_path / "nope"))
    web_app.app.config["TESTING"] = True
    return web_app.app.test_client()


def test_index_serves_spa(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"SPA" in resp.data


def test_history_route_falls_back_to_index(client):
    resp = client.get("/tickets")
    assert resp.status_code == 200
    assert b"SPA" in resp.data


def test_static_assets_served(client):
    resp = client.get("/assets/app.js")
    assert resp.status_code == 200
    assert b"console.log" in resp.data


def test_unknown_api_returns_json_404(client):
    resp = client.get("/api/nope")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not found"


def test_missing_dist_hint(client_without_dist):
    resp = client_without_dist.get("/")
    assert resp.status_code == 200
    assert "npm run build" in resp.get_data(as_text=True)
