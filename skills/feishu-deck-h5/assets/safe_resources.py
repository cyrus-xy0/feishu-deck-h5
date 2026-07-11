"""Security boundaries shared by deck asset and network helpers.

The publisher and import pipeline consume HTML that may originate outside this
repository.  Treat every path and URL embedded in that HTML as untrusted: local
paths must remain below an explicitly supplied root after symlink resolution,
and remote downloads must not be able to reach non-public networks (including
through redirects or DNS rebinding).
"""
from __future__ import annotations

from dataclasses import dataclass
import http.client
import ipaddress
from io import BytesIO
from pathlib import Path, PureWindowsPath
import socket
from typing import Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import (
    HTTPHandler,
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)


class UnsafeResourceError(RuntimeError):
    """Raised when an untrusted resource crosses a local or network boundary."""


def _is_below(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_local_file(
    base_dir: Path,
    ref: str,
    *,
    allowed_roots: Iterable[Path],
    allowed_suffixes: Iterable[str] | None = None,
    allow_hidden: bool = False,
) -> Path | None:
    """Resolve ``ref`` only when it remains inside an explicit trusted root.

    Absolute paths are never accepted as an HTML staging protocol.  Relative
    ``..`` components are allowed only when their fully resolved destination is
    still inside one of ``allowed_roots``.  Resolving before containment also
    closes symlink escapes.
    """

    raw = str(ref or "").strip()
    if not raw:
        return None
    if "\x00" in raw or "\\" in raw:
        raise UnsafeResourceError(f"unsafe local resource path: {ref!r}")
    candidate_path = Path(raw)
    if candidate_path.is_absolute() or PureWindowsPath(raw).is_absolute():
        raise UnsafeResourceError(f"absolute local resource path is not allowed: {ref!r}")

    roots = tuple(Path(root).expanduser().resolve() for root in allowed_roots)
    if not roots:
        raise UnsafeResourceError("local resource resolution requires an allowed root")
    candidate = (Path(base_dir).expanduser().resolve() / candidate_path).resolve()
    containing = tuple(root for root in roots if _is_below(candidate, root))
    if not containing:
        raise UnsafeResourceError(f"local resource escapes allowed roots: {ref!r}")
    if not allow_hidden:
        visible_from_root = any(
            not any(part.startswith(".") for part in candidate.relative_to(root).parts)
            for root in containing
        )
        if not visible_from_root:
            raise UnsafeResourceError(f"hidden local resource is not allowed: {ref!r}")
    if allowed_suffixes is not None:
        suffixes = {
            value.lower() if str(value).startswith(".") else "." + str(value).lower()
            for value in allowed_suffixes
        }
        if candidate.suffix.lower() not in suffixes:
            raise UnsafeResourceError(
                f"local resource type is not allowed: {candidate.suffix or '<none>'}"
            )
    return candidate if candidate.is_file() else None


_METADATA_HOSTS = {
    "metadata",
    "metadata.google.internal",
    "metadata.google.internal.",
    "instance-data",
}


def _public_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    try:
        ip = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError as exc:
        raise UnsafeResourceError(f"invalid destination IP: {value!r}") from exc
    # is_global excludes private, loopback, link-local, multicast, reserved,
    # unspecified, documentation, and IPv4-mapped non-public destinations.
    if not ip.is_global:
        raise UnsafeResourceError(f"non-public destination IP is not allowed: {ip}")
    if getattr(ip, "ipv4_mapped", None) is not None and not ip.ipv4_mapped.is_global:
        raise UnsafeResourceError(f"non-public mapped destination IP is not allowed: {ip}")
    return ip


Resolver = Callable[..., list[tuple]]


def _public_addresses(host: str, port: int, resolver: Resolver) -> list[tuple]:
    try:
        answers = resolver(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise UnsafeResourceError(f"cannot resolve remote resource host {host}: {exc}") from exc
    public: list[tuple] = []
    for answer in answers:
        sockaddr = answer[4]
        if not sockaddr:
            continue
        _public_ip(str(sockaddr[0]))
        public.append(answer)
    if not public:
        raise UnsafeResourceError(f"remote resource host resolved to no usable IP: {host}")
    return public


def validate_remote_url(url: str, *, resolver: Resolver = socket.getaddrinfo) -> set[str]:
    """Validate one HTTP(S) destination and return its approved DNS IP set."""

    parsed = urlsplit(str(url or ""))
    if parsed.scheme.lower() not in {"http", "https"}:
        raise UnsafeResourceError(f"only http(s) resources are allowed: {url!r}")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeResourceError("credentials in remote resource URLs are not allowed")
    host = (parsed.hostname or "").rstrip(".").lower()
    if not host or host in _METADATA_HOSTS or host.endswith(".internal"):
        raise UnsafeResourceError(f"unsafe remote resource host: {host or '<empty>'}")
    try:
        literal = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        literal = None
    if literal is not None:
        return {str(_public_ip(str(literal)))}

    port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    return {str(_public_ip(str(answer[4][0]))) for answer in _public_addresses(host, port, resolver)}


class _SafeRedirectHandler(HTTPRedirectHandler):
    def __init__(self, resolver: Resolver = socket.getaddrinfo):
        super().__init__()
        self._resolver = resolver

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        target = urljoin(req.full_url, newurl)
        validate_remote_url(target, resolver=self._resolver)
        return super().redirect_request(req, fp, code, msg, headers, target)


def _connect_public(
    address: tuple[str, int],
    timeout: float | object,
    source_address: tuple[str, int] | None,
    resolver: Resolver,
) -> socket.socket:
    """Connect to a prevalidated numeric IP without a second DNS lookup."""
    host, port = address
    answers = _public_addresses(host, port, resolver)
    last_error: OSError | None = None
    for family, socktype, proto, _canonname, sockaddr in answers:
        sock = socket.socket(family, socktype, proto)
        try:
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:  # type: ignore[attr-defined]
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            last_error = exc
            sock.close()
    raise OSError(f"could not connect to validated public destination: {last_error}")


class _PinnedHTTPHandler(HTTPHandler):
    def __init__(self, resolver: Resolver):
        super().__init__()
        self._resolver = resolver

    def http_open(self, req):  # noqa: ANN001
        resolver = self._resolver

        def connection(host, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, **kwargs):  # noqa: ANN001
            conn = http.client.HTTPConnection(host, timeout=timeout, **kwargs)
            conn._create_connection = (  # type: ignore[method-assign]
                lambda address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None:
                _connect_public(address, timeout, source_address, resolver)
            )
            return conn

        return self.do_open(connection, req)


class _PinnedHTTPSHandler(HTTPSHandler):
    def __init__(self, resolver: Resolver):
        super().__init__()
        self._resolver = resolver

    def https_open(self, req):  # noqa: ANN001
        resolver = self._resolver

        def connection(host, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, **kwargs):  # noqa: ANN001
            conn = http.client.HTTPSConnection(host, timeout=timeout, **kwargs)
            conn._create_connection = (  # type: ignore[method-assign]
                lambda address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None:
                _connect_public(address, timeout, source_address, resolver)
            )
            return conn

        return self.do_open(
            connection,
            req,
            context=self._context,
            check_hostname=self._check_hostname,
        )


def _response_peer_ip(response: object) -> str:
    fp = getattr(response, "fp", None)
    candidates = [
        getattr(getattr(fp, "raw", None), "_sock", None),
        getattr(fp, "_sock", None),
        getattr(getattr(getattr(fp, "raw", None), "_connection", None), "sock", None),
    ]
    for sock_obj in candidates:
        if sock_obj is None:
            continue
        try:
            peer = sock_obj.getpeername()
        except OSError:
            continue
        if peer:
            return str(peer[0])
    raise UnsafeResourceError("could not verify connected peer IP")


@dataclass(frozen=True)
class SafeDownload:
    url: str
    content_type: str
    payload: bytes


def download_public_resource(
    url: str,
    *,
    max_bytes: int,
    timeout: float,
    user_agent: str,
    allowed_types: Iterable[str] = (),
    allowed_type_prefixes: Iterable[str] = (),
    resolver: Resolver = socket.getaddrinfo,
) -> SafeDownload:
    """Download a bounded public HTTP(S) resource with SSRF defenses.

    Proxies are deliberately disabled: otherwise an attacker could ask a public
    proxy to fetch a private destination after this process validated only the
    proxy's public peer. Every redirect is revalidated. Connections are pinned to
    numeric public DNS answers, so the HTTP stack cannot perform a second,
    attacker-controlled DNS lookup between validation and connect.
    """

    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    validate_remote_url(url, resolver=resolver)
    opener = build_opener(
        ProxyHandler({}),
        _SafeRedirectHandler(resolver),
        _PinnedHTTPHandler(resolver),
        _PinnedHTTPSHandler(resolver),
    )
    request = Request(url, headers={"User-Agent": user_agent})
    try:
        with opener.open(request, timeout=timeout) as response:
            final_url = response.geturl()
            validate_remote_url(final_url, resolver=resolver)
            _public_ip(_response_peer_ip(response))
            status = int(getattr(response, "status", 200) or 200)
            if status >= 400:
                raise RuntimeError(f"HTTP {status}")
            headers = getattr(response, "headers", None)
            declared = headers.get("content-length") if headers is not None else None
            if declared and str(declared).isdigit() and int(declared) > max_bytes:
                raise UnsafeResourceError(
                    f"remote resource too large ({declared} bytes > {max_bytes} cap)"
                )
            content_type = ""
            if headers is not None:
                content_type = str(headers.get("content-type", "") or "")
            content_type = content_type.split(";", 1)[0].strip().lower()
            exact = {value.lower() for value in allowed_types}
            prefixes = tuple(value.lower() for value in allowed_type_prefixes)
            if (exact or prefixes) and content_type not in exact and not content_type.startswith(prefixes):
                raise UnsafeResourceError(
                    f"remote resource content type is not allowed: {content_type or 'unknown'}"
                )
            out = BytesIO()
            size = 0
            while True:
                chunk = response.read(min(1024 * 1024, max_bytes - size + 1))
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise UnsafeResourceError(
                        f"remote resource exceeds {max_bytes}-byte cap"
                    )
                out.write(chunk)
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc
    payload = out.getvalue()
    if not payload:
        raise UnsafeResourceError("remote resource is empty")
    return SafeDownload(url=final_url, content_type=content_type, payload=payload)
