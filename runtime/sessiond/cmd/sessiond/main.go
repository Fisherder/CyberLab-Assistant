package main

import (
	"io"
	"log/slog"
	"net"
	"os"
	"os/exec"
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
	cmd := exec.Command(shell)
	cmd.Dir = env("CLA_WORKSPACE_DIR", "/workspace")
	cmd.Env = append(os.Environ(), "CLA_SESSIOND=1")
	cmd.SysProcAttr = &syscall.SysProcAttr{Setctty: true, Setsid: true}
	ptmx, err := pty.Start(cmd)
	if err != nil {
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
