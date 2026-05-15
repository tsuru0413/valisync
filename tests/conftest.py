"""Shared test fixtures and Hypothesis configuration."""

from hypothesis import settings

# Default profile: fast feedback during development
settings.register_profile("default", max_examples=200)

# CI profile: more thorough testing
settings.register_profile("ci", max_examples=500)

settings.load_profile("default")
