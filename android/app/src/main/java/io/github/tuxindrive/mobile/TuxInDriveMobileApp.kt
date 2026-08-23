package io.github.tuxindrive.mobile

import android.app.Application

class TuxInDriveMobileApp : Application() {
    val repository by lazy { MobileRepository(this) }

    override fun onCreate() {
        super.onCreate()
        repository.initialize()
        repository.scheduleAutomaticUpdates()
    }
}
