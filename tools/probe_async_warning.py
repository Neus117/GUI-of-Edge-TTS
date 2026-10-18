"""复现/定位 "Task was destroyed but it is pending" 的来源。

用法：python tools/probe_async_warning.py <测试名>
"""

import sys
import warnings

sys.path.insert(0, "tests")

warnings.simplefilter("error", ResourceWarning)

import unittest  # noqa: E402

import context  # noqa: F401,E402


def run(names):
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for name in names:
        suite.addTests(loader.loadTestsFromName(name))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    targets = sys.argv[1:] or [
        "test_engine.SynthesisFlowTests.test_success_writes_audio_and_subtitles",
        "test_engine.SynthesisFlowTests.test_cancel_mid_stream_keeps_nothing",
        "test_engine.SynthesisFlowTests.test_zero_audio_raises_and_cleans_up",
        "test_engine.CancelTests.test_preset_cancel_leaves_no_files",
    ]
    print("running:", targets)
    sys.exit(run(targets))
