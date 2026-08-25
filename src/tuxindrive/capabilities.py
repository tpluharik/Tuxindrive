from __future__ import annotations

from dataclasses import dataclass

from .models import Provider, SyncMode


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    browser_oauth: bool
    streaming: bool
    polling: bool
    hashes: bool
    server_move: bool
    share_links: bool
    versions: bool
    notes: str = ""

    def supports_mode(self, mode: SyncMode) -> bool:
        return mode is not SyncMode.VIRTUAL_DRIVE or self.streaming


_DEFAULT = ProviderCapabilities(False, True, True, True, True, False, False)

CAPABILITIES: dict[Provider, ProviderCapabilities] = {
    Provider.GOOGLE_DRIVE: ProviderCapabilities(True, True, True, True, True, True, True, "Shared Drives and Shared with me are separate locations."),
    Provider.ONEDRIVE: ProviderCapabilities(True, True, True, True, True, True, True),
    Provider.DROPBOX: ProviderCapabilities(True, True, True, True, True, True, True),
    Provider.BOX: ProviderCapabilities(True, True, True, True, True, True, True),
    Provider.PCLOUD: ProviderCapabilities(True, True, False, True, True, True, True, "Change polling falls back to scheduled reconciliation."),
    Provider.MEGA: ProviderCapabilities(False, True, False, True, True, True, True, "Credential login; scheduled reconciliation is the safe default."),
    Provider.PROTON_DRIVE: ProviderCapabilities(True, False, False, False, True, False, True, "Official Proton CLI with browser authorization and Secret Service session storage. Scheduled synchronization is supported; streaming is unavailable because Proton exposes no mount API."),
    Provider.NEXTCLOUD: ProviderCapabilities(False, True, False, True, True, True, True, "Capabilities vary with server and WebDAV configuration."),
    Provider.S3: ProviderCapabilities(False, True, False, True, True, True, True, "AWS S3 and compatible endpoints; share links depend on presigned-link support."),
    Provider.WEBDAV: ProviderCapabilities(False, True, False, False, True, False, True, "Server capabilities vary; public-link creation is not standardized by WebDAV."),
    Provider.SFTP: ProviderCapabilities(False, True, False, True, True, False, True, "Password or SSH-agent authentication; public links are not part of SFTP."),
    Provider.GITHUB: ProviderCapabilities(False, False, True, True, True, True, True, "Git-backed repository synchronization; Git history is the version store and files over GitHub's limits are rejected by GitHub."),
    Provider.PEER: ProviderCapabilities(False, False, True, True, True, False, True, "Direct authenticated peer transport with role controls."),
    Provider.VAULT: ProviderCapabilities(False, True, True, False, True, False, True, "Names and content are encrypted before upload."),
}


def capabilities_for(provider: Provider) -> ProviderCapabilities:
    return CAPABILITIES.get(provider, _DEFAULT)
