package main

import (
	"net"
	"os"
	"path/filepath"
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

func TestWorkspaceDirCreatesDedicatedDirectory(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "workspace")
	t.Setenv("CLA_WORKSPACE_DIR", dir)

	got, err := workspaceDir()
	if err != nil {
		t.Fatal(err)
	}
	if got != dir {
		t.Fatalf("workspace dir = %q, want %q", got, dir)
	}
	if info, err := os.Stat(got); err != nil || !info.IsDir() {
		t.Fatalf("workspace dir was not created: info=%v err=%v", info, err)
	}
}

func TestWorkspaceDirRejectsHostTempRoot(t *testing.T) {
	t.Setenv("CLA_WORKSPACE_DIR", "/tmp")
	if got, err := workspaceDir(); err == nil {
		t.Fatalf("workspace dir %q should be rejected", got)
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
