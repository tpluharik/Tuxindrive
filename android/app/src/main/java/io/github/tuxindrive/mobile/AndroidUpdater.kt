package io.github.tuxindrive.mobile

import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider
import org.bouncycastle.crypto.params.Ed25519PublicKeyParameters
import org.bouncycastle.crypto.signers.Ed25519Signer
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest
import java.time.OffsetDateTime
import java.util.Base64

data class AndroidUpdate(val version: String, val url: String, val sha256: String, val notes: String)

class AndroidUpdater(private val context: Context) {
    private val preferences = context.getSharedPreferences("mobile-state", Context.MODE_PRIVATE)
    private var nextDownloadNanos = 0L
    private val manifestUrl =
        "https://raw.githubusercontent.com/tpluharik/TuxInDrive/main/releases/android/latest-v2.json"
    private val publicKey = Base64.getDecoder().decode("3c0BtMjwCmlZR0nw2jdqsAQQm7nYyd68r8BtnK2XzyY=")
    private val trustedPrefix = "https://github.com/tpluharik/Tuxindrive/releases/download/"
    private val maxPackageSize = 1024L * 1024L * 1024L

    fun check(): AndroidUpdate? {
        require(BuildConfig.SELF_UPDATE_ENABLED) { "Self-update is disabled for this distribution" }
        val data = JSONObject(readUrl(manifestUrl, 128 * 1024))
        val version = data.getString("version")
        val url = data.getString("url")
        val sha256 = data.getString("sha256").lowercase()
        val notes = data.optString("notes")
        val expiresAt = data.getString("expires_at")
        val signature = Base64.getDecoder().decode(data.getString("signature"))
        val canonical = listOf(
            "expires_at" to expiresAt,
            "notes" to notes,
            "sha256" to sha256,
            "url" to url,
            "version" to version,
        ).joinToString(prefix = "{", postfix = "}") { (key, value) ->
            "${JSONObject.quote(key)}:${JSONObject.quote(value)}"
        }.toByteArray(Charsets.UTF_8)
        val verifier = Ed25519Signer().apply {
            init(false, Ed25519PublicKeyParameters(publicKey, 0))
            update(canonical, 0, canonical.size)
        }
        require(verifier.verifySignature(signature)) { "The Android update signature is invalid" }
        require(OffsetDateTime.parse(expiresAt).isAfter(OffsetDateTime.now())) { "The Android update channel has expired" }
        require(url.startsWith(trustedPrefix)) { "The Android update URL is not trusted" }
        require(url.substringAfterLast('/') == "TuxInDrive-$version-android.apk") {
            "The Android package filename does not match its signed version"
        }
        require(sha256.matches(Regex("[0-9a-f]{64}"))) { "The Android update checksum is invalid" }
        return AndroidUpdate(version, url, sha256, notes).takeIf {
            MobileValidation.isNewer(it.version, BuildConfig.VERSION_NAME)
        }
    }

    fun download(update: AndroidUpdate): File {
        require(BuildConfig.SELF_UPDATE_ENABLED) { "Self-update is disabled for this distribution" }
        require(isTrustedReleaseUrl(URL(update.url))) { "The Android update URL is not trusted" }
        val directory = File(context.cacheDir, "updates").apply { mkdirs() }
        val target = File(directory, "TuxInDrive-${update.version}-android.apk")
        val part = File(directory, "${target.name}.part")
        if (target.isFile && sha256(target) == update.sha256) return target
        val connection = openTrustedConnection(update.url, manifest = false, readTimeout = 60_000)
        val advertisedLength = connection.contentLengthLong
        require(advertisedLength < 0 || advertisedLength <= maxPackageSize) {
            "The Android update exceeded the 1 GiB limit"
        }
        val digest = MessageDigest.getInstance("SHA-256")
        var received = 0L
        try {
            connection.inputStream.use { input ->
                FileOutputStream(part).use { output ->
                    val buffer = ByteArray(1024 * 1024)
                    while (true) {
                        val count = input.read(buffer)
                        if (count < 0) break
                        throttle(count)
                        received += count
                        require(received <= maxPackageSize) { "The Android update exceeded the 1 GiB limit" }
                        digest.update(buffer, 0, count)
                        output.write(buffer, 0, count)
                    }
                    output.fd.sync()
                }
            }
            require(digest.digest().joinToString("") { "%02x".format(it.toInt() and 0xff) } == update.sha256) {
                "The downloaded Android package failed verification"
            }
            try {
                Files.move(
                    part.toPath(), target.toPath(),
                    StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING,
                )
            } catch (_error: AtomicMoveNotSupportedException) {
                Files.move(part.toPath(), target.toPath(), StandardCopyOption.REPLACE_EXISTING)
            }
            return target
        } catch (error: Exception) {
            part.delete()
            throw error
        } finally {
            connection.disconnect()
        }
    }

