"""Lanzadores contra Docker/curl falsos: no se crean contenedores ni se consulta la red."""

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlencode

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = "ghcr.io/masamunel/cerberus-backend@sha256:" + "a" * 64
FRONTEND = "ghcr.io/masamunel/cerberus-frontend@sha256:" + "b" * 64
REVISION = "c" * 40

FAKE_DOCKER = r"""
import builtins,json,os,signal,sys,time
from pathlib import Path
a=sys.argv[1:]
with open(os.environ["FAKE_DOCKER_LOG"],"a") as log: log.write(json.dumps(a)+"\n")
backend="ghcr.io/masamunel/cerberus-backend@sha256:"+"a"*64
frontend="ghcr.io/masamunel/cerberus-frontend@sha256:"+"b"*64
if a[:2]==["compose","version"]: print(os.environ.get("FAKE_COMPOSE_VERSION","2.30.0"))
elif a[0]=="info":
    if os.environ.get("FAKE_DAEMON_DOWN"): sys.exit(1)
    print(os.environ.get("FAKE_INFO","linux|amd64|4|8589934592"))
elif a[0]=="context": print(os.environ.get("FAKE_ENDPOINT","unix:///fake/docker.sock"))
elif a[0]=="ps": print("active" if os.environ.get("FAKE_ACTIVE") else "")
elif a[0]=="inspect":
    if "compose.service" in a[2]: print(os.environ.get("FAKE_ACTIVE_SERVICE","api"))
    elif a[2]=="{{json .Config.Labels}}":
        print(json.dumps({"com.docker.compose.project.working_dir":os.environ.get("FAKE_ACTIVE_DIRECTORY",os.getcwd()),
                          "com.docker.compose.service":os.environ.get("FAKE_ACTIVE_SERVICE","api")}))
    else: print(os.environ.get("FAKE_ACTIVE_DIRECTORY",os.getcwd()))
elif a[0]=="port": print("127.0.0.1:"+os.environ.get("FAKE_RUNNING_PORT","8080"))
elif a[0]=="exec":
    code=a[a.index("-c")+1]; sys.argv=["-c",*a[a.index("-c")+2:]]
    os.environ["CERBERUS_APP_ORIGIN"]=os.environ.get("FAKE_RUNNING_ORIGIN","http://localhost:8080")
    os.environ["CERBERUS_OIDC_ISSUER_URL"]=os.environ.get("FAKE_RUNNING_ISSUER","http://localhost:8081/realms/cerberus")
    exec(code)
elif a[:2]==["image","inspect"]:
    if "--format" not in a: sys.exit(0 if os.environ.get("FAKE_CACHED_IMAGES") else 1)
    print(json.dumps({"org.opencontainers.image.version":"candidate-test",
                      "org.opencontainers.image.revision":os.environ.get("FAKE_IMAGE_REVISION","c"*40)}))
elif a[0]=="run":
    code=a[a.index("-c")+1]; args=a[a.index("-c")+2:]
    saved_open=builtins.open
    def mapped_open(name,*args,**kwargs):
        return saved_open("release.json" if name=="/release.json" else name,*args,**kwargs)
    builtins.open=mapped_open
    sys.argv=["-c",*args]
    exec(code)
elif a[0]=="compose":
    if "pull" in a:
        Path(os.environ["FAKE_PULL_STARTED"]).touch()
        if os.environ.get("FAKE_PULL_IGNORE_TERM"): signal.signal(signal.SIGTERM,signal.SIG_IGN)
        time.sleep(float(os.environ.get("FAKE_PULL_SLEEP","0")))
        sys.exit(int(os.environ.get("FAKE_PULL_FAILURE","0")))
    elif "up" in a:
        if os.environ.get("FAKE_UP_STARTED"):
            Path(os.environ["FAKE_UP_STARTED"]).touch()
            time.sleep(0.2)
        sys.exit(int(os.environ.get("FAKE_UP_FAILURE","0")))
    elif "--images" in a:
        if a[-1]=="--images": print(backend+"\n"+frontend+"\nredis@sha256:"+"e"*64)
        else: print(backend if a[-1]=="api" else frontend)
    elif "exec" in a:
        code=a[a.index("-c")+1]; sys.argv=["-c",*a[a.index("-c")+2:]]
        os.environ["CERBERUS_OIDC_ISSUER_URL"]="http://localhost:"+os.environ["CERBERUS_KEYCLOAK_HTTP_PORT"]+"/realms/cerberus"
        exec(code)
    else: sys.exit("unexpected compose command "+repr(a))
else: sys.exit("unexpected Docker command "+repr(a))
"""

