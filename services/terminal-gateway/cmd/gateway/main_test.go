package main

import (
	"context"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/coder/websocket"
	"github.com/prometheus/client_golang/prometheus"
	io_prometheus_client "github.com/prometheus/client_model/go"

	"cla-platform/services/terminal-gateway/internal/protocol"
	"cla-platform/services/terminal-gateway/internal/tickets"
	"cla.local/sessionwire"
)

func TestTerminalHandlerRelaysBinaryStdinToSessiondAndStdoutBack(t *testing.T) {
	sessiond := newFakeSessiond(t, func(t *testing.T, conn net.Conn) {
		payload := readSessionFrame(t, conn, sessionwire.FrameStdin)
		assertSessionPayload(t, payload, "hello")
		_, _ = conn.Write([]byte("world"))
	})
	api := newFakeTicketAPI(t, sessiond.Addr().String())
	gateway := httptest.NewServer(terminalHandler(config{
		APIURL:       api.URL,
		ServiceToken: "svc-token",
	}))
	defer gateway.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	conn, _, err := websocket.Dial(ctx, wsURL(gateway.URL)+"/ws/terminal?ticket=opaque-ticket", nil)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close(websocket.StatusNormalClosure, "")

	frame := append([]byte{protocol.ClientStdin}, []byte("hello")...)
	if err := conn.Write(ctx, websocket.MessageBinary, frame); err != nil {
		t.Fatal(err)
	}

	status := readFrameType(t, ctx, conn, protocol.ServerStatus)
	if got := status["state"]; got != "CONNECTED" {
		t.Fatalf("status state = %v, want CONNECTED", got)
	}
	stdout := readBinaryFrame(t, ctx, conn, protocol.ServerStdout)
	if len(stdout) < 9 {
		t.Fatalf("stdout frame too short: %d", len(stdout))
	}
	if seq := binary.BigEndian.Uint64(stdout[1:9]); seq != 0 {
		t.Fatalf("stdout sequence = %d, want 0", seq)
	}
	if got := string(stdout[9:]); got != "world" {
		t.Fatalf("stdout payload = %q, want world", got)
	}
}

func TestTerminalHandlerReportsBadFrameWithoutLoggingPayload(t *testing.T) {
	sessiond := newFakeSessiond(t, func(t *testing.T, conn net.Conn) {
		<-time.After(500 * time.Millisecond)
	})
	api := newFakeTicketAPI(t, sessiond.Addr().String())
	gateway := httptest.NewServer(terminalHandler(config{
		APIURL:       api.URL,
		ServiceToken: "svc-token",
	}))
	defer gateway.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	conn, _, err := websocket.Dial(ctx, wsURL(gateway.URL)+"/ws/terminal?ticket=opaque-ticket", nil)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close(websocket.StatusNormalClosure, "")

	if err := conn.Write(ctx, websocket.MessageBinary, []byte{0x7F, 's', 'e', 'c', 'r', 'e', 't'}); err != nil {
		t.Fatal(err)
	}
	readFrameType(t, ctx, conn, protocol.ServerStatus)
	errPayload := readFrameType(t, ctx, conn, protocol.ServerError)
	if got := errPayload["code"]; got != string(protocol.ErrBadFrame) {
		t.Fatalf("error code = %v, want %s", got, protocol.ErrBadFrame)
	}
	if _, leaked := errPayload["payload"]; leaked {
		t.Fatal("error response must not echo terminal payload")
	}
}

