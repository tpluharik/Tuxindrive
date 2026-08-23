package io.github.tuxindrive.mobile

import android.content.Context
import android.net.Uri
import org.json.JSONArray
import org.json.JSONObject
import org.rclone.gomobile.Gomobile
import java.io.File

data class CloudItem(
    val name: String,
    val path: String,
    val size: Long,
    val isDirectory: Boolean,
)

class RcloneException(message: String) : RuntimeException(message)

class RcloneCore(private val context: Context) {
    private val configuration = File(context.noBackupFilesDir, "rclone.conf")
    private val credentialStore = MobileCredentialStore(context)
    private var initialized = false

    @Synchronized
    fun initialize() {
        if (initialized) return
        Gomobile.rcloneInitialize()
        initialized = true
        rpc("config/setpath", JSONObject().put("path", configuration.absolutePath))
        if (configuration.isFile) {
            credentialStore.load()?.let { password ->
                runCatching {
                    rpc("config/unlock", JSONObject().put("configPassword", password))
                }.onFailure {
                    credentialStore.clear()
                }
            }
        }
    }

    @Synchronized
    fun close() {
        if (initialized) {
            Gomobile.rcloneFinalize()
            initialized = false
        }
    }

    fun version(): String = rpc("core/version").optString("version", "rclone")

    fun setBandwidthLimit(rate: String) {
        rpc("core/bwlimit", JSONObject().put("rate", rate.ifBlank { "off" }))
    }

    fun importConfiguration(uri: Uri) {
        replaceConfiguration(readConfiguration(uri, 2 * 1024 * 1024))
    }

    fun importProfile(uri: Uri, password: String): Int {
        return importProfile(ProfileImporter(context).import(uri, password))
    }

    fun importProfile(bytes: ByteArray, password: String): Int {
        return importProfile(ProfileImporter.decode(bytes, password))
    }

    private fun importProfile(profile: ImportedProfile): Int {
        require(profile.configuration.size <= 2 * 1024 * 1024) {
            "The cloud configuration exceeds the 2 MiB safety limit"
        }
        val previousConfiguration = configuration.takeIf { it.isFile }?.readBytes()
        val previousPassword = credentialStore.load()
        val temporary = File(configuration.parentFile, "rclone.conf.import")
        temporary.writeBytes(profile.configuration)
        try {
            rpc("config/setpath", JSONObject().put("path", temporary.absolutePath))
            rpc("config/unlock", JSONObject().put("configPassword", profile.configurationPassword))
            val remotes = listRemotes()
            require(remotes.isNotEmpty()) { "The imported profile contains no usable cloud accounts" }
            credentialStore.store(profile.configurationPassword)
            if (!temporary.renameTo(configuration)) {
                temporary.copyTo(configuration, overwrite = true)
                temporary.delete()
            }
            rpc("config/setpath", JSONObject().put("path", configuration.absolutePath))
            rpc("config/unlock", JSONObject().put("configPassword", profile.configurationPassword))
            return remotes.size
        } catch (error: Exception) {
            temporary.delete()
            if (previousConfiguration == null) configuration.delete()
            else configuration.writeBytes(previousConfiguration)
            if (previousPassword == null) credentialStore.clear()
            else runCatching { credentialStore.store(previousPassword) }
            runCatching {
                rpc("config/setpath", JSONObject().put("path", configuration.absolutePath))
                if (previousPassword != null) {
                    rpc("config/unlock", JSONObject().put("configPassword", previousPassword))
                }
            }
            throw error
        }
    }

