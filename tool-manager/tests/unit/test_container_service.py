"""Unit tests: app.container_service"""
from unittest.mock import MagicMock, patch

import pytest

from app import container_service


async def _immediate_to_thread(f, *args, **kwargs):
    """
    Патч asyncio.to_thread: выполняет функцию синхронно в тестах.
    Вход: f и аргументы как у to_thread.
    Выход: Результат f(*args, **kwargs).
    """
    return f(*args, **kwargs)


@pytest.mark.asyncio
async def test_create_container_adds_managed_label():
    """
    create_container задаёт label wifiaudit.managed.
    Вход: image test:1; мок containers.run/get.
    Выход: В kwargs.run labels["wifiaudit.managed"] == "1".
    """
    mock_container = MagicMock()
    mock_container.id = "abc"
    mock_container.short_id = "abc123"
    mock_container.name = "n"
    mock_container.status = "running"
    mock_container.attrs = {"Created": "now"}

    mock_client = MagicMock()
    mock_client.containers.run.return_value = mock_container
    mock_client.containers.get.return_value = mock_container

    with patch("app.container_service.asyncio.to_thread", _immediate_to_thread):
        with patch("app.container_service._get_client", return_value=mock_client):
            await container_service.create_container("test:1")

    kwargs = mock_client.containers.run.call_args[1]
    assert kwargs["labels"].get("wifiaudit.managed") == "1"


@pytest.mark.asyncio
async def test_create_container_passes_volumes():
    """
    Проброс volumes в docker.containers.run.
    Вход: volumes=["/data:/data"].
    Выход: В kwargs есть ключ volumes.
    """
    mock_container = MagicMock()
    mock_container.id = "id"
    mock_container.short_id = "id"
    mock_container.name = "n"
    mock_container.status = "running"
    mock_container.attrs = {"Created": "now"}
    mock_client = MagicMock()
    mock_client.containers.run.return_value = mock_container
    mock_client.containers.get.return_value = mock_container

    with patch("app.container_service.asyncio.to_thread", _immediate_to_thread):
        with patch("app.container_service._get_client", return_value=mock_client):
            await container_service.create_container("test:1", volumes=["/data:/data"])

    kwargs = mock_client.containers.run.call_args[1]
    assert "volumes" in kwargs and kwargs["volumes"]


@pytest.mark.asyncio
async def test_create_container_passes_cap_add():
    """
    Проброс cap_add в docker.containers.run.
    Вход: cap_add=["NET_ADMIN"].
    Выход: kwargs["cap_add"] == ["NET_ADMIN"].
    """
    mock_container = MagicMock()
    mock_container.id = "id"
    mock_container.short_id = "id"
    mock_container.name = "n"
    mock_container.status = "running"
    mock_container.attrs = {"Created": "now"}
    mock_client = MagicMock()
    mock_client.containers.run.return_value = mock_container
    mock_client.containers.get.return_value = mock_container

    with patch("app.container_service.asyncio.to_thread", _immediate_to_thread):
        with patch("app.container_service._get_client", return_value=mock_client):
            await container_service.create_container("test:1", cap_add=["NET_ADMIN"])

    assert mock_client.containers.run.call_args[1]["cap_add"] == ["NET_ADMIN"]


@pytest.mark.asyncio
async def test_stop_container_removes():
    """
    stop_container(..., remove=True) вызывает stop и remove.
    Вход: Контейнер с labels wifiaudit.managed=1; remove=True.
    Выход: mock_c.stop и mock_c.remove по одному вызову.
    """
    mock_c = MagicMock()
    mock_c.labels = {"wifiaudit.managed": "1"}
    mock_client = MagicMock()
    mock_client.containers.get.return_value = mock_c

    with patch("app.container_service.asyncio.to_thread", _immediate_to_thread):
        with patch("app.container_service._get_client", return_value=mock_client):
            await container_service.stop_container("cid", remove=True)

    mock_c.stop.assert_called_once()
    mock_c.remove.assert_called_once()


@pytest.mark.asyncio
async def test_stop_container_no_remove():
    """
    stop_container(..., remove=False) не удаляет контейнер.
    Вход: Контейнер с labels wifiaudit.managed=1; remove=False.
    Выход: remove не вызывается; stop вызывается.
    """
    mock_c = MagicMock()
    mock_c.labels = {"wifiaudit.managed": "1"}
    mock_client = MagicMock()
    mock_client.containers.get.return_value = mock_c

    with patch("app.container_service.asyncio.to_thread", _immediate_to_thread):
        with patch("app.container_service._get_client", return_value=mock_client):
            await container_service.stop_container("cid", remove=False)

    mock_c.stop.assert_called_once()
    mock_c.remove.assert_not_called()