func TestTerminalHandlerHandlesControlFramesWithoutWritingThemToSessiond(t *testing.T) {
	sessiond := newFakeSessiond(t, func(t *testing.T, conn net.Conn) {
		resizePayload := readSessionFrame(t, conn, sessionwire.FrameResize)
		resize, err := sessionwire.DecodeResize(resizePayload)
		if err != nil {
			t.Fatal(err)
		}
		if resize.Cols != 100 || resize.Rows != 30 {
			t.Fatalf("resize = %#v, want cols=100 rows=30", resize)
		}
		stdinPayload := readSessionFrame(t, conn, sessionwire.FrameStdin)
		assertSessionPayload(t, stdinPayload, "go")
		_, _ = conn.Write([]byte("ok"))
	})
	api := newFakeTicketAPI(t, sessiond.Addr().String())
	gateway := httptest.NewServer(terminalHandler(config{
		APIURL:       api.URL,
		ServiceToken: "svc-token",
	}))
	defer gateway.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	conn, _, err := websocket.Dial(ctx, wsURL(gateway.URL)+"/ws/terminal?ticket=opaque-ticket", nil)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close(websocket.StatusNormalClosure, "")

	readFrameType(t, ctx, conn, protocol.ServerStatus)
	writeJSONControlFrame(t, ctx, conn, protocol.ClientResize, map[string]int{"cols": 100, "rows": 30})
	status := readStatusWith(t, ctx, conn, "resizeObserved", true)
	if got := status["cols"]; got != float64(100) {
		t.Fatalf("resize cols = %v, want 100", got)
	}
	writeJSONControlFrame(
		t,
		ctx,
		conn,
		protocol.ClientHeartbeat,
		map[string]string{"clientTime": "2026-06-24T00:00:00Z"},
	)
	readStatusWith(t, ctx, conn, "heartbeat", "ok")
	writeJSONControlFrame(t, ctx, conn, protocol.ClientAck, map[string]uint64{"serverSequence": 0})

	frame := append([]byte{protocol.ClientStdin}, []byte("go")...)
	if err := conn.Write(ctx, websocket.MessageBinary, frame); err != nil {
		t.Fatal(err)
	}
	stdout := readBinaryFrame(t, ctx, conn, protocol.ServerStdout)
	if got := string(stdout[9:]); got != "ok" {
		t.Fatalf("stdout payload = %q, want ok", got)
	}
}

func TestTerminalHandlerRecordsConnectionByteAndBackpressureMetrics(t *testing.T) {
	registry := prometheus.NewRegistry()
	metrics := NewMetrics(registry)
	sessiond := newFakeSessiond(t, func(t *testing.T, conn net.Conn) {
		payload := readSessionFrame(t, conn, sessionwire.FrameStdin)
		assertSessionPayload(t, payload, "hello")
		_, _ = conn.Write([]byte("world"))
		<-time.After(500 * time.Millisecond)
	})
	api := newFakeTicketAPI(t, sessiond.Addr().String())
	gateway := httptest.NewServer(terminalHandler(config{
		APIURL:       api.URL,
		ServiceToken: "svc-token",
		Metrics:      metrics,
	}))
	defer gateway.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	conn, _, err := websocket.Dial(ctx, wsURL(gateway.URL)+"/ws/terminal?ticket=opaque-ticket", nil)
	if err != nil {
		t.Fatal(err)
	}

	readFrameType(t, ctx, conn, protocol.ServerStatus)
	if active := metricValue(t, registry, "cla_terminal_gateway_active_connections", nil); active != 1 {
		t.Fatalf("active connections = %f, want 1", active)
	}
	frame := append([]byte{protocol.ClientStdin}, []byte("hello")...)
	if err := conn.Write(ctx, websocket.MessageBinary, frame); err != nil {
		t.Fatal(err)
	}
	stdout := readBinaryFrame(t, ctx, conn, protocol.ServerStdout)
	if got := string(stdout[9:]); got != "world" {
		t.Fatalf("stdout payload = %q, want world", got)
	}
	waitForMetric(t, registry, "cla_terminal_gateway_terminal_bytes_total", map[string]string{"direction": "stdin"}, 5)
	waitForMetric(t, registry, "cla_terminal_gateway_terminal_bytes_total", map[string]string{"direction": "stdout"}, 5)
	if pending := metricValue(t, registry, "cla_terminal_gateway_unacked_window_bytes", nil); pending != float64(len(stdout)) {
		t.Fatalf("unacked bytes = %f, want %d", pending, len(stdout))
	}
	assertNoSensitiveMetricLabels(t, registry)

	writeJSONControlFrame(t, ctx, conn, protocol.ClientAck, map[string]uint64{"serverSequence": 0})
	waitForMetric(t, registry, "cla_terminal_gateway_unacked_window_bytes", nil, 0)
	_ = conn.Close(websocket.StatusNormalClosure, "")
	waitForMetric(t, registry, "cla_terminal_gateway_active_connections", nil, 0)
}