    private fun readConfiguration(uri: Uri, limit: Int): ByteArray {
        val bytes = context.contentResolver.openInputStream(uri).use { input ->
            requireNotNull(input) { "Selected configuration could not be opened" }
            val output = java.io.ByteArrayOutputStream()
            val buffer = ByteArray(64 * 1024)
            var total = 0
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                total += count
                if (total > limit) throw RcloneException("The configuration exceeds the 2 MiB safety limit")
                output.write(buffer, 0, count)
            }
            output.toByteArray()
        }
        return bytes
    }

    private fun replaceConfiguration(bytes: ByteArray) {
        require(bytes.size <= 2 * 1024 * 1024) { "The cloud configuration exceeds the 2 MiB safety limit" }
        val temporary = File(configuration.parentFile, "rclone.conf.new")
        temporary.writeBytes(bytes)
        if (!temporary.renameTo(configuration)) {
            temporary.copyTo(configuration, overwrite = true)
            temporary.delete()
        }
        credentialStore.clear()
        rpc("config/setpath", JSONObject().put("path", configuration.absolutePath))
    }

    fun unlock(password: String) {
        if (password.isBlank()) throw RcloneException("Enter the configuration password")
        rpc("config/unlock", JSONObject().put("configPassword", password))
        require(listRemotes().isNotEmpty()) { "The configuration contains no usable cloud accounts" }
        credentialStore.store(password)
    }

    fun listRemotes(): List<String> {
        val values = rpc("config/listremotes").optJSONArray("remotes") ?: JSONArray()
        return (0 until values.length()).map { values.getString(it).removeSuffix(":") }
    }

    fun list(remote: String, path: String = ""): List<CloudItem> {
        val input = JSONObject()
            .put("fs", "${remote.removeSuffix(":")}:")
            .put("remote", path)
            .put("opt", JSONObject().put("showHash", false))
        val values = rpc("operations/list", input).optJSONArray("list") ?: JSONArray()
        return (0 until values.length()).map { index ->
            val item = values.getJSONObject(index)
            CloudItem(
                name = item.optString("Name", item.optString("Path")),
                path = item.optString("Path"),
                size = item.optLong("Size"),
                isDirectory = item.optBoolean("IsDir"),
            )
        }.sortedWith(compareBy<CloudItem> { !it.isDirectory }.thenBy { it.name.lowercase() })
    }

    fun bisync(local: File, remote: String, remotePath: String, workDirectory: File, firstRun: Boolean) {
        val preferences = context.getSharedPreferences("mobile-state", Context.MODE_PRIVATE)
        setBandwidthLimit(MobileValidation.protectedBandwidth(
            preferences.getString("global-bandwidth-limit", "10M").orEmpty(),
            preferences.getBoolean("automatic-bandwidth-control", true),
            preferences.getInt("bandwidth-headroom-percent", 20),
        ).orEmpty())
        local.mkdirs()
        workDirectory.mkdirs()
        val destination = "${remote.removeSuffix(":")}:$remotePath"
        val input = JSONObject()
            .put("path1", local.absolutePath)
            .put("path2", destination)
            .put("workdir", workDirectory.absolutePath)
            .put("resilient", true)
            .put("recover", true)
            .put("maxDelete", 25)
            .put("conflictResolve", "none")
            .put("conflictLoser", "num")
            .put("createEmptySrcDirs", true)
        if (firstRun) {
            input.put("resync", true)
            input.put("resyncMode", "newer")
        }
        rpc("sync/bisync", input)
    }

    private fun rpc(method: String, input: JSONObject = JSONObject()): JSONObject {
        initialize()
        val result = Gomobile.rcloneRPC(method, input.toString())
        val output = result.output.orEmpty()
        if (result.status !in 200..299) {
            val message = runCatching {
                JSONObject(output).optString("error").ifBlank { output }
            }.getOrDefault(output)
            throw RcloneException(message.ifBlank { "$method failed (${result.status})" })
        }
        return if (output.isBlank()) JSONObject() else JSONObject(output)
    }
}

class MobileRepository(context: Context) {
    private val appContext = context.applicationContext
    private val core = RcloneCore(appContext)
    private val preferences = appContext.getSharedPreferences("mobile-state", Context.MODE_PRIVATE)
    private val updater = AndroidUpdater(appContext)

    fun initialize() {
        core.initialize()
        core.setBandwidthLimit(effectiveBandwidthLimit())
    }
    fun engineVersion() = core.version()
    fun checkUpdate() = MobileNetworkController.exclusive { updater.check() }
    fun downloadUpdate(update: AndroidUpdate) =
        MobileNetworkController.exclusive { updater.download(update) }
    fun installUpdate(packageFile: File) = updater.openInstaller(packageFile)
    fun updateInstallerIntent(packageFile: File) = updater.installerIntent(packageFile)
    fun importConfiguration(uri: Uri) = core.importConfiguration(uri)
    fun importProfile(uri: Uri, password: String) = core.importProfile(uri, password)
    fun importProfile(bytes: ByteArray, password: String) = core.importProfile(bytes, password)
    fun unlock(password: String) = core.unlock(password)
    fun remotes() = core.listRemotes()
    fun files(remote: String, path: String = "") =
        MobileNetworkController.exclusive { core.list(remote, path) }
    fun selectedTree(): String = preferences.getString("selected-tree", "").orEmpty()

    fun selectTree(uri: Uri) {
        appContext.contentResolver.takePersistableUriPermission(
            uri,
            android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION or
                android.content.Intent.FLAG_GRANT_WRITE_URI_PERMISSION,
        )
        preferences.edit().putString("selected-tree", uri.toString()).apply()
    }

    fun saveSyncTarget(remote: String, remotePath: String) {
        preferences.edit()
            .putString("sync-remote", remote.removeSuffix(":"))
            .putString("sync-remote-path", remotePath.trim('/'))
            .apply()
    }

