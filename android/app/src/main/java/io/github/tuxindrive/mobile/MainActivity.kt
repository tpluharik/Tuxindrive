package io.github.tuxindrive.mobile

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val repository = (application as TuxInDriveMobileApp).repository
        setContent {
            MaterialTheme(
                colorScheme = lightColorScheme(
                    primary = Color(0xFF185ABC),
                    secondary = Color(0xFF4B5EAA),
                    surface = Color(0xFFF8FAFF),
                    background = Color(0xFFF5F7FB),
                ),
            ) { TuxInDriveMobile(repository) }
        }
    }
}

private enum class Destination(val label: String, val icon: ImageVector) {
    Accounts("Accounts", Icons.Outlined.Cloud),
    Sync("Sync", Icons.Outlined.Sync),
    Files("Files", Icons.Outlined.Folder),
    Activity("Activity", Icons.Outlined.History),
    Settings("Settings", Icons.Outlined.Settings),
}

@Composable
private fun TuxInDriveMobile(repository: MobileRepository) {
    var destination by remember { mutableStateOf(Destination.Accounts) }
    val remotes = remember { mutableStateListOf<String>() }
    val events = remember { mutableStateListOf("TuxInDrive mobile started") }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val networkMeter = remember { NetworkUsageMeter(context.applicationContext) }
    var networkUsage by remember { mutableStateOf(networkMeter.current()) }
    var showNetworkUsage by remember { mutableStateOf(repository.showNetworkUsage()) }
    var showActivityLog by remember { mutableStateOf(repository.showActivityLog()) }
    LaunchedEffect(networkMeter, showNetworkUsage) {
        if (showNetworkUsage) {
            while (true) {
                delay(1_000)
                networkUsage = networkMeter.sample()
            }
        }
    }
    DisposableEffect(networkMeter) { onDispose { networkMeter.save() } }
    fun refresh() {
        scope.launch {
            busy = true
            error = ""
            runCatching { withContext(Dispatchers.IO) { repository.remotes() } }
                .onSuccess {
                    remotes.clear()
                    remotes.addAll(it)
                    events.add(0, "Cloud accounts refreshed")
                }
                .onFailure { error = it.message ?: "Cloud engine failed" }
            busy = false
        }
    }
    LaunchedEffect(Unit) { refresh() }
    Scaffold(
        bottomBar = {
            NavigationBar {
                Destination.entries.filter { it != Destination.Activity || showActivityLog }.forEach { item ->
                    NavigationBarItem(
                        selected = destination == item,
                        onClick = { destination = item },
                        icon = { Icon(item.icon, contentDescription = null) },
                        label = { Text(item.label) },
                    )
                }
            }
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            Header(busy)
            if (showNetworkUsage) NetworkMeter(networkUsage) {
                showNetworkUsage = false
                repository.setShowNetworkUsage(false)
            }
            if (error.isNotBlank()) {
                Card(
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer),
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp),
                ) { Text(error, Modifier.padding(14.dp), color = MaterialTheme.colorScheme.onErrorContainer) }
            }
            when (destination) {
                Destination.Accounts -> AccountsScreen(repository, remotes, events, ::refresh)
                Destination.Sync -> SyncScreen(repository, remotes, events)
                Destination.Files -> FilesScreen(repository, remotes, events)
                Destination.Activity -> ActivityScreen(events) {
                    showActivityLog = false
                    repository.setShowActivityLog(false)
                    destination = Destination.Settings
                }
                Destination.Settings -> SettingsScreen(
                    repository,
                    showNetworkUsage,
                    showActivityLog,
                    onShowNetworkUsageChange = {
                        showNetworkUsage = it
                        repository.setShowNetworkUsage(it)
                    },
                    onShowActivityLogChange = {
                        showActivityLog = it
                        repository.setShowActivityLog(it)
                    },
                )
            }
        }
    }
}

