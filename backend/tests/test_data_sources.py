"""数据源绑定接口测试。"""


def test_create_data_source(client):
    resp = client.post(
        "/api/data-sources",
        json={
            "source_type": "obsidian",
            "name": "本地笔记库",
            "config": '{"vault_path": "C:/notes"}',
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["source_type"] == "obsidian"
    assert body["enabled"] is True
    assert body["config"] == '{"vault_path": "C:/notes"}'


def test_list_and_filter(client):
    client.post("/api/data-sources", json={"source_type": "notion", "name": "Notion"})
    client.post("/api/data-sources", json={"source_type": "ical", "name": "课表"})

    ical = client.get("/api/data-sources", params={"source_type": "ical"})
    assert len(ical.json()) == 1
    assert ical.json()[0]["name"] == "课表"

    assert len(client.get("/api/data-sources").json()) == 2


def test_update_and_delete(client):
    did = client.post("/api/data-sources", json={"source_type": "notion", "name": "Notion"}).json()["id"]

    upd = client.patch(f"/api/data-sources/{did}", json={"enabled": False, "name": "Notion（停用）"})
    assert upd.status_code == 200
    assert upd.json()["enabled"] is False
    assert upd.json()["name"] == "Notion（停用）"

    assert client.delete(f"/api/data-sources/{did}").status_code == 204
    assert client.get(f"/api/data-sources/{did}").status_code == 404


def test_invalid_source_type_422(client):
    resp = client.post("/api/data-sources", json={"source_type": "wechat"})
    assert resp.status_code == 422
