package io.github.tuxindrive.mobile

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.documentfile.provider.DocumentFile
import androidx.work.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.TimeUnit
import org.json.JSONObject

class MobileSyncWorker(
    appContext: Context,
    parameters: WorkerParameters,
) : CoroutineWorker(appContext, parameters) {
    private val repository = (appContext.applicationContext as TuxInDriveMobileApp).repository
    private val preferences = appContext.getSharedPreferences("mobile-state", Context.MODE_PRIVATE)

    override suspend fun doWork(): Result = syncMutex.withLock { withContext(Dispatchers.IO) {
        setForeground(foregroundInfo("Preparing synchronization…"))
        val treeValue = repository.selectedTree()
        val remote = repository.syncRemote()
        if (treeValue.isBlank() || remote.isBlank()) {
            return@withContext failure("Choose an offline folder and cloud account first")
        }
        val tree = DocumentFile.fromTreeUri(applicationContext, Uri.parse(treeValue))
            ?: return@withContext failure("The selected Android folder is no longer available")
        val root = File(applicationContext.noBackupFilesDir, "sync")
        val mirror = File(root, "mirror")
        val baseline = File(root, "baseline.ready")
        val workdir = File(root, "bisync")
        val indexFile = File(root, "android-tree-index.json")
        return@withContext runCatching {
            mirror.mkdirs()
            val previous = loadIndex(indexFile)
            val documents = snapshotDocuments(tree)
            updateMirrorFromDocuments(documents, mirror, previous)
            setForeground(foregroundInfo("Synchronizing cloud files…"))
            repository.runBisync(mirror, remote, repository.syncRemotePath(), workdir, !baseline.exists())
            setForeground(foregroundInfo("Updating offline folder…"))
            val completed = updateDocumentsFromMirror(mirror, tree, documents, previous)
            saveIndex(indexFile, completed)
            baseline.parentFile?.mkdirs()
            baseline.writeText("ready\n")
            success("Synchronization complete")
        }.getOrElse { error ->
            failure(error.message ?: "Synchronization failed")
        }
    } }

    private data class DocumentNode(val document: DocumentFile, val directory: Boolean, val size: Long, val modified: Long)
    private data class IndexEntry(
        val documentSize: Long, val documentModified: Long,
        val mirrorSize: Long, val mirrorModified: Long, val sha256: String,
    )

    /** Enumerate the Android provider exactly once for this synchronization. */
    private fun snapshotDocuments(root: DocumentFile): MutableMap<String, DocumentNode> {
        val result = mutableMapOf<String, DocumentNode>()
        fun visit(directory: DocumentFile, prefix: String) {
            for (document in directory.listFiles()) {
                val name = document.name ?: continue
                if (name in setOf(".", "..") || '/' in name || '\\' in name) continue
                val path = if (prefix.isBlank()) name else "$prefix/$name"
                if (document.isDirectory) {
                    result[path] = DocumentNode(document, true, 0, document.lastModified())
                    visit(document, path)
                } else if (document.isFile) {
                    result[path] = DocumentNode(document, false, document.length(), document.lastModified())
                }
            }
        }
        visit(root, "")
        return result
    }

    private fun fileMetadata(file: File): Pair<Long, Long> = file.length() to file.lastModified()

    private fun unchanged(node: DocumentNode, file: File, previous: IndexEntry?): Boolean {
        if (previous == null || node.modified <= 0 || !file.isFile) return false
        val (size, modified) = fileMetadata(file)
        return MobileValidation.canReuseIndexedFile(
            node.size, node.modified, size, modified,
            previous.documentSize, previous.documentModified,
            previous.mirrorSize, previous.mirrorModified,
        )
    }

    private fun updateMirrorFromDocuments(
        documents: Map<String, DocumentNode>, mirror: File, previous: Map<String, IndexEntry>,
    ) {
        val currentFiles = documents.filterValues { !it.directory }.keys
        val before = mirror.walkTopDown().filter { it.isFile }.map { it.relativeTo(mirror).invariantSeparatorsPath }.toSet()
        val removed = before - currentFiles
        if (removed.size >= 10 && removed.size * 100 > before.size.coerceAtLeast(1) * 25) {
            throw RcloneException("Safety stop: local changes would remove too many cloud files")
        }
        documents.filterValues { it.directory }.keys.sortedBy { it.count { char -> char == '/' } }
            .forEach { File(mirror, it).mkdirs() }
        for ((path, node) in documents) {
            if (node.directory) continue
            val target = File(mirror, path)
            if (unchanged(node, target, previous[path])) continue
            target.parentFile?.mkdirs()
            applicationContext.contentResolver.openInputStream(node.document.uri).use { input ->
                requireNotNull(input) { "Could not read $path" }
                target.outputStream().use { output -> input.copyTo(output) }
            }
        }
        removed.sortedByDescending { it.count { char -> char == '/' } }.forEach { File(mirror, it).delete() }
        mirror.walkBottomUp().filter { it != mirror && it.isDirectory && it.list().isNullOrEmpty() }.forEach { it.delete() }
    }

    private fun updateDocumentsFromMirror(
        mirror: File,
        tree: DocumentFile,
        documents: MutableMap<String, DocumentNode>,
        previous: Map<String, IndexEntry>,
    ): Map<String, IndexEntry> {
        val mirrorFiles = mirror.walkTopDown().filter { it.isFile }
            .associateBy { it.relativeTo(mirror).invariantSeparatorsPath }
        val mirrorDirectories = mirror.walkTopDown()
            .filter { it != mirror && it.isDirectory }
            .map { it.relativeTo(mirror).invariantSeparatorsPath }
            .toSet()
        val existingFiles = documents.filterValues { !it.directory }.keys
        val removedFiles = existingFiles - mirrorFiles.keys
        if (removedFiles.size >= 10 && removedFiles.size * 100 > existingFiles.size.coerceAtLeast(1) * 25) {
            throw RcloneException("Safety stop: cloud changes would remove too many Android files")
        }
        val directories = mutableMapOf("" to tree)
        documents.filterValues { it.directory }.forEach { (path, node) -> directories[path] = node.document }

        fun directory(path: String): DocumentFile {
            directories[path]?.let { return it }
            val parentPath = path.substringBeforeLast('/', "")
            val name = path.substringAfterLast('/')
            val parent = directory(parentPath)
            val current = documents[path]?.document
            if (current != null && !current.isDirectory) current.delete()
            return (current?.takeIf { it.isDirectory } ?: parent.createDirectory(name))
                ?.also { directories[path] = it }
                ?: throw RcloneException("Could not create $path")
        }

        mirrorDirectories.sortedBy { it.count { char -> char == '/' } }.forEach(::directory)

        val completed = mutableMapOf<String, IndexEntry>()
        for ((path, local) in mirrorFiles) {
            val parentPath = path.substringBeforeLast('/', "")
            val name = path.substringAfterLast('/')
            val oldNode = documents[path]
            val oldIndex = previous[path]
            val mirrorMetadata = fileMetadata(local)
            val canSkip = oldNode != null && !oldNode.directory && oldIndex != null &&
                MobileValidation.canReuseIndexedFile(
                    oldNode.size, oldNode.modified, mirrorMetadata.first, mirrorMetadata.second,
                    oldIndex.documentSize, oldIndex.documentModified,
                    oldIndex.mirrorSize, oldIndex.mirrorModified,
                )
            val document = if (canSkip) oldNode!!.document else {
                val parent = directory(parentPath)
                if (oldNode?.directory == true) oldNode.document.delete()
                val target = oldNode?.document?.takeIf { it.isFile }
                    ?: parent.createFile("application/octet-stream", name)
                    ?: throw RcloneException("Could not create $path")
                applicationContext.contentResolver.openOutputStream(target.uri, "rwt").use { output ->
                    requireNotNull(output) { "Could not write $path" }
                    local.inputStream().use { input -> input.copyTo(output) }
                }
                target
            }
            completed[path] = IndexEntry(
                document.length(), document.lastModified(), mirrorMetadata.first,
                mirrorMetadata.second, oldIndex?.sha256?.takeIf { canSkip } ?: sha256(local),
            )
        }
        val removedDocuments = documents.keys - mirrorFiles.keys - mirrorDirectories
        val removalRoots = removedDocuments.filter { candidate ->
            removedDocuments.none { other -> other != candidate && candidate.startsWith("$other/") }
        }
        removalRoots.forEach { documents[it]?.document?.delete() }
        return completed
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(64 * 1024)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                digest.update(buffer, 0, count)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun loadIndex(file: File): Map<String, IndexEntry> = runCatching {
        val root = JSONObject(file.readText())
        val entries = root.getJSONObject("entries")
        entries.keys().asSequence().associateWith { path ->
            val item = entries.getJSONObject(path)
            IndexEntry(
                item.getLong("documentSize"), item.getLong("documentModified"),
                item.getLong("mirrorSize"), item.getLong("mirrorModified"),
                item.optString("sha256"),
            )
        }
    }.getOrDefault(emptyMap())

    private fun saveIndex(file: File, entries: Map<String, IndexEntry>) {
        val values = JSONObject()
        for ((path, item) in entries) {
            values.put(path, JSONObject()
                .put("documentSize", item.documentSize).put("documentModified", item.documentModified)
                .put("mirrorSize", item.mirrorSize).put("mirrorModified", item.mirrorModified)
                .put("sha256", item.sha256))
        }
        file.parentFile?.mkdirs()
        val temporary = File(file.parentFile, "${file.name}.new")
        temporary.writeText(JSONObject().put("version", 1).put("entries", values).toString())
        if (!temporary.renameTo(file)) {
            temporary.copyTo(file, overwrite = true)
            temporary.delete()
        }
    }

    private fun success(message: String): Result {
        preferences.edit().putString("last-sync-status", message).apply()
        return Result.success()
    }

    private fun failure(message: String): Result {
        preferences.edit().putString("last-sync-status", message).apply()
        return Result.failure()
    }

    private fun foregroundInfo(message: String): ForegroundInfo {
        val manager = applicationContext.getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL, "TuxInDrive synchronization", NotificationManager.IMPORTANCE_LOW),
            )
        }
        val notification = NotificationCompat.Builder(applicationContext, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setContentTitle("TuxInDrive")
            .setContentText(message)
            .setOngoing(true)
            .build()
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ForegroundInfo(
                NOTIFICATION_ID,
                notification,
                android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC,
            )
        } else {
            ForegroundInfo(NOTIFICATION_ID, notification)
        }
    }

    companion object {
        private const val CHANNEL = "tuxindrive-sync"
        private const val NOTIFICATION_ID = 253
        private val syncMutex = Mutex()

        fun enqueue(context: Context, wifiOnly: Boolean, chargingOnly: Boolean) {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(if (wifiOnly) NetworkType.UNMETERED else NetworkType.CONNECTED)
                .setRequiresCharging(chargingOnly)
                .build()
            val request = OneTimeWorkRequestBuilder<MobileSyncWorker>()
                .setConstraints(constraints)
                .build()
            WorkManager.getInstance(context).enqueueUniqueWork(
                "tuxindrive-mobile-sync",
                ExistingWorkPolicy.KEEP,
                request,
            )
        }

        fun schedule(context: Context, enabled: Boolean, wifiOnly: Boolean, chargingOnly: Boolean) {
            val manager = WorkManager.getInstance(context)
            if (!enabled) {
                manager.cancelUniqueWork("tuxindrive-mobile-periodic-sync")
                return
            }
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(if (wifiOnly) NetworkType.UNMETERED else NetworkType.CONNECTED)
                .setRequiresCharging(chargingOnly)
                .build()
            val request = PeriodicWorkRequestBuilder<MobileSyncWorker>(15, TimeUnit.MINUTES)
                .setConstraints(constraints)
                .build()
            manager.enqueueUniquePeriodicWork(
                "tuxindrive-mobile-periodic-sync",
                ExistingPeriodicWorkPolicy.UPDATE,
                request,
            )
        }
    }
}
