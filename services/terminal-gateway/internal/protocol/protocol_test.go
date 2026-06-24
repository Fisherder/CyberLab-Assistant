package protocol

import "testing"

func TestFrameTypeValuesAreStable(t *testing.T) {
	cases := map[string]byte{
		"ClientStdin":     ClientStdin,
		"ClientResize":    ClientResize,
		"ClientAck":       ClientAck,
		"ClientHeartbeat": ClientHeartbeat,
		"ServerStdout":    ServerStdout,
		"ServerStatus":    ServerStatus,
		"ServerReplay":    ServerReplay,
		"ServerError":     ServerError,
	}
	expected := map[string]byte{
		"ClientStdin":     0x01,
		"ClientResize":    0x02,
		"ClientAck":       0x03,
		"ClientHeartbeat": 0x04,
		"ServerStdout":    0x11,
		"ServerStatus":    0x12,
		"ServerReplay":    0x13,
		"ServerError":     0x1F,
	}
	for name, got := range cases {
		if got != expected[name] {
			t.Fatalf("%s changed: got %#x want %#x", name, got, expected[name])
		}
	}
}

func TestStableErrorCodes(t *testing.T) {
	if ErrTicketExpired != "TERMINAL_TICKET_EXPIRED" {
		t.Fatalf("unexpected ticket error code %q", ErrTicketExpired)
	}
	if ErrReplayGap != "TERMINAL_REPLAY_GAP" {
		t.Fatalf("unexpected replay error code %q", ErrReplayGap)
	}
}

