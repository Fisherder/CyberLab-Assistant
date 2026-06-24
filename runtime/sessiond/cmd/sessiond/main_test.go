package main

import (
	"net"
	"testing"
	"time"

	"github.com/creack/pty"

	"cla.local/sessionwire"
)

func TestEnvFallback(t *testing.T) {
	t.Setenv("CLA_SESSIOND_TEST_VALUE", "")
	if got := env("CLA_SESSIOND_TEST_VALUE", "fallback"); got != "fallback" {
		t.Fatalf("got %q want fallback", got)
	}
}

func TestEnvOverride(t *testing.T) {
	t.Setenv("CLA_SESSIOND_TEST_VALUE", "custom")
	if got := env("CLA_SESSIOND_TEST_VALUE", "fallback"); got != "custom" {
		t.Fatalf("got %q want custom", got)
	}
}

func TestReadGatewayFramesAppliesPTYResize(t *testing.T) {
	ptmx, tty, err := pty.Open()
	if err != nil {
		t.Fatal(err)
	}
	defer ptmx.Close()
	defer tty.Close()
	gateway, sessiond := net.Pipe()
	defer gateway.Close()
	defer sessiond.Close()
	go readGatewayFrames(sessiond, ptmx)

	if err := sessionwire.WriteResize(gateway, 111, 33); err != nil {
		t.Fatal(err)
	}

	deadline := time.Now().Add(2 * time.Second)
	for {
		rows, cols, err := pty.Getsize(ptmx)
		if err == nil && rows == 33 && cols == 111 {
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("pty size rows=%d cols=%d err=%v, want rows=33 cols=111", rows, cols, err)
		}
		time.Sleep(10 * time.Millisecond)
	}
}
