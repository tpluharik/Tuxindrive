from tests import signal_safety as _signal_safety  # noqa: F401

import unittest

from tuxindrive.profile_qr import (
    ProfileQrError,
    decode_profile_frames,
    encode_profile_frames,
)


class ProfileQrTests(unittest.TestCase):
    def test_round_trip_accepts_frames_in_any_order_and_deduplicates(self):
        payload = (b"encrypted-profile-content" * 500) + bytes(range(256))
        frames = encode_profile_frames(payload, chunk_size=256)
        supplied = list(reversed(frames)) + [frames[0]]
        self.assertEqual(decode_profile_frames(supplied), payload)

    def test_protocol_has_a_stable_cross_platform_frame(self):
        self.assertEqual(
            encode_profile_frames(b"cross-platform-profile", chunk_size=256),
            [
                "TUXINDRIVE-PROFILE/1/6d353e2ec2700baa/1/1/"
                "6d353e2ec2700baa6f76dfe31dce1e8637b205e81e26d505f899c92603c9ba1f/"
                "eNpLLsovLtYtyEksScsvytUtKMpPy8xJBQBl9Qjb"
            ],
        )

    def test_incomplete_mixed_tampered_and_oversized_transfers_are_rejected(self):
        frames = encode_profile_frames(bytes(range(256)) * 30, chunk_size=256)
        with self.assertRaises(ProfileQrError):
            decode_profile_frames(frames[:-1])
        other = encode_profile_frames(b"other profile", chunk_size=256)[0]
        with self.assertRaises(ProfileQrError):
            decode_profile_frames([frames[0], other])
        tampered = frames.copy()
        tampered[-1] = tampered[-1][:-1] + ("A" if tampered[-1][-1] != "A" else "B")
        with self.assertRaises(ProfileQrError):
            decode_profile_frames(tampered)
        with self.assertRaises(ProfileQrError):
            encode_profile_frames(b"x" * (2 * 1024 * 1024 + 1))


if __name__ == "__main__":
    unittest.main()