func TestTerminalHandlerRecordsRejectReconnectAndReplayGapMetrics(t *testing.T) {
	registry := prometheus.NewRegistry()
	metrics := NewMetrics(registry)
	rejectingAPI := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, "rejected", http.StatusUnauthorized)
	}))
	defer rejectingAPI.Close()
	rejectingGateway := httptest.NewServer(terminalHandler(config{
		APIURL:       rejectingAPI.URL,
		ServiceToken: "svc-token",
		Metrics:      metrics,
	}))
	defer rejectingGateway.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if _, _, err := websocket.Dial(ctx, wsURL(rejectingGateway.URL)+"/ws/terminal?ticket=bad", nil); err == nil {
		t.Fatal("expected rejected websocket dial")
	}
	if got := metricValue(t, registry, "cla_terminal_gateway_ticket_rejects_total", nil); got != 1 {
		t.Fatalf("ticket rejects = %f, want 1", got)
	}

	sessiond := newFakeSessiond(t, func(t *testing.T, conn net.Conn) {
		<-time.After(500 * time.Millisecond)
	})
	replay := newReplayStore(defaultReplayWindow, 1)
	key := fakeReplayKey(sessiond.Addr().String())
	replay.appendOutput(key, []byte("first"))
	replay.appendOutput(key, []byte("second"))
	api := newFakeTicketAPI(t, sessiond.Addr().String())
	gateway := httptest.NewServer(terminalHandler(config{
		APIURL:       api.URL,
		ServiceToken: "svc-token",
		Replay:       replay,
		Metrics:      metrics,
	}))
	defer gateway.Close()

	conn, _, err := websocket.Dial(ctx, wsURL(gateway.URL)+"/ws/terminal?ticket=opaque-ticket&last_server_sequence=0", nil)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close(websocket.StatusNormalClosure, "")
	readFrameType(t, ctx, conn, protocol.ServerStatus)
	errPayload := readFrameType(t, ctx, conn, protocol.ServerError)
	if got := errPayload["code"]; got != string(protocol.ErrReplayGap) {
		t.Fatalf("replay gap error = %v, want %s", got, protocol.ErrReplayGap)
	}
	if got := metricValue(t, registry, "cla_terminal_gateway_reconnects_total", nil); got != 1 {
		t.Fatalf("reconnects = %f, want 1", got)
	}
	if got := metricValue(t, registry, "cla_terminal_gateway_replay_gaps_total", nil); got != 1 {
		t.Fatalf("replay gaps = %f, want 1", got)
	}
	assertNoSensitiveMetricLabels(t, registry)
}