    fun syncRemote(): String = preferences.getString("sync-remote", "").orEmpty()
    fun syncRemotePath(): String = preferences.getString("sync-remote-path", "").orEmpty()
    fun lastSyncStatus(): String = preferences.getString("last-sync-status", "Not synchronized yet").orEmpty()
    fun wifiOnly(): Boolean = preferences.getBoolean("wifi-only", true)
    fun chargingOnly(): Boolean = preferences.getBoolean("charging-only", false)
    fun automaticSync(): Boolean = preferences.getBoolean("automatic-sync", false)
    fun automaticUpdates(): Boolean = BuildConfig.SELF_UPDATE_ENABLED &&
        preferences.getBoolean("automatic-updates", true)
    fun automaticUpdateStatus(): String =
        preferences.getString("automatic-update-status", "").orEmpty()
    fun pendingUpdatePackage(): Pair<String, File>? {
        val version = preferences.getString("pending-update-version", "").orEmpty()
        val sha256 = preferences.getString("pending-update-sha256", "").orEmpty()
        val path = preferences.getString("pending-update-path", "").orEmpty()
        val packageFile = updater.verifiedCachedPackage(version, sha256, path) ?: return null
        return version to packageFile
    }
    fun showNetworkUsage(): Boolean = preferences.getBoolean("show-network-usage", true)
    fun showActivityLog(): Boolean = preferences.getBoolean("show-activity-log", true)
    fun bandwidthLimit(): String = preferences.getString("global-bandwidth-limit", "10M").orEmpty()
    fun automaticBandwidthControl(): Boolean =
        preferences.getBoolean("automatic-bandwidth-control", true)
    fun bandwidthHeadroomPercent(): Int =
        preferences.getInt("bandwidth-headroom-percent", 20).coerceIn(0, 80)
    private fun effectiveBandwidthLimit(): String = MobileValidation.protectedBandwidth(
        bandwidthLimit(), automaticBandwidthControl(), bandwidthHeadroomPercent(),
    ).orEmpty()

    fun setBandwidthLimit(value: String): Boolean {
        val normalized = MobileValidation.normalizeBandwidth(value) ?: return false
        preferences.edit().putString("global-bandwidth-limit", normalized).apply()
        runCatching { core.setBandwidthLimit(effectiveBandwidthLimit()) }
        return true
    }

    fun setAutomaticBandwidthControl(enabled: Boolean) {
        preferences.edit().putBoolean("automatic-bandwidth-control", enabled).apply()
        runCatching { core.setBandwidthLimit(effectiveBandwidthLimit()) }
    }

    fun setBandwidthHeadroomPercent(value: Int) {
        preferences.edit().putInt("bandwidth-headroom-percent", value.coerceIn(0, 80)).apply()
        runCatching { core.setBandwidthLimit(effectiveBandwidthLimit()) }
    }

    fun setShowNetworkUsage(enabled: Boolean) {
        preferences.edit().putBoolean("show-network-usage", enabled).apply()
    }

    fun setShowActivityLog(enabled: Boolean) {
        preferences.edit().putBoolean("show-activity-log", enabled).apply()
    }

    fun configureAutomaticUpdates(enabled: Boolean, wifiOnly: Boolean) {
        val allowed = BuildConfig.SELF_UPDATE_ENABLED && enabled
        preferences.edit().putBoolean("automatic-updates", allowed).apply()
        AndroidUpdateWorker.schedule(appContext, allowed, wifiOnly)
    }

    fun scheduleAutomaticUpdates() {
        AndroidUpdateWorker.schedule(appContext, automaticUpdates(), wifiOnly())
    }

    fun enqueueSync(wifiOnly: Boolean, chargingOnly: Boolean) {
        preferences.edit()
            .putBoolean("wifi-only", wifiOnly)
            .putBoolean("charging-only", chargingOnly)
            .apply()
        MobileSyncWorker.enqueue(appContext, wifiOnly, chargingOnly)
    }

    fun configureAutomaticSync(enabled: Boolean, wifiOnly: Boolean, chargingOnly: Boolean) {
        preferences.edit()
            .putBoolean("automatic-sync", enabled)
            .putBoolean("wifi-only", wifiOnly)
            .putBoolean("charging-only", chargingOnly)
            .apply()
        MobileSyncWorker.schedule(appContext, enabled, wifiOnly, chargingOnly)
    }

    fun runBisync(
        local: File,
        remote: String,
        remotePath: String,
        workDirectory: File,
        firstRun: Boolean,
    ) = MobileNetworkController.exclusive {
        core.bisync(local, remote, remotePath, workDirectory, firstRun)
    }
}