FAKE_CURL = r"""
import json,os,sys,urllib.parse
url=sys.argv[-1]
if os.environ.get("FAKE_HTTP_DOWN"): sys.exit(7)
if url.endswith("/api/auth/login"):
    issuer="http://localhost:"+os.environ["CERBERUS_KEYCLOAK_HTTP_PORT"]+"/realms/cerberus"
    callback=os.environ.get("FAKE_CALLBACK",os.environ["CERBERUS_APP_ORIGIN"]+"/api/auth/callback")
    query=urllib.parse.urlencode({"redirect_uri":callback,"client_id":"cerberus-web"})
    print("HTTP/1.1 302 Found\r\nLocation: "+issuer+"/protocol/openid-connect/auth?"+query+"\r\n\r\n")
elif url.endswith("/healthz"): print(os.environ.get("FAKE_HEALTHZ","ok"))
elif url.endswith("/api/health"): print(json.dumps({"status":os.environ.get("FAKE_HEALTH","ok")}))
elif url.endswith("/api/auth/config"): print(json.dumps({"mode":os.environ.get("FAKE_AUTH_MODE","oidc")}))
else: print(json.dumps({"issuer":os.environ.get("FAKE_ISSUER","http://localhost:"+os.environ["CERBERUS_KEYCLOAK_HTTP_PORT"]+"/realms/cerberus")},indent=2))
"""


