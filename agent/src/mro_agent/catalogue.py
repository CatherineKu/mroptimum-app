"""Approved scientific profiles.

Profiles are intentionally constrained versions of configurations represented in
chloe-mroptimum-tools.  They are not an interface for arbitrary calculation JSON.
"""

from .models import ExperimentProfile


PROFILES: dict[str, ExperimentProfile] = {
    "ac_rss": ExperimentProfile(
        profile_id="ac_rss",
        title="Analytical SNR (RSS)",
        method="ac",
        reconstructor="rss",
        requires_noise=True,
        description="Analytical/Kellman SNR using registered signal and noise inputs.",
        output={"coilsensitivity": False, "gfactor": False, "matlab": True},
    ),
    "ac_rss_fa90": ExperimentProfile(
        profile_id="ac_rss_fa90",
        title="Analytical SNR at 90 degrees (RSS)",
        method="ac",
        reconstructor="rss",
        requires_noise=True,
        requires_flip_angle=True,
        description="AC/RSS SNR with a registered flip-angle map in degrees.",
        output={"coilsensitivity": False, "gfactor": False, "matlab": True},
    ),
    "mr_rss": ExperimentProfile(
        profile_id="mr_rss",
        title="Multiple-replica SNR (RSS)",
        method="mr",
        reconstructor="rss",
        requires_replicas=True,
        description="Multiple-replica SNR using a signal dataset with repeated acquisitions.",
        output={"coilsensitivity": False, "gfactor": False, "matlab": True},
    ),
}


def list_profiles() -> list[dict]:
    return [profile.public_summary() for profile in PROFILES.values()]