func TestTerminalHandlerUploadsTranscriptSegmentsAsynchronously(t *testing.T) {
	registry := prometheus.NewRegistry()
	metrics := NewMetrics(registry)
	uploads := make(chan map[string]any, 4)
	sessiond := newFakeSessiond(t, func(t *testing.T, conn net.Conn) {
		payload := readSessionFrame(t, conn, sessionwire.FrameStdin)
		assertSessionPayload(t, payload, "hello")
		_, _ = conn.Write([]byte("world"))
	})
	api := newFakeTicketAndRecordingAPI(t, sessiond.Addr().String(), uploads)
	recorder := newTranscriptRecorder(api.URL, "svc-token", metrics, 16)
	t.Cleanup(recorder.Stop)
	gateway := httptest.NewServer(terminalHandler(config{
		APIURL:       api.URL,
		ServiceToken: "svc-token",
		Metrics:      metrics,
		Recording:    recorder,
	}))
	defer gateway.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	conn, _, err := websocket.Dial(ctx, wsURL(gateway.URL)+"/ws/terminal?ticket=opaque-ticket", nil)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close(websocket.StatusNormalClosure, "")

	readFrameType(t, ctx, conn, protocol.ServerStatus)
	frame := append([]byte{protocol.ClientStdin}, []byte("hello")...)
	if err := conn.Write(ctx, websocket.MessageBinary, frame); err != nil {
		t.Fatal(err)
	}
	stdout := readBinaryFrame(t, ctx, conn, protocol.ServerStdout)
	if got := string(stdout[9:]); got != "world" {
		t.Fatalf("stdout payload = %q, want world", got)
	}

	first := readUpload(t, uploads)
	second := readUpload(t, uploads)
	byDirection := map[string]map[string]any{
		first["direction"].(string):  first,
		second["direction"].(string): second,
	}
	assertUploadedSegment(t, byDirection["INPUT"], 1, "hello")
	assertUploadedSegment(t, byDirection["OUTPUT"], 1, "world")
	if lag := metricValue(t, registry, "cla_terminal_gateway_recording_lag_seconds", nil); lag < 0 {
		t.Fatalf("recording lag = %f", lag)
	}
	assertNoSensitiveMetricLabels(t, registry)
}

func TestTranscriptRecorderRecordsDropAndFailureMetrics(t *testing.T) {
	registry := prometheus.NewRegistry()
	metrics := NewMetrics(registry)
	blocked := &transcriptRecorder{
		metrics: metrics,
		queue:   make(chan transcriptSegment, 1),
	}
	blocked.Enqueue(transcriptSegment{AttemptID: "a_123", Epoch: 1, Direction: "OUTPUT", Payload: []byte("one")})
	blocked.Enqueue(transcriptSegment{AttemptID: "a_123", Epoch: 1, Direction: "OUTPUT", Payload: []byte("two")})
	if drops := metricValue(t, registry, "cla_terminal_gateway_recording_drops_total", nil); drops != 1 {
		t.Fatalf("recording drops = %f, want 1", drops)
	}

	failingAPI := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, "unavailable", http.StatusServiceUnavailable)
	}))
	defer failingAPI.Close()
	recorder := newTranscriptRecorder(failingAPI.URL, "svc-token", metrics, 4)
	t.Cleanup(recorder.Stop)
	recorder.Enqueue(transcriptSegment{AttemptID: "a_123", Epoch: 1, Direction: "OUTPUT", Payload: []byte("three")})
	waitForMetric(t, registry, "cla_terminal_gateway_recording_failures_total", nil, 1)
	assertNoSensitiveMetricLabels(t, registry)
}

