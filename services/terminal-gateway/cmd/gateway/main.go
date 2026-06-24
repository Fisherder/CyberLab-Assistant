package main

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"errors"
	"log/slog"
	"net"
	"net/http"
	"os"
	"strconv"
	"sync"
	"time"

	"github.com/coder/websocket"
	"github.com/prometheus/client_golang/prometheus/promhttp"

	"cla-platform/services/terminal-gateway/internal/protocol"
	"cla-platform/services/terminal-gateway/internal/tickets"
	"cla.local/sessionwire"
)

type config struct {
	Addr         string
	APIURL       string
	ServiceToken string
	Replay       replayBufferStore
	Metrics      *Metrics
	Recording    recordingSink
}

func main() {
	metrics := DefaultMetrics()
	cfg := config{
		Addr:         env("CLA_GATEWAY_ADDR", ":8081"),
		APIURL:       env("CLA_API_URL", "http://localhost:8000"),
		ServiceToken: env("CLA_INTERNAL_SERVICE_TOKEN", "change-me-internal"),
		Replay:       replayFromEnv(),
		Metrics:      metrics,
		Recording: newTranscriptRecorder(
			env("CLA_API_URL", "http://localhost:8000"),
			env("CLA_INTERNAL_SERVICE_TOKEN", "change-me-internal"),
			metrics,
			intEnv("CLA_RECORDING_QUEUE_SIZE", defaultRecordingQueueSize),
		),
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) { _, _ = w.Write([]byte("ok")) })
	mux.Handle("/metrics", promhttp.Handler())
	mux.HandleFunc("/ws/terminal", terminalHandler(cfg))
	slog.Info("terminal gateway starting", "addr", cfg.Addr)
	if err := http.ListenAndServe(cfg.Addr, mux); err != nil {
		slog.Error("gateway stopped", "error", err)
		os.Exit(1)
	}
}

func terminalHandler(cfg config) http.HandlerFunc {
	consumer := tickets.Client{APIURL: cfg.APIURL, ServiceToken: cfg.ServiceToken}
	replay := cfg.Replay
	if replay == nil {
		replay = newReplayStore(defaultReplayWindow, defaultReplayMaxBytes)
	}
	metrics := cfg.Metrics
	if metrics == nil {
		metrics = DefaultMetrics()
	}
	recording := cfg.Recording
	if recording == nil {
		recording = noopRecorder{}
	}
	return func(w http.ResponseWriter, r *http.Request) {
		lastSeq, wantsReplay, err := parseLastServerSequence(r.URL.Query().Get("last_server_sequence"))
		if err != nil {
			http.Error(w, "invalid last_server_sequence", http.StatusBadRequest)
			return
		}
		if wantsReplay {
			metrics.ObserveReconnect()
		}
		ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
		defer cancel()
		route, err := consumer.Consume(ctx, r.URL.Query().Get("ticket"))
		if err != nil {
			metrics.ObserveTicketReject()
			http.Error(w, "ticket rejected", http.StatusUnauthorized)
			return
		}
		conn, err := websocket.Accept(w, r, &websocket.AcceptOptions{InsecureSkipVerify: true})
		if err != nil {
			return
		}
		defer conn.Close(websocket.StatusNormalClosure, "")
		connCtx, connCancel := context.WithCancel(r.Context())
		defer connCancel()
		writer := &wsWriter{conn: conn}
		flow := newFlowControl(defaultUnackedWindowBytes)
		metrics.ObserveConnectionOpened()
		defer metrics.ObserveConnectionClosed()
		defer func() {
			metrics.AddUnackedBytes(-flow.reset())
		}()

		sessiond, err := net.DialTimeout("tcp", route.SessionRoute.Endpoint, 5*time.Second)
		if err != nil {
			writer.writeJSON(r.Context(), protocol.ServerError, map[string]string{"code": "SESSIOND_UNAVAILABLE"})
			return
		}
		defer sessiond.Close()
		writer.writeJSON(r.Context(), protocol.ServerStatus, map[string]string{"state": "CONNECTED"})
		key := replayKey(route)
		if wantsReplay {
			replayed, gap := replay.replayAfter(key, lastSeq)
			if gap {
				metrics.ObserveReplayGap()
				writer.writeJSON(r.Context(), protocol.ServerError, map[string]any{
					"code":                string(protocol.ErrReplayGap),
					"fullRefreshRequired": true,
				})
			} else if len(replayed) > 0 {
				writeReplay(r.Context(), writer, replayed, metrics)
			}
		}

		go copyPTYToWS(connCtx, writer, replay, flow, metrics, recording, route, key, sessiond)
		copyWSToPTY(connCtx, conn, writer, flow, metrics, recording, route, sessiond)
	}
}

func copyPTYToWS(
	ctx context.Context,
	writer *wsWriter,
	replay replayBufferStore,
	flow *flowControl,
	metrics *Metrics,
	recording recordingSink,
	route tickets.Route,
	key string,
	sessiond net.Conn,
) {
	buf := make([]byte, 32768)
	for {
		if !flow.wait(ctx) {
			return
		}
		n, err := sessiond.Read(buf)
		if err != nil {
			return
		}
		frame := replay.appendOutput(key, buf[:n])
		seq := binary.BigEndian.Uint64(frame[1:9])
		flow.record(seq, len(frame))
		metrics.AddTerminalBytes("stdout", n)
		metrics.AddUnackedBytes(len(frame))
		recording.Enqueue(transcriptSegment{
			AttemptID: route.AttemptID,
			Epoch:     route.SessionEpoch,
			Direction: "OUTPUT",
			SeqFrom:   seq,
			SeqTo:     seq,
			Payload:   buf[:n],
		})
		if err := writer.writeBinary(ctx, frame); err != nil {
			return
		}
	}
}

