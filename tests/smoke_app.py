import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dash

import app

client = app.server.test_client()
for path in [
    "/",
    "/portfolio",
    "/analytics",
    "/covariance",
    "/monte-carlo",
    "/portfolio-news",
    "/sentiment",
    "/settings",
    "/_dash-layout",
    "/_dash-dependencies",
]:
    response = client.get(path)
    assert response.status_code == 200, (path, response.status_code, response.data[:500])

ids = set()


def walk(node):
    if isinstance(node, (list, tuple)):
        for child in node:
            walk(child)
        return
    identifier = getattr(node, "id", None)
    if identifier:
        assert identifier not in ids, identifier
        ids.add(identifier)
    walk(getattr(node, "children", []))


walk(app.app.layout)
for page in dash.page_registry.values():
    layout = page["layout"]() if callable(page["layout"]) else page["layout"]
    walk(layout)
for callback in app.app.callback_map.values():
    for item in callback["inputs"] + callback["state"]:
        assert item["id"] in ids, item
print(f"Smoke check passed: {len(dash.page_registry)} pages, {len(ids)} distinct component IDs.")
