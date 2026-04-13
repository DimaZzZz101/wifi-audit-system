"""Unit tests: app.api.routes.dictionaries"""
import pytest


@pytest.mark.asyncio
async def test_upload_dictionary(client, auth_headers):
    """
    POST /api/dictionaries/ - загрузка файла словаря.
    Вход: multipart: file, name, description; JWT.
    Выход: HTTP 200; в JSON есть id, word_count, size_bytes (как в DictionaryResponse).
    """
    files = {"file": ("words.txt", b"one\ntwo\nthree\n", "text/plain")}
    data = {"name": "mydict", "description": "d"}
    r = await client.post("/api/dictionaries/", headers=auth_headers, files=files, data=data)
    assert r.status_code == 200
    body = r.json()
    assert "id" in body
    assert "word_count" in body
    assert "size_bytes" in body


@pytest.mark.asyncio
async def test_list_dictionaries(client, auth_headers):
    """
    GET /api/dictionaries/ - список словарей.
    Вход: два предварительно загруженных словаря.
    Выход: HTTP 200; длина списка >= 2.
    """
    for i in range(2):
        files = {"file": (f"w{i}.txt", b"a\nb\n", "text/plain")}
        await client.post(
            "/api/dictionaries/",
            headers=auth_headers,
            files=files,
            data={"name": f"dict{i}"},
        )
    r = await client.get("/api/dictionaries/", headers=auth_headers)
    assert r.status_code == 200
    assert len(r.json()) >= 2


@pytest.mark.asyncio
async def test_delete_dictionary(client, auth_headers):
    """
    DELETE /api/dictionaries/{id}.
    Вход: id из ответа POST загрузки.
    Выход: HTTP 200.
    """
    files = {"file": ("del.txt", b"x\n", "text/plain")}
    cr = await client.post(
        "/api/dictionaries/",
        headers=auth_headers,
        files=files,
        data={"name": "todel"},
    )
    did = cr.json()["id"]
    r = await client.delete(f"/api/dictionaries/{did}", headers=auth_headers)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_delete_nonexistent(client, auth_headers):
    """
    DELETE несуществующего id.
    Вход: id=99999.
    Выход: HTTP 404.
    """
    r = await client.delete("/api/dictionaries/99999", headers=auth_headers)
    assert r.status_code == 404
