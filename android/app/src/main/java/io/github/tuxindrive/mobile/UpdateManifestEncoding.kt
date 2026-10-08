package io.github.tuxindrive.mobile

import org.json.JSONObject

/** The exact compact field order signed by scripts/sign-update.py. */
internal object UpdateManifestEncoding {
    fun canonical(version: String, url: String, sha256: String, notes: String, expiresAt: String): ByteArray =
        listOf(
            "expires_at" to expiresAt,
            "notes" to notes,
            "sha256" to sha256,
            "url" to url,
            "version" to version,
        ).joinToString(separator = ",", prefix = "{", postfix = "}") { (key, value) ->
            "${JSONObject.quote(key)}:${JSONObject.quote(value)}"
        }.toByteArray(Charsets.UTF_8)
}
