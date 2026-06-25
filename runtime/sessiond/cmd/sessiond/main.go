package main

import (
	"fmt"
	"io"
	"log/slog"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"

	"github.com/creack/pty"

	"cla.local/sessionwire"
)

func main() {
	if os.Geteuid() == 0 {
		slog.Error("cla-sessiond refuses to run as root")
		os.Exit(1)
	}
	addr := env("CLA_SESSIOND_ADDR", "127.0.0.1:7777")
	listener, err := net.Listen("tcp", addr)
	if err != nil {
		slog.Error("listen failed", "error", err)
		os.Exit(1)
	}
	slog.Info("cla-sessiond listening", "addr", addr)
	for {
		conn, err := listener.Accept()
		if err != nil {
			continue
		}
		go servePTY(conn)
	}
}

func servePTY(conn net.Conn) {
	defer conn.Close()
	shell := env("CLA_WORKSPACE_SHELL", "/bin/bash")
	workspace, err := workspaceDir()
	if err != nil {
		slog.Error("workspace directory rejected", "error", err)
		return
	}
	cmd := exec.Command(shell)
	cmd.Dir = workspace
	cmd.Env = append(
		os.Environ(),
		"CLA_SESSIOND=1",
		"HOME="+workspace,
		"PWD="+workspace,
		"BASH_SILENCE_DEPRECATION_WARNING=1",
	)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setctty: true, Setsid: true}
	ptmx, err := pty.Start(cmd)
	if err != nil {
		slog.Error("pty start failed", "workspace", workspace, "error", err)
		return
	}
	defer ptmx.Close()
	go readGatewayFrames(conn, ptmx)
	_, _ = io.Copy(conn, ptmx)
	_ = cmd.Process.Kill()
}

func readGatewayFrames(conn net.Conn, ptmx *os.File) {
	for {
		frameType, payload, err := sessionwire.ReadFrame(conn)
		if err != nil {
			return
		}
		switch frameType {
		case sessionwire.FrameStdin:
			_, _ = ptmx.Write(payload)
		case sessionwire.FrameResize:
			resize, err := sessionwire.DecodeResize(payload)
			if err != nil {
				continue
			}
			_ = pty.Setsize(ptmx, &pty.Winsize{
				Cols: uint16(resize.Cols),
				Rows: uint16(resize.Rows),
			})
		default:
			return
		}
	}
}

func env(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

func workspaceDir() (string, error) {
	dir := env("CLA_WORKSPACE_DIR", "/workspace")
	abs, err := filepath.Abs(filepath.Clean(dir))
	if err != nil {
		return "", err
	}
	if unsafeWorkspaceDir(abs) {
		return "", fmt.Errorf("CLA_WORKSPACE_DIR must be a dedicated lab directory, got %s", abs)
	}
	if err := os.MkdirAll(abs, 0o750); err != nil {
		return "", err
	}
	return abs, nil
}

func unsafeWorkspaceDir(abs string) bool {
	forbidden := map[string]bool{
		"/":            true,
		"/tmp":         true,
		"/private/tmp": true,
	}
	if temp, err := filepath.Abs(filepath.Clean(os.TempDir())); err == nil {
		forbidden[temp] = true
	}
	return forbidden[abs]
}