@pytest.mark.asyncio
async def test_stop_unmanaged_container_forbidden():
    """
    Остановка контейнера без метки wifiaudit.managed.
    Вход: labels == {}.
    Выход: ValueError, сообщение содержит "not managed".
    """
    mock_c = MagicMock()
    mock_c.labels = {}
    mock_client = MagicMock()
    mock_client.containers.get.return_value = mock_c

    with patch("app.container_service.asyncio.to_thread", _immediate_to_thread):
        with patch("app.container_service._get_client", return_value=mock_client):
            with pytest.raises(ValueError, match="not managed"):
                await container_service.stop_container("cid")


@pytest.mark.asyncio
async def test_run_tool_returns_output():
    """
    run_tool собирает stdout и exit_code из мок-контейнера.
    Вход: wait -> StatusCode 0; logs -> b"hello".
    Выход: exit_code 0; подстрока hello в stdout.
    """
    mock_container = MagicMock()
    mock_container.wait.return_value = {"StatusCode": 0}
    mock_container.logs.return_value = b"hello"
    mock_client = MagicMock()
    mock_client.containers.run.return_value = mock_container

    with patch("app.container_service.asyncio.to_thread", _immediate_to_thread):
        with patch("app.container_service._get_client", return_value=mock_client):
            out = await container_service.run_tool("img:1")

    assert out["exit_code"] == 0
    assert "hello" in out["stdout"]


@pytest.mark.asyncio
async def test_run_tool_removes_after():
    """
    После run_tool у объекта контейнера вызывается remove.
    Вход: Успешный сценарий run_tool (exit 0).
    Выход: mock_container.remove один раз.
    """
    mock_container = MagicMock()
    mock_container.wait.return_value = {"StatusCode": 0}
    mock_container.logs.return_value = b""
    mock_client = MagicMock()
    mock_client.containers.run.return_value = mock_container

    with patch("app.container_service.asyncio.to_thread", _immediate_to_thread):
        with patch("app.container_service._get_client", return_value=mock_client):
            await container_service.run_tool("img:1")

    mock_container.remove.assert_called_once()


@pytest.mark.asyncio
async def test_list_containers_filters_managed():
    """
    list_containers оставляет только контейнеры с wifiaudit.managed.
    Вход: containers.list возвращает один контейнер с меткой managed.
    Выход: Один элемент; id совпадает.
    """
    c1 = MagicMock()
    c1.id = "1"
    c1.short_id = "1"
    c1.name = "a"
    c1.image = MagicMock(tags=["t:latest"])
    c1.status = "running"
    c1.attrs = {"Created": "x"}
    c1.labels = {"wifiaudit.managed": "1"}

    mock_client = MagicMock()
    mock_client.containers.list.return_value = [c1]

    with patch("app.container_service.asyncio.to_thread", _immediate_to_thread):
        with patch("app.container_service._get_client", return_value=mock_client):
            res = await container_service.list_containers()

    assert len(res) == 1
    assert res[0]["id"] == "1"


@pytest.mark.asyncio
async def test_list_images():
    """
    list_images возвращает список описаний образов.
    Вход: images.list возвращает один образ.
    Выход: isinstance(result, list).
    """
    mock_img = MagicMock()
    mock_img.short_id = "abc"
    mock_img.attrs = {"RepoTags": ["x:latest"], "Created": "", "Size": 0}
    mock_client = MagicMock()
    mock_client.images.list.return_value = [mock_img]

    with patch("app.container_service.asyncio.to_thread", _immediate_to_thread):
        with patch("app.container_service._get_client", return_value=mock_client):
            res = await container_service.list_images()

    assert isinstance(res, list)


@pytest.mark.asyncio
async def test_pull_image():
    """
    Успешный docker pull.
    Вход: images.pull без исключения.
    Выход: Словарь с pulled is True.
    """
    mock_client = MagicMock()
    mock_client.images.pull.return_value = None

    with patch("app.container_service.asyncio.to_thread", _immediate_to_thread):
        with patch("app.container_service._get_client", return_value=mock_client):
            res = await container_service.pull_image("test:1")

    assert res.get("pulled") is True


@pytest.mark.asyncio
async def test_pull_image_error():
    """
    Ошибка docker API при pull.
    Вход: images.pull -> APIError.
    Выход: pulled False; ключ error в результате.
    """
    import docker

    mock_client = MagicMock()
    mock_client.images.pull.side_effect = docker.errors.APIError("fail")

    with patch("app.container_service.asyncio.to_thread", _immediate_to_thread):
        with patch("app.container_service._get_client", return_value=mock_client):
            res = await container_service.pull_image("bad:1")

    assert res.get("pulled") is False
    assert "error" in res
