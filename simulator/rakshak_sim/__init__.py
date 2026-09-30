"""Rakshak device simulator: a virtual hub + tags that speak the real wire protocol.

Everything produced here is SIMULATED. It uses the production codec (AES-256-GCM frames, SHA-256 hash chain)
and the same edge rules as the hub firmware, so the backend cannot tell it from hardware.
"""

__version__ = "0.1.0"
