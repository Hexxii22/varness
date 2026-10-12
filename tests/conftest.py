"""Hypothesis profiles: `ci` (default, bounded runtime) and `deep` (VARNESS_TEST_PROFILE=deep, ~10× inputs)."""

import os

from hypothesis import HealthCheck, settings

settings.register_profile("ci", deadline=None, suppress_health_check=[HealthCheck.too_slow])
settings.register_profile("deep", deadline=None, max_examples=2000, suppress_health_check=[HealthCheck.too_slow])
settings.load_profile(os.environ.get("VARNESS_TEST_PROFILE", "ci"))