@pytest.fixture
def installation(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "Instalación con espacios ñ"
    (root / "tools/setup").mkdir(parents=True)
    for name in ("start.sh", "start.command", "start.ps1", "tools/setup/start.sh", "tools/setup/start.ps1"):
        shutil.copy(ROOT / name, root / name)
    (root / "compose.yaml").write_text("name: cerberus\nservices: {}\n")
    (root / "release.json").write_text(
        json.dumps(
            {
                "format": 1,
                "version": "candidate-test",
                "revision": REVISION,
                "images": {"backend": BACKEND, "frontend": FRONTEND},
            }
        )
    )
    binary = tmp_path / "fake binaries"
    binary.mkdir()
    for name, source in {"docker": FAKE_DOCKER, "curl": FAKE_CURL}.items():
        target = binary / name
        target.write_text(f"#!{sys.executable}\n" + source)
        target.chmod(0o755)
    env = {key: value for key, value in os.environ.items() if not key.startswith(("CERBERUS_", "COMPOSE_", "DOCKER_"))}
    env.update(
        {
            "PATH": str(binary) + os.pathsep + env["PATH"],
            "CERBERUS_NO_BROWSER": "1",
            "FAKE_DOCKER_LOG": str(tmp_path / "docker.jsonl"),
            "FAKE_PULL_STARTED": str(tmp_path / "pull-started"),
        }
    )
    return root, env


@pytest.fixture(params=["bash", "powershell"])
def launcher(request: pytest.FixtureRequest) -> str:
    if request.param == "powershell" and not (shutil.which("pwsh") or os.environ.get("CERBERUS_TEST_PWSH")):
        pytest.skip("PowerShell no está instalado")
    return request.param


def launcher_command(root: Path, name: str = "start.sh", launcher: str = "bash") -> list[str]:
    if launcher == "powershell":
        executable = os.environ.get("CERBERUS_TEST_PWSH") or shutil.which("pwsh")
        assert executable
        return [executable, "-NoLogo", "-NoProfile", "-File", str(root / "start.ps1"), "-NoBrowser"]
    return ["bash", str(root / name)]


def run_launcher(
    root: Path, env: dict[str, str], name: str = "start.sh", launcher: str = "bash"
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        launcher_command(root, name, launcher), cwd=root.parent, env=env, capture_output=True, text=True, timeout=25
    )


def docker_commands(env: dict[str, str]) -> list[list[str]]:
    path = Path(env["FAKE_DOCKER_LOG"])
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_start_from_other_directory_spaces_unicode_and_quoted_crlf_env(
    installation: tuple[Path, dict[str, str]],
) -> None:
    root, env = installation
    (root / ".env").write_bytes(
        b"# configuracion\r\nCERBERUS_HTTP_PORT='19321'\r\nCERBERUS_KEYCLOAK_HTTP_PORT=\"19322\"\r\n"
        b"COMPOSE_PROJECT_NAME='cerberus-test'\r\nCERBERUS_STORAGE_PATH='/original/path with spaces'\r\n"
        b"UNKNOWN=$(touch should-never-exist)\r\n"
    )
    result = run_launcher(root, env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "http://localhost:19321" in result.stdout and "demo / demo" in result.stdout
    contents = (root / ".env").read_text()
    assert "CERBERUS_STORAGE_PATH='/original/path with spaces'" in contents
    assert "UNKNOWN=$(touch should-never-exist)" in contents
    assert "COMPOSE_PROJECT_NAME=cerberus-test" in contents
    assert not (root / "should-never-exist").exists()
    assert not (root / ".cerberus-setup.lock").exists()
    commands = docker_commands(env)
    assert any("pull" in command for command in commands)
    assert any("--wait-timeout" in command and "up" in command for command in commands)
    assert not any("--build" in command or "down" in command for command in commands)


def test_explicit_occupied_port_fails_before_pull(installation: tuple[Path, dict[str, str]]) -> None:
    root, env = installation
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        env["CERBERUS_HTTP_PORT"] = str(listener.getsockname()[1])
        result = run_launcher(root, env)
    assert result.returncode != 0 and "ocupado" in result.stderr
    assert not any("pull" in command or "up" in command for command in docker_commands(env))


@pytest.mark.parametrize(
    "changes",
    [
        {"CERBERUS_HTTP_PORT": "19321"},
        {"CERBERUS_KEYCLOAK_HTTP_PORT": "19322"},
        {"CERBERUS_APP_ORIGIN": "http://127.0.0.1:8080"},
        {"FAKE_ACTIVE_SERVICE": "frontend", "FAKE_RUNNING_PORT": "19321"},
        {"FAKE_ACTIVE_SERVICE": "keycloak", "FAKE_RUNNING_PORT": "19322"},
    ],
)
def test_active_instance_configuration_is_verified_before_pull(
    installation: tuple[Path, dict[str, str]], changes: dict[str, str], launcher: str
) -> None:
    root, env = installation
    env.update({"FAKE_ACTIVE": "1", **changes})
    result = run_launcher(root, env, launcher=launcher)
    assert result.returncode != 0 and "activa" in result.stderr
    assert not (root / ".env").exists()
    assert not any("pull" in command or "up" in command for command in docker_commands(env))


def test_active_instance_with_matching_configuration_restarts(
    installation: tuple[Path, dict[str, str]],
) -> None:
    root, env = installation
    env["FAKE_ACTIVE"] = "1"
    result = run_launcher(root, env)
    assert result.returncode == 0, result.stdout + result.stderr


def test_restart_uses_all_cached_digests_without_pull(installation: tuple[Path, dict[str, str]]) -> None:
    root, env = installation
    env.update({"FAKE_CACHED_IMAGES": "1", "FAKE_PULL_FAILURE": "1"})
    result = run_launcher(root, env)
    assert result.returncode == 0, result.stdout + result.stderr
    commands = docker_commands(env)
    assert not any("pull" in command for command in commands)
    inspected = [command[-1] for command in commands if command[:2] == ["image", "inspect"]]
    assert BACKEND in inspected and FRONTEND in inspected and "redis@sha256:" + "e" * 64 in inspected
    assert any("up" in command and "--pull" in command and "never" in command for command in commands)


def test_default_busy_ports_are_selected_and_persisted(installation: tuple[Path, dict[str, str]]) -> None:
    root, env = installation
    listeners = []
    try:
        for port in (8080, 8081):
            listener = socket.socket()
            try:
                listener.bind(("127.0.0.1", port))
                listener.listen()
                listeners.append(listener)
            except OSError:
                listener.close()
        result = run_launcher(root, env)
        assert result.returncode == 0, result.stdout + result.stderr
        values = dict(line.split("=", 1) for line in (root / ".env").read_text().splitlines())
        assert values["CERBERUS_HTTP_PORT"] not in {"8080", "8081"}
        assert values["CERBERUS_KEYCLOAK_HTTP_PORT"] not in {"8080", "8081", values["CERBERUS_HTTP_PORT"]}
    finally:
        for listener in listeners:
            listener.close()


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({"FAKE_COMPOSE_VERSION": "2.29.9"}, "2.30.0"),
        ({"FAKE_DAEMON_DOWN": "1"}, "daemon"),
        ({"FAKE_INFO": "windows|amd64|4|8589934592"}, "Linux"),
        ({"FAKE_ENDPOINT": "ssh://remote"}, "local"),
        ({"DOCKER_CONTEXT": "remote", "DOCKER_HOST": "unix:///local.sock", "FAKE_ENDPOINT": "ssh://remote"}, "local"),
        ({"FAKE_ACTIVE": "1", "FAKE_ACTIVE_DIRECTORY": "/another/daily/installation"}, "otra carpeta"),
        ({"CERBERUS_HTTP_PORT": "$(touch injected)"}, "enteros"),
    ],
)
def test_preflight_failure_never_touches_stack(
    installation: tuple[Path, dict[str, str]],
    changes: dict[str, str],
    expected: str,
    launcher: str,
) -> None:
    root, env = installation
    env.update(changes)
    result = run_launcher(root, env, launcher=launcher)
    assert result.returncode != 0 and expected in result.stderr
    assert not any("pull" in command or "up" in command for command in docker_commands(env))
    assert not (root / ".cerberus-setup.lock").exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"FAKE_HEALTHZ": "other service"},
        {"FAKE_HEALTH": "wrong"},
        {"FAKE_AUTH_MODE": "off"},
        {"FAKE_ISSUER": "http://unrelated:8081/realms/cerberus"},
        {"FAKE_IMAGE_REVISION": "d" * 40},
        {"FAKE_UP_FAILURE": "1"},
        {"FAKE_PULL_FAILURE": "1"},
        {"FAKE_HTTP_DOWN": "1"},
        {"FAKE_CALLBACK": "http://other:8080/api/auth/callback"},
    ],
)
def test_unready_or_wrong_stack_fails_without_browser_or_reset(
    installation: tuple[Path, dict[str, str]],
    changes: dict[str, str],
) -> None:
    root, env = installation
    env.update(changes)
    result = run_launcher(root, env)
    assert result.returncode != 0
    assert "Cerberus listo:" not in result.stdout
    assert not (root / ".cerberus-setup.lock").exists()
    assert not any("down" in command or "prune" in command for command in docker_commands(env))