func writeReplay(ctx context.Context, writer *wsWriter, frames []replayFrame, metrics *Metrics) {
	writer.writeJSON(ctx, protocol.ServerReplay, map[string]any{
		"state":        "REPLAY_BEGIN",
		"fromSequence": frames[0].seq,
		"toSequence":   frames[len(frames)-1].seq,
	})
	for _, frame := range frames {
		if err := writer.writeBinary(ctx, frame.frame); err != nil {
			return
		}
		if len(frame.frame) > 9 {
			metrics.AddTerminalBytes("replay_stdout", len(frame.frame)-9)
		}
	}
	writer.writeJSON(ctx, protocol.ServerReplay, map[string]any{
		"state":        "REPLAY_END",
		"fromSequence": frames[0].seq,
		"toSequence":   frames[len(frames)-1].seq,
	})
}

func copyWSToPTY(
	ctx context.Context,
	conn *websocket.Conn,
	writer *wsWriter,
	flow *flowControl,
	metrics *Metrics,
	recording recordingSink,
	route tickets.Route,
	sessiond net.Conn,
) {
	var inputSeq uint64
	for {
		typ, data, err := conn.Read(ctx)
		if err != nil {
			return
		}
		if typ == websocket.MessageText {
			continue
		}
		if len(data) == 0 {
			continue
		}
		switch data[0] {
		case protocol.ClientStdin:
			if err := sessionwire.WriteStdin(sessiond, data[1:]); err == nil {
				metrics.AddTerminalBytes("stdin", len(data)-1)
				seq := inputSeq
				inputSeq++
				recording.Enqueue(transcriptSegment{
					AttemptID: route.AttemptID,
					Epoch:     route.SessionEpoch,
					Direction: "INPUT",
					SeqFrom:   seq,
					SeqTo:     seq,
					Payload:   data[1:],
				})
			}
		case protocol.ClientResize:
			if err := handleResizeFrame(ctx, writer, sessiond, data[1:]); err != nil {
				writer.writeJSON(ctx, protocol.ServerError, map[string]string{"code": string(protocol.ErrBadFrame)})
			}
		case protocol.ClientAck:
			serverSequence, err := handleAckFrame(data[1:])
			if err != nil {
				writer.writeJSON(ctx, protocol.ServerError, map[string]string{"code": string(protocol.ErrBadFrame)})
				continue
			}
			metrics.AddUnackedBytes(-flow.ack(serverSequence))
		case protocol.ClientHeartbeat:
			if err := handleHeartbeatFrame(ctx, writer, data[1:]); err != nil {
				writer.writeJSON(ctx, protocol.ServerError, map[string]string{"code": string(protocol.ErrBadFrame)})
			}
		default:
			writer.writeJSON(ctx, protocol.ServerError, map[string]string{"code": string(protocol.ErrBadFrame)})
		}
	}
}

type wsWriter struct {
	conn *websocket.Conn
	mu   sync.Mutex
}

func (w *wsWriter) writeBinary(ctx context.Context, frame []byte) error {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.conn.Write(ctx, websocket.MessageBinary, frame)
}

func (w *wsWriter) writeJSON(ctx context.Context, frameType byte, value any) {
	body, _ := json.Marshal(value)
	frame := append([]byte{frameType}, body...)
	_ = w.writeBinary(ctx, frame)
}

type resizeFrame struct {
	Cols int `json:"cols"`
	Rows int `json:"rows"`
}

type ackFrame struct {
	ServerSequence uint64 `json:"serverSequence"`
}

type heartbeatFrame struct {
	ClientTime string `json:"clientTime"`
}

func handleResizeFrame(ctx context.Context, writer *wsWriter, sessiond net.Conn, payload []byte) error {
	var frame resizeFrame
	if err := json.Unmarshal(payload, &frame); err != nil {
		return err
	}
	if frame.Cols <= 0 || frame.Rows <= 0 {
		return errors.New(string(protocol.ErrBadFrame))
	}
	if err := sessionwire.WriteResize(sessiond, frame.Cols, frame.Rows); err != nil {
		return err
	}
	writer.writeJSON(ctx, protocol.ServerStatus, map[string]any{
		"state":          "CONNECTED",
		"resizeObserved": true,
		"cols":           frame.Cols,
		"rows":           frame.Rows,
	})
	return nil
}

func handleAckFrame(payload []byte) (uint64, error) {
	var frame ackFrame
	if err := json.Unmarshal(payload, &frame); err != nil {
		return 0, err
	}
	return frame.ServerSequence, nil
}

func handleHeartbeatFrame(ctx context.Context, writer *wsWriter, payload []byte) error {
	var frame heartbeatFrame
	if err := json.Unmarshal(payload, &frame); err != nil {
		return err
	}
	writer.writeJSON(ctx, protocol.ServerStatus, map[string]any{
		"state":     "CONNECTED",
		"heartbeat": "ok",
	})
	return nil
}

func parseLastServerSequence(value string) (uint64, bool, error) {
	if value == "" {
		return 0, false, nil
	}
	seq, err := strconv.ParseUint(value, 10, 64)
	if err != nil {
		return 0, false, err
	}
	return seq, true, nil
}

func env(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

func intEnv(key string, fallback int) int {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	parsed, err := strconv.Atoi(value)
	if err != nil || parsed <= 0 {
		return fallback
	}
	return parsed
}
