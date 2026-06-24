package main

import (
	"testing"
	"time"
)

func TestDurationEnvParsesConfiguredDuration(t *testing.T) {
	t.Setenv("CLA_TEST_DURATION", "30s")
	if got := durationEnv("CLA_TEST_DURATION", time.Minute); got != 30*time.Second {
		t.Fatalf("duration = %s", got)
	}
}

func TestDurationEnvUsesFallbackForMissingOrInvalidValue(t *testing.T) {
	if got := durationEnv("CLA_TEST_MISSING_DURATION", 2*time.Minute); got != 2*time.Minute {
		t.Fatalf("missing duration = %s", got)
	}
	t.Setenv("CLA_TEST_INVALID_DURATION", "soon")
	if got := durationEnv("CLA_TEST_INVALID_DURATION", 3*time.Minute); got != 3*time.Minute {
		t.Fatalf("invalid duration = %s", got)
	}
}