func TestTerminalHandlerReplaysBufferedOutputAfterLastServerSequence(t *testing.T) {
	replay := newReplayStore(defaultReplayWindow, defaultReplayMaxBytes)
	var connections int32
	sessiond := newFakeSessiond(t, func(t *testing.T, conn net.Conn) {
		switch atomic.AddInt32(&connections, 1) {
		case 1:
			payload := readSessionFrame(t, conn, sessionwire.FrameStdin)
			assertSessionPayload(t, payload, "start")
			_, _ = conn.Write([]byte("first"))
			waitForReplaySequence(t, replay, fakeReplayKey("127.0.0.1:0"), 1)
			_, _ = conn.Write([]byte("second"))
			waitForReplaySequence(t, replay, fakeReplayKey("127.0.0.1:0"), 2)
		default:
			<-time.After(500 * time.Millisecond)
		}
	})
	api := newFakeTicketAPI(t, sessiond.Addr().String())
	gateway := httptest.NewServer(terminalHandler(config{
		APIURL:       api.URL,
		ServiceToken: "svc-token",
		Replay:       replay,
	}))
	defer gateway.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	first, _, err := websocket.Dial(ctx, wsURL(gateway.URL)+"/ws/terminal?ticket=opaque-ticket", nil)
	if err != nil {
		t.Fatal(err)
	}
	readFrameType(t, ctx, first, protocol.ServerStatus)
	frame := append([]byte{protocol.ClientStdin}, []byte("start")...)
	if err := first.Write(ctx, websocket.MessageBinary, frame); err != nil {
		t.Fatal(err)
	}
	stdout := readBinaryFrame(t, ctx, first, protocol.ServerStdout)
	if seq := binary.BigEndian.Uint64(stdout[1:9]); seq != 0 {
		t.Fatalf("first stdout sequence = %d, want 0", seq)
	}
	waitForReplaySequence(t, replay, fakeReplayKey("127.0.0.1:0"), 2)
	_ = first.Close(websocket.StatusNormalClosure, "")

	second, _, err := websocket.Dial(
		ctx,
		wsURL(gateway.URL)+"/ws/terminal?ticket=opaque-ticket&last_server_sequence=0",
		nil,
	)
	if err != nil {
		t.Fatal(err)
	}
	defer second.Close(websocket.StatusNormalClosure, "")
	readFrameType(t, ctx, second, protocol.ServerStatus)
	replayBegin := readFrameType(t, ctx, second, protocol.ServerReplay)
	if got := replayBegin["state"]; got != "REPLAY_BEGIN" {
		t.Fatalf("replay state = %v, want REPLAY_BEGIN", got)
	}
	replayed := readBinaryFrame(t, ctx, second, protocol.ServerStdout)
	if seq := binary.BigEndian.Uint64(replayed[1:9]); seq != 1 {
		t.Fatalf("replayed stdout sequence = %d, want 1", seq)
	}
	if got := string(replayed[9:]); got != "second" {
		t.Fatalf("replayed stdout payload = %q, want second", got)
	}
	replayEnd := readFrameType(t, ctx, second, protocol.ServerReplay)
	if got := replayEnd["state"]; got != "REPLAY_END" {
		t.Fatalf("replay state = %v, want REPLAY_END", got)
	}
}

func newFakeTicketAPI(t *testing.T, endpoint string) *httptest.Server {
	t.Helper()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/internal/terminal/tickets/consume" {
			t.Fatalf("unexpected API path %s", r.URL.Path)
		}
		if got := r.Header.Get("X-CLA-Service-Token"); got != "svc-token" {
			t.Fatalf("service token = %q, want svc-token", got)
		}
		var body map[string]string
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Fatal(err)
		}
		if body["ticket"] != "opaque-ticket" {
			t.Fatalf("ticket = %q, want opaque-ticket", body["ticket"])
		}
		_ = json.NewEncoder(w).Encode(fakeRoute(endpoint))
	}))
	t.Cleanup(server.Close)
	return server
}

func newFakeTicketAndRecordingAPI(
	t *testing.T,
	endpoint string,
	uploads chan<- map[string]any,
) *httptest.Server {
	t.Helper()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if got := r.Header.Get("X-CLA-Service-Token"); got != "svc-token" {
			t.Fatalf("service token = %q, want svc-token", got)
		}
		switch r.URL.Path {
		case "/internal/terminal/tickets/consume":
			var body map[string]string
			if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
				t.Fatal(err)
			}
			if body["ticket"] != "opaque-ticket" {
				t.Fatalf("ticket = %q, want opaque-ticket", body["ticket"])
			}
			_ = json.NewEncoder(w).Encode(fakeRoute(endpoint))
		case "/internal/attempts/a_123/transcript-segments/upload":
			var body map[string]any
			if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
				t.Fatal(err)
			}
			uploads <- body
			w.WriteHeader(http.StatusAccepted)
			_ = json.NewEncoder(w).Encode(map[string]any{"segmentId": "seg_123"})
		default:
			t.Fatalf("unexpected API path %s", r.URL.Path)
		}
	}))
	t.Cleanup(server.Close)
	return server
}