@Composable
private fun NetworkMeter(usage: MobileNetworkUsage, onHide: () -> Unit) {
    Card(
        shape = RoundedCornerShape(14.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer),
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
    ) {
        Column(Modifier.padding(horizontal = 14.dp, vertical = 10.dp)) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text(
                    "Network",
                    fontWeight = FontWeight.Bold,
                    style = MaterialTheme.typography.labelLarge,
                    modifier = Modifier.weight(1f),
                )
                TextButton(onClick = onHide) { Text("Hide") }
            }
            if (!usage.available) {
                Text("Traffic counters unavailable", style = MaterialTheme.typography.bodySmall)
            } else {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    NetworkValue("↓ Now", formatRate(usage.downloadRate))
                    NetworkValue("↑ Now", formatRate(usage.uploadRate))
                    NetworkValue("↓ Today", formatBytes(usage.downloadedToday))
                    NetworkValue("↑ Today", formatBytes(usage.uploadedToday))
                }
            }
        }
    }
}

@Composable
private fun NetworkValue(label: String, value: String) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(label, style = MaterialTheme.typography.labelSmall)
        Text(value, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun Header(busy: Boolean) {
    Row(
        Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(Icons.Outlined.Sync, null, Modifier.size(30.dp), tint = MaterialTheme.colorScheme.primary)
        Column(Modifier.padding(start = 12.dp).weight(1f)) {
            Text("TuxInDrive", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Text("Cloud sync for your phone", style = MaterialTheme.typography.bodySmall)
        }
        if (busy) CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 2.dp)
    }
}

@Composable
private fun AccountsScreen(
    repository: MobileRepository,
    remotes: List<String>,
    events: MutableList<String>,
    refresh: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var profilePassword by remember { mutableStateOf("") }
    var configurationPassword by remember { mutableStateOf("") }
    var status by remember { mutableStateOf("") }
    val qrAssembler = remember { ProfileQrAssembler() }
    val importConfig = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) scope.launch {
            runCatching { withContext(Dispatchers.IO) { repository.importConfiguration(uri) } }
                .onSuccess {
                    status = "Raw configuration imported. Unlock it below before using cloud accounts."
                    events.add(0, status)
                }
                .onFailure { status = it.message ?: "Import failed" }
        }
    }
    val importProfile = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) scope.launch {
            runCatching { withContext(Dispatchers.IO) { repository.importProfile(uri, profilePassword) } }
                .onSuccess { accountCount ->
                    status = "Imported, unlocked, and verified $accountCount cloud account(s)"
                    events.add(0, status)
                    refresh()
                }
                .onFailure { status = it.message ?: "Profile import failed" }
        }
    }
    val scanProfileQr = rememberLauncherForActivityResult(ScanContract()) { result ->
        val contents = result.contents
        if (contents != null) {
            runCatching { qrAssembler.add(contents) }
                .onSuccess { progress ->
                    if (progress.profile == null) {
                        status = "Scanned ${progress.received}/${progress.total} encrypted QR frames. Scan the next frame."
                    } else {
                        status = "All ${progress.total} QR frames received; verifying cloud configuration…"
                        scope.launch {
                            val profile = progress.profile
                            runCatching {
                                withContext(Dispatchers.IO) {
                                    repository.importProfile(profile, profilePassword)
                                }
                            }.onSuccess { accountCount ->
                                status = "QR transfer imported, unlocked, and verified $accountCount cloud account(s)"
                                events.add(0, status)
                                qrAssembler.reset()
                                refresh()
                            }.onFailure { status = it.message ?: "QR profile import failed" }
                            profile.fill(0)
                        }
                    }
                }
                .onFailure { status = it.message ?: "QR scan failed" }
        }
    }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            SectionTitle("Cloud accounts", "${remotes.size} connected")
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { importConfig.launch(arrayOf("text/plain", "application/octet-stream")) }) {
                    Text("Import rclone config")
                }
                OutlinedButton(onClick = refresh) { Text("Refresh") }
            }
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = profilePassword,
                onValueChange = { profilePassword = it },
                label = { Text("Profile backup passphrase") },
                leadingIcon = { Icon(Icons.Outlined.Lock, null) },
                visualTransformation = PasswordVisualTransformation(),
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedButton(
                onClick = { importProfile.launch(arrayOf("application/octet-stream", "application/json", "*/*")) },
                enabled = profilePassword.length >= 14,
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Import TuxInDrive-Profile.tdx") }
            Button(
                onClick = {
                    scanProfileQr.launch(
                        ScanOptions()
                            .setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                            .setPrompt("Scan every TuxInDrive profile frame shown on the desktop")
                            .setBeepEnabled(false)
                            .setOrientationLocked(false),
                    )
                },
                enabled = profilePassword.length >= 14,
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Scan encrypted profile QR") }
            OutlinedButton(
                onClick = {
                    qrAssembler.reset()
                    status = "QR scan reset"
                },
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Reset QR scan") }
            HorizontalDivider(Modifier.padding(vertical = 8.dp))
            OutlinedTextField(
                value = configurationPassword,
                onValueChange = { configurationPassword = it },
                label = { Text("Raw rclone configuration password") },
                leadingIcon = { Icon(Icons.Outlined.Key, null) },
                visualTransformation = PasswordVisualTransformation(),
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedButton(onClick = {
                scope.launch {
                    runCatching { withContext(Dispatchers.IO) { repository.unlock(configurationPassword) } }
                        .onSuccess { status = "Configuration unlocked"; refresh() }
                        .onFailure { status = it.message ?: "Unlock failed" }
                }
            }, enabled = configurationPassword.isNotBlank()) { Text("Unlock manually imported rclone config") }
            if (status.isNotBlank()) Text(status, style = MaterialTheme.typography.bodySmall)
        }
        items(remotes) { remote -> CloudCard(remote, "Ready for secure browsing and transfer") }
        if (remotes.isEmpty()) {
            item { EmptyState("No cloud account", "Import an existing encrypted rclone configuration to connect the same providers as desktop TuxInDrive.") }
        }
    }
}

@Composable
private fun SyncScreen(repository: MobileRepository, remotes: List<String>, events: MutableList<String>) {
    var selected by remember(remotes) {
        mutableStateOf(repository.syncRemote().ifBlank { remotes.firstOrNull().orEmpty() })
    }
    var remotePath by remember { mutableStateOf(repository.syncRemotePath()) }
    var wifiOnly by remember { mutableStateOf(repository.wifiOnly()) }
    var chargingOnly by remember { mutableStateOf(repository.chargingOnly()) }
    var automatic by remember { mutableStateOf(repository.automaticSync()) }
    var status by remember { mutableStateOf(repository.lastSyncStatus()) }
    val pickTree = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) {
            repository.selectTree(uri)
            status = "Offline folder selected"
        }
    }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            SectionTitle("Synchronized folder", status)
            OutlinedButton(onClick = { pickTree.launch(null) }, modifier = Modifier.fillMaxWidth()) {
                Text(if (repository.selectedTree().isBlank()) "Choose Android folder" else "Change Android folder")
            }
            OutlinedTextField(
                value = remotePath,
                onValueChange = { remotePath = it },
                label = { Text("Cloud subfolder (optional)") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
        }
        items(remotes) { remote ->
            OutlinedButton(
                onClick = { selected = remote },
                modifier = Modifier.fillMaxWidth(),
            ) { Text(if (selected == remote) "✓ $remote" else remote) }
        }
        item {
            SettingSwitch("Wi-Fi only", "Run on an unmetered network", wifiOnly) { wifiOnly = it }
            Spacer(Modifier.height(8.dp))
            SettingSwitch("Only while charging", "Wait for external power", chargingOnly) { chargingOnly = it }
            Spacer(Modifier.height(8.dp))
            SettingSwitch("Automatic sync", "Run at OS-managed intervals of at least 15 minutes", automatic) {
                automatic = it
                repository.configureAutomaticSync(it, wifiOnly, chargingOnly)
            }
            Spacer(Modifier.height(12.dp))
            Button(
                enabled = selected.isNotBlank() && repository.selectedTree().isNotBlank(),
                onClick = {
                    repository.saveSyncTarget(selected, remotePath)
                    repository.configureAutomaticSync(automatic, wifiOnly, chargingOnly)
                    repository.enqueueSync(wifiOnly, chargingOnly)
                    status = "Synchronization queued safely"
                    events.add(0, status)
                },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Icon(Icons.Outlined.Sync, null)
                Text(" Sync now")
            }
            Text(
                "Two-way synchronization keeps its baseline inside the app, preserves conflicts, and stops before large deletion batches.",
                Modifier.padding(top = 10.dp),
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun FilesScreen(repository: MobileRepository, remotes: List<String>, events: MutableList<String>) {
    var selected by remember(remotes) { mutableStateOf(remotes.firstOrNull().orEmpty()) }
    var cloudItems by remember { mutableStateOf<List<CloudItem>>(emptyList()) }
    var status by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()
    Column(Modifier.fillMaxSize().padding(16.dp)) {
        SectionTitle("Cloud files", if (selected.isBlank()) "Select an account" else selected)
        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.weight(1f)) {
            items(remotes) { remote ->
                OutlinedButton(onClick = { selected = remote }, modifier = Modifier.fillMaxWidth()) { Text(remote) }
            }
            item {
                Button(
                    enabled = selected.isNotBlank(),
                    onClick = {
                        scope.launch {
                            status = "Loading…"
                            runCatching { withContext(Dispatchers.IO) { repository.files(selected) } }
                                .onSuccess { cloudItems = it; status = "${it.size} items"; events.add(0, "$selected listed") }
                                .onFailure { status = it.message ?: "Listing failed" }
                        }
                    },
                ) { Text("Open account") }
                Text(status, Modifier.padding(vertical = 8.dp))
            }
            items(cloudItems) { item ->
                CloudCard(item.name, if (item.isDirectory) "Folder" else formatBytes(item.size))
            }
        }
    }
}

@Composable
private fun ActivityScreen(events: List<String>, onHide: () -> Unit) {
    LazyColumn(
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
        modifier = Modifier.fillMaxSize(),
    ) {
        item {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) { SectionTitle("Activity", "This device") }
                TextButton(onClick = onHide) { Text("Hide") }
            }
        }
        items(events) { event -> CloudCard(event, "Completed") }
    }
}

