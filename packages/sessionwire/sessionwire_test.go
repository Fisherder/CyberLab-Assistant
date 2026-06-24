package sessionwire

import (
	"bytes"
	"testing"
)

func TestWriteReadFrameRoundTrip(t *testing.T) {
	var buf bytes.Buffer
	if err := WriteStdin(&buf, []byte("whoami\n")); err != nil {
		t.Fatal(err)
	}
	frameType, payload, err := ReadFrame(&buf)
	if err != nil {
		t.Fatal(err)
	}
	if frameType != FrameStdin {
		t.Fatalf("frame type = %#x, want %#x", frameType, FrameStdin)
	}
	if string(payload) != "whoami\n" {
		t.Fatalf("payload = %q", string(payload))
	}
}

func TestWriteDecodeResize(t *testing.T) {
	var buf bytes.Buffer
	if err := WriteResize(&buf, 120, 32); err != nil {
		t.Fatal(err)
	}
	frameType, payload, err := ReadFrame(&buf)
	if err != nil {
		t.Fatal(err)
	}
	if frameType != FrameResize {
		t.Fatalf("frame type = %#x, want %#x", frameType, FrameResize)
	}
	resize, err := DecodeResize(payload)
	if err != nil {
		t.Fatal(err)
	}
	if resize.Cols != 120 || resize.Rows != 32 {
		t.Fatalf("resize = %#v", resize)
	}
}

func TestRejectOversizedFrame(t *testing.T) {
	if err := WriteFrame(&bytes.Buffer{}, FrameStdin, make([]byte, MaxPayloadBytes+1)); err != ErrFrameTooLarge {
		t.Fatalf("err = %v, want ErrFrameTooLarge", err)
	}
}