    private fun throttle(byteCount: Int) {
        val protected = MobileValidation.protectedBandwidth(
            preferences.getString("global-bandwidth-limit", "10M").orEmpty(),
            preferences.getBoolean("automatic-bandwidth-control", true),
            preferences.getInt("bandwidth-headroom-percent", 20),
        ).orEmpty()
        val rate = MobileValidation.downloadRateBytes(protected)
        if (rate <= 0.0 || byteCount <= 0) return
        val now = System.nanoTime()
        val scheduled = synchronized(this) {
            val start = maxOf(now, nextDownloadNanos)
            nextDownloadNanos = start + ((byteCount / rate) * 1_000_000_000L).toLong()
            start
        }
        val delay = scheduled - now
        if (delay > 0) {
            val millis = delay / 1_000_000L
            val nanos = (delay % 1_000_000L).toInt()
            Thread.sleep(millis, nanos)
        }
    }

    fun openInstaller(packageFile: File) {
        context.startActivity(installerIntent(packageFile))
    }

    fun installerIntent(packageFile: File): Intent {
        require(BuildConfig.SELF_UPDATE_ENABLED) { "Self-update is disabled for this distribution" }
        val updateDirectory = File(context.cacheDir, "updates").canonicalFile
        val verifiedPackage = packageFile.canonicalFile
        require(verifiedPackage.isFile && verifiedPackage.parentFile == updateDirectory) {
            "The Android update package is not in the verified update cache"
        }
        val uri = FileProvider.getUriForFile(context, "${BuildConfig.APPLICATION_ID}.files", verifiedPackage)
        return Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
    }

    fun verifiedCachedPackage(version: String, expectedSha256: String, path: String): File? {
        if (!BuildConfig.SELF_UPDATE_ENABLED || !MobileValidation.isNewer(version, BuildConfig.VERSION_NAME)) {
            return null
        }
        val updateDirectory = File(context.cacheDir, "updates").canonicalFile
        val candidate = runCatching { File(path).canonicalFile }.getOrNull() ?: return null
        if (
            candidate.parentFile != updateDirectory ||
            candidate.name != "TuxInDrive-$version-android.apk" ||
            !candidate.isFile ||
            !expectedSha256.matches(Regex("[0-9a-f]{64}"))
        ) return null
        return candidate.takeIf { sha256(it) == expectedSha256 }
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(1024 * 1024)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                digest.update(buffer, 0, count)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it.toInt() and 0xff) }
    }

    private fun readUrl(url: String, limit: Int): String {
        val connection = openTrustedConnection(url, manifest = true, readTimeout = 20_000)
        val advertisedLength = connection.contentLengthLong
        require(advertisedLength < 0 || advertisedLength <= limit) {
            "The Android update manifest is too large"
        }
        return try {
            connection.inputStream.use { input ->
                val output = java.io.ByteArrayOutputStream()
                val buffer = ByteArray(8192)
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    require(output.size() + count <= limit) { "The Android update manifest is too large" }
                    output.write(buffer, 0, count)
                }
                output.toString(Charsets.UTF_8.name())
            }
        } finally {
            connection.disconnect()
        }
    }

    private fun openTrustedConnection(
        original: String,
        manifest: Boolean,
        readTimeout: Int,
    ): HttpURLConnection {
        var current = URL(original)
        repeat(6) {
            require(if (manifest) isTrustedManifestUrl(current) else isTrustedReleaseUrl(current)) {
                "The Android update redirected to an untrusted origin"
            }
            val connection = current.openConnection() as HttpURLConnection
            connection.instanceFollowRedirects = false
            connection.connectTimeout = 20_000
            connection.readTimeout = readTimeout
            connection.setRequestProperty("User-Agent", "TuxInDrive-Android-Updater")
            when (val status = connection.responseCode) {
                HttpURLConnection.HTTP_MOVED_PERM,
                HttpURLConnection.HTTP_MOVED_TEMP,
                HttpURLConnection.HTTP_SEE_OTHER,
                307,
                308 -> {
                    val location = connection.getHeaderField("Location")
                        ?: error("The Android update redirect has no destination")
                    current = URL(current, location)
                    connection.disconnect()
                }
                in 200..299 -> return connection
                else -> {
                    connection.disconnect()
                    error("The Android update server returned HTTP $status")
                }
            }
        }
        error("The Android update exceeded the redirect limit")
    }

    private fun isTrustedManifestUrl(url: URL): Boolean =
        url.protocol == "https" && url.userInfo == null && url.port == -1 &&
            url.host.equals("raw.githubusercontent.com", ignoreCase = true) &&
            url.path == "/tpluharik/TuxInDrive/main/releases/android/latest-v2.json" &&
            url.query == null && url.ref == null

    private fun isTrustedReleaseUrl(url: URL): Boolean {
        if (url.protocol != "https" || url.userInfo != null || url.port != -1) return false
        val host = url.host.lowercase()
        if (host == "github.com") {
            return url.toString().startsWith(trustedPrefix) && url.query == null && url.ref == null
        }
        return host == "release-assets.githubusercontent.com" || host == "objects.githubusercontent.com"
    }

}