@Composable
private fun SettingsScreen(
    repository: MobileRepository,
    showNetworkUsage: Boolean,
    showActivityLog: Boolean,
    onShowNetworkUsageChange: (Boolean) -> Unit,
    onShowActivityLogChange: (Boolean) -> Unit,
) {
    var wifiOnly by remember { mutableStateOf(repository.wifiOnly()) }
    var chargingOnly by remember { mutableStateOf(repository.chargingOnly()) }
    var bandwidthLimit by remember { mutableStateOf(repository.bandwidthLimit()) }
    var automaticBandwidth by remember {
        mutableStateOf(repository.automaticBandwidthControl())
    }
    var bandwidthHeadroom by remember {
        mutableStateOf(repository.bandwidthHeadroomPercent().toString())
    }
    var engine by remember { mutableStateOf("Checking…") }
    var updateStatus by remember { mutableStateOf("TuxInDrive ${BuildConfig.VERSION_NAME}") }
    var updateBusy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(Unit) {
        engine = runCatching { withContext(Dispatchers.IO) { repository.engineVersion() } }.getOrElse { "Unavailable" }
    }
    val pickTree = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) repository.selectTree(uri)
    }
    LazyColumn(
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
        modifier = Modifier.fillMaxSize(),
    ) {
        item { SectionTitle("Mobile settings", "rclone $engine") }
        item { SettingSwitch("Wi-Fi only", "Pause automatic transfers on metered mobile data", wifiOnly) { wifiOnly = it } }
        item { SettingSwitch("Only while charging", "Defer background work until power is connected", chargingOnly) { chargingOnly = it } }
        item {
            OutlinedTextField(
                value = bandwidthLimit,
                onValueChange = { value ->
                    bandwidthLimit = value
                    repository.setBandwidthLimit(value)
                },
                label = { Text("Global bandwidth limit") },
                supportingText = { Text("Combined safety target, for example 10M or 2M:10M") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
        }
        item {
            SettingSwitch(
                "Automatic bandwidth protection",
                "Reserve capacity for other apps and avoid filling the connection",
                automaticBandwidth,
            ) { enabled ->
                automaticBandwidth = enabled
                repository.setAutomaticBandwidthControl(enabled)
            }
        }
        item {
            OutlinedTextField(
                value = bandwidthHeadroom,
                onValueChange = { value ->
                    val candidate = value.filter { character -> character.isDigit() }.take(2)
                    if (candidate.isBlank() || (candidate.toIntOrNull() ?: 81) <= 80) {
                        bandwidthHeadroom = candidate
                        candidate.toIntOrNull()?.let(repository::setBandwidthHeadroomPercent)
                    }
                },
                label = { Text("Reserved network headroom (%)") },
                supportingText = { Text("0–80%; default 20%") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
        }
        item {
            SettingSwitch(
                "Show network usage",
                "Display current speed and daily device totals",
                showNetworkUsage,
                onShowNetworkUsageChange,
            )
        }
        item {
            SettingSwitch(
                "Show activity log",
                "Render the Activity destination; hiding it also removes it from navigation",
                showActivityLog,
                onShowActivityLogChange,
            )
        }
        item {
            OutlinedButton(onClick = { pickTree.launch(null) }, modifier = Modifier.fillMaxWidth()) {
                Text(if (repository.selectedTree().isBlank()) "Choose offline files folder" else "Change offline files folder")
            }
        }
        item {
            OutlinedButton(
                enabled = !updateBusy,
                onClick = {
                    scope.launch {
                        updateBusy = true
                        runCatching {
                            withContext(Dispatchers.IO) {
                                val update = repository.checkUpdate() ?: return@withContext null
                                update to repository.downloadUpdate(update)
                            }
                        }.onSuccess { result ->
                            if (result == null) {
                                updateStatus = "TuxInDrive ${BuildConfig.VERSION_NAME} is up to date"
                            } else {
                                updateStatus = "TuxInDrive ${result.first.version} verified; opening installer"
                                repository.installUpdate(result.second)
                            }
                        }.onFailure { updateStatus = it.message ?: "Update check failed" }
                        updateBusy = false
                    }
                },
                modifier = Modifier.fillMaxWidth(),
            ) { Text(if (updateBusy) "Checking and verifying…" else "Check for updates") }
        }
        item { Text(updateStatus, style = MaterialTheme.typography.bodySmall) }
        item {
            Text(
                "Android grants access only to folders you choose. Long transfers use OS-managed background work and remain visible to you.",
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun SettingSwitch(title: String, detail: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Card(shape = RoundedCornerShape(16.dp), modifier = Modifier.fillMaxWidth()) {
        Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(title, fontWeight = FontWeight.SemiBold)
                Text(detail, style = MaterialTheme.typography.bodySmall)
            }
            Switch(checked, onChange)
        }
    }
}

@Composable
private fun SectionTitle(title: String, subtitle: String) {
    Text(title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
    Text(subtitle, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    Spacer(Modifier.height(8.dp))
}

@Composable
private fun CloudCard(title: String, detail: String) {
    Card(
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Outlined.Cloud, null, tint = MaterialTheme.colorScheme.primary)
            Column(Modifier.padding(start = 14.dp)) {
                Text(title, fontWeight = FontWeight.SemiBold)
                Text(detail, style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}

@Composable
private fun EmptyState(title: String, detail: String) {
    Box(Modifier.fillMaxWidth().padding(24.dp), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(title, fontWeight = FontWeight.Bold)
            Text(detail, style = MaterialTheme.typography.bodySmall)
        }
    }
}

private fun formatBytes(size: Long): String {
    var amount = size.coerceAtLeast(0).toDouble()
    val units = arrayOf("B", "KiB", "MiB", "GiB", "TiB")
    var index = 0
    while (amount >= 1024 && index < units.lastIndex) { amount /= 1024; index++ }
    return if (index == 0) "${amount.toLong()} ${units[index]}" else "%.1f %s".format(amount, units[index])
}

private fun formatRate(size: Long) = "${formatBytes(size)}/s"
