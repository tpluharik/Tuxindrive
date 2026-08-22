package io.github.tuxindrive.mobile

internal object MobileValidation {
    private val bandwidthPattern =
        Regex("(\\d+(?:\\.\\d+)?)([BKMGTP]?)", RegexOption.IGNORE_CASE)

    fun normalizeBandwidth(value: String): String? {
        val normalized = value.trim()
        if (normalized.isBlank()) return ""
        val parts = normalized.split(':')
        if (parts.size > 2 || parts.any { part ->
                !part.equals("off", ignoreCase = true) && !bandwidthPattern.matches(part)
            }
        ) return null
        return normalized
    }

    fun protectedBandwidth(value: String, automatic: Boolean, headroomPercent: Int): String? {
        val normalized = normalizeBandwidth(value) ?: return null
        if (!automatic || normalized.isBlank()) return normalized
        val factor = (100 - headroomPercent.coerceIn(0, 80)) / 100.0
        return normalized.split(':').joinToString(":") { part ->
            if (part.equals("off", ignoreCase = true)) "off"
            else {
                val match = requireNotNull(bandwidthPattern.matchEntire(part))
                val scale = when (match.groupValues[2].uppercase()) {
                    "B" -> 1.0
                    "K" -> 1024.0
                    "M" -> 1024.0 * 1024.0
                    "G" -> 1024.0 * 1024.0 * 1024.0
                    "T" -> 1024.0 * 1024.0 * 1024.0 * 1024.0
                    "P" -> 1024.0 * 1024.0 * 1024.0 * 1024.0 * 1024.0
                    else -> 1024.0
                }
                val rate = match.groupValues[1].toDouble() * scale
                if (rate <= 0.0) "0B" else "${maxOf(1L, (rate * factor).toLong())}B"
            }
        }
    }

    fun downloadRateBytes(value: String): Double {
        val normalized = normalizeBandwidth(value) ?: return 0.0
        val parts = normalized.split(':')
        val part = if (parts.size == 2) parts[1] else parts[0]
        if (part.isBlank() || part.equals("off", ignoreCase = true)) return 0.0
        val match = bandwidthPattern.matchEntire(part) ?: return 0.0
        val scale = when (match.groupValues[2].uppercase()) {
            "B" -> 1.0
            "K" -> 1024.0
            "M" -> 1024.0 * 1024.0
            "G" -> 1024.0 * 1024.0 * 1024.0
            "T" -> 1024.0 * 1024.0 * 1024.0 * 1024.0
            "P" -> 1024.0 * 1024.0 * 1024.0 * 1024.0 * 1024.0
            else -> 1024.0
        }
        return match.groupValues[1].toDouble() * scale
    }

    fun versionKey(value: String): List<Int> = value.removePrefix("v").split('.').map {
        it.toIntOrNull() ?: throw IllegalArgumentException("Invalid release version")
    }

    fun isNewer(candidate: String, current: String): Boolean {
        val left = versionKey(candidate)
        val right = versionKey(current)
        for (index in 0 until maxOf(left.size, right.size)) {
            val comparison = left.getOrElse(index) { 0 }.compareTo(right.getOrElse(index) { 0 })
            if (comparison != 0) return comparison > 0
        }
        return false
    }
}
