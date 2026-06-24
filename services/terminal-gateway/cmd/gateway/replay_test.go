package main

import "testing"

func TestReplayStoreDetectsGapWhenOldFramesAreTrimmed(t *testing.T) {
	store := newReplayStore(defaultReplayWindow, 12)
	key := fakeReplayKey("127.0.0.1:0")
	store.appendOutput(key, []byte("first"))
	store.appendOutput(key, []byte("second"))

	frames, gap := store.replayAfter(key, 0)

	if !gap {
		t.Fatalf("gap = false, frames = %d", len(frames))
	}
}

func TestReplayStoreReturnsFramesAfterLastSequence(t *testing.T) {
	store := newReplayStore(defaultReplayWindow, defaultReplayMaxBytes)
	key := fakeReplayKey("127.0.0.1:0")
	store.appendOutput(key, []byte("first"))
	store.appendOutput(key, []byte("second"))

	frames, gap := store.replayAfter(key, 0)

	if gap {
		t.Fatal("gap = true")
	}
	if len(frames) != 1 {
		t.Fatalf("frames = %d, want 1", len(frames))
	}
	if got := string(frames[0].frame[9:]); got != "second" {
		t.Fatalf("payload = %q, want second", got)
	}
}