@pytest.mark.parametrize("ignore_term", [False, True])
def test_pull_timeout_is_bounded_and_releases_lock(
    installation: tuple[Path, dict[str, str]], ignore_term: bool, launcher: str
) -> None:
    root, env = installation
    env.update({"FAKE_PULL_SLEEP": "10", "CERBERUS_PULL_TIMEOUT_SECONDS": "1"})
    if ignore_term:
        env["FAKE_PULL_IGNORE_TERM"] = "1"
    before = time.monotonic()
    result = run_launcher(root, env, launcher=launcher)
    assert result.returncode != 0 and time.monotonic() - before < 8
    assert not (root / ".cerberus-setup.lock").exists()
    assert not any("up" in command for command in docker_commands(env))


def test_concurrent_start_and_cancel_preserve_lock_ownership(
    installation: tuple[Path, dict[str, str]], launcher: str
) -> None:
    root, env = installation
    env["FAKE_PULL_SLEEP"] = "10"
    first = subprocess.Popen(
        launcher_command(root, launcher=launcher), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        deadline = time.monotonic() + 10
        while not Path(env["FAKE_PULL_STARTED"]).exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert Path(env["FAKE_PULL_STARTED"]).exists()
        second = run_launcher(root, env, launcher=launcher)
        assert second.returncode != 0 and "Otra operación" in second.stderr
        assert (root / ".cerberus-setup.lock").is_dir()
        first.send_signal(signal.SIGINT if launcher == "powershell" else signal.SIGTERM)
        output = first.communicate(timeout=5)
        if launcher == "bash":
            assert first.returncode != 0
        # pwsh -File puede devolver 0 por Ctrl+C aun cuando ejecuta finally.
        assert "Cerberus listo:" not in output[0]
        assert not (root / ".cerberus-setup.lock").exists()
    finally:
        if first.poll() is None:
            first.kill()
            first.communicate(timeout=5)


def test_macos_wrapper_and_powershell_contract(installation: tuple[Path, dict[str, str]]) -> None:
    root, env = installation
    assert run_launcher(root, env, "start.command").returncode == 0
    source = (ROOT / "tools/setup/start.ps1").read_text()
    assert (ROOT / "tools/setup/start.ps1").read_bytes().startswith(b"\xef\xbb\xbf")
    for required in (
        ".cerberus-setup.lock",
        "GetResponse",
        "ConvertFrom-Json",
        "--wait-timeout",
        "working_dir",
        "Wait-Job",
    ):
        assert required in source
    assert "ExecutionPolicy" not in source


@pytest.mark.skipif(
    not (shutil.which("pwsh") or os.environ.get("CERBERUS_TEST_PWSH")), reason="PowerShell no está instalado"
)
def test_powershell_with_fake_docker_and_local_http(installation: tuple[Path, dict[str, str]]) -> None:
    root, env = installation
    sockets = [socket.socket(), socket.socket()]
    try:
        for item in sockets:
            item.bind(("127.0.0.1", 0))
        http, identity = [item.getsockname()[1] for item in sockets]
    finally:
        for item in sockets:
            item.close()
    origin = f"http://127.0.0.1:{http}"
    issuer = f"http://localhost:{identity}/realms/cerberus"
    (root / ".env").write_bytes(
        f"CERBERUS_HTTP_PORT='{http}'\r\nCERBERUS_KEYCLOAK_HTTP_PORT='{identity}'\r\n"
        f"COMPOSE_PROJECT_NAME='cerberus-test'\r\nCERBERUS_APP_ORIGIN='{origin}'\r\n".encode()
    )
    env["FAKE_UP_STARTED"] = str(root / "up-started")
    env.update({"FAKE_CACHED_IMAGES": "1", "FAKE_PULL_FAILURE": "1"})

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = b"ok\n"
            if self.path == "/api/auth/login":
                self.send_response(302)
                self.send_header(
                    "Location",
                    issuer
                    + "/protocol/openid-connect/auth?"
                    + urlencode(
                        {
                            "redirect_uri": origin + "/api/auth/callback",
                            "client_id": "cerberus-web",
                        }
                    ),
                )
                self.end_headers()
                return
            if self.path == "/api/health":
                body = b'{"status":"ok"}'
            elif self.path == "/api/auth/config":
                body = b'{"mode":"oidc"}'
            elif self.path.endswith("openid-configuration"):
                body = json.dumps({"issuer": issuer}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    servers: list[ThreadingHTTPServer] = []

    def start_servers() -> None:
        deadline = time.monotonic() + 12
        while not Path(env["FAKE_UP_STARTED"]).exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not Path(env["FAKE_UP_STARTED"]).exists():
            return
        for port in (http, identity):
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            servers.append(server)
            Thread(target=server.serve_forever, daemon=True).start()

    worker = Thread(target=start_servers, daemon=True)
    worker.start()
    try:
        executable = os.environ.get("CERBERUS_TEST_PWSH") or shutil.which("pwsh")
        assert executable
        result = subprocess.run(
            [executable, "-NoLogo", "-NoProfile", "-File", str(root / "start.ps1"), "-NoBrowser"],
            cwd=root.parent,
            env=env,
            capture_output=True,
            text=True,
            timeout=25,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Cerberus listo:" in result.stdout
        assert not (root / ".cerberus-setup.lock").exists()
        assert not any("pull" in command for command in docker_commands(env))
    finally:
        worker.join(timeout=13)
        for server in servers:
            server.shutdown()
            server.server_close()
