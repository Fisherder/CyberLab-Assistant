package main

import "testing"

func TestFlowControlAckReleasesPendingBytes(t *testing.T) {
	flow := newFlowControl(1024)
	flow.record(0, 100)
	flow.record(1, 200)

	flow.ack(0)
	if got := flow.pendingBytes(); got != 200 {
		t.Fatalf("pending bytes = %d, want 200", got)
	}

	flow.ack(1)
	if got := flow.pendingBytes(); got != 0 {
		t.Fatalf("pending bytes = %d, want 0", got)
	}
}
