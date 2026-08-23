package io.github.tuxindrive.mobile

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.util.concurrent.TimeUnit

class AndroidUpdateWorker(
    appContext: Context,
    parameters: WorkerParameters,
) : CoroutineWorker(appContext, parameters) {
    private val repository = (appContext.applicationContext as TuxInDriveMobileApp).repository
    private val preferences = appContext.getSharedPreferences("mobile-state", Context.MODE_PRIVATE)

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        if (!BuildConfig.SELF_UPDATE_ENABLED || !repository.automaticUpdates()) {
            return@withContext Result.success()
        }
        val now = System.currentTimeMillis()
        val lastCheck = preferences.getLong("last-automatic-update-check", 0L)
        if (now - lastCheck in 0 until MINIMUM_CHECK_INTERVAL_MILLIS) {
            return@withContext Result.success()
        }
        preferences.edit().putLong("last-automatic-update-check", now).apply()
        runCatching {
            val update = repository.checkUpdate() ?: run {
                preferences.edit()
                    .remove("pending-update-version")
                    .remove("pending-update-path")
                    .remove("pending-update-sha256")
                    .remove("automatic-update-status")
                    .apply()
                return@runCatching
            }
            val packageFile = repository.downloadUpdate(update)
            preferences.edit()
                .putString("pending-update-version", update.version)
                .putString("pending-update-path", packageFile.absolutePath)
                .putString("pending-update-sha256", update.sha256)
                .putString("automatic-update-status", "TuxInDrive ${update.version} is ready to install")
                .apply()
            notifyReady(update, packageFile)
        }.onFailure { error ->
            preferences.edit().putString(
                "automatic-update-status",
                error.message ?: "Automatic update check failed",
            ).apply()
        }
        Result.success()
    }

    private fun notifyReady(update: AndroidUpdate, packageFile: java.io.File) {
        if (
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(
                applicationContext,
                Manifest.permission.POST_NOTIFICATIONS,
            ) != PackageManager.PERMISSION_GRANTED
        ) {
            preferences.edit().putString(
                "automatic-update-status",
                "TuxInDrive ${update.version} is verified; open Settings to install it",
            ).apply()
            return
        }
        val manager = applicationContext.getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            manager.createNotificationChannel(
                NotificationChannel(
                    CHANNEL,
                    "TuxInDrive updates",
                    NotificationManager.IMPORTANCE_HIGH,
                ),
            )
        }
        val install = PendingIntent.getActivity(
            applicationContext,
            update.version.hashCode(),
            repository.updateInstallerIntent(packageFile),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = NotificationCompat.Builder(applicationContext, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_sys_download_done)
            .setContentTitle("TuxInDrive ${update.version} is ready")
            .setContentText("Tap to approve the verified Android update")
            .setStyle(NotificationCompat.BigTextStyle().bigText(
                update.notes.ifBlank { "Tap to approve the verified Android update" },
            ))
            .setContentIntent(install)
            .setAutoCancel(true)
            .setOnlyAlertOnce(true)
            .build()
        manager.notify(NOTIFICATION_ID, notification)
    }

    companion object {
        private const val UNIQUE_WORK = "tuxindrive-android-auto-update"
        private const val IMMEDIATE_WORK = "tuxindrive-android-auto-update-now"
        private const val CHANNEL = "tuxindrive-updates"
        private const val NOTIFICATION_ID = 254
        private const val MINIMUM_CHECK_INTERVAL_MILLIS = 6L * 60L * 60L * 1000L

        fun schedule(context: Context, enabled: Boolean, wifiOnly: Boolean) {
            val manager = WorkManager.getInstance(context)
            if (!enabled || !BuildConfig.SELF_UPDATE_ENABLED) {
                manager.cancelUniqueWork(UNIQUE_WORK)
                manager.cancelUniqueWork(IMMEDIATE_WORK)
                return
            }
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(if (wifiOnly) NetworkType.UNMETERED else NetworkType.CONNECTED)
                .setRequiresBatteryNotLow(true)
                .build()
            val request = PeriodicWorkRequestBuilder<AndroidUpdateWorker>(12, TimeUnit.HOURS)
                .setConstraints(constraints)
                .build()
            val immediate = OneTimeWorkRequestBuilder<AndroidUpdateWorker>()
                .setConstraints(constraints)
                .build()
            manager.enqueueUniqueWork(IMMEDIATE_WORK, ExistingWorkPolicy.KEEP, immediate)
            manager.enqueueUniquePeriodicWork(
                UNIQUE_WORK,
                ExistingPeriodicWorkPolicy.UPDATE,
                request,
            )
        }
    }
}