func fakeRoute(endpoint string) tickets.Route {
	return tickets.Route{
		TenantID:     "tenant_dev",
		AttemptID:    "a_123",
		SessionID:    "ls_123",
		SessionEpoch: 1,
		SessionRoute: tickets.SessionRoute{
			RouteRef: "route_123",
			Endpoint: endpoint,
			Protocol: "tcp-sessionwire",
		},
		Permissions: []string{"terminal.connect", "terminal.resize"},
	}
}

func fakeReplayKey(endpoint string) string {
	return replayKey(fakeRoute(endpoint))
}

func newFakeSessiond(t *testing.T, handler func(*testing.T, net.Conn)) net.Listener {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = listener.Close() })
	go func() {
		for {
			conn, err := listener.Accept()
			if err != nil {
				return
			}
			go func() {
				defer conn.Close()
				handler(t, conn)
			}()
		}
	}()
	return listener
}

func wsURL(httpURL string) string {
	return "ws" + strings.TrimPrefix(httpURL, "http")
}

func readFrameType(t *testing.T, ctx context.Context, conn *websocket.Conn, frameType byte) map[string]any {
	t.Helper()
	for {
		_, data, err := conn.Read(ctx)
		if err != nil {
			t.Fatal(err)
		}
		if len(data) == 0 || data[0] != frameType {
			continue
		}
		var payload map[string]any
		if err := json.Unmarshal(data[1:], &payload); err != nil {
			t.Fatal(err)
		}
		return payload
	}
}

func readStatusWith(
	t *testing.T,
	ctx context.Context,
	conn *websocket.Conn,
	key string,
	want any,
) map[string]any {
	t.Helper()
	for {
		payload := readFrameType(t, ctx, conn, protocol.ServerStatus)
		if payload[key] == want {
			return payload
		}
	}
}

func readBinaryFrame(t *testing.T, ctx context.Context, conn *websocket.Conn, frameType byte) []byte {
	t.Helper()
	for {
		_, data, err := conn.Read(ctx)
		if err != nil {
			t.Fatal(err)
		}
		if len(data) > 0 && data[0] == frameType {
			return data
		}
	}
}

func writeJSONControlFrame(
	t *testing.T,
	ctx context.Context,
	conn *websocket.Conn,
	frameType byte,
	payload any,
) {
	t.Helper()
	body, err := json.Marshal(payload)
	if err != nil {
		t.Fatal(err)
	}
	frame := append([]byte{frameType}, body...)
	if err := conn.Write(ctx, websocket.MessageBinary, frame); err != nil {
		t.Fatal(err)
	}
}

func readSessionFrame(t *testing.T, conn net.Conn, wantType byte) []byte {
	t.Helper()
	if err := conn.SetReadDeadline(time.Now().Add(2 * time.Second)); err != nil {
		t.Fatal(err)
	}
	frameType, payload, err := sessionwire.ReadFrame(conn)
	if err != nil {
		t.Fatal(err)
	}
	if frameType != wantType {
		t.Fatalf("session frame type = %#x, want %#x", frameType, wantType)
	}
	return payload
}

func assertSessionPayload(t *testing.T, payload []byte, want string) {
	t.Helper()
	if got := string(payload); got != want {
		t.Fatalf("session payload = %q, want %q", got, want)
	}
}

func readUpload(t *testing.T, uploads <-chan map[string]any) map[string]any {
	t.Helper()
	select {
	case upload := <-uploads:
		return upload
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for transcript upload")
		return nil
	}
}

