package io.github.tuxindrive.mobile

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class MobileValidationTest {
    @Test
    fun bandwidthSyntaxAcceptsSupportedDirectionalValues() {
        assertEquals("10M", MobileValidation.normalizeBandwidth(" 10M "))
        assertEquals("2M:10M", MobileValidation.normalizeBandwidth("2M:10M"))
        assertEquals("", MobileValidation.normalizeBandwidth(" "))
        assertEquals("off", MobileValidation.normalizeBandwidth("off"))
    }

    @Test
    fun bandwidthSyntaxRejectsSchedulesAndMalformedValues() {
        for (value in listOf("1M:2M:3M", "-1M", "1 MiB", "weekday 10M", "off:bad")) {
            assertNull(value, MobileValidation.normalizeBandwidth(value))
        }
    }

    @Test
    fun downloadRateUsesTheDownloadSideAndBinaryUnits() {
        assertEquals(10.0 * 1024 * 1024, MobileValidation.downloadRateBytes("2M:10M"), 0.0)
        assertEquals(1024.0, MobileValidation.downloadRateBytes("1"), 0.0)
        assertEquals(0.0, MobileValidation.downloadRateBytes("2M:off"), 0.0)
        assertEquals(0.0, MobileValidation.downloadRateBytes("bad"), 0.0)
    }

    @Test
    fun automaticBandwidthProtectionReservesHeadroom() {
        assertEquals(
            "8388608B",
            MobileValidation.protectedBandwidth("10M", automatic = true, headroomPercent = 20),
        )
        assertEquals(
            "2M:10M",
            MobileValidation.protectedBandwidth("2M:10M", automatic = false, headroomPercent = 20),
        )
        assertEquals(
            "419430B:2097152B",
            MobileValidation.protectedBandwidth("1M:5M", automatic = true, headroomPercent = 60),
        )
    }

    @Test
    fun versionComparisonIsNumericAndPadsMissingParts() {
        assertTrue(MobileValidation.isNewer("0.10.0", "0.9.9"))
        assertFalse(MobileValidation.isNewer("0.26.6", "0.26.6"))
        assertFalse(MobileValidation.isNewer("0.26", "0.26.0"))
    }

    @Test
    fun invalidVersionsAreRejected() {
        assertThrows(IllegalArgumentException::class.java) {
            MobileValidation.isNewer("0.beta.0", "0.26.6")
        }
    }
}
