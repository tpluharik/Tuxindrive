package io.github.tuxindrive.mobile

import java.util.Base64
import org.bouncycastle.crypto.params.Ed25519PublicKeyParameters
import org.bouncycastle.crypto.signers.Ed25519Signer
import org.junit.Assert.assertTrue
import org.junit.Test

class UpdateManifestEncodingTest {
    @Test
    fun verifiesManifestPublishedByOfflinePythonSigner() {
        // Public 0.26.68 channel fixture: no private key, process, or network.
        val canonical = UpdateManifestEncoding.canonical(
            "0.26.68",
            "https://github.com/tpluharik/Tuxindrive/releases/download/v0.26.68/TuxInDrive-0.26.68-android.apk",
            "2de16f9ba7b127a6b3be46cf906111d2bf649eddf7daf89fe21511915c74f5fa",
            "Tray alert summaries with direct folder error details",
            "2027-01-04T19:24:51.685772+00:00",
        )
        val publicKey = Base64.getDecoder().decode("3c0BtMjwCmlZR0nw2jdqsAQQm7nYyd68r8BtnK2XzyY=")
        val signature = Base64.getDecoder().decode(
            "j5xcOkYbFBWXwx1PKHpIWnPhdEZUdmgFqB0YK3wycjgl3gMRvSCSGsZFRe8yMx2mM18tGrDshhGhHG5eL/PpBw==",
        )
        val verifier = Ed25519Signer().apply {
            init(false, Ed25519PublicKeyParameters(publicKey, 0))
            update(canonical, 0, canonical.size)
        }
        assertTrue("Android must verify the same compact JSON bytes as the offline signer", verifier.verifySignature(signature))
    }
}