func assertUploadedSegment(t *testing.T, upload map[string]any, epoch float64, wantPlaintext string) {
	t.Helper()
	if upload == nil {
		t.Fatal("missing upload")
	}
	if got := upload["sessionEpoch"]; got != epoch {
		t.Fatalf("sessionEpoch = %v, want %v", got, epoch)
	}
	encoded, ok := upload["segmentBase64"].(string)
	if !ok || encoded == "" {
		t.Fatalf("segmentBase64 missing in %#v", upload)
	}
	decoded, err := base64.StdEncoding.DecodeString(encoded)
	if err != nil {
		t.Fatalf("segmentBase64 invalid: %v", err)
	}
	if string(decoded) != wantPlaintext {
		t.Fatalf("uploaded plaintext = %q, want %q", decoded, wantPlaintext)
	}
	if _, leaked := upload["routeRef"]; leaked {
		t.Fatalf("upload leaked routeRef: %#v", upload)
	}
	if _, leaked := upload["endpoint"]; leaked {
		t.Fatalf("upload leaked endpoint: %#v", upload)
	}
}

func waitForReplaySequence(t *testing.T, replay *replayStore, key string, want uint64) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for {
		if replay.nextSequence(key) >= want {
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("replay next sequence = %d, want at least %d", replay.nextSequence(key), want)
		}
		time.Sleep(10 * time.Millisecond)
	}
}

func waitForMetric(
	t *testing.T,
	gatherer prometheus.Gatherer,
	name string,
	labels map[string]string,
	want float64,
) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for {
		if got, ok := findMetricValue(t, gatherer, name, labels); ok && got == want {
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("metric %s did not reach %f", name, want)
		}
		time.Sleep(10 * time.Millisecond)
	}
}

func metricValue(t *testing.T, gatherer prometheus.Gatherer, name string, labels map[string]string) float64 {
	t.Helper()
	value, ok := findMetricValue(t, gatherer, name, labels)
	if !ok {
		t.Fatalf("metric %s with labels %#v not found", name, labels)
	}
	return value
}

func findMetricValue(
	t *testing.T,
	gatherer prometheus.Gatherer,
	name string,
	labels map[string]string,
) (float64, bool) {
	t.Helper()
	families, err := gatherer.Gather()
	if err != nil {
		t.Fatalf("gather metrics: %v", err)
	}
	for _, family := range families {
		if family.GetName() != name {
			continue
		}
		for _, metric := range family.Metric {
			if !metricLabelsMatch(metric.GetLabel(), labels) {
				continue
			}
			if metric.GetGauge() != nil {
				return metric.GetGauge().GetValue(), true
			}
			if metric.GetCounter() != nil {
				return metric.GetCounter().GetValue(), true
			}
			t.Fatalf("metric %s is not gauge or counter", name)
		}
	}
	return 0, false
}

func metricLabelsMatch(pairs []*io_prometheus_client.LabelPair, labels map[string]string) bool {
	if len(labels) == 0 {
		return true
	}
	seen := map[string]string{}
	for _, pair := range pairs {
		seen[pair.GetName()] = pair.GetValue()
	}
	for key, value := range labels {
		if seen[key] != value {
			return false
		}
	}
	return true
}

func assertNoSensitiveMetricLabels(t *testing.T, gatherer prometheus.Gatherer) {
	t.Helper()
	forbidden := map[string]bool{
		"tenant":     true,
		"tenant_id":  true,
		"attempt":    true,
		"attempt_id": true,
		"route":      true,
		"route_ref":  true,
		"endpoint":   true,
		"sessiond":   true,
	}
	families, err := gatherer.Gather()
	if err != nil {
		t.Fatalf("gather metrics: %v", err)
	}
	for _, family := range families {
		for _, metric := range family.Metric {
			for _, label := range metric.GetLabel() {
				if forbidden[label.GetName()] {
					t.Fatalf("metric %s has forbidden label %q", family.GetName(), label.GetName())
				}
			}
		}
	}
}
