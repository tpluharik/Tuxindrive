from __future__ import annotations

import os
import platform
import stat
import base64
import json
import shutil
from contextlib import contextmanager
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


class UnsafePathError(ValueError):
    """Raised when an untrusted relative path can escape its configured root."""


def _is_reparse_point(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", lambda: False)
    return path.is_symlink() or is_junction()


def safe_relative(value: str | Path) -> Path:
    path = Path(value)
    if not str(value) or path.is_absolute() or not path.parts or ".." in path.parts:
        raise UnsafePathError("Path must remain inside the configured root")
    parts = tuple(part for part in path.parts if part not in {"", "."})
    if not parts:
        raise UnsafePathError("Path must identify an item inside the configured root")
    return Path(*parts)


def confined_path(root: Path, relative: str | Path, *, create_parents: bool = False) -> Path:
    """Return a path beneath root while rejecting symlinked components."""
    root = root.expanduser().resolve(strict=True)
    relative_path = safe_relative(relative)
    if platform.system() == "Windows":
        parent = root
        for component in relative_path.parts[:-1]:
            candidate = parent / component
            if _is_reparse_point(candidate):
                raise UnsafePathError("Reparse-point parents are not allowed")
            if candidate.exists():
                if not candidate.is_dir():
                    raise UnsafePathError("Reparse-point parents are not allowed")
            elif create_parents:
                candidate.mkdir(mode=0o700)
            else:
                raise UnsafePathError("A parent directory does not exist")
            parent = candidate
        final = parent / relative_path.name
        if _is_reparse_point(final):
            raise UnsafePathError("Reparse-point targets are not allowed")
        resolved_parent = parent.resolve(strict=True)
        if root != resolved_parent and root not in resolved_parent.parents:
            raise UnsafePathError("Path escaped its configured root")
        return final
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(root, flags)
    try:
        for component in relative_path.parts[:-1]:
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create_parents:
                    raise UnsafePathError("A parent directory does not exist") from None
                os.mkdir(component, mode=0o700, dir_fd=descriptor)
                child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        final = root / relative_path
        try:
            metadata = os.stat(relative_path.parts[-1], dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            metadata = None
        if metadata is not None and stat.S_ISLNK(metadata.st_mode):
            raise UnsafePathError("Symbolic-link targets are not allowed")
        resolved_parent = final.parent.resolve(strict=True)
        if root != resolved_parent and root not in resolved_parent.parents:
            raise UnsafePathError("Path escaped its configured root")
        return final
    finally:
        os.close(descriptor)


@contextmanager
def confined_parent(root: Path, relative: str | Path, *, create_parents: bool = False):
    """Yield an open, no-follow parent descriptor and a safe final name."""
    root = root.expanduser().resolve(strict=True)
    relative_path = safe_relative(relative)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(root, flags)
    try:
        for component in relative_path.parts[:-1]:
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create_parents:
                    raise UnsafePathError("A parent directory does not exist") from None
                os.mkdir(component, mode=0o700, dir_fd=descriptor)
                child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor, relative_path.name, relative_path
    finally:
        os.close(descriptor)


def ensure_private_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    return path


def prepare_private_file(path: Path) -> Path:
    ensure_private_directory(path.parent)
    descriptor = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    os.close(descriptor)
    os.chmod(path, 0o600)
    return path


def install_confined(source: Path, root: Path, relative: str | Path) -> Path:
    """Atomically copy source below root without following destination symlinks."""
    if platform.system() == "Windows":
        target = confined_path(root, relative, create_parents=True)
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tuxindrive-install")
        try:
            with source.open("rb") as input_file, temporary.open("xb") as output_file:
                shutil.copyfileobj(input_file, output_file)
                output_file.flush()
                os.fsync(output_file.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return target
    with confined_parent(root, relative, create_parents=True) as (parent_fd, name, normalized):
        temporary = f".{name}.{os.getpid()}.tuxindrive-install"
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=parent_fd)
        try:
            with source.open("rb") as input_file, os.fdopen(descriptor, "wb", closefd=False) as output_file:
                shutil.copyfileobj(input_file, output_file)
                output_file.flush()
                os.fsync(output_file.fileno())
            os.replace(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        finally:
            os.close(descriptor)
            try:
                os.unlink(temporary, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
    return root / normalized


def unlink_confined(root: Path, relative: str | Path) -> None:
    if platform.system() == "Windows":
        confined_path(root, relative).unlink(missing_ok=True)
        return
    with confined_parent(root, relative) as (parent_fd, name, _normalized):
        try:
            os.unlink(name, dir_fd=parent_fd)
        except FileNotFoundError:
            pass


def copy_from_confined(root: Path, relative: str | Path, destination: Path) -> None:
    if platform.system() == "Windows":
        source = confined_path(root, relative)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with source.open("rb") as input_file, destination.open("xb") as output_file:
            shutil.copyfileobj(input_file, output_file)
        return
    with confined_parent(root, relative) as (parent_fd, name, _normalized):
        source_fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
        try:
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(source_fd, "rb", closefd=False) as input_file, os.fdopen(descriptor, "wb") as output_file:
                shutil.copyfileobj(input_file, output_file)
        finally:
            os.close(source_fd)


def canonical_json(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_json(value: dict, private_key_path: Path) -> tuple[str, str]:
    private = serialization.load_ssh_private_key(private_key_path.read_bytes(), password=None)
    if not isinstance(private, Ed25519PrivateKey):
        raise ValueError("Delta signing requires an Ed25519 peer identity")
    public = private.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode("ascii")
    signature = private.sign(canonical_json(value))
    return public, base64.b64encode(signature).decode("ascii")


def verify_signed_json(value: dict, public_key: str, signature: str) -> None:
    loaded = serialization.load_ssh_public_key(public_key.encode("ascii"))
    if not isinstance(loaded, Ed25519PublicKey):
        raise ValueError("Delta signer must use Ed25519")
    loaded.verify(base64.b64decode(signature, validate=True), canonical_json(value))
